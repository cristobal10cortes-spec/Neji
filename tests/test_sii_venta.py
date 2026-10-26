"""Boleta electrónica dentro de Neji: configuración, emisión al vender, nota de crédito y envío al SII."""

import io

import pytest

pytest.importorskip("lxml")
pytest.importorskip("cryptography")

from lxml import etree  # noqa: E402

from neji.sii import envio, servicio  # noqa: E402
from neji.sii.firma import Firma, verificar_xml  # noqa: E402
from sii_prueba import EMISOR, caf_de_prueba, pfx_de_prueba, validar_esquema  # noqa: E402

SII = "{http://www.sii.cl/SiiDte}"


def subir(api, url, archivos, **campos):
    datos = {"archivo": archivos if isinstance(archivos, list) else [archivos], **campos}
    return api.http.post(url, data=datos, content_type="multipart/form-data")


@pytest.fixture
def sii(api):
    api.put("/api/sii", {"rut": EMISOR["rut"], "razon_social": EMISOR["razon_social"], "giro": EMISOR["giro"],
                         "actecos": "477310", "direccion": EMISOR["direccion"], "comuna": EMISOR["comuna"],
                         "ciudad": EMISOR["ciudad"], "fecha_resolucion": "2026-10-01", "numero_resolucion": 0})
    r = subir(api, "/api/sii/firma", (io.BytesIO(pfx_de_prueba()), "firma.pfx"), clave="1234")
    assert r.status_code == 200, r.get_json()
    r = subir(api, "/api/sii/caf", [(io.BytesIO(caf_de_prueba(t, 1, hasta)), f"caf{t}.xml")
                                    for t, hasta in ((39, 3), (41, 50), (33, 50), (61, 50))])
    assert r.status_code == 200, r.get_json()
    estado = api.put("/api/sii", {"activo": True})
    assert estado["config"]["activo"] == "1" and estado["pendientes"] == []
    return estado


def vender(api, productos, turno, items=None, **extra):
    datos = {"caja_id": 1, "items": items or [{"producto_id": productos["bebida"]["id"], "cantidad": 2}], **extra}
    return api.post("/api/ventas", datos, esperado=201)


def xml_de(app, documento_id):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    try:
        return con.execute("SELECT xml FROM sii_documentos WHERE id = ?", (documento_id,)).fetchone()[0]
    finally:
        con.close()


def test_sin_configurar_no_se_puede_activar(api):
    r = api.put("/api/sii", {"activo": True}, esperado=400)
    assert "firma electrónica" in r["error"] and "folios" in r["error"]
    assert api.get("/api/config")["sii_activo"] == "0"


def test_la_firma_y_los_folios_se_ven_en_configuracion(api, sii):
    assert sii["firma"]["rut"] == "13185095-6" and sii["firma"]["vigente"]
    assert "firma_pfx" not in sii["config"] and "firma_clave" not in sii["config"]
    assert {(f["tipo"], f["desde"], f["hasta"], f["disponibles"]) for f in sii["folios"]} == {
        (39, 1, 3, 3), (41, 1, 50, 50), (33, 1, 50, 50), (61, 1, 50, 50)}
    r = api.put("/api/sii", {"actecos": "47731000"}, esperado=400)
    assert "6 dígitos" in r["error"]
    r = subir(api, "/api/sii/caf", (io.BytesIO(caf_de_prueba(39, 2, 10)), "otro.xml"))
    assert r.status_code == 400 and "se cruzan" in r.get_json()["error"]
    r = subir(api, "/api/sii/caf", (io.BytesIO(caf_de_prueba(39, 100, 110, rut="11111111-1")), "ajeno.xml"))
    assert r.status_code == 400 and "11111111-1" in r.get_json()["error"]


def test_vender_emite_la_boleta_con_su_timbre(app, api, productos, turno, sii):
    assert api.get("/api/config")["sii_activo"] == "1"
    venta = vender(api, productos, turno, items=[{"producto_id": productos["bebida"]["id"], "cantidad": 2},
                                                {"producto_id": productos["pan"]["id"], "cantidad": 0.5}],
                   descuento=100)
    assert venta["avisos"] == ["Quedan 2 folios de boleta electrónica: pide más al SII."]   # el CAF de prueba trae 3
    doc, = venta["documentos"]
    assert (doc["tipo"], doc["folio"], doc["estado"], doc["total"]) == (39, 1, "pendiente", venta["total"])
    assert (doc["neto"], doc["iva"]) == (venta["neto"], venta["iva"])
    assert doc["ted"].startswith('<TED version="1.0">') and len(doc["pdf417"]) <= 90
    assert doc["resolucion"] == {"numero": "0", "anio": "2026"}
    # El XML guardado: firma válida y dentro de un sobre cumple el esquema del SII.
    xml = xml_de(app, doc["id"])
    assert verificar_xml(etree.fromstring(xml)) == 1
    sobre = envio.construir([xml], [39], EMISOR["rut"], Firma(pfx_de_prueba(), "1234"), "2026-10-01", 0)
    validar_esquema(sobre, "EnvioBOLETA")
    # Otra venta toma el folio siguiente.
    assert vender(api, productos, turno)["documentos"][0]["folio"] == 2


def test_boleta_exenta_y_factura(api, productos, turno, sii):
    exento = api.post("/api/productos", {"codigo": "LIBRO", "descripcion": "Libro", "precio_venta": 5000,
                                         "exento": True, "existencia": 5}, esperado=201)
    venta = vender(api, productos, turno, items=[{"producto_id": exento["id"], "cantidad": 1}])
    assert venta["documentos"][0]["tipo"] == 41 and venta["documentos"][0]["exento"] == 5000
    # Factura sin cliente: no se vende.
    r = api.post("/api/ventas", {"caja_id": 1, "documento": "factura",
                                 "items": [{"producto_id": productos["bebida"]["id"], "cantidad": 1}]}, esperado=400)
    assert "cliente" in r["error"]
    cliente = api.post("/api/clientes", {"nombre": "Minera Los Pelambres", "rut": "96.790.240-3",
                                         "giro": "Minería", "direccion": "Av. Apoquindo 4001", "comuna": "Las Condes",
                                         "ciudad": "Santiago"}, esperado=201)
    factura = vender(api, productos, turno, documento="factura", cliente_id=cliente["id"])
    doc = factura["documentos"][0]
    assert (doc["tipo"], doc["rut_receptor"], doc["razon_receptor"]) == (33, "96790240-3", "Minera Los Pelambres")
    # Lo que va impreso sale del documento firmado: emisor, cliente y líneas.
    assert doc["receptor"] == {"rut": "96790240-3", "razon_social": "Minera Los Pelambres", "giro": "Minería",
                               "direccion": "Av. Apoquindo 4001", "comuna": "Las Condes", "ciudad": "Santiago"}
    assert (doc["emisor"]["rut"], doc["emisor"]["razon_social"]) == (EMISOR["rut"], EMISOR["razon_social"])
    assert [(x["nombre"], x["cantidad"], x["monto"]) for x in doc["lineas"]] == [
        (factura["items"][0]["descripcion"], 2, factura["items"][0]["importe"])]
    # Cliente sin comuna: la factura no se emite y la venta no queda registrada.
    incompleto = api.post("/api/clientes", {"nombre": "Otro", "rut": "76.086.428-5", "giro": "Comercio",
                                            "direccion": "Calle 1"}, esperado=201)
    antes = len(api.get("/api/ventas"))
    r = api.post("/api/ventas", {"caja_id": 1, "documento": "factura", "cliente_id": incompleto["id"],
                                 "items": [{"producto_id": productos["bebida"]["id"], "cantidad": 1}]}, esperado=400)
    assert "comuna" in r["error"] and len(api.get("/api/ventas")) == antes


def test_sin_folios_la_venta_se_registra_con_aviso(api, productos, turno, sii):
    for _ in range(3):
        assert vender(api, productos, turno)["documentos"]
    venta = vender(api, productos, turno)
    assert venta["documentos"] == [] and "No quedan folios" in venta["avisos"][0]
    # Con folios nuevos se emite la boleta pendiente.
    subir(api, "/api/sii/caf", (io.BytesIO(caf_de_prueba(39, 10, 20)), "mas.xml"))
    emitida = api.post(f"/api/sii/ventas/{venta['id']}/emitir", {}, esperado=201)
    assert emitida["documentos"][0]["folio"] == 10
    api.post(f"/api/sii/ventas/{venta['id']}/emitir", {}, esperado=400)


def test_quedan_pocos_folios_avisa(api, productos, turno, sii):
    assert any("Quedan 2 folios" in a for a in vender(api, productos, turno)["avisos"])


def test_devolucion_emite_nota_de_credito(app, api, productos, turno, sii):
    venta = vender(api, productos, turno, items=[{"producto_id": productos["bebida"]["id"], "cantidad": 3}])
    boleta = venta["documentos"][0]
    item = venta["items"][0]
    parcial = api.post(f"/api/ventas/{venta['id']}/devolucion",
                       {"caja_id": 1, "items": [{"venta_item_id": item["id"], "cantidad": 1}], "motivo": "Vencido"},
                       esperado=201)
    nota = parcial["documentos"][-1]
    assert (nota["tipo"], nota["folio"], nota["total"]) == (61, 1, parcial["devoluciones"][0]["monto"])
    raiz = etree.fromstring(xml_de(app, nota["id"]))
    ref = raiz.find(f".//{SII}Referencia")
    assert (ref.findtext(f"{SII}TpoDocRef"), ref.findtext(f"{SII}FolioRef"), ref.findtext(f"{SII}CodRef"),
            ref.findtext(f"{SII}RazonRef")) == ("39", str(boleta["folio"]), "3", "Vencido")
    sobre = envio.construir([xml_de(app, nota["id"])], [61], EMISOR["rut"], Firma(pfx_de_prueba(), "1234"),
                            "2026-10-01", 0)
    assert verificar_xml(validar_esquema(sobre, "EnvioDTE")) == 2
    assert nota["referencias"] == [{"tipo": 39, "folio": str(boleta["folio"]), "fecha": boleta["fecha"], "codigo": 3,
                                    "razon": "Vencido"}]
    assert nota["devolucion_id"] == parcial["devoluciones"][0]["id"] and nota["receptor"]["rut"] == "66666666-6"
    resto = api.post(f"/api/ventas/{venta['id']}/devolucion", {"caja_id": 1, "todo": True}, esperado=201)
    assert [d["tipo"] for d in resto["documentos"]] == [39, 61, 61]


def test_venta_con_devolucion_no_se_emite_despues(api, productos, turno):
    """Una venta hecha sin boleta electrónica y con devoluciones ya no puede recibir su boleta (no cuadraría)."""
    venta = vender(api, productos, turno, items=[{"producto_id": productos["bebida"]["id"], "cantidad": 3}])
    api.post(f"/api/ventas/{venta['id']}/devolucion",
             {"caja_id": 1, "items": [{"venta_item_id": venta["items"][0]["id"], "cantidad": 1}]}, esperado=201)
    r = api.post(f"/api/sii/ventas/{venta['id']}/emitir", {}, esperado=400)
    assert "activada" in r["error"]          # sin activar, primero eso


class SIIFalso:
    def __init__(self, codigo="EPR", rechazados=0):
        self.codigo, self.rechazados, self.subidos = codigo, rechazados, []

    def enviar(self, xml, boleta):
        self.subidos.append((xml, boleta))
        return str(1000 + len(self.subidos))

    def estado(self, trackid, boleta):
        return {"estado": self.codigo, "final": True, "glosa": "", "informados": 1, "aceptados": 1 - self.rechazados,
                "rechazados": self.rechazados, "reparos": 0, "detalle": []}


def test_envio_al_sii_en_segundo_plano(app, api, productos, turno, sii):
    for _ in range(2):
        vender(api, productos, turno)
    factura_cliente = api.post("/api/clientes", {"nombre": "Empresa", "rut": "96.790.240-3", "giro": "Comercio",
                                                 "direccion": "Calle 1", "comuna": "La Serena"}, esperado=201)
    vender(api, productos, turno, documento="factura", cliente_id=factura_cliente["id"])
    falso = SIIFalso()
    r = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)
    assert r["sobres"] == 2 and r["subidos"] == 2           # las 2 boletas juntas; la factura, aparte
    sobres = [etree.fromstring(x) for x, _ in falso.subidos]
    assert [s.tag.replace(SII, "") for s in sobres] == ["EnvioBOLETA", "EnvioDTE"]
    assert [verificar_xml(s) for s in sobres] == [3, 2]
    validar_esquema(falso.subidos[0][0], "EnvioBOLETA")
    validar_esquema(falso.subidos[1][0], "EnvioDTE")
    # Todavía no toca consultar (se espera un poco después de subir).
    assert servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)["consultados"] == 0
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE sii_envios SET proximo = NULL")
    con.commit()
    con.close()
    assert servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=falso)["consultados"] == 2
    docs = api.get("/api/sii/documentos")
    assert {d["estado"] for d in docs} == {"aceptado"} and all(d["trackid"] for d in docs)
    venta = api.get(f"/api/ventas/{docs[-1]['venta_id']}")
    assert venta["documentos"][0]["estado_texto"] == "Aceptado por el SII"


def test_envio_rechazado_y_sin_conexion(app, api, productos, turno, sii):
    from neji.sii import ErrorSII

    vender(api, productos, turno)

    class SinRed(SIIFalso):
        def enviar(self, xml, boleta):
            raise ErrorSII("No se pudo conectar con el SII (sin red). Se reintentará solo.")

    r = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SinRed())
    assert r["subidos"] == 0 and "sin red" in r["errores"][0]
    assert api.get("/api/sii/documentos")[0]["estado"] == "pendiente"
    assert "sin red" in api.get("/api/sii")["envios"]["error"]

    class Esquema(SIIFalso):
        def enviar(self, xml, boleta):
            raise ErrorSII("El SII no recibió el envío: El sobre no cumple el esquema del SII.", definitivo=True)

    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE sii_envios SET proximo = NULL")
    con.commit()
    con.close()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=Esquema())
    doc = api.get("/api/sii/documentos")[0]
    assert doc["estado"] == "rechazado" and "esquema" in doc["glosa"]
    # La venta de una boleta rechazada se puede volver a emitir (con otro folio).
    otra = api.post(f"/api/sii/ventas/{doc['venta_id']}/emitir", {}, esperado=201)
    assert [d["folio"] for d in otra["documentos"]] == [1, 2]


def test_la_firma_no_se_lee_con_otra_clave_de_neji(app, sii):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    cfg = servicio.leer(con)
    con.close()
    servicio._firmas.clear()
    with pytest.raises(Exception, match="Vuelve a subir la firma"):
        servicio.cargar_firma(cfg, "otra-clave")
    servicio._firmas.clear()


def test_venta_parcialmente_devuelta_no_recibe_boleta(api, productos, turno, sii):
    for _ in range(3):
        vender(api, productos, turno)                       # se acaban los folios de boleta
    venta = vender(api, productos, turno, items=[{"producto_id": productos["bebida"]["id"], "cantidad": 3}])
    assert venta["documentos"] == []
    api.post(f"/api/ventas/{venta['id']}/devolucion",
             {"caja_id": 1, "items": [{"venta_item_id": venta["items"][0]["id"], "cantidad": 1}]}, esperado=201)
    subir(api, "/api/sii/caf", (io.BytesIO(caf_de_prueba(39, 10, 20)), "mas.xml"))
    r = api.post(f"/api/sii/ventas/{venta['id']}/emitir", {}, esperado=400)
    assert "devoluciones" in r["error"]


def test_autoprueba_del_programa():
    """La que corre NejiPOS.exe --prueba en la compilación de Windows."""
    from neji.sii.autoprueba import probar

    r = probar()
    assert r["firmas_verificadas"] == 1 and r["timbre_80mm"] > 0 and r["timbre_58mm"] > 0


class CorreoFalso:
    def __init__(self):
        self.enviados = []

    def __call__(self, mensaje):
        self.enviados.append(mensaje)


def _consultar_ya(app):
    from neji.db import conectar

    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE sii_envios SET proximo = NULL")
    con.commit()
    con.close()


def test_factura_aceptada_va_al_cliente_por_correo(app, api, productos, turno, sii):
    estado = api.put("/api/sii", {"correo_servidor": "smtp.ejemplo.cl", "correo_puerto": "587",
                                  "correo_usuario": "farmacia@ejemplo.cl", "correo_clave": "secreta",
                                  "correo_remitente": "farmacia@ejemplo.cl"})
    assert estado["correo"] == {"configurado": True, "clave_guardada": True}
    assert "correo_clave" not in estado["config"]
    con_correo = api.post("/api/clientes", {"nombre": "Clínica Peña Ltda.", "rut": "96.790.240-3", "giro": "Salud",
                                            "direccion": "Av. del Mar 500", "comuna": "La Serena",
                                            "email": "dte@clinica.cl"}, esperado=201)
    sin_correo = api.post("/api/clientes", {"nombre": "Otra", "rut": "76.086.428-5", "giro": "Comercio",
                                            "direccion": "Calle 1", "comuna": "Coquimbo"}, esperado=201)
    factura = vender(api, productos, turno, documento="factura", cliente_id=con_correo["id"])
    assert factura["documentos"][0]["correo"]["estado"] == "pendiente"
    otra = vender(api, productos, turno, documento="factura", cliente_id=sin_correo["id"])
    assert otra["documentos"][0]["correo"]["estado"] == "sin_correo"
    assert vender(api, productos, turno)["documentos"][0]["correo"] is None      # la boleta no va por correo

    correo = CorreoFalso()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    assert correo.enviados == []           # todavía no la acepta el SII
    _consultar_ya(app)
    r = servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    assert r["correos"] == 1 and len(correo.enviados) == 1
    mensaje = correo.enviados[0]
    assert mensaje["To"] == "dte@clinica.cl" and "farmacia@ejemplo.cl" in mensaje["From"]
    assert mensaje["Subject"] == f"DTE {EMISOR['rut']} - Factura electrónica N° 1"
    adjunto = next(mensaje.iter_attachments())
    assert adjunto.get_filename() == f"DTE_{EMISOR['rut']}_T33_F1.xml"
    sobre = validar_esquema(adjunto.get_content(), "EnvioDTE")
    assert sobre.findtext(f".//{SII}Caratula/{SII}RutReceptor") == "96790240-3"      # dirigido al cliente
    assert verificar_xml(sobre) == 2
    assert api.get(f"/api/ventas/{factura['id']}")["documentos"][0]["correo"]["estado"] == "enviado"
    assert servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)["correos"] == 0

    # La factura del cliente sin correo se manda cuando se indica uno.
    doc = next(d for d in api.get("/api/sii/documentos") if d["venta_id"] == otra["id"])
    assert doc["correo_estado"] == "sin_correo" and doc["correo_texto"] == "Cliente sin correo"
    api.post(f"/api/sii/documentos/{doc['id']}/correo", {"correo": "no es un correo"}, esperado=400)
    api.post(f"/api/sii/documentos/{doc['id']}/correo", {"correo": "compras@otra.cl"})
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    assert correo.enviados[-1]["To"] == "compras@otra.cl"

    # La nota de crédito de una factura también va al cliente.
    api.post(f"/api/ventas/{factura['id']}/devolucion", {"caja_id": 1, "todo": True}, esperado=201)
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    _consultar_ya(app)
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    assert correo.enviados[-1]["Subject"].endswith("Nota de crédito electrónica N° 1")
    assert correo.enviados[-1]["To"] == "dte@clinica.cl"


def test_sin_cuenta_de_correo_las_facturas_esperan(app, api, productos, turno, sii):
    cliente = api.post("/api/clientes", {"nombre": "Clínica", "rut": "96.790.240-3", "giro": "Salud",
                                         "direccion": "Av. del Mar 500", "comuna": "La Serena",
                                         "email": "dte@clinica.cl"}, esperado=201)
    vender(api, productos, turno, documento="factura", cliente_id=cliente["id"])
    correo = CorreoFalso()
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    _consultar_ya(app)
    servicio.ciclo(app.config["DATABASE"], app.secret_key, conexion=SIIFalso(), correo=correo)
    assert correo.enviados == []
    assert api.get("/api/sii")["envios"]["correos_pendientes"] == 1
    r = api.post("/api/sii/correo/probar", {}, esperado=400)
    assert "servidor" in r["error"]


def test_conversacion_con_el_servidor_de_correo(app, api, sii, monkeypatch):
    """STARTTLS en el 587, SSL en el 465, la contraseña guardada cifrada y los errores en palabras simples."""
    import smtplib

    llamadas = []

    class SMTPFalso:
        def __init__(self, servidor, puerto, timeout=None, context=None):
            llamadas.append(("conectar", type(self).__name__, servidor, puerto))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def has_extn(self, nombre):
            return nombre == "starttls"

        def starttls(self, context=None):
            llamadas.append(("starttls",))

        def login(self, usuario, clave):
            llamadas.append(("login", usuario, clave))
            if clave != "secreta":
                raise smtplib.SMTPAuthenticationError(535, b"no")

        def send_message(self, mensaje):
            llamadas.append(("enviar", mensaje["To"], mensaje["Subject"]))

    class SSLFalso(SMTPFalso):
        pass

    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SSLFalso)
    api.put("/api/sii", {"correo_servidor": "smtp.gmail.com", "correo_puerto": "587",
                         "correo_usuario": "farmacia@gmail.com", "correo_clave": "secreta"})
    r = api.post("/api/sii/correo/probar", {})
    assert r["mensaje"] == "Correo de prueba enviado a farmacia@gmail.com."
    assert llamadas == [("conectar", "SMTPFalso", "smtp.gmail.com", 587), ("starttls",),
                        ("login", "farmacia@gmail.com", "secreta"),
                        ("enviar", "farmacia@gmail.com", "Prueba de correo de Neji POS")]
    llamadas.clear()
    api.put("/api/sii", {"correo_puerto": "465", "correo_clave": ""})     # la contraseña vacía no se borra
    api.post("/api/sii/correo/probar", {"para": "otro@ejemplo.cl"})
    assert llamadas[0] == ("conectar", "SSLFalso", "smtp.gmail.com", 465) and ("starttls",) not in llamadas
    api.put("/api/sii", {"correo_clave": "mala"})
    r = api.post("/api/sii/correo/probar", {}, esperado=400)
    assert "contraseña de aplicación" in r["error"]
    r = api.put("/api/sii", {"correo_puerto": "abc"}, esperado=400)
    assert "puerto" in r["error"]
