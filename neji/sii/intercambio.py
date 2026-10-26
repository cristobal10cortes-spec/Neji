"""Intercambio de información entre contribuyentes: las respuestas a un envío de DTE recibido.

En la certificación el SII le manda al postulante (a su correo de intercambio) un EnvioDTE con facturas a su
nombre, y el postulante debe responder con tres XML firmados (formato_mensaje_respuesta_dte.pdf):

1. RespuestaDTE con RecepcionEnvio: acuse de recibo del archivo (RespuestaEnvioDTE_v10.xsd).
2. EnvioRecibos: recibo de las mercaderías o servicios, Ley 19.983 (EnvioRecibos_v10.xsd).
3. RespuestaDTE con ResultadoDTE: aceptación (o rechazo) comercial de cada documento.

Un documento a nombre de otro RUT se informa como no recibido / rechazado; lo demás se acepta.
"""

import re

from ..chile import limpiar_rut
from . import NS_SII, NS_XSI, ErrorSII
from .dte import marca_de_tiempo
from .textos import correo_valido, texto_sii

DECLARACION = ("El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto en la letra b) del Art. 4, "
               "y la letra c) del Art. 5 de la Ley 19.983, acredita que la entrega de mercaderias o servicio(s) "
               "prestado(s) ha(n) sido recibido(s).")


def leer_envio(xml):
    """El EnvioDTE recibido -> {id, rut_emisor, rut_receptor, digest, documentos: [...], firma_valida}."""
    from lxml import etree

    from .firma import DS, verificar_xml

    if b"<!DOCTYPE" in bytes(xml)[:4096].upper():
        raise ErrorSII("El archivo no es un envío de documentos del SII (trae una declaración DOCTYPE).")
    try:
        raiz = etree.fromstring(bytes(xml), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        raise ErrorSII("El archivo no es un XML válido (debe ser el EnvioDTE que mandó el SII).") from None
    ns = {"s": NS_SII}
    set_dte = raiz.find("s:SetDTE", ns)
    if etree.QName(raiz).localname != "EnvioDTE" or set_dte is None:
        raise ErrorSII("El archivo no es un envío de documentos (EnvioDTE).")
    texto = lambda el, ruta: (el.findtext(ruta, namespaces=ns) or "").strip()   # noqa: E731
    caratula = set_dte.find("s:Caratula", ns)
    documentos = []
    for doc in set_dte.findall("s:DTE/s:Documento", ns):
        documentos.append({
            "tipo": int(texto(doc, "s:Encabezado/s:IdDoc/s:TipoDTE") or 0),
            "folio": int(texto(doc, "s:Encabezado/s:IdDoc/s:Folio") or 0),
            "fecha": texto(doc, "s:Encabezado/s:IdDoc/s:FchEmis"),
            "rut_emisor": limpiar_rut(texto(doc, "s:Encabezado/s:Emisor/s:RUTEmisor")),
            "razon_emisor": texto(doc, "s:Encabezado/s:Emisor/s:RznSoc"),
            "rut_receptor": limpiar_rut(texto(doc, "s:Encabezado/s:Receptor/s:RUTRecep")),
            "total": int(texto(doc, "s:Encabezado/s:Totales/s:MntTotal") or 0),
        })
    if not documentos:
        raise ErrorSII("El envío no trae documentos.")
    for d in documentos:
        # Lo que se copia a las respuestas tiene que tener la forma que pide el esquema (y nada más).
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["fecha"]) or not d["rut_emisor"] or not d["rut_receptor"]:
            raise ErrorSII(f"El documento {d['tipo']} N° {d['folio']} del envío no tiene la fecha o los RUT bien "
                           "escritos.")
    firma_set = raiz.find(f"{{{DS}}}Signature", None)
    digest = firma_set.findtext(f".//{{{DS}}}DigestValue") if firma_set is not None else None
    try:
        firma_valida = verificar_xml(raiz) > 0
    except ErrorSII:
        firma_valida = False
    ident = set_dte.get("ID") or "SetDoc"
    if not re.fullmatch(r"[A-Za-z_][\w.\-]{0,79}", ident):
        ident = "SetDoc"
    return {"id": ident, "rut_emisor": limpiar_rut(texto(caratula, "s:RutEmisor")),
            "rut_receptor": limpiar_rut(texto(caratula, "s:RutReceptor")), "digest": (digest or "").strip(),
            "documentos": documentos, "firma_valida": firma_valida}


def _caratula(rut_empresa, rut_recibe, contacto, marca, detalles=None, etiqueta_tiempo="TmstFirmaResp"):
    partes = [f"<RutResponde>{rut_empresa}</RutResponde>", f"<RutRecibe>{rut_recibe}</RutRecibe>"]
    if detalles is not None:
        partes += ["<IdRespuesta>1</IdRespuesta>", f"<NroDetalles>{detalles}</NroDetalles>"]
    nombre = texto_sii((contacto or {}).get("nombre"), 40)
    if nombre:
        partes.append(f"<NmbContacto>{_escapar(nombre)}</NmbContacto>")
    correo = str((contacto or {}).get("correo") or "").strip()
    if correo_valido(correo) and len(correo) <= 40:
        partes.append(f"<MailContacto>{_escapar(correo)}</MailContacto>")
    partes.append(f"<{etiqueta_tiempo}>{marca}</{etiqueta_tiempo}>")
    return f'<Caratula version="1.0">{"".join(partes)}</Caratula>'


def _escapar(texto):
    return str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _firmado(texto, firma, *ids):
    from lxml import etree

    raiz = etree.fromstring(texto.encode("utf-8"))
    for ident in ids:
        objetivo = raiz.xpath("//*[@ID=$id]", id=ident)[0]
        firma.firmar_xml(objetivo.getparent(), ident)
    return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(
        raiz, encoding="ISO-8859-1", xml_declaration=False)


def _estado(doc, envio, rut_empresa):
    """(estado de recepción, glosa) de un documento: 0 recibido; 3 a otro receptor; 2 de otro emisor."""
    if doc["rut_receptor"] != rut_empresa:
        return 3, "DTE No Recibido - Error en RUT Receptor"
    if envio["rut_emisor"] and doc["rut_emisor"] != envio["rut_emisor"]:
        return 2, "DTE No Recibido - Error en RUT Emisor"
    return 0, "DTE Recibido OK"


def respuestas(xml, nombre_archivo, rut_empresa, firma, contacto=None, recinto=None, momento=None):
    """Las tres respuestas firmadas: {"recepcion": bytes, "recibos": bytes, "resultado": bytes, "envio": {...}}."""
    rut_empresa = limpiar_rut(rut_empresa)
    if not firma.rut:
        raise ErrorSII("La firma electrónica no trae el RUT de su titular.")
    envio = leer_envio(xml)
    marca = marca_de_tiempo(momento)
    rut_emisor = envio["rut_emisor"] or envio["documentos"][0]["rut_emisor"]
    abre = f'xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}"'
    estados = [_estado(d, envio, rut_empresa) for d in envio["documentos"]]

    # 1. Acuse de recibo del envío.
    recibido = envio["rut_receptor"] in ("", rut_empresa)
    filas = "".join(
        f"<RecepcionDTE><TipoDTE>{d['tipo']}</TipoDTE><Folio>{d['folio']}</Folio><FchEmis>{d['fecha']}</FchEmis>"
        f"<RUTEmisor>{d['rut_emisor']}</RUTEmisor><RUTRecep>{d['rut_receptor']}</RUTRecep>"
        f"<MntTotal>{d['total']}</MntTotal><EstadoRecepDTE>{estado}</EstadoRecepDTE>"
        f"<RecepDTEGlosa>{glosa}</RecepDTEGlosa></RecepcionDTE>"
        for d, (estado, glosa) in zip(envio["documentos"], estados))
    digest = f"<Digest>{envio['digest']}</Digest>" if envio["digest"] else ""
    recepcion = (
        f'<RespuestaDTE {abre} xsi:schemaLocation="{NS_SII} RespuestaEnvioDTE_v10.xsd" version="1.0">\n'
        f'<Resultado ID="RespuestaRecepcion">\n{_caratula(rut_empresa, rut_emisor, contacto, marca, 1)}\n'
        f"<RecepcionEnvio><NmbEnvio>{_escapar(texto_sii(nombre_archivo, 80) or 'EnvioDTE.xml')}</NmbEnvio>"
        f"<FchRecep>{marca}</FchRecep><CodEnvio>1</CodEnvio><EnvioDTEID>{_escapar(envio['id'][:80])}</EnvioDTEID>"
        f"{digest}<RutEmisor>{rut_emisor}</RutEmisor><RutReceptor>{rut_empresa}</RutReceptor>"
        f"<EstadoRecepEnv>{0 if recibido else 3}</EstadoRecepEnv>"
        f"<RecepEnvGlosa>{'Envio Recibido Conforme' if recibido else 'Envio Rechazado - RUT Receptor No Corresponde'}"
        f"</RecepEnvGlosa><NroDTE>{len(envio['documentos'])}</NroDTE>\n{filas}\n</RecepcionEnvio>\n"
        f"</Resultado>\n</RespuestaDTE>")

    # 2. Recibo de mercaderías (solo de lo que se recibió).
    aceptados = [d for d, (estado, _) in zip(envio["documentos"], estados) if estado == 0 and recibido]
    lugar = _escapar(texto_sii(recinto, 80) or "Oficina central")
    recibos = "\n".join(
        f'<Recibo version="1.0"><DocumentoRecibo ID="Recibo{n}"><TipoDoc>{d["tipo"]}</TipoDoc>'
        f"<Folio>{d['folio']}</Folio><FchEmis>{d['fecha']}</FchEmis><RUTEmisor>{d['rut_emisor']}</RUTEmisor>"
        f"<RUTRecep>{d['rut_receptor']}</RUTRecep><MntTotal>{d['total']}</MntTotal><Recinto>{lugar}</Recinto>"
        f"<RutFirma>{limpiar_rut(firma.rut)}</RutFirma><Declaracion>{DECLARACION}</Declaracion>"
        f"<TmstFirmaRecibo>{marca}</TmstFirmaRecibo></DocumentoRecibo></Recibo>"
        for n, d in enumerate(aceptados, start=1))
    envio_recibos = None
    if aceptados:
        envio_recibos = (
            f'<EnvioRecibos {abre} xsi:schemaLocation="{NS_SII} EnvioRecibos_v10.xsd" version="1.0">\n'
            f'<SetRecibos ID="SetRecibos">\n'
            f'{_caratula(rut_empresa, rut_emisor, contacto, marca, etiqueta_tiempo="TmstFirmaEnv")}\n'
            f"{recibos}\n</SetRecibos>\n</EnvioRecibos>")

    # 3. Aceptación (o rechazo) comercial de cada documento.
    resultados = "\n".join(
        f"<ResultadoDTE><TipoDTE>{d['tipo']}</TipoDTE><Folio>{d['folio']}</Folio><FchEmis>{d['fecha']}</FchEmis>"
        f"<RUTEmisor>{d['rut_emisor']}</RUTEmisor><RUTRecep>{d['rut_receptor']}</RUTRecep>"
        f"<MntTotal>{d['total']}</MntTotal><CodEnvio>{n}</CodEnvio>"
        + ("<EstadoDTE>0</EstadoDTE><EstadoDTEGlosa>ACEPTADO OK</EstadoDTEGlosa>" if estado == 0 and recibido else
           f"<EstadoDTE>2</EstadoDTE><EstadoDTEGlosa>RECHAZADO - {glosa}</EstadoDTEGlosa><CodRchDsc>-1</CodRchDsc>")
        + "</ResultadoDTE>"
        for n, (d, (estado, glosa)) in enumerate(zip(envio["documentos"], estados), start=1))
    resultado = (
        f'<RespuestaDTE {abre} xsi:schemaLocation="{NS_SII} RespuestaEnvioDTE_v10.xsd" version="1.0">\n'
        f'<Resultado ID="ResultadoDTE">\n'
        f"{_caratula(rut_empresa, rut_emisor, contacto, marca, len(envio['documentos']))}\n"
        f"{resultados}\n</Resultado>\n</RespuestaDTE>")

    return {"recepcion": _firmado(recepcion, firma, "RespuestaRecepcion"),
            "recibos": _firmado(envio_recibos, firma, *[f"Recibo{n}" for n in range(1, len(aceptados) + 1)],
                                "SetRecibos") if envio_recibos else None,
            "resultado": _firmado(resultado, firma, "ResultadoDTE"),
            "envio": envio}
