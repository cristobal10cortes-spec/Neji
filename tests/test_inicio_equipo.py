"""¿Principal o caja?: la primera vez NejiPOS.exe pregunta cómo se usa el computador; la caja busca sola al
principal en la red (neji/red_local.py) y la elección queda guardada (equipo.json)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import escritorio
from neji import red_local


# --- Buscar en la red -------------------------------------------------------------------------------------

def test_busca_solo_en_las_redes_privadas_del_equipo():
    hosts = red_local.candidatos(["192.168.1.37", "127.0.0.1", "169.254.3.4", "8.8.8.8"])
    assert len(hosts) == 253 and "192.168.1.37" not in hosts            # sin el propio
    assert hosts[0] == "192.168.1.1" and hosts[-1] == "192.168.1.254"
    # Dos adaptadores (el del local y uno virtual): las dos redes, cada una una vez.
    assert len(red_local.redes(["192.168.1.37", "10.0.0.5", "192.168.1.40"])) == 2
    assert red_local.candidatos(["127.0.0.1"]) == []


@pytest.mark.parametrize("entrada, salida", [
    ("192.168.1.20", "192.168.1.20:5000"),
    (" http://192.168.1.20:5000/ ", "192.168.1.20:5000"),
    ("192.168.1.20:8080", "192.168.1.20:8080"),
    ("CAJA-PRINCIPAL", "CAJA-PRINCIPAL:5000"),
])
def test_normalizar_direccion(entrada, salida):
    assert red_local.normalizar(entrada) == salida


@pytest.mark.parametrize("entrada", ["", "192.168.1.20:0", "192.168.1.20:99999", "mi casa", "a;b"])
def test_direccion_invalida(entrada):
    with pytest.raises(ValueError):
        red_local.normalizar(entrada)


def _servidor(respuesta):
    class Manejador(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            cuerpo = json.dumps(respuesta).encode() if self.path == "/api/estado" else b"no"
            self.send_response(200 if self.path == "/api/estado" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *a):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def test_encuentra_el_neji_pos_de_la_red_y_no_otros_programas():
    neji = _servidor({"configurado": True, "negocio": "Farmacia Easy Pharma", "version": "0.1.66"})
    otro = _servidor({"hola": "no soy Neji"})
    try:
        encontrados = red_local.buscar(neji.server_address[1], hosts=["127.0.0.1", "127.0.0.2"])
        assert encontrados == [{"direccion": f"127.0.0.1:{neji.server_address[1]}", "ip": "127.0.0.1",
                                "negocio": "Farmacia Easy Pharma", "version": "0.1.66"}]
        assert red_local.buscar(otro.server_address[1], hosts=["127.0.0.1"]) == []
        assert red_local.buscar(neji.server_address[1], hosts=[]) == []
    finally:
        neji.shutdown()
        otro.shutdown()


# --- La elección guardada ---------------------------------------------------------------------------------

def test_guardar_y_leer_la_eleccion(tmp_path):
    assert escritorio.leer_eleccion(tmp_path) is None
    escritorio.guardar_eleccion(tmp_path, {"tipo": "caja", "principal": "192.168.1.20:5000", "negocio": "Ñuñoa"})
    assert escritorio.leer_eleccion(tmp_path)["principal"] == "192.168.1.20:5000"
    (tmp_path / "equipo.json").write_text('{"tipo": "caja"}', encoding="utf-8")     # caja sin principal
    assert escritorio.leer_eleccion(tmp_path) is None
    (tmp_path / "equipo.json").write_text("roto", encoding="utf-8")
    assert escritorio.leer_eleccion(tmp_path) is None


def test_una_base_en_uso_es_de_un_principal(tmp_path):
    from neji import db
    assert escritorio.base_configurada(tmp_path) is False                  # computador nuevo
    db.inicializar(str(tmp_path / "neji.db"))
    assert escritorio.base_configurada(tmp_path) is False                  # base vacía: aún se puede elegir
    con = db.conectar(str(tmp_path / "neji.db"))
    con.execute("INSERT INTO usuarios (usuario, nombre, password_hash, rol, creado) "
                "VALUES ('admin', 'Admin', 'x', 'admin', '2026-11-02')")
    con.close()
    assert escritorio.base_configurada(tmp_path) is True


# --- Al abrir NejiPOS.exe ---------------------------------------------------------------------------------

@pytest.fixture
def inicio(monkeypatch, tmp_path):
    """main() sin abrir nada: anota qué camino tomó."""
    llamadas = []
    monkeypatch.setattr(escritorio, "carpeta_datos", lambda: tmp_path)
    monkeypatch.setattr(escritorio, "configurar_registro", lambda datos: None)
    monkeypatch.setattr(escritorio, "inicio_con_eleccion",
                        lambda datos, puerto=5000, **k: llamadas.append(("elegir", k)) or 0)
    monkeypatch.setattr(escritorio, "conectar_caja", lambda e, datos, puerto=5000: llamadas.append(("caja", e)) or 0)
    monkeypatch.setattr(escritorio, "iniciar_principal", lambda puerto, red=False: llamadas.append(("principal",)) or 0)
    monkeypatch.setattr(escritorio, "conectar", lambda destino, datos: llamadas.append(("conectar", destino)) or 0)
    return llamadas, tmp_path


def test_la_primera_vez_pregunta(inicio):
    llamadas, _ = inicio
    assert escritorio.main([]) == 0 and llamadas == [("elegir", {})]


def test_una_caja_elegida_se_conecta_y_un_principal_en_uso_no_pregunta(inicio, monkeypatch):
    llamadas, datos = inicio
    escritorio.guardar_eleccion(datos, {"tipo": "caja", "principal": "192.168.1.20:5000"})
    escritorio.main([])
    assert llamadas[-1] == ("caja", {"tipo": "caja", "principal": "192.168.1.20:5000"})
    # --conectar sigue mandando (los accesos directos de antes).
    escritorio.main(["--conectar", "192.168.1.9"])
    assert llamadas[-1] == ("conectar", "192.168.1.9")
    # --elegir vuelve a preguntar.
    escritorio.main(["--elegir"])
    assert llamadas[-1] == ("elegir", {})
    # Una instalación que ya vende (base con usuarios) y sin elección guardada: principal, sin preguntar.
    (datos / "equipo.json").unlink()
    monkeypatch.setattr(escritorio, "base_configurada", lambda d: True)
    escritorio.main([])
    assert llamadas[-1] == ("principal",)


def test_sin_ventana_propia_sigue_como_principal(inicio, monkeypatch):
    llamadas, _ = inicio
    monkeypatch.setattr(escritorio, "inicio_con_eleccion", lambda datos, puerto=5000, **k: None)
    escritorio.main([])
    assert llamadas == [("principal",)]


def test_si_el_principal_cambio_de_direccion_lo_vuelve_a_encontrar(monkeypatch, tmp_path):
    conectados, preguntas = [], []
    monkeypatch.setattr(escritorio, "conectar", lambda destino, datos: conectados.append(destino) or 0)
    monkeypatch.setattr(escritorio, "inicio_con_eleccion", lambda datos, puerto=5000, **k: preguntas.append(k) or 0)
    eleccion = {"tipo": "caja", "principal": "192.168.1.20:5000", "negocio": "Farmacia Easy Pharma"}
    # Responde donde estaba: se conecta ahí.
    monkeypatch.setattr(escritorio, "responde_neji", lambda base, segundos=2.0: True)
    escritorio.conectar_caja(eleccion, tmp_path)
    assert conectados == ["192.168.1.20:5000"]
    # El router le dio otra dirección: se encuentra por el nombre del negocio y queda guardada.
    monkeypatch.setattr(escritorio, "responde_neji", lambda base, segundos=2.0: False)
    monkeypatch.setattr(red_local, "buscar", lambda puerto=5000, **k: [
        {"direccion": "192.168.1.31:5000", "ip": "192.168.1.31", "negocio": "Otra Farmacia", "version": "0.1.66"},
        {"direccion": "192.168.1.45:5000", "ip": "192.168.1.45", "negocio": "Farmacia Easy Pharma", "version": "0.1.66"}])
    escritorio.conectar_caja(eleccion, tmp_path)
    assert conectados[-1] == "192.168.1.45:5000"
    assert escritorio.leer_eleccion(tmp_path)["principal"] == "192.168.1.45:5000"
    # No está (o solo hay otro negocio): pregunta de nuevo, con el aviso, y busca.
    monkeypatch.setattr(red_local, "buscar", lambda puerto=5000, **k: [
        {"direccion": "192.168.1.31:5000", "ip": "192.168.1.31", "negocio": "Otra Farmacia", "version": "0.1.66"}])
    escritorio.conectar_caja(eleccion, tmp_path)
    assert len(conectados) == 2 and preguntas[-1]["buscar"] is True
    assert "Farmacia Easy Pharma" in preguntas[-1]["aviso"] and preguntas[-1]["direccion"] == "192.168.1.20:5000"


# --- La ventana del primer inicio -------------------------------------------------------------------------

class VentanaFalsa:
    def __init__(self):
        self.titulo, self.url = None, None

    def set_title(self, titulo):
        self.titulo = titulo

    def load_url(self, url):
        self.url = url


def test_elegir_caja_desde_la_ventana(monkeypatch, tmp_path):
    api = escritorio.ApiInicio(tmp_path)
    api._ventana = VentanaFalsa()
    monkeypatch.setattr(escritorio, "VERSION", "0.1.66")
    monkeypatch.setattr(red_local, "estado", lambda direccion, segundos=1.5: None)
    r = api.conectar("192.168.1.20")
    assert r["ok"] is False and "No respondió Neji POS en 192.168.1.20:5000" in r["error"]
    assert api.conectar("mi casa")["ok"] is False and escritorio.leer_eleccion(tmp_path) is None
    monkeypatch.setattr(red_local, "estado", lambda direccion, segundos=1.5: {
        "configurado": True, "negocio": "Farmacia Easy Pharma", "version": "0.1.66"})
    assert api.conectar("192.168.1.20") == {"ok": True}
    assert api._ventana.url == "http://192.168.1.20:5000/"
    assert api._ventana.titulo == "Neji POS 0.1.66 (conectado a 192.168.1.20:5000)"
    assert escritorio.leer_eleccion(tmp_path) == {"tipo": "caja", "principal": "192.168.1.20:5000",
                                                  "negocio": "Farmacia Easy Pharma"}
    # La misma ventana sigue dando las impresoras de este computador (ApiEscritorio).
    assert callable(api.impresoras) and callable(api.imprimir)


def test_elegir_principal_desde_la_ventana(monkeypatch, tmp_path):
    iniciados = []
    api = escritorio.ApiInicio(tmp_path)
    api._ventana = VentanaFalsa()
    monkeypatch.setattr(escritorio, "iniciar_principal", lambda puerto, red=False, recordar_red=False: 1)
    r = api.usar_principal(True)
    assert r["ok"] is False and escritorio.leer_eleccion(tmp_path) is None
    monkeypatch.setattr(escritorio, "iniciar_principal", lambda puerto, red=False, recordar_red=False: iniciados.append(
        (red, recordar_red)) or ("servidor", "http://127.0.0.1:5000", red))
    assert api.usar_principal(True) == {"ok": True}
    assert iniciados == [(True, True)] and api._servidor == "servidor"
    assert api._ventana.url == "http://127.0.0.1:5000/" and escritorio.leer_eleccion(tmp_path) == {"tipo": "principal"}
    # Ya es el principal: no se conecta a otro.
    assert api.conectar("192.168.1.20")["ok"] is False


def test_principal_que_acepta_cajas_queda_recordado(monkeypatch, tmp_path):
    monkeypatch.setenv("NEJI_DATOS", str(tmp_path))
    monkeypatch.setattr(escritorio, "responde_neji", lambda base, segundos=2.0: False)
    monkeypatch.setattr(escritorio, "puerto_libre", lambda host, puerto: True)
    monkeypatch.setattr(escritorio, "iniciar_servidor", lambda app, host, puerto: ("servidor", host))
    monkeypatch.setattr(escritorio, "esperar", lambda base, segundos=20: True)
    servidor, base, red = escritorio.iniciar_principal(5000, True, recordar_red=True)
    assert servidor == ("servidor", "0.0.0.0") and red is True
    from neji import equipo
    assert equipo.modo_red_configurado(str(tmp_path / "neji.db"))


def test_pagina_de_inicio():
    html = escritorio.pagina_inicio({"aviso": "</script>", "buscar": True})
    assert "¿Cómo vas a usar este computador?" in html
    assert '"aviso": "\\u003c/script>"' in html and "</script>\"" not in html
