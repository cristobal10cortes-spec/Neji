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
