"""Lanzador de escritorio (NejiPOS.exe): carpeta de datos, prueba sin ventana y datos del equipo."""

import sys

import pytest

import escritorio


def test_sin_compilar_usa_la_carpeta_datos_del_proyecto(monkeypatch):
    monkeypatch.delenv("NEJI_DATOS", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    carpeta = escritorio.carpeta_datos()
    assert carpeta.name == "datos"
    assert carpeta.parent == escritorio.Path(escritorio.__file__).resolve().parent


def test_neji_datos_manda(monkeypatch, tmp_path):
    monkeypatch.setenv("NEJI_DATOS", str(tmp_path / "x"))
    assert escritorio.carpeta_datos() == tmp_path / "x"


def test_compilado_usa_localappdata_o_la_carpeta_portatil(monkeypatch, tmp_path):
    monkeypatch.delenv("NEJI_DATOS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "Neji POS" / "NejiPOS.exe"
    exe.parent.mkdir()
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    # Por defecto, fuera de la carpeta del programa: actualizarlo o moverlo no toca los datos.
    assert escritorio.carpeta_datos() == tmp_path / "local" / "NejiPOS" / "datos"
    assert not (tmp_path / "local").exists()  # decidir no crea carpetas
    # Una carpeta «datos» con base junto al .exe (modo portátil) tiene prioridad.
    (exe.parent / "datos").mkdir()
    assert escritorio.carpeta_datos() == tmp_path / "local" / "NejiPOS" / "datos"  # vacía no cuenta
    (exe.parent / "datos" / "neji.db").write_bytes(b"")
    assert escritorio.carpeta_datos() == exe.parent / "datos"


def test_prueba_sin_ventana(tmp_path, monkeypatch):
    monkeypatch.delenv("NEJI_DATOS", raising=False)
    salida = tmp_path / "prueba.json"
    assert escritorio.prueba_de_humo(str(salida)) == 0
    assert '"ok": true' in salida.read_text(encoding="utf-8")


def test_no_inicia_si_el_puerto_esta_ocupado():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert not escritorio.puerto_libre("127.0.0.1", s.getsockname()[1])
        assert not escritorio.responde_neji(f"http://127.0.0.1:{s.getsockname()[1]}", segundos=0.5)


def test_impresion_directa(monkeypatch):
    monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--algo")
    escritorio.imprimir_directo()
    escritorio.imprimir_directo()
    import os
    assert os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] == "--algo --kiosk-printing"


def test_textos_de_cierre_en_espanol():
    assert escritorio.textos(False)["global.quitConfirmation"] == "¿Cerrar Neji POS?"
    assert "otras cajas" in escritorio.textos(True)["global.quitConfirmation"]


def test_datos_del_equipo_y_modo_red(api, monkeypatch):
    from neji import equipo

    monkeypatch.setenv("NEJI_RED", "0")
    datos = api.get("/api/equipo")
    assert datos["carpeta_datos"] and datos["red_activa"] is False and datos["direccion_red"] is None
    monkeypatch.setenv("NEJI_RED", "1")
    monkeypatch.setenv("NEJI_PUERTO", "5000")
    assert api.get("/api/equipo")["direccion_red"].endswith(":5000")
    # «Permitir otras cajas» se guarda en la configuración y lo leen los lanzadores al iniciar
    ruta = api.http.application.config["DATABASE"]
    assert equipo.modo_red_configurado(ruta) is False
    api.put("/api/config", {"modo_red": True})
    assert equipo.modo_red_configurado(ruta) is True


def test_desbloquear_quita_la_marca_de_descarga(tmp_path, monkeypatch):
    # En Windows «archivo:Zone.Identifier» es un flujo alterno del archivo; aquí basta un archivo
    # con ese nombre para probar que se quita solo la marca y nada más.
    monkeypatch.delenv("NEJI_SIN_DESBLOQUEO", raising=False)
    (tmp_path / "_internal").mkdir()
    for nombre in ("NejiPOS.exe", "_internal/Python.Runtime.dll"):
        (tmp_path / nombre).write_bytes(b"x")
        (tmp_path / (nombre + ":Zone.Identifier")).write_text("[ZoneTransfer]\nZoneId=3")
    assert escritorio.desbloquear_archivos(str(tmp_path)) == 2
    restantes = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert restantes == ["NejiPOS.exe", "_internal/Python.Runtime.dll"]


def test_busca_webview2_en_el_disco(tmp_path, monkeypatch):
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(tmp_path / variable))
    assert escritorio.carpeta_webview2() is None
    for version in ("98.0.1108.56", "153.0.4234.48", "120.0.2210.91"):
        carpeta = tmp_path / "ProgramFiles(x86)" / "Microsoft" / "EdgeWebView" / "Application" / version
        carpeta.mkdir(parents=True)
        (carpeta / "msedgewebview2.exe").write_bytes(b"")
    assert escritorio.carpeta_webview2().name == "153.0.4234.48"


def test_fuera_de_windows_el_motor_no_necesita_preparacion():
    if sys.platform != "win32":
        assert escritorio.preparar_motor() == ("ok", "", {})


def test_la_ventana_le_da_a_la_interfaz_las_impresoras_de_este_computador(monkeypatch):
    creadas = {}

    class WebviewFalso:
        def create_window(self, *args, **kwargs):
            creadas.update(kwargs)
            return object()

    escritorio.crear_ventana(WebviewFalso(), "http://127.0.0.1:5000/")
    api = creadas["js_api"]
    assert isinstance(api, escritorio.ApiEscritorio)
    # Los errores vuelven como {ok: False, error} para mostrarlos en la caja, nunca como excepción.
    assert api.imprimir({"impresora": ""}) == {"ok": False, "error": "No hay una impresora elegida."}
    if sys.platform != "win32":
        r = api.impresoras()
        assert r["ok"] is False and "Windows" in r["error"]


def test_imprimir_arma_escpos_y_lo_manda_a_la_impresora(monkeypatch):
    from neji import impresoras
    enviados = []
    monkeypatch.setattr(impresoras, "imprimir_crudo", lambda nombre, datos, *a: enviados.append((nombre, datos)))
    r = escritorio.ApiEscritorio().imprimir({"impresora": "POS-80", "papel": "80", "cajon": True, "copias": 2,
                                             "bloques": escritorio.TICKET_PRUEBA})
    assert r == {"ok": True}
    assert [n for n, _ in enviados] == ["POS-80", "POS-80"]
    primero, segundo = enviados[0][1], enviados[1][1]
    assert impresoras.ABRIR_CAJON in primero and impresoras.ABRIR_CAJON not in segundo   # cajón solo una vez
    assert "Tildes y eñes".encode("cp850") in primero and primero.endswith(impresoras.CORTAR)
    # Sin bloques: solo abre el cajón.
    enviados.clear()
    escritorio.ApiEscritorio().imprimir({"impresora": "POS-80", "cajon": True, "bloques": []})
    assert enviados == [("POS-80", impresoras.INICIAR + impresoras.SIN_CHINO + b"\x1bt\x02" + impresoras.ABRIR_CAJON)]


def test_sin_consola_las_pruebas_de_impresora_se_muestran_en_un_cuadro(monkeypatch, tmp_path):
    """NejiPOS.exe no tiene consola (sys.stdout es None): --listar-impresoras debe mostrar algo."""
    from neji import impresoras
    vistos = []
    monkeypatch.setattr(escritorio, "mensaje", lambda texto, error=False, **k: vistos.append((texto, error)))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(impresoras, "listar", lambda: [
        {"nombre": "POS-80C", "conexion": "USB", "termica": True, "predeterminada": True, "sin_conexion": False}])
    assert escritorio.listar_impresoras() == 0
    assert vistos == [("Impresoras de este computador:\n\n• POS-80C (USB) · de tickets · predeterminada", False)]
    vistos.clear()
    monkeypatch.setattr(impresoras, "listar", lambda: (_ for _ in ()).throw(RuntimeError("se cayó")))
    assert escritorio.listar_impresoras() == 1
    assert vistos and vistos[0][1] is True and "se cayó" in vistos[0][0]
    # Con --salida no se abre ningún cuadro (lo usan las pruebas automáticas).
    vistos.clear()
    assert escritorio.probar_impresora("", salida=tmp_path / "r.json") == 1
    assert vistos == [] and "No hay una impresora elegida" in (tmp_path / "r.json").read_text(encoding="utf-8")


NETSTAT = """
Conexiones activas

  Proto  Dirección local          Dirección remota        Estado           PID
  TCP    0.0.0.0:135            0.0.0.0:0              ESCUCHANDO       1052
  TCP    127.0.0.1:5000         0.0.0.0:0              ESCUCHANDO       4321
  TCP    127.0.0.1:5000         127.0.0.1:50123        ESTABLECIDA      4321
  TCP    127.0.0.1:50123        127.0.0.1:5000         ESTABLECIDA      9999
"""


def test_encuentra_el_programa_que_usa_el_puerto():
    assert escritorio.pid_en_puerto(NETSTAT, 5000) == 4321          # en español («ESCUCHANDO») o inglés
    assert escritorio.pid_en_puerto(NETSTAT.replace("127.0.0.1:5000         0.0.0.0:0", "0.0.0.0:5000           0.0.0.0:0"), 5000) == 4321
    assert escritorio.pid_en_puerto(NETSTAT, 5001) is None
    assert escritorio.nombre_de_proceso('"NejiPOS.exe","4321","Console","1","120.000 KB"\r\n') == "NejiPOS.exe"
    assert escritorio.nombre_de_proceso("INFORMACIÓN: no hay tareas ejecutándose con los criterios especificados.") == ""


def test_otra_version_abierta_se_cierra_y_se_abre_la_nueva(monkeypatch):
    preguntas, cerrados = [], []
    monkeypatch.setattr(escritorio, "VERSION", "0.1.20")
    monkeypatch.setattr(escritorio, "mensaje", lambda texto, error=False, pregunta=False: preguntas.append(texto) or True)
    abierta = {"si": True}
    monkeypatch.setattr(escritorio, "estado_neji", lambda base, segundos=2.0: {"configurado": True} if abierta["si"] else None)
    monkeypatch.setattr(escritorio, "puerto_libre", lambda host, puerto: not abierta["si"])

    def cerrar(puerto):
        cerrados.append(puerto)
        abierta["si"] = False
        return True
    monkeypatch.setattr(escritorio, "cerrar_neji_en_puerto", cerrar)
    # Una versión anterior (sin «version» en /api/estado): se pregunta, se cierra y se sigue.
    assert escritorio.resolver_otra_instancia("http://127.0.0.1:5000", 5000) is True
    assert cerrados == [5000] and "una versión anterior" in preguntas[0] and "0.1.20" in preguntas[0]


def test_misma_version_abierta_no_se_cierra(monkeypatch):
    vistos = []
    monkeypatch.setattr(escritorio, "VERSION", "0.1.20")
    monkeypatch.setattr(escritorio, "estado_neji", lambda base, segundos=2.0: {"configurado": True, "version": "0.1.20"})
    monkeypatch.setattr(escritorio, "mensaje", lambda texto, **k: vistos.append(texto))
    monkeypatch.setattr(escritorio, "cerrar_neji_en_puerto", lambda puerto: pytest.fail("no debía cerrar"))
    assert escritorio.resolver_otra_instancia("http://127.0.0.1:5000", 5000) is False
    assert "ya está abierto" in vistos[0]


def test_si_no_quiere_cerrar_la_otra_no_se_abre(monkeypatch):
    monkeypatch.setattr(escritorio, "estado_neji", lambda base, segundos=2.0: {"configurado": True, "version": "0.1.9"})
    monkeypatch.setattr(escritorio, "mensaje", lambda texto, pregunta=False, **k: False)
    monkeypatch.setattr(escritorio, "cerrar_neji_en_puerto", lambda puerto: pytest.fail("no debía cerrar"))
    assert escritorio.resolver_otra_instancia("http://127.0.0.1:5000", 5000) is False


def test_si_no_se_puede_cerrar_avisa(monkeypatch):
    vistos = []
    monkeypatch.setattr(escritorio, "estado_neji", lambda base, segundos=2.0: {"configurado": True, "version": "0.1.9"})
    monkeypatch.setattr(escritorio, "mensaje", lambda texto, pregunta=False, **k: vistos.append(texto) or True)
    monkeypatch.setattr(escritorio, "cerrar_neji_en_puerto", lambda puerto: False)   # p. ej. lo usa otro programa
    assert escritorio.resolver_otra_instancia("http://127.0.0.1:5000", 5000) is False
    assert "No se pudo cerrar" in vistos[-1]


def test_la_version_se_ve_en_el_estado_y_en_la_prueba(api, tmp_path):
    from neji.version import VERSION
    assert api.get("/api/estado")["version"] == VERSION
    import json
    escritorio.prueba_de_humo(tmp_path / "informe.json")
    assert json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))["version"] == VERSION


def test_la_version_empaquetada_manda(tmp_path, monkeypatch):
    import neji.version as v
    archivo = tmp_path / "version.txt"
    archivo.write_text("0.1.42\n", encoding="utf-8")
    monkeypatch.setattr(v, "__file__", str(tmp_path / "version.py"))
    monkeypatch.setenv("NEJI_VERSION", "9.9.9")
    assert v.version() == "0.1.42"
    archivo.unlink()
    assert v.version() == "9.9.9"
    monkeypatch.delenv("NEJI_VERSION")
    assert v.version() == "desarrollo"
