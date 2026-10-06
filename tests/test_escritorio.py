"""Lanzador de escritorio (NejiPOS.exe): carpeta de datos, prueba sin ventana y datos del equipo."""

import sys

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
