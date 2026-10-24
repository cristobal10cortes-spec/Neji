"""Impresoras leídas directo del USB y lectores de códigos por puerto COM (NejiPOS.exe)."""

import logging
import sys
import threading
import time
import types

import pytest

from neji import impresora_usb as usb
from neji import impresoras as imp
from neji import lector_serie as ls

RUTA = r"\\?\usb#vid_0416&pid_5011#5&2c6b5b6b&0&1#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"


def test_nombre_desde_el_identificador_de_la_impresora():
    assert usb.leer_1284("MFG:POS;CMD:ESC/POS;MDL:POS-80C;CLS:PRINTER;")["MDL"] == "POS-80C"
    assert usb.nombre_impresora("MFG:POS;CMD:ESC/POS;MDL:POS-80C;", RUTA) == "POS-80C"   # sin repetir la marca
    assert usb.nombre_impresora("MFG:Xprinter;MDL:XP-58IIH;", RUTA) == "Xprinter XP-58IIH"
    assert usb.nombre_impresora("MANUFACTURER:EPSON;MODEL:EPSON TM-T20II;COMMAND SET:ESC/POS;", RUTA) == "EPSON TM-T20II"
    assert usb.nombre_impresora("", RUTA) == "Impresora USB 0416:5011"      # sin identificador: VID:PID
    assert usb.es_de_oficina("MFG:HP;MDL:LaserJet;CMD:PJL,PCL,PCLXL,POSTSCRIPT;")
    assert not usb.es_de_oficina("MFG:POS;CMD:ESC/POS;MDL:POS-58;")


def _windows(*impresoras):
    return [{"nombre": n, "puerto": p, "controlador": n, "predeterminada": d, "sin_conexion": False, "sin_papel": False,
             "con_error": False, **imp.clasificar(n, p, n)} for n, p, d in impresoras]


def test_lista_las_usb_sin_controlador_y_no_repite_las_instaladas(monkeypatch):
    monkeypatch.setattr(imp, "_listar_windows", lambda: _windows(("POS-80C", "USB001", False), ("HP LaserJet", "USB002", True)))
    monkeypatch.setattr(imp, "_usb", lambda: [
        {"nombre": "POS POS-80C", "ruta": "r1", "puerto": "USB001", "id_1284": "", "oficina": False},     # ya instalada
        {"nombre": "POS POS-58", "ruta": "r3", "puerto": "", "id_1284": "", "oficina": False},           # sin controlador
        {"nombre": "Canon LBP", "ruta": "r4", "puerto": "", "id_1284": "", "oficina": True},
    ])
    lista = imp.listar()
    nombres = [i["nombre"] for i in lista]
    assert nombres[:2] == ["POS-80C", "POS POS-58 (USB directo)"]   # las de tickets primero; la instalada antes
    assert "POS POS-80C (USB directo)" not in nombres
    pos80 = next(i for i in lista if i["nombre"] == "POS-80C")
    assert pos80["usb_directo"] and not pos80.get("solo_usb")
    directa = next(i for i in lista if i["nombre"] == "POS POS-58 (USB directo)")
    assert directa["termica"] and directa["solo_usb"] and directa["conexion"] == "USB"
    assert not next(i for i in lista if i["nombre"] == "Canon LBP (USB directo)")["termica"]


def test_con_la_cola_de_impresion_detenida_igual_se_ven_las_usb(monkeypatch):
    def detenida():
        raise imp.ErrorImpresora("El servicio «Cola de impresión» de Windows está detenido.")
    monkeypatch.setattr(imp, "_listar_windows", detenida)
    monkeypatch.setattr(imp, "_usb", lambda: [{"nombre": "POS-58", "ruta": "r", "puerto": "", "id_1284": "", "oficina": False}])
    assert [i["nombre"] for i in imp.listar()] == ["POS-58 (USB directo)"]
    monkeypatch.setattr(imp, "_usb", lambda: [])
    with pytest.raises(imp.ErrorImpresora, match="Cola de impresión"):
        imp.listar()


@pytest.fixture
def envios(monkeypatch):
    """Registra lo que se manda por USB y por la cola de Windows."""
    registro = {"usb": [], "cola": [], "falla_usb": None}
    monkeypatch.setattr(imp, "_listar_windows", lambda: _windows(("POS-80C", "USB001", True), ("Archivo", "FILE:", False)))
    monkeypatch.setattr(imp, "_usb", lambda: [
        {"nombre": "POS-80C", "ruta": "ruta-instalada", "puerto": "USB001", "id_1284": "", "oficina": False},
        {"nombre": "POS-58", "ruta": "ruta-sin-controlador", "puerto": "", "id_1284": "", "oficina": False},
    ])

    def escribir(ruta, datos, espera=15):
        if registro["falla_usb"]:
            raise registro["falla_usb"]
        registro["usb"].append((ruta, bytes(datos)))
    monkeypatch.setattr(usb, "escribir", escribir)
    monkeypatch.setattr(imp, "imprimir_crudo", lambda nombre, datos, documento="": registro["cola"].append((nombre, bytes(datos))))
    monkeypatch.setattr(imp, "imprimir_windows", lambda *a, **k: registro["cola"].append(("GDI", b"")))
    return registro


BLOQUES = [{"tipo": "texto", "texto": "Prueba"}]


def test_la_usb_sin_controlador_imprime_directo_aunque_pidan_modo_windows(envios):
    imp.imprimir_trabajo({"impresora": "POS-58 (USB directo)", "modo": "windows", "bloques": BLOQUES})
    assert [r for r, _ in envios["usb"]] == ["ruta-sin-controlador"] and envios["cola"] == []
    assert envios["usb"][0][1].startswith(imp.INICIAR)


def test_la_instalada_en_usb_va_directo_y_si_el_usb_esta_ocupado_por_la_cola(envios):
    imp.imprimir_trabajo({"impresora": "POS-80C", "bloques": BLOQUES})
    assert [r for r, _ in envios["usb"]] == ["ruta-instalada"] and envios["cola"] == []
    envios["usb"].clear()
    envios["falla_usb"] = usb.ErrorAbrirUSB("No se pudo abrir la impresora USB (código 32).")
    imp.imprimir_trabajo({"impresora": "POS-80C", "bloques": BLOQUES})
    assert [n for n, _ in envios["cola"]] == ["POS-80C"]                  # se usó la cola de Windows


def test_si_la_usb_no_responde_se_avisa_sin_mandarlo_a_la_cola(envios):
    envios["falla_usb"] = usb.ErrorUSB("La impresora USB no responde. Revisa que tenga papel...")
    with pytest.raises(imp.ErrorImpresora, match="no responde"):
        imp.imprimir_trabajo({"impresora": "POS-80C", "bloques": BLOQUES})
    assert envios["cola"] == []


def test_sin_usb_directo_o_en_otro_puerto_va_por_la_cola(envios):
    imp.imprimir_trabajo({"impresora": "POS-80C", "usb_directo": False, "bloques": BLOQUES})
    imp.imprimir_trabajo({"impresora": "Archivo", "bloques": BLOQUES})
    assert envios["usb"] == [] and [n for n, _ in envios["cola"]] == ["POS-80C", "Archivo"]


def test_usb_directo_desconectada_avisa(envios, monkeypatch):
    monkeypatch.setattr(imp, "_usb", lambda: [])
    with pytest.raises(imp.ErrorImpresora, match="conectada por USB"):
        imp.imprimir_trabajo({"impresora": "POS-58 (USB directo)", "bloques": BLOQUES})


def test_fuera_de_windows_no_hay_usb_directo():
    if sys.platform == "win32":
        pytest.skip("en Windows sí hay")
    with pytest.raises(usb.ErrorUSB, match="Windows"):
        usb.listar()


# --- Lectores por puerto COM --------------------------------------------------------------------------

def test_acumulador_separa_los_codigos():
    a = ls.Acumulador(pausa=0.25)
    assert a.agregar(b"7800001\r\n78000", 1.0) == ["7800001"]
    assert a.vencidos(1.1) == []                        # todavía puede llegar el resto
    assert a.agregar(b"04\r", 1.15) == ["7800004"]
    assert a.agregar(b"\x02ABC123\x03", 2.0) == []      # sin terminador y con caracteres de control
    assert a.vencidos(2.3) == ["ABC123"]
    assert a.agregar(b"\r\n\r\n", 3.0) == []            # Enter sueltos no son códigos


def test_reconoce_lectores_por_fabricante_o_descripcion():
    assert ls.parece_lector(0x0C2E, "USB Serial Device")           # Honeywell
    assert ls.parece_lector(0x1A86, "Barcode Scanner (COM5)")
    assert not ls.parece_lector(0x1A86, "USB-SERIAL CH340 (COM3)")   # podría ser otra cosa: se activa a mano


class PuertoFalso:
    def __init__(self, device, vid, description):
        self.device, self.vid, self.description, self.manufacturer, self.product = device, vid, description, "", ""


def test_lee_los_lectores_y_respeta_lo_elegido(monkeypatch):
    leidos = {"COM5": [b"7800001\r", b"78000", b"04\n"], "COM3": [b"NO-DEBERIA\r"]}

    class Serial:
        def __init__(self, puerto, baudios, timeout):
            self.puerto = puerto
            self.datos = list(leidos.get(puerto, []))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            if self.datos:
                return self.datos.pop(0)
            time.sleep(0.01)
            return b""

    falso = types.ModuleType("serial")
    falso.Serial = Serial
    falso.SerialException = OSError
    monkeypatch.setitem(sys.modules, "serial", falso)
    elegidos = {}
    lector = ls.LectorSerie(excluir=lambda: {"COM7"}, elegidos=lambda: elegidos)
    puertos = [PuertoFalso("COM5", 0x0C2E, "Honeywell Scanner"), PuertoFalso("COM3", 0x1A86, "USB-SERIAL CH340"),
               PuertoFalso("COM7", 0x0416, "POS-80 Barcode printer"), PuertoFalso("COM1", None, "Puerto de comunicaciones")]
    lector.revisar(lambda: puertos)
    try:
        codigos = []
        limite = time.monotonic() + 3
        while len(codigos) < 2 and time.monotonic() < limite:
            codigos += lector.esperar(0.5)
        assert codigos == ["7800001", "7800004"]
        estado = {p["puerto"]: p for p in lector.estado()}
        assert set(estado) == {"COM5", "COM3", "COM7"}                     # COM1 no es USB
        assert estado["COM5"]["usar"] and not estado["COM3"]["usar"]       # CH340 desconocido: a mano
        assert estado["COM7"]["impresora"] and not estado["COM7"]["usar"]  # el de la impresora no se abre
        assert estado["COM5"]["ultima"] == "7800004"
        # Elegido a mano: también se lee.
        elegidos["COM3"] = True
        lector.revisar(lambda: puertos)
        assert lector.esperar(2) == ["NO-DEBERIA"]
        # Desenchufado.
        lector.revisar(lambda: puertos[:1])
        assert {p["puerto"]: p["estado"] for p in lector.estado()}["COM3"] == "desconectado"
    finally:
        lector.detener()


def test_si_la_ventana_se_recarga_la_espera_anterior_no_se_lleva_el_codigo():
    lector = ls.LectorSerie()
    vieja = {}
    hilo = threading.Thread(target=lambda: vieja.setdefault("codigos", lector.esperar(5)))
    hilo.start()
    time.sleep(0.2)
    nueva = {}
    hilo2 = threading.Thread(target=lambda: nueva.setdefault("codigos", lector.esperar(5)))
    hilo2.start()
    hilo.join(2)
    assert not hilo.is_alive() and vieja["codigos"] == []    # la de la página que ya no está se retira
    lector.recibir("COM5", "7800001")
    hilo2.join(2)
    assert nueva["codigos"] == ["7800001"]


def test_un_puerto_ocupado_se_anota_una_vez_en_el_registro(monkeypatch, caplog):
    class Ocupado:
        def __init__(self, *a, **k):
            raise OSError("Acceso denegado")

    falso = types.ModuleType("serial")
    falso.Serial = Ocupado
    falso.SerialException = OSError
    monkeypatch.setitem(sys.modules, "serial", falso)
    lector = ls.LectorSerie()
    lector.puertos["COM5"] = {"puerto": "COM5", "estado": "sin usar", "ultima": "", "usar": True}
    with caplog.at_level(logging.WARNING, logger="neji.lector"):
        for _ in range(3):   # los reintentos de revisar()
            lector._leer("COM5")
    assert len([r for r in caplog.records if "COM5" in r.getMessage()]) == 1
    assert lector.estado()[0]["estado"].startswith("no se pudo abrir")
