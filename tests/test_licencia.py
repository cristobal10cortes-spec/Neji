"""Licencias: 15 días de prueba, licencia de pago único por caja o por local, y el generador del vendedor."""

import base64
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from neji import licencia  # noqa: E402

EQUIPO = "ABCD-EFGH-IJKL-MNOP"


def publica(llave):
    return base64.b64encode(llave.public_key().public_bytes(serialization.Encoding.Raw,
                                                            serialization.PublicFormat.Raw)).decode()


@pytest.fixture
def llave(monkeypatch):
    """Una llave del vendedor, y Neji con su llave pública y un código de equipo fijo."""
    privada = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licencia, "LLAVES_PUBLICAS", [publica(privada)])
    monkeypatch.setattr(licencia, "codigo_equipo", lambda: EQUIPO)
    return privada


def hecha(llave, tipo="caja", cajas=1, equipo=EQUIPO, cliente="Farmacia Los Andes"):
    return licencia.armar({"numero": "0007", "emitida": "2026-10-28", "cliente": cliente, "rut": "76.086.428-5",
                           "tipo": tipo, "cajas": cajas, "equipo": equipo}, llave)


def poner(app, **valores):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    try:
        for clave, valor in valores.items():
            con.execute("INSERT INTO licencia (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = ?",
                        (clave, valor, valor))
    finally:
        con.close()


def hace(dias):
    return (date.today() - timedelta(days=dias)).isoformat()


def vender(api, productos, caja_id=1, esperado=201):
    return api.post("/api/ventas", {"caja_id": caja_id, "items": [{"producto_id": productos["bebida"]["id"],
                                                                   "cantidad": 1}]}, esperado=esperado)


def test_sin_llaves_no_hay_control(api, productos, turno, monkeypatch):
    monkeypatch.setattr(licencia, "LLAVES_PUBLICAS", [])     # una compilación sin la llave del vendedor
    assert api.get("/api/config")["licencia"] == {"estado": "libre"}
    d = api.get("/api/licencia")
    assert (d["estado"], d["control"], d["puede_vender"]) == ("libre", False, True)
    vender(api, productos)


def test_prueba_de_15_dias(app, api, productos, turno, llave):
    assert api.get("/api/config")["licencia"] == {"estado": "prueba", "dias": 15}
    d = api.get("/api/licencia")
    assert (d["estado"], d["dias"], d["codigo_equipo"], d["vence"]) == (
        "prueba", 15, EQUIPO, (date.today() + timedelta(days=15)).isoformat())
    vender(api, productos)
    poner(app, prueba_inicio=hace(14))
    assert api.get("/api/config")["licencia"] == {"estado": "prueba", "dias": 1}
    vender(api, productos)
    # Al día 15 termina: se puede ver y configurar todo, pero no vender.
    poner(app, prueba_inicio=hace(15))
    assert api.get("/api/config")["licencia"] == {"estado": "vencida", "dias": 0}
    r = vender(api, productos, esperado=403)
    assert "15 días de prueba" in r["error"] and "Configuración → Licencia" in r["error"]
    assert api.get("/api/productos")
    assert len(api.get("/api/ventas")) == 2


def test_atrasar_el_reloj_no_alarga_la_prueba(app, api, llave):
    poner(app, prueba_inicio=date.today().isoformat(), ultima_fecha=(date.today() + timedelta(days=20)).isoformat())
    assert api.get("/api/licencia")["estado"] == "vencida"


def test_licencia_de_una_caja(app, api, productos, turno, llave):
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    api.post("/api/caja/2/abrir", {"fondo_inicial": 0}, esperado=201)
    poner(app, prueba_inicio=hace(30))
    vender(api, productos, esperado=403)
    d = api.put("/api/licencia", {"texto": hecha(llave)})
    assert (d["estado"], d["cliente"], d["tipo_texto"], d["cajas"], d["numero"]) == (
        "activa", "Farmacia Los Andes", "Caja", 1, "0007")
    assert api.get("/api/config")["licencia"] == {"estado": "activa"}
    vender(api, productos)
    # Solo vende la caja principal; no se crean ni reactivan más.
    r = vender(api, productos, caja_id=2, esperado=403)
    assert "una caja" in r["error"]
    r = api.post("/api/cajas", {"nombre": "Caja 3"}, esperado=403)
    assert "una caja" in r["error"] and "local" in r["error"]


def test_licencia_de_local(api, productos, turno, llave):
    api.put("/api/licencia", {"texto": hecha(llave, "local", 2)})
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    api.post("/api/cajas", {"nombre": "Caja 3"}, esperado=403)
    api.put("/api/cajas/2", {"activa": False})
    api.post("/api/cajas", {"nombre": "Caja 3"}, esperado=201)
    r = api.put("/api/cajas/2", {"activa": True}, esperado=403)
    assert "2 cajas" in r["error"]
    # Local sin límite de cajas.
    d = api.put("/api/licencia", {"texto": hecha(llave, "local", 0)})
    assert (d["tipo_texto"], d["cajas"]) == ("Local (multicaja)", 0)
    api.put("/api/cajas/2", {"activa": True})
    api.post("/api/cajas", {"nombre": "Caja 4"}, esperado=201)


def test_licencias_que_no_sirven(app, api, llave):
    r = api.put("/api/licencia", {"texto": hecha(llave, equipo="ZZZZ-YYYY-XXXX-WWWW")}, esperado=400)
    assert "otro computador" in r["error"] and EQUIPO in r["error"]
    r = api.put("/api/licencia", {"texto": hecha(Ed25519PrivateKey.generate())}, esperado=400)
    assert "no es válida" in r["error"]
    firma = hecha(llave).split(".")[1]
    otro = licencia.armar({"cliente": "Otro", "tipo": "local", "cajas": 0, "equipo": "*"}, Ed25519PrivateKey.generate())
    r = api.put("/api/licencia", {"texto": f"{otro.split('.')[0]}.{firma}"}, esperado=400)
    assert "no es válida" in r["error"]
    r = api.put("/api/licencia", {"texto": "hola"}, esperado=400)
    assert "NEJI-" in r["error"]
    assert api.get("/api/licencia")["estado"] == "prueba"
    # Copiada con saltos de línea, y válida en cualquier computador.
    texto = hecha(llave, equipo="*")
    d = api.put("/api/licencia", {"texto": "\n".join(texto[i:i + 60] for i in range(0, len(texto), 60))})
    assert d["estado"] == "activa"
    # Si después la base se lleva a otro computador, la licencia de ese equipo ya no vale ahí.
    api.put("/api/licencia", {"texto": hecha(llave)})
    poner(app, prueba_inicio=hace(40))
    licencia.codigo_equipo = lambda: "QQQQ-RRRR-SSSS-TTTT"   # el fixture lo devuelve a su lugar
    d = api.get("/api/licencia")
    assert d["estado"] == "vencida" and "otro computador" in d["error"]


def test_solo_el_administrador(api, llave):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    api.get("/api/licencia", esperado=403)
    api.put("/api/licencia", {"texto": hecha(llave)}, esperado=403)
    assert api.get("/api/config")["licencia"]["estado"] == "prueba"


# --- El generador del vendedor ----------------------------------------------------------------------------

@pytest.fixture
def generador(tmp_path, monkeypatch):
    ruta = Path(__file__).resolve().parent.parent / "herramientas" / "licencias.py"
    spec = importlib.util.spec_from_file_location("generador_licencias", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    monkeypatch.setenv("NEJI_LICENCIAS_CARPETA", str(tmp_path / "NejiLicencias"))
    return modulo


def test_generador_crea_licencias_que_neji_acepta(generador, tmp_path, monkeypatch, capsys):
    carpeta = tmp_path / "NejiLicencias"
    with pytest.raises(generador.Error, match="6 caracteres"):
        generador.crear_llave("123")
    llave_publica = generador.crear_llave("secreta1")
    assert (carpeta / "llave_privada.pem").read_bytes().startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
    with pytest.raises(generador.Error, match="Ya tienes una llave"):
        generador.crear_llave("secreta1")
    with pytest.raises(generador.Error, match="contraseña"):
        generador.cargar_llave("otra-clave")
    privada = generador.cargar_llave("secreta1")
    texto, datos = generador.crear_licencia(privada, "Farmacia Los Andes", "caja", equipo="abcd efgh ijkl mnop",
                                            rut="760864285", nota="$150.000 transferencia")
    assert (datos["numero"], datos["equipo"], datos["rut"], datos["cajas"]) == ("0001", EQUIPO, "76.086.428-5", 1)
    assert licencia.leer(texto, [llave_publica]) == datos
    with pytest.raises(generador.Error, match="XXXX-XXXX"):
        generador.crear_licencia(privada, "Otro", "caja", equipo="1234")
    with pytest.raises(generador.Error, match="RUT"):
        generador.crear_licencia(privada, "Otro", "caja", rut="11.111.111-2")
    # Por la línea de comandos, con la contraseña en una variable (sin preguntar).
    monkeypatch.setenv("NEJI_LICENCIAS_CLAVE", "secreta1")
    assert generador.main(["crear", "--cliente", "Minimarket Don Pepe", "--tipo", "local", "--cajas", "3"]) == 0
    salida = capsys.readouterr().out
    assert "Licencia N° 0002" in salida and "Local (multicaja), 3 cajas" in salida and "cualquier computador" in salida
    registro = (carpeta / "registro.csv").read_text(encoding="utf-8-sig").splitlines()
    assert registro[0].startswith("numero;emitida;cliente") and len(registro) == 3
    assert "$150.000 transferencia" in registro[1]
    archivo = carpeta / "licencias" / "0002_Minimarket_Don_Pepe.txt"
    assert "Configuración → Licencia" in archivo.read_text(encoding="utf-8")
    # Y Neji la acepta con esa llave pública.
    monkeypatch.setattr(licencia, "LLAVES_PUBLICAS", [llave_publica])
    nueva = archivo.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert licencia.leer(nueva)["cliente"] == "Minimarket Don Pepe"
    assert generador.main(["ver", nueva]) == 0
    assert "Minimarket Don Pepe" in capsys.readouterr().out


def test_el_generador_solo_necesita_cryptography(tmp_path):
    """En el computador del vendedor basta con `pip install cryptography`: el generador no carga Flask."""
    import os
    import subprocess
    import sys

    ruta = Path(__file__).resolve().parent.parent / "herramientas" / "licencias.py"
    codigo = ("import runpy, sys; sys.modules['flask'] = None; sys.argv = ['licencias.py', 'llave']; "
              f"runpy.run_path({str(ruta)!r}, run_name='__main__')")
    entorno = {**os.environ, "NEJI_LICENCIAS_CARPETA": str(tmp_path), "NEJI_LICENCIAS_CLAVE": "secreta1"}
    r = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True, env=entorno,
                       cwd=tmp_path, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Tu llave PÚBLICA" in r.stdout and (tmp_path / "llave_privada.pem").exists()
