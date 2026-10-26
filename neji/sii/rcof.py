"""Reporte de consumo de folios de boletas (RCOF, ConsumoFolio_v10.xsd).

Desde 2022 ya no se envía en la operación normal (Res. Ex. SII N° 53), pero la certificación de la boleta
electrónica todavía lo pide junto con el envío del set de pruebas de boletas.
"""

from collections import defaultdict

from ..chile import limpiar_rut
from . import BOLETAS, NS_SII, NS_XSI, ErrorSII
from .dte import marca_de_tiempo

TASA_IVA = 19


def rangos(folios):
    """[1, 2, 3, 7] -> [(1, 3), (7, 7)]"""
    resultado = []
    for folio in sorted(folios):
        if resultado and folio == resultado[-1][1] + 1:
            resultado[-1][1] = folio
        else:
            resultado.append([folio, folio])
    return [tuple(r) for r in resultado]


def construir(boletas, rut_emisor, firma, fecha_resolucion, numero_resolucion, secuencia=1, momento=None):
    """`boletas`: [{tipo, folio, fecha, neto, iva, exento, total}] (filas de sii_documentos). Bytes ISO-8859-1."""
    from lxml import etree

    if not boletas:
        raise ErrorSII("No hay boletas para el reporte de consumo de folios.")
    if any(b["tipo"] not in BOLETAS for b in boletas):
        raise ErrorSII("El consumo de folios es solo de boletas (39 y 41).")
    if not firma.rut:
        raise ErrorSII("La firma electrónica no trae el RUT de su titular: no se puede enviar al SII.")
    fechas = sorted(b["fecha"] for b in boletas)
    por_tipo = defaultdict(list)
    for b in boletas:
        por_tipo[b["tipo"]].append(b)
    ident = f"RCOF_{fechas[0].replace('-', '')}_{int(secuencia)}"
    partes = [f"<Caratula version=\"1.0\"><RutEmisor>{limpiar_rut(rut_emisor)}</RutEmisor>"
              f"<RutEnvia>{limpiar_rut(firma.rut)}</RutEnvia><FchResol>{fecha_resolucion}</FchResol>"
              f"<NroResol>{int(numero_resolucion)}</NroResol><FchInicio>{fechas[0]}</FchInicio>"
              f"<FchFinal>{fechas[-1]}</FchFinal><SecEnvio>{int(secuencia)}</SecEnvio>"
              f"<TmstFirmaEnv>{marca_de_tiempo(momento)}</TmstFirmaEnv></Caratula>"]
    for tipo in sorted(por_tipo):
        docs = por_tipo[tipo]
        neto, iva = sum(d["neto"] for d in docs), sum(d["iva"] for d in docs)
        exento, total = sum(d["exento"] for d in docs), sum(d["total"] for d in docs)
        resumen = f"<Resumen><TipoDocumento>{tipo}</TipoDocumento>"
        if neto or iva:
            resumen += f"<MntNeto>{neto}</MntNeto><MntIva>{iva}</MntIva><TasaIVA>{TASA_IVA}</TasaIVA>"
        if exento:
            resumen += f"<MntExento>{exento}</MntExento>"
        resumen += (f"<MntTotal>{total}</MntTotal><FoliosEmitidos>{len(docs)}</FoliosEmitidos>"
                    f"<FoliosAnulados>0</FoliosAnulados><FoliosUtilizados>{len(docs)}</FoliosUtilizados>")
        resumen += "".join(f"<RangoUtilizados><Inicial>{a}</Inicial><Final>{b}</Final></RangoUtilizados>"
                           for a, b in rangos(d["folio"] for d in docs))
        partes.append(resumen + "</Resumen>")
    cuerpo = "\n".join(partes)
    texto = (f'<ConsumoFolios xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" '
             f'xsi:schemaLocation="{NS_SII} ConsumoFolio_v10.xsd" version="1.0">\n'
             f'<DocumentoConsumoFolios ID="{ident}">\n{cuerpo}\n</DocumentoConsumoFolios>\n</ConsumoFolios>')
    raiz = etree.fromstring(texto.encode("utf-8"))
    firma.firmar_xml(raiz, ident)
    return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(
        raiz, encoding="ISO-8859-1", xml_declaration=False)
