"""¿Quién emite la boleta?: Neji, un proveedor de boleta electrónica (por su API) o la máquina POS.

Los proveedores reales están pendientes (falta su documentación); aquí uno de mentira hace de proveedor: arma el
documento timbrado como lo haría la empresa (con folios y firma de prueba) y lo devuelve.
"""

import pytest

pytest.importorskip("lxml")
pytest.importorskip("cryptography")

from neji.sii import ErrorSII, caf, dte, proveedores, servicio  # noqa: E402
from neji.sii.firma import Firma  # noqa: E402
from sii_prueba import EMISOR, caf_de_prueba, pfx_de_prueba  # noqa: E402
from test_sii_demo import SIIQueAnota, contar, vender  # noqa: E402

DATOS_EMPRESA = {"rut": EMISOR["rut"], "razon_social": EMISOR["razon_social"], "giro": EMISOR["giro"],
                 "actecos": "477310", "direccion": EMISOR["direccion"], "comuna": EMISOR["comuna"],
                 "ciudad": EMISOR["ciudad"],
                 "fecha_resolucion": "2026-10-01", "numero_resolucion": 80}


class ProveedorDePrueba(proveedores.Proveedor):
    """Hace de OpenFactura, SuperFactura...: recibe el documento y lo devuelve timbrado."""

    clave = "deprueba"
    nombre = "Proveedor de Prueba"
    campos = (
        {"clave": "llave", "etiqueta": "Llave de la API", "tipo": "secreto"},
        {"clave": "ambiente", "etiqueta": "Ambiente", "tipo": "opciones",
         "opciones": {"produccion": "Producción", "pruebas": "Pruebas"}},
    )

    def __init__(self):
        self.pedidos = []
        self.falla = None
        self.folios = {}
        self.firma = Firma(pfx_de_prueba(), "1234")
        self.cafs = {t: caf.Caf(caf_de_prueba(t, 1, 50)) for t in (39, 41, 33, 61)}

    def validar(self, datos):
        if datos.get("ambiente") not in ("produccion", "pruebas"):
            raise ErrorSII("El ambiente es producción o pruebas.")
        return {"ambiente": datos["ambiente"]}

    def pruebas(self, config):
        return config.get("ambiente") == "pruebas"

    def emitir(self, doc, config):
        self.pedidos.append((doc, config))
        if self.falla:
            raise self.falla
        folio = self.folios[doc["tipo"]] = self.folios.get(doc["tipo"], 0) + 1
        r = dte.construir(doc | {"folio": folio}, self.cafs[doc["tipo"]], self.firma)
        return {"folio": folio, "xml": r["xml"], "externo": f"tok-{doc['tipo']}-{folio}"}


@pytest.fixture
def proveedor(monkeypatch):
    p = ProveedorDePrueba()
    monkeypatch.setitem(proveedores.CONECTORES, p.clave, p)
    return p


def activar_proveedor(api, ambiente="produccion"):
    api.put("/api/sii", {**DATOS_EMPRESA, "modo": "proveedor", "proveedor": "deprueba",
                         "proveedor_datos": {"llave": "llave-secreta-123", "ambiente": ambiente}})
    return api.put("/api/sii", {"activo": True})


def test_las_tres_formas_y_los_proveedores_pendientes(api):
    estado = api.get("/api/sii")
    assert estado["modo"] == "neji" and set(estado["modos"]) == {"neji", "proveedor", "maquina"}
    claves = {p["clave"]: p for p in estado["proveedores"]}
    assert {"openfactura", "superfactura", "simplefactura", "libredte"} <= set(claves)
    assert not any(p["disponible"] for p in claves.values())
    assert "Klap" in estado["maquinas"] and "Mercado Pago" in estado["maquinas"]
    # Un proveedor pendiente no se puede elegir todavía.
    r = api.put("/api/sii", {"modo": "proveedor", "proveedor": "openfactura", "proveedor_datos": {}}, esperado=400)
    assert "todavía no se puede usar" in r["error"]
    # Las máquinas POS: también Mercado Pago, Transbank y Getnet (pendientes).
    maquinas = {p["clave"]: p for p in api.get("/api/pos")["proveedores"]}
    assert {"klap", "tuu", "mercadopago", "transbank", "getnet"} <= set(maquinas)
    assert not any(maquinas[c]["disponible"] for c in ("klap", "tuu", "mercadopago", "transbank", "getnet"))


def test_con_proveedor_falta_su_configuracion_para_activar(api, proveedor):
    api.put("/api/sii", {**DATOS_EMPRESA, "modo": "proveedor"})
    assert "elegir el proveedor de boleta electrónica" in api.get("/api/sii")["pendientes"]
    api.put("/api/sii", {"proveedor": "deprueba", "proveedor_datos": {"ambiente": "produccion"}})
    estado = api.get("/api/sii")
    assert estado["pendientes"] == ["llave de la api de Proveedor de Prueba"]
    r = api.put("/api/sii", {"activo": True}, esperado=400)
    assert "llave de la api" in r["error"]
    # Con un proveedor no hacen falta la firma ni los folios del negocio.
    estado = activar_proveedor(api)
    assert estado["config"]["activo"] == "1" and estado["pendientes"] == []


def test_la_venta_sale_con_la_boleta_del_proveedor(app, api, productos, turno, proveedor):
    estado = activar_proveedor(api)
    # La llave nunca vuelve a la pantalla y se guarda cifrada.
    assert estado["proveedor"] == {"proveedor": "deprueba",
                                   "datos": {"ambiente": "produccion", "llave_guardada": True}}
    assert "proveedor_datos" not in estado["config"]
    assert contar(app, "SELECT COUNT(*) FROM sii_config WHERE valor LIKE '%llave-secreta%'") == 0
    config = api.get("/api/config")
    assert (config["sii_activo"], config["sii_modo"], config["sii_ambiente"]) == ("1", "proveedor", "proveedor")

    venta = vender(api, productos)
    assert venta["avisos"] == []
    [boleta] = venta["documentos"]
    assert (boleta["tipo"], boleta["folio"], boleta["total"], boleta["ambiente"]) == (39, 1, venta["total"],
                                                                                     "proveedor")
    assert boleta["estado_texto"] == "Emitido por Proveedor de Prueba" and boleta["demo"] is False
    assert boleta["ted"].startswith("<TED") and "xmlns" not in boleta["ted"] and boleta["pdf417"]
    assert boleta["resolucion"] == {"numero": "80", "anio": "2026"}
    assert boleta["emisor"]["razon_social"] == EMISOR["razon_social"]
    # Lo que recibió el proveedor: la venta, el emisor, una referencia única y la llave descifrada.
    doc, config_proveedor = proveedor.pedidos[0]
    assert doc["referencia"] == f"venta-{venta['id']}" and doc["emisor"]["rut"] == EMISOR["rut"]
    assert [linea["monto"] for linea in doc["lineas"]] == [i["importe"] for i in venta["items"]]
    assert config_proveedor == {"llave": "llave-secreta-123", "ambiente": "produccion"}
    # El timbre guardado es el mismo que va dentro del documento del proveedor.
    assert contar(app, "SELECT COUNT(*) FROM sii_documentos WHERE externo = 'tok-39-1' AND proveedor = ?",
                  "Proveedor de Prueba") == 1
    # Neji no le manda nada al SII: eso lo hace el proveedor.
    sii = SIIQueAnota()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, sii)
    assert sii.subidos == []
    lista = api.get("/api/sii/documentos")
    assert [(d["folio"], d["estado_texto"]) for d in lista] == [(1, "Emitido por Proveedor de Prueba")]


def test_si_el_proveedor_no_responde_la_venta_igual_se_hace(api, productos, turno, proveedor):
    activar_proveedor(api)
    proveedor.falla = ErrorSII("Sin conexión con el proveedor.")
    venta = vender(api, productos)
    assert venta["documentos"] == []
    assert "sin boleta electrónica: Sin conexión con el proveedor." in venta["avisos"][0]
    assert "historial" in venta["avisos"][0]
    # Un error inesperado del conector tampoco impide vender.
    proveedor.falla = RuntimeError("se cayó")
    otra = vender(api, productos)
    assert "Proveedor de Prueba no pudo emitir el documento: se cayó" in otra["avisos"][0]
    # Cuando vuelve, la boleta se emite desde el historial, y no dos veces.
    proveedor.falla = None
    emitida = api.post(f"/api/sii/ventas/{venta['id']}/emitir", {"documento": "boleta"}, esperado=201)
    assert [d["folio"] for d in emitida["documentos"]] == [1]
    r = api.post(f"/api/sii/ventas/{venta['id']}/emitir", {"documento": "boleta"}, esperado=400)
    assert "ya tiene su documento" in r["error"]


def test_devolucion_y_factura_con_proveedor(api, productos, turno, proveedor):
    activar_proveedor(api)
    venta = vender(api, productos, items=[{"producto_id": productos["bebida"]["id"], "cantidad": 3}])
    item = venta["items"][0]
    parcial = api.post(f"/api/ventas/{venta['id']}/devolucion",
                       {"caja_id": 1, "items": [{"venta_item_id": item["id"], "cantidad": 1}], "motivo": "Vencido"},
                       esperado=201)
    nota = parcial["documentos"][-1]
    assert (nota["tipo"], nota["folio"], nota["total"]) == (61, 1, parcial["devoluciones"][0]["monto"])
    doc, _ = proveedor.pedidos[-1]
    assert doc["referencia"] == f"devolucion-{parcial['devoluciones'][0]['id']}"
    assert doc["referencias"][0]["tipo"] == 39 and doc["referencias"][0]["folio"] == 1
    # La factura sin cliente no se vende (se revisa antes de guardar la venta).
    antes = len(proveedor.pedidos)
    r = api.post("/api/ventas", {"caja_id": 1, "documento": "factura",
                                 "items": [{"producto_id": productos["bebida"]["id"], "cantidad": 1}]}, esperado=400)
    assert "factura" in r["error"] and len(proveedor.pedidos) == antes


def test_ambiente_de_pruebas_del_proveedor(api, productos, turno, proveedor):
    activar_proveedor(api, ambiente="pruebas")
    assert api.get("/api/config")["sii_ambiente"] == "proveedor_pruebas"
    [boleta] = vender(api, productos)["documentos"]
    assert boleta["demo"] is True and boleta["estado_texto"] == "Prueba de Proveedor de Prueba: no vale como documento"


def test_la_maquina_pos_entrega_la_boleta(api, productos, turno, proveedor):
    activar_proveedor(api)
    estado = api.put("/api/sii", {"modo": "maquina"})
    # Al cambiar de forma se desactiva: Neji ya no emite (la máquina entrega la boleta, no se emiten dos).
    assert estado["modo"] == "maquina" and estado["config"]["activo"] == "0"
    config = api.get("/api/config")
    assert (config["sii_activo"], config["sii_modo"]) == ("0", "maquina")
    venta = vender(api, productos)
    assert venta["documentos"] == [] and venta["avisos"] == []
    r = api.put("/api/sii", {"activo": True}, esperado=400)
    assert "¿Quién emite la boleta?" in r["error"]
    r = api.put("/api/sii/demo", {"activo": True}, esperado=400)
    assert "Neji, directo con el SII" in r["error"]
    assert api.put("/api/sii", {"modo": "otra"}, esperado=400)["error"].startswith("Elige quién emite")
    # Volver a Neji: queda desactivada hasta que se active de nuevo.
    estado = api.put("/api/sii", {"modo": "neji"})
    assert estado["modo"] == "neji" and estado["config"]["activo"] == "0"


def test_el_timbre_se_saca_del_documento_del_proveedor():
    firma = Firma(pfx_de_prueba(), "1234")
    doc = {"tipo": 39, "folio": 7, "fecha": "2026-11-02", "emisor": EMISOR, "receptor": None,
           "lineas": [{"nombre": "Paracetamol", "cantidad": 1, "precio": 990, "monto": 990, "exento": False}]}
    r = dte.construir(doc, caf.Caf(caf_de_prueba(39, 1, 10)), firma)
    assert proveedores.ted_del_xml(r["xml"]) == r["ted"].decode("iso-8859-1").strip()
    with pytest.raises(ErrorSII, match="no trae el timbre"):
        proveedores.ted_del_xml(b"<DTE><Documento/></DTE>")
    with pytest.raises(ErrorSII, match="no se puede leer"):
        proveedores.ted_del_xml(b"no es xml")
