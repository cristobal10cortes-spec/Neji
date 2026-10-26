"""Boleta electrónica: firma, CAF, armado del DTE, timbre, sobre y conexión con el SII (con un SII simulado).

Los XML se validan contra los esquemas oficiales del SII (tests/sii_xsd) y las firmas se verifican.
"""

import base64
import json
import re

import pytest

pytest.importorskip("lxml")
pytest.importorskip("cryptography")

from lxml import etree  # noqa: E402

from neji.sii import NS_SII, NS_XSI, ErrorSII, dte, envio  # noqa: E402
from neji.sii.caf import Caf  # noqa: E402
from neji.sii.conexion import ConexionSII  # noqa: E402
from neji.sii.firma import Firma, c14n, verificar_xml  # noqa: E402
from neji.sii.pdf417 import matriz  # noqa: E402
from neji.sii.textos import texto_sii, texto_timbre  # noqa: E402
from sii_prueba import EMISOR, RUT_FIRMANTE, caf_de_prueba, pfx_de_prueba, validar_esquema  # noqa: E402

SII = "{http://www.sii.cl/SiiDte}"


@pytest.fixture(scope="module")
def firma():
    return Firma(pfx_de_prueba(), "1234")


def linea(nombre, cantidad, precio, exento=False, codigo=None):
    return {"nombre": nombre, "cantidad": cantidad, "precio": precio, "codigo": codigo, "exento": exento,
            "monto": round(cantidad * precio)}


def boleta(tipo=39, folio=1, **extra):
    return {"tipo": tipo, "folio": folio, "fecha": "2026-10-26", "emisor": EMISOR, "receptor": None,
            "lineas": [linea("PARACETAMOL 500MG X 16 COMP", 2, 990, codigo="7800001")], **extra}


def verificar_timbre(xml_dte, caf):
    """Como el SII: saca el DD del documento, lo aplana sin espacio de nombres y verifica FRMT con el CAF."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    raiz = etree.fromstring(xml_dte)
    ted = raiz.find(f".//{SII}TED")
    texto = etree.tostring(ted, encoding="unicode")
    texto = texto.replace(' xmlns="http://www.sii.cl/SiiDte"', "")
    texto = re.sub(r' xmlns:xsi="[^"]*"', "", texto)
    plano = etree.fromstring(texto)
    dd = etree.tostring(plano.find("DD"), encoding="ISO-8859-1", xml_declaration=False)
    frmt = base64.b64decode(plano.findtext("FRMT"))
    caf.llave.public_key().verify(frmt, dd, padding.PKCS1v15(), hashes.SHA1())
    return plano


# --- Firma electrónica -------------------------------------------------------------------------------

def test_la_firma_lee_el_rut_del_titular_y_su_vencimiento(firma):
    assert firma.rut == RUT_FIRMANTE and firma.vigente
    assert firma.resumen()["nombre"] == "Dueño de Prueba"


def test_firma_con_clave_equivocada_o_vencida():
    with pytest.raises(ErrorSII, match="contraseña"):
        Firma(pfx_de_prueba(), "otra")
    vencida = Firma(pfx_de_prueba(vencida=True), "1234")
    with pytest.raises(ErrorSII, match="venció"):
        vencida.exigir_vigente()
    assert Firma(pfx_de_prueba(clave=""), "").rut == RUT_FIRMANTE


# --- CAF -----------------------------------------------------------------------------------------------

DS = "http://www.w3.org/2000/09/xmldsig#"


def test_c14n_de_un_elemento_interior_en_su_contexto():
    """lxml canonicaliza mal un elemento que no es la raíz (xmlns="" en los nietos): el SII rechazaría todo."""
    raiz = etree.fromstring(f'<DTE xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" version="1.0"><Documento ID="F1T39">'
                            "<Encabezado><IdDoc><TipoDTE>39</TipoDTE></IdDoc></Encabezado> \n</Documento></DTE>")
    assert c14n(raiz[0]) == (f'<Documento xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" ID="F1T39"><Encabezado><IdDoc>'
                             "<TipoDTE>39</TipoDTE></IdDoc></Encabezado> \n</Documento>").encode()
    # Una firma (con su propio xmlns por defecto) agregada con la API dentro de un documento sin espacio de nombres.
    semilla = etree.fromstring("<getToken><item/></getToken>")
    info = etree.SubElement(etree.SubElement(semilla, f"{{{DS}}}Signature", nsmap={None: DS}), f"{{{DS}}}SignedInfo")
    etree.SubElement(etree.SubElement(etree.SubElement(info, f"{{{DS}}}Reference"), f"{{{DS}}}Transforms"),
                     f"{{{DS}}}Transform", Algorithm="x")
    assert c14n(info) == (f'<SignedInfo xmlns="{DS}"><Reference><Transforms><Transform Algorithm="x"></Transform>'
                          "</Transforms></Reference></SignedInfo>").encode()
    assert b'xmlns=""' not in c14n(info)


def test_firma_de_la_semilla_envuelta(firma):
    """La firma de la semilla está dentro de lo firmado (URI=""): quien verifica la quita y deja el texto que la
    sigue, así que después de ella no puede quedar un salto de línea."""
    raiz = etree.fromstring("<getToken><item><Semilla>012345678901</Semilla></item></getToken>")
    firma.firmar_xml(raiz)
    assert not raiz[-1].tail
    assert verificar_xml(etree.fromstring(etree.tostring(raiz))) == 1
    # Con un texto agregado después de la firma, el digest ya no calza (la verificación lo considera).
    raiz[-1].tail = "\n"
    with pytest.raises(ErrorSII, match="digest"):
        verificar_xml(etree.fromstring(etree.tostring(raiz)))


def test_firmas_verificadas_con_xmlsec(firma):
    """xmlsec, la implementación de referencia de XMLDSig (si está instalada): semilla, DTE y sobres."""
    xmlsec = pytest.importorskip("xmlsec")
    from cryptography.hazmat.primitives.serialization import Encoding

    pem = firma.certificado.public_bytes(Encoding.PEM)

    def verificar(xml):
        raiz = etree.fromstring(xml)
        xmlsec.tree.add_ids(raiz, ["ID"])
        firmas = raiz.findall(f".//{{{DS}}}Signature")
        for f in firmas:
            ctx = xmlsec.SignatureContext()
            ctx.key = xmlsec.Key.from_memory(pem, xmlsec.constants.KeyDataFormatCertPem)
            ctx.verify(f)
        return len(firmas)

    semilla = etree.fromstring("<getToken><item><Semilla>012345678901</Semilla></item></getToken>")
    firma.firmar_xml(semilla)
    assert verificar(etree.tostring(semilla)) == 1
    caf = Caf(caf_de_prueba(39, 1, 10))
    r = dte.construir(boleta(), caf, firma)
    assert verificar(r["xml"]) == 1
    assert verificar(envio.construir([r["xml"]], [39], EMISOR["rut"], firma, "2026-10-01", 0)) == 2


def test_caf_lee_el_rango_y_valida_su_llave():
    caf = Caf(caf_de_prueba(39, 101, 200))
    assert (caf.tipo, caf.desde, caf.hasta, caf.rut) == (39, 101, 200, "76354771-K")
    assert caf.contiene(150) and not caf.contiene(201)
    # Con tildes en ISO-8859-1 aunque el archivo no lo declare (así vienen del SII).
    assert Caf(caf_de_prueba(33, razon="PEÑA Y CÍA LTDA")).razon_social == "PEÑA Y CÍA LTDA"
    otra = caf_de_prueba(61)
    mezclado = re.sub(rb"<RSASK>.*</RSASK>", re.search(rb"<RSASK>.*</RSASK>", caf_de_prueba(39), re.S).group(0),
                      otra, flags=re.S)
    with pytest.raises(ErrorSII, match="no corresponde"):
        Caf(mezclado)
    with pytest.raises(ErrorSII, match="no emite el tipo"):
        Caf(caf_de_prueba(52))
    with pytest.raises(ErrorSII, match="no es un CAF"):
        Caf(b"<?xml version='1.0'?><OTRA/>")


# --- Boletas ----------------------------------------------------------------------------------------------

def test_boleta_afecta_con_exento_y_descuento(firma):
    caf = Caf(caf_de_prueba(39))
    doc = boleta(lineas=[linea("Paracetamol «Ñandú» — oferta", 2, 990, codigo="7800001"),
                         linea("Pan batido", 0.525, 2290, codigo="PAN") | {"unidad": "KG"},
                         linea("Huevos", 3, 250, exento=True)],
                 descuento_afecto=182)
    r = dte.construir(doc, caf, firma)
    assert r["totales"] == {"neto": 2521, "iva": 479, "exento": 750, "total": 3750, "afecto": 3000,
                           "descuento_afecto": 182}
    raiz = etree.fromstring(r["xml"])
    assert raiz.nsmap == {None: "http://www.sii.cl/SiiDte", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    assert verificar_xml(raiz) == 1
    tot = raiz.find(f".//{SII}Totales")
    assert [(e.tag.replace(SII, ""), e.text) for e in tot] == [
        ("MntNeto", "2521"), ("MntExe", "750"), ("IVA", "479"), ("MntTotal", "3750")]
    assert raiz.findtext(f".//{SII}Detalle/{SII}NmbItem") == "Paracetamol «Ñandú» - oferta"
    assert raiz.findtext(f".//{SII}Detalle[3]/{SII}IndExe") == "1"
    assert raiz.findtext(f".//{SII}Detalle[2]/{SII}QtyItem") == "0.525"
    ted = verificar_timbre(r["xml"], caf)
    assert ted.findtext("DD/IT1") == "Paracetamol Nandu - oferta"       # sin tildes en el timbre
    assert ted.findtext("DD/MNT") == "3750" and ted.findtext("DD/RR") == "66666666-6"

    sobre = envio.construir([r["xml"]], [39], EMISOR["rut"], firma, "2026-10-01", 0)
    doc_sobre = validar_esquema(sobre, "EnvioBOLETA")
    assert verificar_xml(doc_sobre) == 2          # la del sobre y la de la boleta, que sigue valiendo dentro
    assert max(len(l) for l in sobre.split(b"\n")) < 4000   # el SII rechaza líneas de más de ~4090 letras


def test_boleta_exenta_y_varias_boletas_en_un_sobre(firma):
    caf39, caf41 = Caf(caf_de_prueba(39)), Caf(caf_de_prueba(41))
    exenta = dte.construir(boleta(41, 5, lineas=[linea("Huevos", 12, 250, exento=True)]), caf41, firma)
    assert exenta["totales"]["total"] == 3000 and exenta["totales"]["neto"] == 0
    raiz = etree.fromstring(exenta["xml"])
    assert raiz.find(f".//{SII}MntNeto") is None and raiz.findtext(f".//{SII}MntExe") == "3000"
    afectas = [dte.construir(boleta(39, f), caf39, firma)["xml"] for f in (1, 2, 3)]
    sobre = envio.construir(afectas + [exenta["xml"]], [39, 39, 39, 41], EMISOR["rut"], firma, "2026-10-01", 0)
    doc = validar_esquema(sobre, "EnvioBOLETA")
    assert verificar_xml(doc) == 5
    sub = {e.findtext(f"{SII}TpoDTE"): e.findtext(f"{SII}NroDTE") for e in doc.iter(f"{SII}SubTotDTE")}
    assert sub == {"39": "3", "41": "1"}
    assert doc.findtext(f".//{SII}RutEnvia") == RUT_FIRMANTE and doc.findtext(f".//{SII}RutReceptor") == "60803000-K"


def test_boleta_validaciones(firma):
    caf = Caf(caf_de_prueba(39, 1, 10))
    with pytest.raises(ErrorSII, match="folio 11"):
        dte.construir(boleta(folio=11), caf, firma)
    with pytest.raises(ErrorSII, match="CAF"):
        dte.construir(boleta() | {"emisor": EMISOR | {"rut": "11111111-1"}}, caf, firma)
    with pytest.raises(ErrorSII, match="comuna"):
        dte.construir(boleta() | {"emisor": EMISOR | {"comuna": ""}}, caf, firma)
    with pytest.raises(ErrorSII, match="exentos"):
        dte.construir(boleta(lineas=[linea("Huevos", 1, 250, exento=True)]), caf, firma)
    with pytest.raises(ErrorSII, match="no tiene productos"):
        dte.construir(boleta(lineas=[]), caf, firma)


# --- Factura y nota de crédito ----------------------------------------------------------------------------

CLIENTE = {"rut": "96790240-3", "razon_social": "Minera Los Pelambres", "giro": "Extracción y procesamiento de cobre",
           "direccion": "Av. Apoquindo 4001", "comuna": "Las Condes", "ciudad": "Santiago", "email": "pagos@minera.cl"}


def test_factura_con_montos_brutos(firma):
    caf = Caf(caf_de_prueba(33))
    doc = {"tipo": 33, "folio": 9, "fecha": "2026-10-26", "emisor": EMISOR, "receptor": CLIENTE, "credito": True,
           "lineas": [linea("Alcohol 70% 1 L", 3, 2490), linea("Mascarillas x 50", 1, 5990)],
           "descuento_afecto": 460}
    r = dte.construir(doc, caf, firma)
    assert r["totales"]["total"] == 3 * 2490 + 5990 - 460
    raiz = etree.fromstring(r["xml"])
    assert raiz.findtext(f".//{SII}MntBruto") == "1" and raiz.findtext(f".//{SII}FmaPago") == "2"
    assert raiz.findtext(f".//{SII}TasaIVA") == "19" and raiz.findtext(f".//{SII}Acteco") == "477310"
    tot = r["totales"]
    assert tot["neto"] + tot["iva"] == tot["total"]
    # El DTE suelto también cumple el esquema DTE_v10 (como lo valida el receptor de la factura).
    validar_esquema(r["xml"], "DTE")
    verificar_timbre(r["xml"], caf)
    sobre = envio.construir([r["xml"]], [33], EMISOR["rut"], firma, "2026-10-01", 0)
    assert verificar_xml(validar_esquema(sobre, "EnvioDTE")) == 2


def test_factura_pide_los_datos_del_cliente(firma):
    caf = Caf(caf_de_prueba(33))
    base = {"tipo": 33, "folio": 1, "fecha": "2026-10-26", "emisor": EMISOR, "lineas": [linea("X", 1, 100)]}
    with pytest.raises(ErrorSII, match="RUT"):
        dte.construir(base | {"receptor": {"rut": "66666666-6"}}, caf, firma)
    with pytest.raises(ErrorSII, match="giro del cliente"):
        dte.construir(base | {"receptor": CLIENTE | {"giro": ""}}, caf, firma)
    with pytest.raises(ErrorSII, match="Acteco"):
        dte.construir(base | {"receptor": CLIENTE, "emisor": EMISOR | {"actecos": []}}, caf, firma)


def test_nota_de_credito_de_una_boleta(firma):
    caf = Caf(caf_de_prueba(61))
    doc = {"tipo": 61, "folio": 3, "fecha": "2026-10-27", "emisor": EMISOR, "receptor": None,
           "lineas": [linea("PARACETAMOL 500MG X 16 COMP", 1, 990)],
           "referencias": [{"tipo": 39, "folio": 7, "fecha": "2026-10-26", "codigo": 3, "razon": "Devolución"}]}
    r = dte.construir(doc, caf, firma)
    raiz = etree.fromstring(r["xml"])
    ref = raiz.find(f".//{SII}Referencia")
    assert [(e.tag.replace(SII, ""), e.text) for e in ref] == [
        ("NroLinRef", "1"), ("TpoDocRef", "39"), ("FolioRef", "7"), ("FchRef", "2026-10-26"), ("CodRef", "3"),
        ("RazonRef", "Devolución")]
    sobre = envio.construir([r["xml"]], [61], EMISOR["rut"], firma, "2026-10-01", 0)
    assert verificar_xml(validar_esquema(sobre, "EnvioDTE")) == 2
    with pytest.raises(ErrorSII, match="qué documento"):
        dte.construir(doc | {"referencias": []}, caf, firma)
    with pytest.raises(ErrorSII, match="sobres distintos"):
        envio.construir([r["xml"]], [61, 39], EMISOR["rut"], firma, "2026-10-01", 0)


# --- Textos, timbre y PDF417 --------------------------------------------------------------------------

def test_textos_para_el_sii():
    assert texto_sii("Crema “Nivea” 50 ml — 2×1 😀", 80) == "Crema Nivea 50 ml - 2×1"
    assert texto_sii("  muchos\t espacios aquí ") == "muchos espacios aquí"
    assert texto_timbre("Pañuelos ÆGIS Straße ﬁno", 40) == "Panuelos AEGIS Strasse fino"
    assert len(texto_timbre("ß" * 30)) == 40          # se corta después de plegar


def test_pdf417_del_timbre(firma):
    r = dte.construir(boleta(), Caf(caf_de_prueba(39)), firma)
    filas = matriz(r["ted"], 12)
    assert len(filas) <= 90 and len({len(f) for f in filas}) == 1
    assert len(filas[0]) == 17 * (12 + 4) + 1       # inicio, indicadores, 12 columnas y parada
    assert all(f.startswith("11111111010101000") and f.endswith("111111101000101001") for f in filas)
    # Si no cabe en 90 filas con pocas columnas, usa más.
    assert len(matriz(r["ted"], 3)) <= 90


# --- Conexión con el SII (simulado) ---------------------------------------------------------------------

class SIISimulado:
    def __init__(self, respuestas):
        self.respuestas, self.pedidos = respuestas, []

    def __call__(self, metodo, url, cabeceras, cuerpo=None):
        self.pedidos.append((metodo, url, cabeceras, cuerpo))
        for patron, respuesta in self.respuestas:
            if patron in url:
                return respuesta(cuerpo) if callable(respuesta) else respuesta
        return 404, b""


def _escapado(xml):
    return xml.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").encode()


SEMILLA = (200, b'<soapenv:Envelope><soapenv:Body><getSeedResponse><getSeedReturn>' + _escapado(
    '<?xml version="1.0" encoding="UTF-8"?><SII:RESPUESTA xmlns:SII="http://www.sii.cl/XMLSchema"><SII:RESP_BODY>'
    '<SEMILLA>012345678901</SEMILLA></SII:RESP_BODY><SII:RESP_HDR><ESTADO>00</ESTADO></SII:RESP_HDR>'
    '</SII:RESPUESTA>') + b"</getSeedReturn></getSeedResponse></soapenv:Body></soapenv:Envelope>")


def _token(cuerpo):
    # El SII recibe la semilla firmada (escapada dentro del SOAP): se comprueba que la firma valga.
    texto = re.search(rb"<pszXml>(.*)</pszXml>", cuerpo, re.S).group(1).decode()
    firmado = texto.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    raiz = etree.fromstring(firmado.split("?>", 1)[1].encode())
    assert raiz.findtext("item/Semilla") == "012345678901" and verificar_xml(raiz) == 1
    return 200, b"<getTokenReturn>" + _escapado(
        "<SII:RESPUESTA><SII:RESP_BODY><TOKEN>TOKEN123</TOKEN></SII:RESP_BODY><SII:RESP_HDR><ESTADO>00</ESTADO>"
        "</SII:RESP_HDR></SII:RESPUESTA>") + b"</getTokenReturn>"


def test_conexion_soap_semilla_token_envio_y_estado(firma):
    sii = SIISimulado([
        ("CrSeed", SEMILLA), ("GetTokenFromSeed", _token),
        ("DTEUpload", (200, b'<?xml version="1.0"?><RECEPCIONDTE><RUTSENDER>13185095-6</RUTSENDER><STATUS>0</STATUS>'
                            b"<TRACKID>4567</TRACKID></RECEPCIONDTE>")),
        ("QueryEstUp", (200, b"<getEstUpReturn>" + _escapado(
            "<SII:RESPUESTA><SII:RESP_HDR><ESTADO>EPR</ESTADO><GLOSA>Envio Procesado</GLOSA></SII:RESP_HDR>"
            "<SII:RESP_BODY><TIPO_DOCTO>33</TIPO_DOCTO><INFORMADOS>1</INFORMADOS><ACEPTADOS>1</ACEPTADOS>"
            "<RECHAZADOS>0</RECHAZADOS><REPAROS>0</REPAROS></SII:RESP_BODY></SII:RESPUESTA>") + b"</getEstUpReturn>")),
    ])
    con = ConexionSII("certificacion", firma, EMISOR["rut"], transporte=sii)
    assert con.enviar(b"<EnvioDTE/>", boleta=False) == "4567"
    metodo, url, cab, cuerpo = sii.pedidos[-1]
    assert url == "https://maullin.sii.cl/cgi_dte/UPL/DTEUpload" and cab["Cookie"] == "TOKEN=TOKEN123"
    assert b'name="rutSender"\r\n\r\n13185095\r\n' in cuerpo and b'name="dvCompany"\r\n\r\nK\r\n' in cuerpo
    assert b"<EnvioDTE/>" in cuerpo
    estado = con.estado("4567", boleta=False)
    assert estado["estado"] == "EPR" and estado["final"] and estado["aceptados"] == 1
    # El token se reutiliza: una sola semilla para el envío y la consulta.
    assert sum("CrSeed" in p[1] for p in sii.pedidos) == 1
    # En certificación las boletas también van por DTEUpload (no por la API REST).
    con.enviar(b"<EnvioBOLETA/>", boleta=True)
    assert sii.pedidos[-1][1].endswith("/DTEUpload")


def test_conexion_soap_rechazo_de_esquema(firma):
    sii = SIISimulado([("CrSeed", SEMILLA), ("GetTokenFromSeed", _token),
                       ("DTEUpload", (200, b"<RECEPCIONDTE><STATUS>7</STATUS></RECEPCIONDTE>"))])
    with pytest.raises(ErrorSII, match="esquema"):
        ConexionSII("produccion", firma, EMISOR["rut"], transporte=sii).enviar(b"<x/>", boleta=False)
    assert sii.pedidos[-1][1].startswith("https://palena.sii.cl/")


def test_conexion_rest_de_boletas_en_produccion(firma):
    def token_rest(cuerpo):
        raiz = etree.fromstring(cuerpo.split(b"?>", 1)[1])
        assert verificar_xml(raiz) == 1
        return 200, b"<SII:RESPUESTA><SII:RESP_BODY><TOKEN>TK9</TOKEN></SII:RESP_BODY></SII:RESPUESTA>"

    estado = {"rut_emisor": "76354771-K", "trackid": 99, "estado": "EPR",
              "estadistica": [{"tipo": 39, "informados": 2, "aceptados": 1, "rechazados": 1, "reparos": 0}],
              "detalle_rep_rech": [{"tipo": 39, "folio": 8, "estado": "RCH",
                                    "error": [{"descripcion": "Monto no cuadra"}]}]}
    sii = SIISimulado([
        ("boleta.electronica.semilla", (200, b"<SII:RESPUESTA><SII:RESP_BODY><SEMILLA>777</SEMILLA></SII:RESP_BODY>"
                                             b"</SII:RESPUESTA>")),
        ("boleta.electronica.token", token_rest),
        ("rahue.sii.cl/recursos/v1/boleta.electronica.envio", (200, json.dumps({"trackid": 99, "estado": "REC"}).encode())),
        ("api.sii.cl/recursos/v1/boleta.electronica.envio/", (200, json.dumps(estado).encode())),
    ])
    con = ConexionSII("produccion", firma, EMISOR["rut"], transporte=sii)
    assert con.enviar(b"<EnvioBOLETA/>", boleta=True) == "99"
    assert sii.pedidos[-1][2]["Cookie"] == "TOKEN=TK9"
    r = con.estado("99", boleta=True)
    assert sii.pedidos[-1][1].endswith("/boleta.electronica.envio/76354771-K-99")
    assert r["final"] and r["rechazados"] == 1 and r["detalle"] == [
        {"tipo": 39, "folio": 8, "estado": "RCH", "glosa": "Monto no cuadra"}]


def test_conexion_firma_no_autorizada(firma):
    sii = SIISimulado([("CrSeed", SEMILLA), ("GetTokenFromSeed", (200, b"<getTokenReturn>" + _escapado(
        "<SII:RESPUESTA><SII:RESP_HDR><ESTADO>11</ESTADO><GLOSA>FIRMA NO AUTORIZADA</GLOSA></SII:RESP_HDR>"
        "</SII:RESPUESTA>") + b"</getTokenReturn>"))])
    with pytest.raises(ErrorSII, match="FIRMA NO AUTORIZADA"):
        ConexionSII("certificacion", firma, EMISOR["rut"], transporte=sii).token()
