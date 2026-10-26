"""Libros de compras y ventas electrónicos (Información Electrónica de Compras y Ventas, IECV).

Hoy el SII arma solo el registro de compras y ventas con lo que recibe, pero en la certificación pide enviar los
libros del set de pruebas («SET LIBRO DE VENTAS», con los documentos del set básico, y «SET LIBRO DE COMPRAS»,
con las facturas recibidas que trae el set). Esquema: LibroCV_v10.xsd.

Los montos siguen el formato del SII (formato_iecv.pdf): en compras, el IVA de una factura se reparte entre el IVA
recuperable (MntIVA), el no recuperable (IVANoRec) y el de uso común (IVAUsoComun); el monto total es neto + exento
+ IVA (de los tres tipos) - IVA retenido. Así lo arman también LibreDTE y dte-sii, que pasaron la certificación.
"""

from decimal import Decimal

from ..chile import limpiar_rut, redondear
from . import NS_SII, NS_XSI, ErrorSII
from .dte import marca_de_tiempo, numero_xml
from .textos import texto_sii

TASA_IVA = 19
ORDEN_DETALLE = ("TpoDoc", "NroDoc", "TpoImp", "TasaImp", "FchDoc", "RUTDoc", "RznSoc", "TpoDocRef", "FolioDocRef",
                 "MntExe", "MntNeto", "MntIVA", "IVANoRec", "IVAUsoComun", "OtrosImp", "IVARetTotal", "MntTotal")
ORDEN_TOTALES = ("TpoDoc", "TotDoc", "TotMntExe", "TotMntNeto", "TotMntIVA", "TotIVANoRec", "TotOpIVAUsoComun",
                 "TotIVAUsoComun", "FctProp", "TotCredIVAUsoComun", "TotOtrosImp", "TotIVARetTotal", "TotMntTotal")
# Códigos de IVA no recuperable (formato IECV): 1 operaciones exentas, 2 fuera de plazo, 3 gastos rechazados,
# 4 entregas gratuitas, 9 otros.
IVA_NO_RECUPERABLE = (("ENTREGA GRATUITA", 4), ("FUERA DE PLAZO", 2), ("GASTO RECHAZADO", 3),
                      ("SIN DERECHO A CREDITO", 1), ("NO RECUPERABLE", 9))


def iva(neto, tasa=TASA_IVA):
    return redondear(Decimal(int(neto)) * Decimal(str(tasa)) / 100)


def fecha_en_periodo(fecha, periodo):
    """La fecha del documento si cae en el período del libro; si no, el día 15 del período."""
    return fecha if str(fecha or "")[:7] == periodo else f"{periodo}-15"


# --- Detalle ---------------------------------------------------------------------------------------------

def detalle_ventas(documentos, periodo):
    """Documentos emitidos (filas de sii_documentos) -> detalle del libro de ventas."""
    detalle = []
    for d in documentos:
        fila = {"TpoDoc": d["tipo"], "NroDoc": d["folio"], "FchDoc": fecha_en_periodo(d["fecha"], periodo),
                "RUTDoc": limpiar_rut(d["rut_receptor"]), "RznSoc": texto_sii(d["razon_receptor"], 50)}
        if d["neto"] or d["iva"]:
            fila.update(TasaImp=TASA_IVA, MntNeto=d["neto"], MntIVA=d["iva"])
        if d["exento"]:
            fila["MntExe"] = d["exento"]
        fila["MntTotal"] = d["total"]
        detalle.append(fila)
    return detalle


def _no_recuperable(observacion):
    texto = (observacion or "").upper().replace("É", "E").replace("Í", "I")
    if "CON DERECHO A CREDITO" in texto:
        return None
    for frase, codigo in IVA_NO_RECUPERABLE:
        if frase in texto:
            return codigo
    return None


def _referencia_nota(doc, documentos):
    """La factura que corrige una nota del libro de compras: 'NOTA DE CREDITO POR DESCUENTO A FACTURA 234'."""
    import re

    from .set_pruebas import tipo_libro

    m = re.search(r"(FACTURA[A-ZÁÉÍÓÚ ]*?)\s*(\d+)\s*$", (doc.get("observacion") or "").upper())
    if not m:
        return None, None
    folio = int(m.group(2))
    for otro in documentos:
        if otro is not doc and otro["folio"] == folio and otro["tpo_doc"] not in (55, 56, 60, 61):
            return otro["tpo_doc"], folio
    return tipo_libro(m.group(1)), folio


def detalle_compras(documentos, periodo, fecha, exentos=False, rut_proveedor="60803000-K",
                    razon_proveedor="PROVEEDOR DEL SET DE PRUEBAS"):
    """Documentos recibidos del set (set_pruebas.leer_set: libro) -> detalle del libro de compras.

    El set no trae proveedores: se informa el SII como proveedor (un RUT que existe y no es de una persona).
    `exentos`: el libro de compras para contribuyentes exentos de IVA (todo su IVA es no recuperable).
    """
    detalle = []
    for doc in documentos:
        tipo = doc["tpo_doc"]
        if tipo is None:
            raise ErrorSII(f"No se reconoce el documento «{doc['documento']}» del libro de compras.")
        observacion = (doc.get("observacion") or "").upper()
        neto, exento = int(doc.get("afecto") or 0), int(doc.get("exento") or 0)
        if exentos and tipo == 30 and exento and not neto:
            tipo = 32                                  # factura exenta (papel)
        fila = {"TpoDoc": tipo, "NroDoc": doc["folio"], "FchDoc": fecha_en_periodo(fecha, periodo),
                "RUTDoc": rut_proveedor, "RznSoc": razon_proveedor[:50]}
        if tipo in (55, 56, 60, 61):
            tipo_ref, folio_ref = _referencia_nota(doc, documentos)
            if folio_ref:
                if tipo_ref:
                    fila["TpoDocRef"] = tipo_ref
                fila["FolioDocRef"] = folio_ref
        if exento:
            fila["MntExe"] = exento
        impuesto = iva(neto)
        total = neto + exento
        if tipo != 32:
            # El SII pide la tasa, el neto y el IVA aunque sean cero (sin ellos rechaza el libro).
            fila.update(TasaImp=TASA_IVA, MntNeto=neto, MntIVA=impuesto)
        if neto:
            codigo = 1 if exentos and tipo != 46 else _no_recuperable(observacion)
            if "USO COMUN" in observacion and not exentos:
                fila.update(TpoImp=1, MntIVA=0, IVAUsoComun=impuesto)
            elif codigo:
                fila.update(MntIVA=0, IVANoRec={"CodIVANoRec": codigo, "MntIVANoRec": impuesto})
            total += impuesto
            if "RETENCION TOTAL" in observacion:
                fila["OtrosImp"] = {"CodImp": 15, "TasaImp": TASA_IVA, "MntImp": impuesto}
                fila["IVARetTotal"] = impuesto
                total -= impuesto
        fila["MntTotal"] = total
        detalle.append(fila)
    return detalle


# --- Resumen ---------------------------------------------------------------------------------------------

def resumen(detalle, factor=None):
    """Totales del período por tipo de documento (TotalesPeriodo), como los suma el SII."""
    totales = {}
    for d in detalle:
        t = totales.setdefault(d["TpoDoc"], {"TpoDoc": d["TpoDoc"], "TotDoc": 0, "TotMntExe": 0, "TotMntNeto": 0,
                                             "TotMntIVA": 0, "TotMntTotal": 0})
        t["TotDoc"] += 1
        t["TotMntExe"] += int(d.get("MntExe") or 0)
        t["TotMntNeto"] += int(d.get("MntNeto") or 0)
        t["TotMntIVA"] += int(d.get("MntIVA") or 0)
        t["TotMntTotal"] += int(d.get("MntTotal") or 0)
        if d.get("IVANoRec"):
            por_codigo = t.setdefault("TotIVANoRec", {})
            codigo = d["IVANoRec"]["CodIVANoRec"]
            acumulado = por_codigo.setdefault(codigo, {"CodIVANoRec": codigo, "TotOpIVANoRec": 0, "TotMntIVANoRec": 0})
            acumulado["TotOpIVANoRec"] += 1
            acumulado["TotMntIVANoRec"] += int(d["IVANoRec"]["MntIVANoRec"])
        if d.get("IVAUsoComun"):
            if not factor:
                raise ErrorSII("Hay IVA de uso común: falta el factor de proporcionalidad del set de compras.")
            t["TotOpIVAUsoComun"] = t.get("TotOpIVAUsoComun", 0) + 1
            t["TotIVAUsoComun"] = t.get("TotIVAUsoComun", 0) + int(d["IVAUsoComun"])
        if d.get("OtrosImp"):
            por_codigo = t.setdefault("TotOtrosImp", {})
            codigo = d["OtrosImp"]["CodImp"]
            acumulado = por_codigo.setdefault(codigo, {"CodImp": codigo, "TotMntImp": 0})
            acumulado["TotMntImp"] += int(d["OtrosImp"]["MntImp"])
        if d.get("IVARetTotal"):
            t["TotIVARetTotal"] = t.get("TotIVARetTotal", 0) + int(d["IVARetTotal"])
    for t in totales.values():
        if t.get("TotIVAUsoComun"):
            t["FctProp"] = Decimal(str(factor))
            t["TotCredIVAUsoComun"] = redondear(Decimal(t["TotIVAUsoComun"]) * Decimal(str(factor)))
        for clave in ("TotIVANoRec", "TotOtrosImp"):
            if clave in t:
                t[clave] = [t[clave][c] for c in sorted(t[clave])]
    return [totales[k] for k in sorted(totales)]


# --- XML -------------------------------------------------------------------------------------------------

def _poner(padre, etiqueta, valor):
    from lxml import etree

    el = etree.SubElement(padre, etiqueta)
    if isinstance(valor, dict):
        for k, v in valor.items():
            _poner(el, k, v)
    else:
        el.text = numero_xml(valor) if isinstance(valor, Decimal) else str(valor)
    return el


def _agregar(padre, etiqueta, datos, orden):
    from lxml import etree

    el = etree.SubElement(padre, etiqueta)
    for clave in orden:
        valor = datos.get(clave)
        if valor is None or valor == "":
            continue
        for item in (valor if isinstance(valor, list) else [valor]):
            _poner(el, clave, item)
    el.tail = "\n"
    return el


def construir(operacion, detalle, rut_emisor, firma, periodo, fecha_resolucion, numero_resolucion,
              tipo_envio="TOTAL", tipo_libro="MENSUAL", folio_notificacion=None, factor=None, momento=None):
    """Libro firmado (bytes ISO-8859-1). `operacion`: VENTA o COMPRA; `periodo`: AAAA-MM."""
    from lxml import etree

    if operacion not in ("VENTA", "COMPRA"):
        raise ErrorSII("El libro es de VENTA o de COMPRA.")
    if tipo_envio not in ("TOTAL", "PARCIAL", "FINAL", "AJUSTE"):
        raise ErrorSII("El tipo de envío del libro es TOTAL, PARCIAL, FINAL o AJUSTE.")
    if tipo_libro not in ("MENSUAL", "ESPECIAL", "RECTIFICA"):
        raise ErrorSII("El tipo de libro es MENSUAL, ESPECIAL o RECTIFICA.")
    if tipo_libro != "MENSUAL" and not str(folio_notificacion or "").isdigit():
        raise ErrorSII("Un libro especial o rectificatorio necesita el folio de notificación (o la autorización).")
    if not firma.rut:
        raise ErrorSII("La firma electrónica no trae el RUT de su titular: no se puede enviar al SII.")
    ident = f"LIBRO_{operacion}_{periodo.replace('-', '')}"
    envio = etree.Element("EnvioLibro", ID=ident)
    envio.text = "\n"
    caratula = {"RutEmisorLibro": limpiar_rut(rut_emisor), "RutEnvia": limpiar_rut(firma.rut),
                "PeriodoTributario": periodo, "FchResol": fecha_resolucion, "NroResol": int(numero_resolucion),
                "TipoOperacion": operacion, "TipoLibro": tipo_libro, "TipoEnvio": tipo_envio}
    if tipo_libro != "MENSUAL":
        caratula["FolioNotificacion"] = int(folio_notificacion)
    _agregar(envio, "Caratula", caratula, tuple(caratula))
    resumen_periodo = etree.SubElement(envio, "ResumenPeriodo")
    resumen_periodo.text = "\n"
    resumen_periodo.tail = "\n"
    for totales in resumen(detalle, factor):
        _agregar(resumen_periodo, "TotalesPeriodo", totales, ORDEN_TOTALES)
    for fila in detalle:
        _agregar(envio, "Detalle", fila, ORDEN_DETALLE)
    _poner(envio, "TmstFirma", marca_de_tiempo(momento)).tail = "\n"
    # Como el DTE: el contenido se arma sin espacio de nombres y la raíz declara los del SII.
    texto = (f'<LibroCompraVenta xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" '
             f'xsi:schemaLocation="{NS_SII} LibroCV_v10.xsd" version="1.0">\n'
             f'{etree.tostring(envio, encoding="unicode")}\n</LibroCompraVenta>')
    raiz = etree.fromstring(texto.encode("utf-8"))
    firma.firmar_xml(raiz, ident)
    return b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(
        raiz, encoding="ISO-8859-1", xml_declaration=False)
