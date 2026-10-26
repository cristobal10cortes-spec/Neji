"""Modo demostración: boletas y facturas timbradas con folios y firma de mentira, que nunca van al SII."""

import io

import pytest

pytest.importorskip("lxml")
pytest.importorskip("cryptography")

from lxml import etree  # noqa: E402

from neji.sii import demostracion, envio, servicio  # noqa: E402
from neji.sii.firma import verificar_xml  # noqa: E402
from sii_prueba import EMISOR, caf_de_prueba, pfx_de_prueba, validar_esquema  # noqa: E402
from test_sii_nucleo import verificar_timbre  # noqa: E402

SII = "{http://www.sii.cl/SiiDte}"


def subir(api, url, archivos, **campos):
    datos = {"archivo": archivos if isinstance(archivos, list) else [archivos], **campos}
    return api.http.post(url, data=datos, content_type="multipart/form-data")


def vender(api, productos, items=None, **extra):
    datos = {"caja_id": 1, "items": items or [{"producto_id": productos["bebida"]["id"], "cantidad": 2}], **extra}
    return api.post("/api/ventas", datos, esperado=201)


def xml_de(app, documento_id):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    try:
        return con.execute("SELECT xml FROM sii_documentos WHERE id = ?", (documento_id,)).fetchone()[0]
    finally:
        con.close()


def contar(app, sql, *parametros):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    try:
        return con.execute(sql, parametros).fetchone()[0]
    finally:
        con.close()


class SIIQueAnota:
    """Hace de SII: anota lo que se le sube (no debe llegarle nada de demostración)."""

    def __init__(self):
        self.subidos = []

    def enviar(self, xml, boleta, clase="documentos"):
        self.subidos.append(xml)
        return str(1000 + len(self.subidos))

    def estado(self, trackid, boleta, clase="documentos"):
        return {"estado": "EPR", "final": True, "glosa": "", "informados": 1, "aceptados": 1, "rechazados": 0,
                "reparos": 0, "detalle": []}


def configurar_sii(api, ambiente="certificacion"):
    """La boleta electrónica de verdad, lista y activada (como en test_sii_venta)."""
    api.put("/api/sii", {"rut": EMISOR["rut"], "razon_social": EMISOR["razon_social"], "giro": EMISOR["giro"],
                         "actecos": "477310", "direccion": EMISOR["direccion"], "comuna": EMISOR["comuna"],
                         "ciudad": EMISOR["ciudad"], "fecha_resolucion": "2026-10-01", "numero_resolucion": 0,
                         "ambiente": ambiente})
    assert subir(api, "/api/sii/firma", (io.BytesIO(pfx_de_prueba()), "firma.pfx"), clave="1234").status_code == 200
    r = subir(api, "/api/sii/caf", [(io.BytesIO(caf_de_prueba(t, 1, 3)), f"caf{t}.xml") for t in (39, 61)])
    assert r.status_code == 200, r.get_json()
    return api.put("/api/sii", {"activo": True})


def test_sin_configurar_nada_la_venta_sale_con_boleta_timbrada(app, api, productos, turno):
    estado = api.get("/api/sii")
    assert estado["demo"]["activo"] is False and api.get("/api/config")["sii_activo"] == "0"
    # Sin datos del SII, el emisor es el negocio (Configuración → Negocio).
    assert estado["demo"]["emisor"] == {"rut": "76086428-5", "razon_social": "Almacén Prueba"}
    assert estado["demo"]["de_ejemplo"] == ["el giro", "la dirección", "la comuna"]
    estado = api.put("/api/sii/demo", {"activo": True})
    assert estado["demo"]["activo"] is True and estado["config"]["activo"] == "0"
    config = api.get("/api/config")
    assert (config["sii_activo"], config["sii_ambiente"]) == ("1", "demostracion")

    venta = vender(api, productos)
    assert venta["avisos"] == []
    doc, = venta["documentos"]
    assert (doc["tipo"], doc["folio"], doc["ambiente"], doc["demo"], doc["total"]) == (
        39, 1, "demostracion", True, venta["total"])
    assert doc["estado_texto"] == "Demostración: no se envía al SII"
    assert doc["ted"].startswith('<TED version="1.0">') and doc["pdf417"]
    assert (doc["emisor"]["rut"], doc["emisor"]["razon_social"]) == ("76086428-5", "Almacén Prueba")
    # Un documento completo: firmado, con el timbre del CAF de demostración y según el esquema del SII.
    xml = xml_de(app, doc["id"])
    raiz = etree.fromstring(xml)
    assert verificar_xml(raiz) == 1
    validar_esquema(envio.construir([xml], [39], "76086428-5", demostracion.firma(), "2026-10-01", 0), "EnvioBOLETA")
    caf = demostracion.caf("76086428-5", "Almacén Prueba", 39)
    assert caf.desde == 1 and caf.llave.key_size == 512             # como los del SII: el timbre mide lo mismo
    assert verificar_timbre(xml, caf).findtext("DD/F") == "1"
    assert vender(api, productos)["documentos"][0]["folio"] == 2
    # El listado de Configuración muestra los de demostración mientras está encendido.
    listado = api.get("/api/sii/documentos")
    assert [(d["folio"], d["estado_texto"]) for d in listado] == [(2, "Demostración: no se envía al SII"),
                                                                 (1, "Demostración: no se envía al SII")]
    assert api.get("/api/sii")["demo"]["documentos"] == 2


def test_lo_de_demostracion_nunca_se_envia_al_sii(app, api, productos, turno):
    configurar_sii(api)
    api.put("/api/sii/demo", {"activo": True})
    venta = vender(api, productos)
    assert venta["documentos"][0]["ambiente"] == "demostracion"
    # La firma y los folios de verdad no se usan: los 3 folios de boleta siguen disponibles.
    estado = api.get("/api/sii")
    assert {f["tipo"]: f["disponibles"] for f in estado["folios"]} == {39: 3, 61: 3}
    assert estado["config"]["ambiente"] == "certificacion" and estado["config"]["activo"] == "1"
    sii = SIIQueAnota()
    resumen = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=sii)
    assert (resumen["sobres"], resumen["subidos"], sii.subidos) == (0, 0, [])
    assert contar(app, "SELECT COUNT(*) FROM sii_envios") == 0

    # Al apagarlo vuelve la boleta de verdad, con sus folios, y solo ella va al SII.
    api.put("/api/sii/demo", {"activo": False})
    assert api.get("/api/config")["sii_ambiente"] == "certificacion"
    real = vender(api, productos)["documentos"][0]
    assert (real["ambiente"], real["folio"], real["demo"]) == ("certificacion", 1, False)
    resumen = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=sii)
    assert resumen["subidos"] == 1
    sobre = etree.fromstring(sii.subidos[0])
    assert [d.findtext(f".//{SII}Folio") for d in sobre.iter(f"{SII}DTE")] == ["1"]
    assert contar(app, "SELECT COUNT(*) FROM sii_documentos WHERE ambiente = 'demostracion' AND envio_id IS NULL "
                       "AND estado = 'pendiente'") == 1
    assert [d["folio"] for d in api.get("/api/sii/documentos")] == [1]
    assert [d["ambiente"] for d in api.get("/api/sii/documentos")] == ["certificacion"]


def test_factura_y_nota_de_credito_de_demostracion(app, api, productos, turno):
    api.put("/api/sii/demo", {"activo": True})
    cliente = api.post("/api/clientes", {"nombre": "Minera Los Pelambres", "rut": "96.790.240-3", "giro": "Minería",
                                         "direccion": "Av. Apoquindo 4001", "comuna": "Las Condes",
                                         "email": "dte@minera.cl"}, esperado=201)
    venta = vender(api, productos, documento="factura", cliente_id=cliente["id"])
    factura = venta["documentos"][0]
    assert (factura["tipo"], factura["folio"], factura["demo"], factura["correo"]) == (33, 1, True, None)
    validar_esquema(xml_de(app, factura["id"]), "DTE")
    devolucion = api.post(f"/api/ventas/{venta['id']}/devolucion", {"caja_id": 1, "todo": True}, esperado=201)
    nota = devolucion["documentos"][-1]
    assert (nota["tipo"], nota["folio"], nota["demo"]) == (61, 1, True)
    assert nota["referencias"][0]["tipo"] == 33 and nota["referencias"][0]["codigo"] == 1
    assert contar(app, "SELECT COUNT(*) FROM sii_documentos WHERE correo_estado IS NOT NULL") == 0


def test_usa_los_datos_de_la_empresa_del_sii(api, productos, turno):
    api.put("/api/sii", {"rut": "96.790.240-3", "razon_social": "Easy Pharma SpA", "giro": "Farmacia",
                         "direccion": "Balmaceda 123", "comuna": "La Serena"})
    estado = api.put("/api/sii/demo", {"activo": True})
    assert estado["demo"]["emisor"] == {"rut": "96790240-3", "razon_social": "Easy Pharma SpA"}
    assert estado["demo"]["de_ejemplo"] == []
    doc = vender(api, productos)["documentos"][0]
    assert {k: doc["emisor"][k] for k in ("rut", "razon_social", "giro", "direccion", "comuna")} == {
        "rut": "96790240-3", "razon_social": "Easy Pharma SpA", "giro": "Farmacia", "direccion": "Balmaceda 123",
        "comuna": "La Serena"}


def test_no_se_enciende_con_la_boleta_de_verdad_en_produccion(api):
    configurar_sii(api)
    api.put("/api/sii/demo", {"activo": True})
    # Al activar producción se apaga la demostración: ahí las ventas llevan la boleta de verdad.
    api.put("/api/sii", {"ambiente": "produccion", "activo": False})
    assert subir(api, "/api/sii/caf", (io.BytesIO(caf_de_prueba(39, 1, 50)), "caf.xml")).status_code == 200
    estado = api.put("/api/sii", {"activo": True})
    assert estado["config"]["activo"] == "1" and estado["demo"]["activo"] is False
    assert "producción" in estado["demo"]["bloqueo"]
    r = api.put("/api/sii/demo", {"activo": True}, esperado=400)
    assert "producción" in r["error"]
    assert api.get("/api/config")["sii_ambiente"] == "produccion"
