"""Tickets para impresoras térmicas: columnas, ESC/POS, tildes y detección del tipo de impresora."""

import pytest

from neji import impresoras as imp


BLOQUES = [
    {"tipo": "texto", "texto": "Farmacia Easy Pharma", "alinear": "centro", "negrita": True, "grande": True},
    {"tipo": "texto", "texto": "RUT: 76.086.428-5", "alinear": "centro"},
    {"tipo": "linea"},
    {"tipo": "par", "izq": "Folio: 1024", "der": "08-10-2026 12:30"},
    {"tipo": "texto", "texto": "Caja 1 · Atendió: Cristóbal Araya Cortés"},
    {"tipo": "texto", "texto": "PARACETAMOL 500MG X 16 COMP"},
    {"tipo": "par", "izq": "  2 x $990", "der": "$1.980"},
    {"tipo": "par", "izq": "TOTAL", "der": "$3.870", "negrita": True, "grande": True},
    {"tipo": "espacio", "lineas": 2},
]


def test_componer_ajusta_al_ancho_del_papel():
    for columnas in (48, 32):
        renglones = imp.componer(BLOQUES, columnas)
        for texto, _, grande in renglones:
            assert len(texto) <= (columnas // 2 if grande else columnas)
        textos = [r[0] for r in renglones]
        assert textos[0].strip() == "Farmacia Easy Pharma"[:columnas // 2] or "Farmacia" in textos[0]
        assert "-" * columnas in textos
        assert any(t.startswith("Folio: 1024") and t.endswith("08-10-2026 12:30") for t in textos)
        total = next(t for t, _, g in renglones if g and "TOTAL" in t)
        assert total.startswith("TOTAL") and total.endswith("$3.870") and len(total) == columnas // 2
        assert textos[-2:] == ["", ""]


def test_par_largo_baja_el_monto_a_otra_linea():
    r = imp.componer([{"tipo": "par", "izq": "x" * 40, "der": "$123.456"}], 32)
    assert [t for t, _, _ in r] == ["x" * 32, "x" * 8 + " " * 16 + "$123.456"]


def test_escpos_con_tildes_corte_y_cajon():
    datos = imp.escpos(imp.componer(BLOQUES, 48), cortar=True, cajon=True)
    assert datos.startswith(b"\x1b@\x1bt\x02")             # iniciar + página de códigos 850
    assert imp.ABRIR_CAJON in datos and datos.endswith(imp.AVANZAR + imp.CORTAR)
    assert "Atendió: Cristóbal Araya Cortés".encode("cp850") in datos
    assert "·".encode("cp850") in datos                      # el punto medio existe en la 850
    assert imp.GRANDE[0] in datos and imp.NEGRITA[0] in datos
    sin_corte = imp.escpos(imp.componer(BLOQUES, 48), cortar=False)
    assert imp.CORTAR not in sin_corte and imp.ABRIR_CAJON not in sin_corte
    # Solo abrir el cajón (sin ticket): ni avance ni corte.
    assert imp.escpos([], cajon=True) == b"\x1b@\x1bt\x02" + imp.ABRIR_CAJON


def test_letras_que_no_existen_se_aproximan():
    datos = imp.escpos([("Ñandú — 10 € … “ok”", False, False)], codigo="cp850")
    assert "Ñandú - 10 EUR ... \"ok\"".encode("cp850") in datos
    assert "€".encode("cp858") in imp.escpos([("10 €", False, False)], codigo="cp858")


def test_leer_trabajo_valida_y_limita():
    t = imp.leer_trabajo({"impresora": " POS-80 ", "modo": "raro", "papel": "58", "copias": 99,
                          "codigo": "inventado", "bloques": BLOQUES})
    assert t["impresora"] == "POS-80" and t["modo"] == "escpos" and t["columnas"] == 32
    assert t["copias"] == 5 and t["codigo"] == "cp850" and t["cortar"] is True and t["papel_mm"] == 48
    with pytest.raises(imp.ErrorImpresora):
        imp.leer_trabajo({"impresora": "", "bloques": []})
    with pytest.raises(imp.ErrorImpresora):
        imp.leer_trabajo({"impresora": "X", "bloques": "no"})


@pytest.mark.parametrize("nombre,puerto,controlador,termica,virtual,conexion", [
    ("POS-80C", "USB001", "POS-80C", True, False, "USB"),
    ("POS58 Printer", "USB002", "POS58 Printer Driver", True, False, "USB"),
    ("SLK-TS100", "USB003", "SLK TS100", True, False, "USB"),
    ("EPSON TM-T20II Receipt", "ESDPRT001", "EPSON TM-T20II Receipt5", True, False, "ESDPRT001"),
    ("XP-80", "COM3:", "XP-80", True, False, "COM3"),
    ("HP LaserJet M111w", "WSD-1234", "HP LaserJet M110w", False, False, "Red"),
    ("Microsoft Print to PDF", "PORTPROMPT:", "Microsoft Print To PDF", False, True, "PORTPROMPT:"),
    ("OneNote (Desktop)", "nul:", "Send to Microsoft OneNote 16 Driver", False, True, "nul:"),
    # Térmicas que antes no se reconocían, o que tienen «Series» en el nombre
    ("POS-80 Series", "USB001", "POS-80 Series", True, False, "USB"),
    ("80mm Series Printer", "USB001", "80mm Series Printer", True, False, "USB"),
    ("GP-80250 Series", "USB001", "GP-80250 Series", True, False, "USB"),
    ("ZJ-5890", "USB001", "ZJ-5890K", True, False, "USB"),
    ("XP-N160II", "USB001", "XP-N160II", True, False, "USB"),
    ("Caja", "USB001", "Generic / Text Only", True, False, "USB"),
    # De oficina o con nombres que solo se parecen: nunca de tickets
    ("EPSON XP-2100 Series", "USB001", "EPSON XP-2100 Series", False, False, "USB"),
    ("Brother HL-L5100DN series BR-Script3", "IP_10.0.0.4", "Brother HL-L5100DN series BR-Script3", False, False, "Red"),
    ("Xerox VersaLink B405", "IP_10.0.0.5", "Xerox Global Print Driver PostScript", False, False, "Red"),
    ("Deposito Bodega", "USB001", "HP DeskJet 2700 series", False, False, "USB"),
    ("Customer Desk Printer", "USB001", "Canon PIXMA G3110", False, False, "USB"),
    ("ZDesigner GK420t", "USB001", "ZDesigner GK420t", False, False, "USB"),
])
def test_clasificar_impresoras(nombre, puerto, controlador, termica, virtual, conexion):
    c = imp.clasificar(nombre, puerto, controlador)
    assert (c["termica"], c["virtual"], c["conexion"]) == (termica, virtual, conexion)


def test_fuera_de_windows_avisa():
    import sys
    if sys.platform == "win32":
        pytest.skip("en Windows sí se puede")
    with pytest.raises(imp.ErrorImpresora, match="Windows"):
        imp.listar()


def test_modo_chino_se_apaga_en_las_genericas():
    con = imp.escpos([("Ñandú", False, False)], sin_chino=True)
    assert con.startswith(b"\x1b@" + imp.SIN_CHINO + b"\x1bt\x02")
    assert imp.SIN_CHINO not in imp.escpos([("Ñandú", False, False)])
    assert imp.leer_trabajo({"impresora": "POS-80C", "bloques": []})["sin_chino"] is True
    assert imp.leer_trabajo({"impresora": "XP-58", "bloques": []})["sin_chino"] is True
    assert imp.leer_trabajo({"impresora": "EPSON TM-T20II Receipt", "bloques": []})["sin_chino"] is False
    assert imp.leer_trabajo({"impresora": "POS-80C", "sin_chino": False, "bloques": []})["sin_chino"] is False


def test_modo_windows_si_falla_el_cajon_el_ticket_igual_salio(monkeypatch):
    llamadas = []
    monkeypatch.setattr(imp, "imprimir_windows", lambda *a, **k: llamadas.append("ticket"))

    def crudo(nombre, datos, documento="Ticket Neji POS"):
        llamadas.append("cajon")
        raise imp.ErrorImpresora("La impresora «HP» no acepta impresión directa (ESC/POS).")
    monkeypatch.setattr(imp, "imprimir_crudo", crudo)
    aviso = imp.imprimir_trabajo({"impresora": "HP", "modo": "windows", "cajon": True, "copias": 2, "bloques": BLOQUES})
    assert llamadas == ["ticket", "cajon", "ticket"]          # el cajón solo con la primera copia
    assert aviso and "no se pudo abrir el cajón" in aviso
    monkeypatch.setattr(imp, "imprimir_crudo", lambda *a, **k: None)
    assert imp.imprimir_trabajo({"impresora": "HP", "modo": "windows", "cajon": True, "bloques": BLOQUES}) is None


def test_cola_de_impresion_detenida_se_explica(monkeypatch):
    """EnumPrintersW falla con 1722 cuando el servicio de impresión está detenido: no es «no hay impresoras»."""
    import ctypes
    import types
    from ctypes import wintypes

    for codigo, esperado in ((1722, "Cola de impresión"), (5, "código 5")):
        falso_ctypes = types.SimpleNamespace(**{k: getattr(ctypes, k) for k in dir(ctypes) if not k.startswith("__")})
        falso_ctypes.get_last_error = lambda c=codigo: c
        falso_ctypes.FormatError = lambda c: "Acceso denegado."
        w = types.SimpleNamespace(EnumPrintersW=lambda *a: 0)
        monkeypatch.setattr(imp, "_winspool", lambda: (falso_ctypes, wintypes, w))
        with pytest.raises(imp.ErrorImpresora, match=esperado):
            imp.listar()
