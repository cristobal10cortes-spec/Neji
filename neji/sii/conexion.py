"""Conexión con los servidores del SII: autenticación (semilla y token), envío de sobres y consulta de estado.

- Facturas y notas de crédito: servicios SOAP (CrSeed, GetTokenFromSeed, DTEUpload, QueryEstUp) en maullin
  (certificación) o palena (producción).
- Boletas en producción: la API REST de boletas (api.sii.cl y rahue.sii.cl). En certificación el SII recibe las
  boletas por el mismo DTEUpload de las facturas (la API REST no sirve para el set de pruebas).

`transporte(metodo, url, cabeceras, cuerpo)` -> (status, cuerpo_bytes) se puede reemplazar en las pruebas.
"""

import html
import json
import re
import secrets
import time
import urllib.error
import urllib.request

from ..chile import limpiar_rut
from . import ErrorSII

SOAP = {
    "certificacion": "https://maullin.sii.cl",
    "produccion": "https://palena.sii.cl",
}
REST = {
    "certificacion": {"api": "https://apicert.sii.cl/recursos/v1", "envio": "https://pangal.sii.cl/recursos/v1"},
    "produccion": {"api": "https://api.sii.cl/recursos/v1", "envio": "https://rahue.sii.cl/recursos/v1"},
}
AGENTE = "Mozilla/4.0 (compatible; PROG 1.0; Windows NT 5.0; YComp 5.0.2.4)"
DURACION_TOKEN = 30 * 60   # se renueva antes de que el SII lo dé por vencido

ESTADOS_SUBIDA = {
    "1": "El usuario que firma no tiene permiso para enviar documentos de esta empresa.",
    "2": "El tamaño del archivo no es válido.", "3": "El archivo llegó cortado.",
    "5": "No se pudo autenticar con el SII.", "6": "La empresa no está autorizada para enviar documentos.",
    "7": "El sobre no cumple el esquema del SII.", "8": "La firma del sobre no es válida.",
    "9": "El sistema del SII está bloqueado. Se reintentará.",
}
# Estados del envío (QueryEstUp / API de boletas)
EN_PROCESO = {"REC", "SOK", "FOK", "PRD", "CRT", "PDR", "-11", ""}
RECHAZADO = {"RSC": "rechazado por error de esquema", "RFR": "rechazado por error en la firma",
             "RCT": "rechazado por error en la carátula", "RCH": "rechazado", "RPT": "rechazado por esquema",
             "VOF": "rechazado: el archivo no es válido"}


def transporte_http(metodo, url, cabeceras, cuerpo=None, espera=40):
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(pedido, timeout=espera) as respuesta:
            return respuesta.status, respuesta.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        motivo = getattr(e, "reason", e)
        raise ErrorSII(f"No se pudo conectar con el SII ({motivo}). Se reintentará solo.") from None


def _xml_respuesta(cuerpo):
    """Las respuestas SOAP del SII traen el XML de verdad escapado dentro del sobre SOAP."""
    texto = cuerpo.decode("utf-8", "replace") if isinstance(cuerpo, bytes) else cuerpo
    for _ in range(2):
        texto = html.unescape(texto)
    return texto


def _etiqueta(texto, nombre):
    m = re.search(rf"<(?:\w+:)?{nombre}>\s*([^<]*?)\s*</(?:\w+:)?{nombre}>", texto)
    return m.group(1) if m else None


def _soap(cuerpo_xml):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<soapenv:Envelope '
            'xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
            f"{cuerpo_xml}</soapenv:Body></soapenv:Envelope>").encode("utf-8")


def _multipart(campos, nombre_archivo, archivo):
    limite = "----NejiPOS" + secrets.token_hex(12)
    partes = []
    for nombre, valor in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'.encode())
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="archivo"; filename="{nombre_archivo}"\r\n'
                  "Content-Type: text/xml\r\n\r\n".encode() + archivo + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


class ConexionSII:
    def __init__(self, ambiente, firma, rut_emisor, transporte=transporte_http):
        if ambiente not in SOAP:
            raise ErrorSII("El ambiente del SII debe ser certificación o producción.")
        self.ambiente, self.firma, self.transporte = ambiente, firma, transporte
        self.rut_emisor = limpiar_rut(rut_emisor)
        self._tokens = {}

    # --- Autenticación ----------------------------------------------------------------------------------

    def _semilla_firmada(self, semilla):
        from lxml import etree

        raiz = etree.fromstring(f"<getToken><item><Semilla>{semilla}</Semilla></item></getToken>")
        self.firma.firmar_xml(raiz)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(raiz, encoding="unicode")

    def token(self, rest=False):
        clave = "rest" if rest else "soap"
        guardado = self._tokens.get(clave)
        if guardado and time.monotonic() - guardado[1] < DURACION_TOKEN:
            return guardado[0]
        self.firma.exigir_vigente()
        if rest:
            base = REST[self.ambiente]["api"]
            status, cuerpo = self.transporte("GET", f"{base}/boleta.electronica.semilla", {"Accept": "application/xml"})
            semilla = _etiqueta(_xml_respuesta(cuerpo), "SEMILLA")
            if status != 200 or not semilla:
                raise ErrorSII(f"El SII no entregó la semilla (HTTP {status}).")
            status, cuerpo = self.transporte(
                "POST", f"{base}/boleta.electronica.token",
                {"Accept": "application/xml", "Content-Type": "application/xml"},
                self._semilla_firmada(semilla).encode("utf-8"))
        else:
            base = SOAP[self.ambiente]
            cab = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
            status, cuerpo = self.transporte("POST", f"{base}/DTEWS/CrSeed.jws", cab, _soap("<getSeed/>"))
            semilla = _etiqueta(_xml_respuesta(cuerpo), "SEMILLA")
            if status != 200 or not semilla:
                raise ErrorSII(f"El SII no entregó la semilla (HTTP {status}).")
            firmada = html.escape(self._semilla_firmada(semilla), quote=False)
            status, cuerpo = self.transporte("POST", f"{base}/DTEWS/GetTokenFromSeed.jws", cab,
                                             _soap(f"<getToken><pszXml>{firmada}</pszXml></getToken>"))
        texto = _xml_respuesta(cuerpo)
        token = _etiqueta(texto, "TOKEN")
        if status != 200 or not token:
            glosa = _etiqueta(texto, "GLOSA") or f"HTTP {status}"
            raise ErrorSII(f"El SII no aceptó la firma electrónica para conectarse: {glosa}. Revisa que la firma "
                           "esté vigente y autorizada en el SII para esta empresa.")
        self._tokens[clave] = (token, time.monotonic())
        return token

    def _usa_rest(self, boleta):
        return boleta and self.ambiente == "produccion"

    # --- Envío ------------------------------------------------------------------------------------------

    def enviar(self, sobre, boleta):
        """Sube el sobre firmado. Devuelve el número de atención (trackid)."""
        rest = self._usa_rest(boleta)
        token = self.token(rest)
        envia = limpiar_rut(self.firma.rut)
        campos = {"rutSender": envia[:-2], "dvSender": envia[-1], "rutCompany": self.rut_emisor[:-2],
                  "dvCompany": self.rut_emisor[-1]}
        cuerpo, tipo = _multipart(campos, "EnvioBOLETA.xml" if boleta else "EnvioDTE.xml", sobre)
        cab = {"Content-Type": tipo, "Cookie": f"TOKEN={token}", "User-Agent": AGENTE,
               "Accept": "application/json" if rest else "*/*"}
        if rest:
            url = f"{REST[self.ambiente]['envio']}/boleta.electronica.envio"
        else:
            url = f"{SOAP[self.ambiente]}/cgi_dte/UPL/DTEUpload"
        status, respuesta = self.transporte("POST", url, cab, cuerpo)
        if rest:
            try:
                datos = json.loads(respuesta.decode("iso-8859-1"))
            except ValueError:
                datos = {}
            if status == 200 and datos.get("trackid"):
                return str(datos["trackid"])
            if status in (401, 403):
                self._tokens.pop("rest", None)
            motivo = datos.get("mensaje") or datos.get("error") or f"HTTP {status}"
            raise ErrorSII(f"El SII no recibió las boletas: {motivo}.")
        texto = _xml_respuesta(respuesta)
        estado, trackid = _etiqueta(texto, "STATUS"), _etiqueta(texto, "TRACKID")
        if status == 200 and estado == "0" and trackid:
            return trackid
        if estado == "5":
            self._tokens.pop("soap", None)
        motivo = ESTADOS_SUBIDA.get(estado or "", f"estado {estado}" if estado else f"HTTP {status}")
        raise ErrorSII(f"El SII no recibió el envío: {motivo}", definitivo=estado in ("7", "8"))

    # --- Estado -----------------------------------------------------------------------------------------

    def estado(self, trackid, boleta):
        """{estado, glosa, final, aceptados, rechazados, reparos, detalle: [{tipo, folio, estado, glosa}]}"""
        if self._usa_rest(boleta):
            return self._estado_rest(trackid)
        token = self.token(False)
        rut = self.rut_emisor
        cuerpo = _soap(f"<getEstUp><RutCompania>{rut[:-2]}</RutCompania><DvCompania>{rut[-1]}</DvCompania>"
                       f"<TrackId>{trackid}</TrackId><Token>{token}</Token></getEstUp>")
        status, respuesta = self.transporte("POST", f"{SOAP[self.ambiente]}/DTEWS/QueryEstUp.jws",
                                            {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}, cuerpo)
        texto = _xml_respuesta(respuesta)
        estado = _etiqueta(texto, "ESTADO")
        if status != 200 or estado is None:
            raise ErrorSII(f"No se pudo consultar el envío {trackid} en el SII (HTTP {status}).")
        if estado in ("001", "002", "003", "-3"):    # token o envío no encontrado todavía
            self._tokens.pop("soap", None)
            return {"estado": estado, "glosa": _etiqueta(texto, "GLOSA") or "", "final": False}
        numeros = {k: sum(int(n) for n in re.findall(rf"<{k.upper()}>(\d+)</{k.upper()}>", texto))
                   for k in ("informados", "aceptados", "rechazados", "reparos")}
        return {"estado": estado, "glosa": _etiqueta(texto, "GLOSA") or "",
                "final": estado not in EN_PROCESO, "detalle": [], **numeros}

    def _estado_rest(self, trackid):
        token = self.token(True)
        rut = self.rut_emisor
        url = f"{REST[self.ambiente]['api']}/boleta.electronica.envio/{rut[:-2]}-{rut[-1]}-{trackid}"
        status, respuesta = self.transporte("GET", url, {"Accept": "application/json", "Cookie": f"TOKEN={token}",
                                                         "User-Agent": AGENTE})
        if status in (401, 403):
            self._tokens.pop("rest", None)
        if status != 200:
            raise ErrorSII(f"No se pudo consultar el envío {trackid} en el SII (HTTP {status}).")
        try:
            datos = json.loads(respuesta.decode("iso-8859-1"))
        except ValueError:
            raise ErrorSII("El SII respondió algo que no se entiende al consultar el envío.") from None
        estado = str(datos.get("estado") or "")
        numeros = {k: sum(int(e.get(k) or 0) for e in datos.get("estadistica") or [])
                   for k in ("informados", "aceptados", "rechazados", "reparos")}
        detalle = []
        for d in datos.get("detalle_rep_rech") or []:
            errores = d.get("error") or []
            glosa = "; ".join(str(e.get("descripcion") or e.get("detalle") or "") for e in errores if e)
            detalle.append({"tipo": int(d.get("tipo") or 0), "folio": int(d.get("folio") or 0),
                            "estado": str(d.get("estado") or ""), "glosa": glosa})
        return {"estado": estado, "glosa": RECHAZADO.get(estado, ""), "final": estado not in EN_PROCESO,
                "detalle": detalle, **numeros}
