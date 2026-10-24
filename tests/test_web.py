"""Neji en internet (NEJI_WEB): código de instalación, freno de intentos y restaurar un respaldo."""

import io
import sqlite3

from conftest import Cliente
from neji import create_app
from neji.api import sistema


def _app(tmp_path, **extra):
    return create_app({
        "TESTING": True, "DATOS": str(tmp_path), "DATABASE": str(tmp_path / "neji.db"),
        "RESPALDOS": str(tmp_path / "respaldos"), "RESPALDO_AUTOMATICO": False, "SECRET_KEY": "pruebas",
        **extra,
    })


SETUP = {"negocio_nombre": "Farmacia Piedra", "usuario": "admin", "password": "1234"}


def test_en_internet_la_instalacion_pide_el_codigo(tmp_path):
    app = _app(tmp_path, WEB=True, MARCA="Farmacia Piedra", CODIGO_INSTALACION="piedra-2026")
    c = Cliente(app.test_client())
    estado = c.get("/api/estado")
    assert estado["pide_codigo"] and estado["web"] and estado["marca"] == "Farmacia Piedra"
    assert "código" in c.post("/api/setup", SETUP, esperado=403)["error"]
    assert "código" in c.post("/api/setup", {**SETUP, "codigo": "otro"}, esperado=403)["error"]
    c.post("/api/setup", {**SETUP, "codigo": "piedra-2026"})
    assert c.get("/api/estado")["usuario"]["usuario"] == "admin"
    assert c.get("/api/equipo")["web"] is True


def test_en_internet_sin_codigo_configurado_nadie_instala(tmp_path):
    c = Cliente(_app(tmp_path, WEB=True).test_client())
    assert "NEJI_CODIGO_INSTALACION" in c.post("/api/setup", {**SETUP, "codigo": ""}, esperado=403)["error"]


def test_en_el_computador_no_pide_codigo(tmp_path):
    c = Cliente(_app(tmp_path).test_client())
    assert c.get("/api/estado")["pide_codigo"] is False
    c.post("/api/setup", SETUP)


def test_freno_de_intentos_de_acceso(tmp_path):
    app = _app(tmp_path)
    c = Cliente(app.test_client())
    c.post("/api/setup", SETUP)
    c.post("/api/logout")
    for _ in range(sistema.INTENTOS_MAXIMOS):
        c.post("/api/login", {"usuario": "admin", "password": "mala"}, esperado=401)
    # Bloqueado incluso con la contraseña correcta, hasta que pase el tiempo.
    assert "Demasiados intentos" in c.post("/api/login", {"usuario": "admin", "password": "1234"}, esperado=429)["error"]
    sistema._fallos.clear()
    c.post("/api/login", {"usuario": "admin", "password": "1234"})


def test_un_usuario_bloqueado_no_bloquea_a_los_demas(tmp_path):
    c = Cliente(_app(tmp_path).test_client())
    c.post("/api/setup", SETUP)
    c.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    c.post("/api/logout")
    for _ in range(sistema.INTENTOS_MAXIMOS):
        c.post("/api/login", {"usuario": "admin", "password": "mala"}, esperado=401)
    c.post("/api/login", {"usuario": "admin", "password": "1234"}, esperado=429)
    c.post("/api/login", {"usuario": "caja", "password": "1111"})


def test_restaurar_respaldo(tmp_path):
    # Un respaldo de «otro computador», con su propio negocio y administrador.
    otro = _app(tmp_path / "otro")
    co = Cliente(otro.test_client())
    co.post("/api/setup", {**SETUP, "negocio_nombre": "Desde Windows", "usuario": "jefa"})
    archivo = (tmp_path / "otro" / "neji.db").read_bytes()

    app = _app(tmp_path / "web")
    c = Cliente(app.test_client())
    c.post("/api/setup", SETUP)
    r = c.http.post("/api/respaldos/restaurar", data={"archivo": (io.BytesIO(archivo), "neji.db")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["respaldo_previo"].startswith("neji-")
    estado = c.get("/api/estado")
    assert estado["usuario"] is None and estado["negocio"] == "Desde Windows"
    c.post("/api/login", {"usuario": "jefa", "password": "1234"})


def test_restaurar_rechaza_lo_que_no_es_respaldo(tmp_path):
    app = _app(tmp_path)
    c = Cliente(app.test_client())
    c.post("/api/setup", SETUP)
    for contenido in (b"hola", _db_vacia(tmp_path)):
        r = c.http.post("/api/respaldos/restaurar", data={"archivo": (io.BytesIO(contenido), "x.db")},
                        content_type="multipart/form-data")
        assert r.status_code == 400 and "respaldo" in r.get_json()["error"]
    assert c.get("/api/estado")["negocio"] == "Farmacia Piedra"


def _db_vacia(tmp_path):
    ruta = tmp_path / "vacia.db"
    sqlite3.connect(ruta).execute("CREATE TABLE x (a)").connection.commit()
    return ruta.read_bytes()
