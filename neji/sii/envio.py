"""El sobre que se sube al SII: EnvioBOLETA (boletas 39/41) o EnvioDTE (facturas y notas de crédito).

Los DTE se insertan tal como se firmaron (con sus xmlns): dentro del sobre heredan los mismos espacios de
nombres que declaran, así su firma sigue valiendo. Después se firma el SetDTE completo.
"""

import re
from collections import Counter

from ..chile import limpiar_rut
from . import BOLETAS, NS_SII, NS_XSI, RUT_SII, ErrorSII
from .dte import marca_de_tiempo

ESQUEMAS = {"EnvioBOLETA": "EnvioBOLETA_v11.xsd", "EnvioDTE": "EnvioDTE_v10.xsd"}


def raiz_del_sobre(tipos):
    """EnvioBOLETA si son boletas; EnvioDTE para lo demás. No se mezclan en un mismo sobre."""
    boletas = {t in BOLETAS for t in tipos}
    if len(boletas) != 1:
        raise ErrorSII("Las boletas y las facturas van en sobres distintos.")
    return "EnvioBOLETA" if boletas.pop() else "EnvioDTE"


def _sin_declaracion(xml):
    texto = xml.decode("iso-8859-1") if isinstance(xml, bytes) else xml
    return re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", texto).strip()


def construir(dtes, tipos, emisor_rut, firma, fecha_resolucion, numero_resolucion, momento=None,
              rut_receptor=RUT_SII):
    """`dtes`: XML firmados (bytes) de los documentos; `tipos`: el tipo de cada uno. Devuelve bytes ISO-8859-1.

    `rut_receptor`: el SII (el sobre que se sube) o el cliente (el que se le manda por correo con su factura).
    """
    from lxml import etree

    if not dtes:
        raise ErrorSII("No hay documentos que enviar.")
    if not firma.rut:
        raise ErrorSII("La firma electrónica no trae el RUT de su titular: no se puede enviar al SII.")
    raiz_nombre = raiz_del_sobre(tipos)
    subtotales = "".join(f"<SubTotDTE><TpoDTE>{t}</TpoDTE><NroDTE>{n}</NroDTE></SubTotDTE>"
                         for t, n in sorted(Counter(tipos).items()))
    caratula = (f'<Caratula version="1.0"><RutEmisor>{limpiar_rut(emisor_rut)}</RutEmisor>'
                f"<RutEnvia>{limpiar_rut(firma.rut)}</RutEnvia>"
                f"<RutReceptor>{limpiar_rut(rut_receptor)}</RutReceptor>"
                f"<FchResol>{fecha_resolucion}</FchResol><NroResol>{int(numero_resolucion)}</NroResol>"
                f"<TmstFirmaEnv>{marca_de_tiempo(momento)}</TmstFirmaEnv>{subtotales}</Caratula>")
    cuerpo = "\n".join(_sin_declaracion(d) for d in dtes)
    texto = (f'<{raiz_nombre} xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" '
             f'xsi:schemaLocation="{NS_SII} {ESQUEMAS[raiz_nombre]}" version="1.0">\n'
             f'<SetDTE ID="SetDoc">\n{caratula}\n{cuerpo}\n</SetDTE>\n</{raiz_nombre}>')
    raiz = etree.fromstring(texto.encode("utf-8"), etree.XMLParser(resolve_entities=False, huge_tree=True))
    firma.firmar_xml(raiz, "SetDoc")
    return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(
        raiz, encoding="ISO-8859-1", xml_declaration=False)
