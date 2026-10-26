"""Certificación del SII desde Neji: set de pruebas, libros, simulación, boletas con su RCOF, intercambio y muestras.

Cada XML se valida contra los esquemas oficiales del SII (tests/sii_xsd) y se verifican sus firmas; los montos de los
casos se comparan con los calculados a mano según las reglas del SII (precios netos, descuentos al peso).
"""

import io
import re
import zipfile
import zlib
from pathlib import Path

import pytest

pytest.importorskip("lxml")
pytest.importorskip("cryptography")

from lxml import etree  # noqa: E402

from neji.sii import envio, servicio  # noqa: E402
from neji.sii.firma import Firma, verificar_xml  # noqa: E402
from neji.sii.set_pruebas import codigo_referencia, leer_set, leer_set_boletas  # noqa: E402
from sets_sii import SET_BASICO, SET_BOLETAS, SET_EXENTA, SET_LIBROS  # noqa: E402
from sii_prueba import EMISOR, caf_de_prueba, pfx_de_prueba, validar_esquema  # noqa: E402

S = {"s": "http://www.sii.cl/SiiDte"}
SET_COMPLETO = SET_BASICO + SET_EXENTA + SET_LIBROS


def esquema(xml, nombre):
    validador = etree.XMLSchema(etree.parse(str(Path(__file__).with_name("sii_xsd") / nombre)))
    doc = etree.fromstring(xml)
    assert validador.validate(doc), "\n".join(str(e) for e in validador.error_log)
    return doc


def subir(api, url, archivos, **campos):
    datos = {"archivo": archivos if isinstance(archivos, list) else [archivos], **campos}
    return api.http.post(url, data=datos, content_type="multipart/form-data")


@pytest.fixture
def cert(api):
    """Emisor configurado en el ambiente de certificación, con firma y folios, pero sin activar la boleta."""
    api.put("/api/sii", {"rut": EMISOR["rut"], "razon_social": EMISOR["razon_social"], "giro": EMISOR["giro"],
                         "actecos": "477310", "direccion": EMISOR["direccion"], "comuna": EMISOR["comuna"],
                         "ciudad": EMISOR["ciudad"], "fecha_resolucion": "2026-10-01", "numero_resolucion": 0,
                         "oficina_sii": "La Serena"})
    r = subir(api, "/api/sii/firma", (io.BytesIO(pfx_de_prueba()), "firma.pfx"), clave="1234")
    assert r.status_code == 200, r.get_json()
    r = subir(api, "/api/sii/caf", [(io.BytesIO(caf_de_prueba(t, 1, 80)), f"caf{t}.xml")
                                    for t in (33, 34, 39, 41, 56, 61)])
    assert r.status_code == 200, r.get_json()
    return api


def xml_envio(app, envio_id):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    try:
        return con.execute("SELECT xml FROM sii_envios WHERE id = ?", (envio_id,)).fetchone()[0]
    finally:
        con.close()


def documentos(sobre):
    """{caso: elemento Documento} de un sobre."""
    raiz = etree.fromstring(sobre)
    resultado = {}
    for doc in raiz.findall(".//s:Documento", S):
        refs = [r.findtext("s:RazonRef", namespaces=S) for r in doc.findall("s:Referencia", S)
                if r.findtext("s:TpoDocRef", namespaces=S) in ("SET", None)]
        resultado[(refs[0] or "").replace("CASO ", "") if refs else doc.get("ID")] = doc
    return resultado


def totales(doc):
    return {e.tag.split("}")[1]: e.text for e in doc.find("s:Encabezado/s:Totales", S)}


# --- Lectura del set ------------------------------------------------------------------------------------------

def test_lee_el_set_de_pruebas():
    sets = {s["tipo"]: s for s in leer_set(SET_COMPLETO)}
    assert set(sets) == {"basico", "exenta", "libro_ventas", "libro_compras"}
    basico = sets["basico"]
    assert basico["numero_atencion"] == "4670590" and len(basico["casos"]) == 8
    caso2 = basico["casos"][1]
    assert [(i["nombre"], int(i["cantidad"]), int(i["precio"]), int(i["descuento_pct"])) for i in caso2["items"]] == [
        ("Pañuelo AFECTO", 235, 1926, 4), ("ITEM 2 AFECTO", 161, 990, 9)]
    assert basico["casos"][3]["descuento_pct"] == 17
    nc = basico["casos"][5]
    assert (nc["tipo_dte"], nc["referencia_caso"], nc["razon"]) == (61, "4670590-2", "DEVOLUCION DE MERCADERIAS")
    assert [(i["nombre"], int(i["cantidad"]), i["precio"]) for i in nc["items"]] == [
        ("Pañuelo AFECTO", 86, None), ("ITEM 2 AFECTO", 112, None)]
    assert basico["casos"][7]["tipo_dte"] == 56
    exenta = sets["exenta"]
    assert exenta["casos"][0]["items"][0]["unidad"] == "Hora"
    # Un nombre pegado a la cantidad con un solo espacio (al copiar desde la página) igual se separa.
    assert [(i["nombre"], int(i["cantidad"])) for i in exenta["casos"][1]["items"]] == [
        ("ASESORIA FINANCIERA", 1), ("CURSO EXCEL", 3)]
    compras = sets["libro_compras"]
    assert str(compras["factor"]) == "0.60" and len(compras["libro"]) == 7
    assert compras["libro"][1] == {"documento": "FACTURA ELECTRONICA", "tpo_doc": 33, "folio": 32,
                                   "observacion": "FACTURA DEL GIRO CON DERECHO A CREDITO", "exento": 10633,
                                   "afecto": 11473}
    assert [d["tpo_doc"] for d in compras["libro"]] == [30, 33, 30, 60, 33, 46, 60]
    assert [codigo_referencia(r) for r in ("ANULA FACTURA", "CORRIGE GIRO DEL RECEPTOR", "DEVOLUCION DE MERCADERIAS",
                                           "MODIFICA MONTO")] == [1, 2, 3, 3]


def test_lee_el_set_de_boletas():
    casos = leer_set_boletas(SET_BOLETAS)
    assert [c["numero"] for c in casos] == [1, 2, 3, 4, 5]
    assert casos[3]["items"][1]["exento"] and not casos[3]["items"][0]["exento"]
    assert casos[4]["items"][0]["unidad"] == "Kg"


def test_texto_que_no_es_un_set(cert):
    r = cert.post("/api/sii/certificacion/set", {"texto": "hola"}, esperado=400)
    assert "no parece un set de pruebas" in r["error"]


# --- Set de pruebas ---------------------------------------------------------------------------------------------

def test_emite_el_set_basico_y_el_exento(app, cert):
    estado = cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO})
    resultado = {r["etapa"]: r for r in estado["resultado"]}
    assert {k: v["documentos"] for k, v in resultado.items()} == {"basico": 8, "exenta": 5}

    sobre = xml_envio(app, resultado["basico"]["envio_id"])
    validar_esquema(sobre, "EnvioDTE")
    assert verificar_xml(etree.fromstring(sobre)) == 9          # 8 documentos y el sobre
    docs = documentos(sobre)
    assert set(docs) == {f"4670590-{n}" for n in range(1, 9)}
    # Montos calculados a mano: precios netos, descuentos al peso, IVA sobre el neto.
    assert totales(docs["4670590-1"]) == {"MntNeto": "191598", "TasaIVA": "19", "IVA": "36404", "MntTotal": "228002"}
    assert totales(docs["4670590-2"]) == {"MntNeto": "579551", "TasaIVA": "19", "IVA": "110115", "MntTotal": "689666"}
    assert totales(docs["4670590-3"]) == {"MntNeto": "489787", "MntExe": "34973", "TasaIVA": "19", "IVA": "93060",
                                          "MntTotal": "617820"}
    assert totales(docs["4670590-4"]) == {"MntNeto": "301390", "MntExe": "13640", "TasaIVA": "19", "IVA": "57264",
                                          "MntTotal": "372294"}
    assert totales(docs["4670590-5"]) == {"MntTotal": "0"}
    assert totales(docs["4670590-6"]) == {"MntNeto": "259912", "TasaIVA": "19", "IVA": "49383", "MntTotal": "309295"}
    assert totales(docs["4670590-7"]) == totales(docs["4670590-3"])
    assert totales(docs["4670590-8"]) == {"MntTotal": "0"}
    # Sin MntBruto (los precios del set son netos), con el descuento de línea en % y en pesos.
    assert docs["4670590-1"].find(".//s:MntBruto", S) is None
    linea = docs["4670590-2"].find("s:Detalle", S)
    assert [linea.findtext(f"s:{c}", namespaces=S) for c in ("QtyItem", "PrcItem", "DescuentoPct", "DescuentoMonto",
                                                             "MontoItem")] == ["235", "1926", "4", "18104", "434506"]
    global_ = docs["4670590-4"].find("s:DscRcgGlobal", S)
    assert [global_.findtext(f"s:{c}", namespaces=S) for c in ("TpoMov", "TpoValor", "ValorDR")] == ["D", "%", "17"]
    assert docs["4670590-3"].findall("s:Detalle", S)[2].findtext("s:IndExe", namespaces=S) == "1"
    # Referencias: el caso del set y el documento que corrige la nota, con su código.
    folio = lambda caso: docs[caso].findtext("s:Encabezado/s:IdDoc/s:Folio", namespaces=S)   # noqa: E731
    set_ref, ref = docs["4670590-6"].findall("s:Referencia", S)
    assert [set_ref.findtext(f"s:{c}", namespaces=S) for c in ("NroLinRef", "TpoDocRef", "RazonRef")] == [
        "1", "SET", "CASO 4670590-6"]
    assert set_ref.find("s:CodRef", S) is None
    assert [ref.findtext(f"s:{c}", namespaces=S) for c in ("NroLinRef", "TpoDocRef", "FolioRef", "CodRef")] == [
        "2", "33", folio("4670590-2"), "3"]
    # La devolución usa los precios y el descuento de la factura.
    assert [d.findtext("s:MontoItem", namespaces=S) for d in docs["4670590-6"].findall("s:Detalle", S)] == [
        "159011", "100901"]
    # Corrige giro: una línea sin cantidad ni precio, monto cero, «donde dice... debe decir...».
    giro = docs["4670590-5"].find("s:Detalle", S)
    assert giro.find("s:QtyItem", S) is None and giro.findtext("s:MontoItem", namespaces=S) == "0"
    assert giro.findtext("s:DscItem", namespaces=S) == "DONDE DICE: GIRO ERRONEO(A) DEBE DECIR: ADMINISTRACION PUBLICA"
    assert docs["4670590-5"].findall("s:Referencia", S)[1].findtext("s:CodRef", namespaces=S) == "2"
    # La nota de débito anula la nota de crédito 5.
    ref_nd = docs["4670590-8"].findall("s:Referencia", S)[1]
    assert [ref_nd.findtext(f"s:{c}", namespaces=S) for c in ("TpoDocRef", "FolioRef", "CodRef")] == [
        "61", folio("4670590-5"), "1"]
    # El receptor por omisión es el SII.
    assert docs["4670590-1"].findtext(".//s:RUTRecep", namespaces=S) == "60803000-K"

    exenta = documentos(xml_envio(app, resultado["exenta"]["envio_id"]))
    assert totales(exenta["4670592-1"]) == {"MntExe": "74976", "MntTotal": "74976"}
    assert exenta["4670592-1"].findtext("s:Detalle/s:UnmdItem", namespaces=S) == "Hora"
    assert totales(exenta["4670592-3"]) == {"MntExe": "14400", "MntTotal": "14400"}   # 12 horas a 1.200
    assert totales(exenta["4670592-4"]) == {"MntExe": "661042", "MntTotal": "661042"}
    assert totales(exenta["4670592-5"]) == totales(exenta["4670592-4"])

    etapas = {e["etapa"]: e for e in estado["etapas"]}
    assert etapas["basico"]["envio"]["estado"] == "por_enviar" and len(etapas["basico"]["documentos"]) == 8
    assert etapas["basico"]["documentos"][0]["caso"] == "4670590-1"


def test_el_set_se_envia_aunque_la_boleta_no_este_activa(app, cert):
    from test_sii_venta import SIIFalso

    cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO})
    assert cert.get("/api/config")["sii_activo"] == "0"
    falso = SIIFalso()
    r = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
    assert r["subidos"] == 2 and r["sobres"] == 0 and falso.clases == ["documentos", "documentos"]
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE sii_envios SET proximo = NULL")
    con.commit()
    con.close()
    assert servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)["consultados"] == 2
    etapas = {e["etapa"]: e for e in cert.get("/api/sii/certificacion")["etapas"]}
    assert etapas["basico"]["envio"]["estado"] == "procesado" and etapas["basico"]["envio"]["trackid"] == "1001"
    assert {d["estado"] for d in etapas["basico"]["documentos"]} == {"aceptado"}


def test_la_certificacion_pide_el_ambiente_de_certificacion(cert):
    cert.put("/api/sii", {"ambiente": "produccion"})
    r = cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO}, esperado=400)
    assert "ambiente de certificación" in r["error"]


def test_receptor_del_set(app, cert):
    r = cert.put("/api/sii/certificacion/receptor", {"rut": "96.790.240-3", "razon_social": "Cliente de Prueba SA",
                                                    "giro": "Comercio", "direccion": "Calle 1", "comuna": "Ovalle"})
    assert r["receptor"]["rut"] == "96790240-3"
    estado = cert.post("/api/sii/certificacion/set", {"texto": SET_BASICO})
    sobre = xml_envio(app, estado["resultado"][0]["envio_id"])
    assert documentos(sobre)["4670590-1"].findtext(".//s:RUTRecep", namespaces=S) == "96790240-3"
    cert.put("/api/sii/certificacion/receptor", {"rut": "1-2"}, esperado=400)


# --- Libros ---------------------------------------------------------------------------------------------------------

def test_libros_de_ventas_y_compras(app, cert):
    cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO})
    estado = cert.post("/api/sii/certificacion/libros", {"periodo": "2026-10"})
    libros = {r["etapa"]: r for r in estado["resultado"]}
    assert {k: v["documentos"] for k, v in libros.items()} == {"libro_ventas": 8, "libro_compras": 7}

    ventas = esquema(xml_envio(app, libros["libro_ventas"]["envio_id"]), "LibroCV_v10.xsd")
    assert verificar_xml(ventas) == 1
    assert ventas.findtext(".//s:Caratula/s:TipoOperacion", namespaces=S) == "VENTA"
    assert ventas.findtext(".//s:Caratula/s:PeriodoTributario", namespaces=S) == "2026-10"
    resumen = {t.findtext("s:TpoDoc", namespaces=S): t for t in ventas.findall(".//s:TotalesPeriodo", S)}
    assert {k: v.findtext("s:TotDoc", namespaces=S) for k, v in resumen.items()} == {"33": "4", "56": "1", "61": "3"}
    assert resumen["33"].findtext("s:TotMntTotal", namespaces=S) == str(228002 + 689666 + 617820 + 372294)
    assert resumen["61"].findtext("s:TotMntNeto", namespaces=S) == str(259912 + 489787)

    compras = esquema(xml_envio(app, libros["libro_compras"]["envio_id"]), "LibroCV_v10.xsd")
    assert verificar_xml(compras) == 1
    detalle = {d.findtext("s:NroDoc", namespaces=S): d for d in compras.findall(".//s:Detalle", S)}
    uso_comun = detalle["781"]
    assert [uso_comun.findtext(f"s:{c}", namespaces=S) for c in ("MntNeto", "MntIVA", "IVAUsoComun", "MntTotal")] == [
        "30171", "0", "5732", "35903"]
    gratuita = detalle["67"]
    assert gratuita.findtext("s:IVANoRec/s:CodIVANoRec", namespaces=S) == "4"
    retencion = detalle["9"]
    assert [retencion.findtext(f"s:{c}", namespaces=S) for c in ("TpoDoc", "IVARetTotal", "MntTotal")] == [
        "46", "1967", "10351"]
    assert retencion.findtext("s:OtrosImp/s:CodImp", namespaces=S) == "15"
    nota = detalle["451"]
    assert [nota.findtext(f"s:{c}", namespaces=S) for c in ("TpoDoc", "TpoDocRef", "FolioDocRef")] == ["60", "30", "234"]
    papel = [t for t in compras.findall(".//s:TotalesPeriodo", S) if t.findtext("s:TpoDoc", namespaces=S) == "30"][0]
    assert [papel.findtext(f"s:{c}", namespaces=S) for c in ("FctProp", "TotCredIVAUsoComun")] == ["0.6", "3439"]

    # El hilo los sube como libros (y el estado LOK los da por aceptados).
    from test_sii_venta import SIIFalso

    falso = SIIFalso(codigo="LOK")
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
    assert falso.clases.count("libro") == 2
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE sii_envios SET proximo = NULL")
    con.commit()
    con.close()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
    etapas = {e["etapa"]: e for e in cert.get("/api/sii/certificacion")["etapas"]}
    assert etapas["libro_compras"]["envio"]["estado"] == "procesado"
    assert "LOK" in etapas["libro_compras"]["envio"]["glosa"]


def test_libro_rechazado_porque_el_periodo_ya_tiene_libro(app, cert):
    from test_sii_venta import SIIFalso

    cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO})
    cert.post("/api/sii/certificacion/libros", {"periodo": "2026-10", "cuales": ["compras"]})
    falso = SIIFalso(codigo="LNC")
    from neji.db import conectar

    for _ in range(2):
        servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
        con = conectar(app.config["DATABASE"])
        con.execute("UPDATE sii_envios SET proximo = NULL")
        con.commit()
        con.close()
    etapas = {e["etapa"]: e for e in cert.get("/api/sii/certificacion")["etapas"]}
    assert etapas["libro_compras"]["envio"]["estado"] == "rechazado"
    assert "AJUSTE" in etapas["libro_compras"]["envio"]["glosa"]
    # Se puede volver a mandar como ajuste.
    cert.post("/api/sii/certificacion/libros", {"periodo": "2026-10", "cuales": ["compras"], "tipo_envio": "AJUSTE"})
    etapas = {e["etapa"]: e for e in cert.get("/api/sii/certificacion")["etapas"]}
    assert etapas["libro_compras"]["envio"]["detalle"]["tipo_envio"] == "AJUSTE"


def test_libro_de_ventas_sin_set(cert):
    r = cert.post("/api/sii/certificacion/libros", {"cuales": ["ventas"]}, esperado=400)
    assert "set básico" in r["error"]
    r = cert.post("/api/sii/certificacion/libros", {"periodo": "2026-13"}, esperado=400)
    assert "AAAA-MM" in r["error"]


# --- Simulación -----------------------------------------------------------------------------------------------------

def test_simulacion(app, cert, productos):
    estado = cert.post("/api/sii/certificacion/simulacion")
    assert estado["resultado"]["documentos"] == 11              # con folios de factura exenta, va una también
    sobre = xml_envio(app, estado["resultado"]["envio_id"])
    validar_esquema(sobre, "EnvioDTE")
    assert verificar_xml(etree.fromstring(sobre)) == 12
    docs = etree.fromstring(sobre).findall(".//s:Documento", S)
    tipos = [int(d.findtext(".//s:TipoDTE", namespaces=S)) for d in docs]
    assert tipos == [33] * 6 + [61, 61, 61, 56, 34]
    # Como en la operación real: precios con IVA (MntBruto) y productos del inventario.
    assert docs[0].findtext(".//s:MntBruto", namespaces=S) == "1"
    nombres = {d.findtext("s:NmbItem", namespaces=S) for doc in docs for d in doc.findall("s:Detalle", S)}
    assert "Bebida cola 1.5L" in nombres
    for doc in docs[6:10]:
        assert doc.find("s:Referencia/s:CodRef", S) is not None
    # La nota de débito anula la nota de crédito que anuló la factura 2: mismos montos.
    assert totales(docs[9])["MntTotal"] == totales(docs[7])["MntTotal"] == totales(docs[1])["MntTotal"]


# --- Boletas --------------------------------------------------------------------------------------------------------

def test_set_de_boletas_con_su_consumo_de_folios(app, cert):
    estado = cert.post("/api/sii/certificacion/boletas", {"texto": SET_BOLETAS})
    assert estado["resultado"]["documentos"] == 5
    sobre = xml_envio(app, estado["resultado"]["envio_id"])
    validar_esquema(sobre, "EnvioBOLETA")
    assert verificar_xml(etree.fromstring(sobre)) == 6
    docs = etree.fromstring(sobre).findall(".//s:Documento", S)
    ref = docs[0].find("s:Referencia", S)
    assert [ref.findtext(f"s:{c}", namespaces=S) for c in ("NroLinRef", "CodRef", "RazonRef")] == [
        "1", "SET", "CASO-1"]
    assert totales(docs[0]) == {"MntNeto": "25042", "IVA": "4758", "MntTotal": "29800"}
    assert totales(docs[3]) == {"MntNeto": "10689", "MntExe": "2000", "IVA": "2031", "MntTotal": "14720"}
    assert docs[4].findtext("s:Detalle/s:UnmdItem", namespaces=S) == "Kg"

    rcof = esquema(xml_envio(app, estado["resultado"]["rcof_id"]), "ConsumoFolio_v10.xsd")
    assert verificar_xml(rcof) == 1
    resumen = rcof.find(".//s:Resumen", S)
    assert [resumen.findtext(f"s:{c}", namespaces=S) for c in ("TipoDocumento", "MntTotal", "FoliosEmitidos",
                                                               "FoliosUtilizados")] == [
        "39", str(29800 + 2040 + 4100 + 14720 + 3500), "5", "5"]
    assert [resumen.findtext(f"s:RangoUtilizados/s:{c}", namespaces=S) for c in ("Inicial", "Final")] == ["1", "5"]
    assert rcof.findtext(".//s:Caratula/s:SecEnvio", namespaces=S) == "1"

    from test_sii_venta import SIIFalso

    falso = SIIFalso()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
    assert falso.clases == ["documentos", "rcof"]
    assert [b for _, b in falso.subidos] == [True, False]


# --- Intercambio ----------------------------------------------------------------------------------------------------

def envio_de_proveedor(rut_destino, otro_destino=False):
    """Un EnvioDTE de otra empresa con dos facturas a nombre de `rut_destino` (como el que manda el SII)."""
    from neji.sii import dte
    from neji.sii.caf import Caf

    proveedor = {**EMISOR, "rut": "96790240-3", "razon_social": "PROVEEDOR DE PRUEBA SA"}
    caf = Caf(caf_de_prueba(33, 1, 10, rut="96790240-3", razon="PROVEEDOR DE PRUEBA SA"))
    firma = Firma(pfx_de_prueba(), "1234")
    receptor = {"rut": rut_destino, "razon_social": "Farmacia de Prueba SpA", "giro": "Farmacia",
                "direccion": "Av. Balmaceda 1234", "comuna": "La Serena"}
    xmls = []
    for folio in (1, 2):
        destino = dict(receptor, rut="11111111-1") if otro_destino and folio == 2 else receptor
        doc = {"tipo": 33, "folio": folio, "fecha": "2026-10-26", "emisor": proveedor, "receptor": destino,
               "lineas": [{"nombre": "Caja de guantes", "cantidad": 10, "precio": 5000, "monto": 50000}]}
        xmls.append(dte.construir(doc, caf, firma)["xml"])
    return envio.construir(xmls, [33, 33], "96790240-3", firma, "2026-10-01", 0, rut_receptor=rut_destino)


def test_intercambio_las_tres_respuestas(cert):
    cert.get("/api/sii/certificacion/intercambio", esperado=404)
    r = subir(cert, "/api/sii/certificacion/intercambio",
              (io.BytesIO(envio_de_proveedor(EMISOR["rut"], otro_destino=True)), "ENVIO_DTE_123.xml"))
    assert r.status_code == 200, r.get_json()
    leido = r.get_json()
    assert leido["firma_valida"] and leido["emisor"] == "96790240-3" and len(leido["documentos"]) == 2
    r = cert.http.get("/api/sii/certificacion/intercambio")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["1_RespuestaRecepcionEnvio.xml", "2_EnvioRecibos.xml",
                                    "3_RespuestaResultadoDTE.xml"]
    recepcion = esquema(z.read("1_RespuestaRecepcionEnvio.xml"), "RespuestaEnvioDTE_v10.xsd")
    assert verificar_xml(recepcion) == 1
    assert recepcion.findtext(".//s:NmbEnvio", namespaces=S) == "ENVIO_DTE_123.xml"
    assert recepcion.findtext(".//s:EstadoRecepEnv", namespaces=S) == "0"
    assert [e.text for e in recepcion.findall(".//s:EstadoRecepDTE", S)] == ["0", "3"]   # la 2 es para otro RUT
    assert recepcion.findtext(".//s:RutRecibe", namespaces=S) == "96790240-3"
    assert recepcion.findtext(".//s:Digest", namespaces=S)
    recibos = esquema(z.read("2_EnvioRecibos.xml"), "EnvioRecibos_v10.xsd")
    assert verificar_xml(recibos) == 2                    # el recibo de la factura 1 y el set
    assert len(recibos.findall(".//s:Recibo", S)) == 1
    assert recibos.findtext(".//s:RutFirma", namespaces=S) == "13185095-6"
    resultado = esquema(z.read("3_RespuestaResultadoDTE.xml"), "RespuestaEnvioDTE_v10.xsd")
    assert verificar_xml(resultado) == 1
    assert [e.text for e in resultado.findall(".//s:EstadoDTE", S)] == ["0", "2"]
    assert resultado.findtext(".//s:NroDetalles", namespaces=S) == "2"


def test_intercambio_archivo_invalido(cert):
    r = subir(cert, "/api/sii/certificacion/intercambio", (io.BytesIO(b"no es xml"), "x.xml"))
    assert r.status_code == 400 and "XML" in r.get_json()["error"]
    r = subir(cert, "/api/sii/certificacion/intercambio",
              (io.BytesIO(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><EnvioDTE>&e;</EnvioDTE>'), "x.xml"))
    assert r.status_code == 400


# --- Muestras impresas ----------------------------------------------------------------------------------------------

def textos_del_pdf(pdf):
    """El texto de las páginas (los flujos comprimidos), para revisar lo que se imprime."""
    texto = b""
    for crudo in re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S):
        try:
            contenido = zlib.decompress(crudo)
        except zlib.error:
            continue
        if b"Tj" in contenido:
            texto += b" ".join(re.findall(rb"\((.*?)\) Tj", contenido))
    return texto.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\").decode("cp1252")


def test_muestras_impresas(app, cert):
    cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO})
    cert.post("/api/sii/certificacion/boletas", {"texto": SET_BOLETAS})
    r = cert.http.get("/api/sii/certificacion/muestras")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.data))
    pdfs = [n for n in z.namelist() if n.endswith(".pdf")]
    # 8 del básico (4 facturas con su cedible) + 5 del exento (2 cedibles) + 5 boletas.
    assert len(pdfs) == 8 + 4 + 5 + 2 + 5
    for nombre in pdfs:
        pdf = z.read(nombre)
        assert pdf.startswith(b"%PDF-1.4") and len(pdf) < 500_000       # el SII acepta hasta 500 KB
        assert pdf.count(b"/Type /Page ") == 1 and b"/Subtype /Image" in pdf
    factura = textos_del_pdf(z.read("basico_caso_4670590-2_factura_2.pdf"))
    for esperado in ("FACTURA ELECTRÓNICA", "R.U.T.: 76.354.771-K", "S.I.I. - LA SERENA", "Timbre Electrónico SII",
                     "Res. 0 de 2026 - Verifique documento: www.sii.cl", "$434.506", "$18.104", "IVA (19%)",
                     "Set de pruebas: CASO 4670590-2", "Fecha de emisión"):
        assert esperado in factura, esperado
    assert "CEDIBLE" not in factura and "ACUSE DE RECIBO" not in factura
    cedible = textos_del_pdf(z.read("basico_caso_4670590-2_factura_2_cedible.pdf"))
    assert "CEDIBLE" in cedible and "ACUSE DE RECIBO" in cedible and "Recinto:" in cedible
    nota = textos_del_pdf(z.read("basico_caso_4670590-6_nota_credito_2.pdf"))
    assert "Factura electrónica N° 2" in nota and "Motivo: Corrige montos - DEVOLUCION DE MERCADERIAS" in nota
    exenta = textos_del_pdf(z.read("exenta_caso_4670592-1_factura_exenta_1.pdf"))
    assert "Monto exento" in exenta and "IVA" not in exenta and "Monto neto" not in exenta
    boleta = textos_del_pdf(z.read("boletas_caso_CASO-1_boleta_1.pdf"))
    assert "BOLETA ELECTRÓNICA" in boleta and "Timbre Electrónico SII" in boleta
    assert not any(n.endswith("_cedible.pdf") for n in z.namelist() if "nota" in n)


def test_muestras_sin_documentos(cert):
    r = cert.http.get("/api/sii/certificacion/muestras")
    assert r.status_code == 400 and "set de pruebas" in r.get_json()["error"]


def test_libro_de_compras_para_exentos():
    from neji.sii import libros
    from sets_sii import SET_COMPRAS_EXENTOS

    set_, = leer_set(SET_COMPRAS_EXENTOS)
    assert set_["tipo"] == "libro_compras_exentos"
    assert [(d["tpo_doc"], d["folio"], d["exento"], d["afecto"]) for d in set_["libro"]] == [
        (30, 2061, None, 12345), (32, 321, 5000, None), (33, 45, 1500, 8000)]
    detalle = libros.detalle_compras(set_["libro"], "2026-10", "2026-10-26", exentos=True)
    papel, exenta, electronica = detalle
    # Un contribuyente exento no recupera IVA: va como no recuperable (código 1) y el IVA recuperable en cero.
    assert (papel["MntIVA"], papel["IVANoRec"], papel["MntTotal"]) == (0, {"CodIVANoRec": 1, "MntIVANoRec": 2346},
                                                                      14691)
    assert exenta["TpoDoc"] == 32 and "MntNeto" not in exenta and exenta["MntTotal"] == 5000
    assert electronica["MntTotal"] == 1500 + 8000 + 1520
    xml = libros.construir("COMPRA", detalle, EMISOR["rut"], Firma(pfx_de_prueba(), "1234"), "2026-10",
                           "2026-10-01", 0)
    assert verificar_xml(esquema(xml, "LibroCV_v10.xsd")) == 1


def test_sin_folios_suficientes_no_se_emite_nada(app, cert):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("DELETE FROM sii_caf WHERE tipo = 34")
    con.commit()
    con.close()
    r = cert.post("/api/sii/certificacion/set", {"texto": SET_COMPLETO}, esperado=400)
    assert "factura no afecta o exenta electrónica (34): se necesitan 2 y quedan 0" in r["error"]
    assert all(e["envio"] is None for e in cert.get("/api/sii/certificacion")["etapas"])
