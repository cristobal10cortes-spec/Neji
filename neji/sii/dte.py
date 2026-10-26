"""Arma, timbra y firma un documento tributario electrónico (DTE).

Los montos de Neji incluyen IVA (precios de góndola). La boleta (39/41) se expresa así tal cual; la factura
(33) y las notas de crédito (61) y débito (56) también, con el indicador MntBruto=1: el SII deriva el neto y el
IVA del total bruto, y así el documento suma exactamente lo que se cobró (sin perder pesos al pasar cada línea
a neto). Con `netos` (el set de pruebas del SII, que da precios netos) las líneas van sin IVA y el IVA se
calcula sobre el neto.
"""

from datetime import datetime
from decimal import Decimal

from ..chile import desglosar_iva, limpiar_rut, redondear, validar_rut
from . import BOLETAS, NOMBRES, NOTAS, NS_SII, NS_XSI, RUT_CONSUMIDOR_FINAL, ErrorSII
from .textos import correo_valido, texto_sii, texto_timbre

EXENTOS = (34, 41)       # documentos sin IVA: todas sus líneas son exentas
MAX_LINEAS = {39: 1000, 41: 1000, 33: 60, 34: 60, 56: 60, 61: 60}
MOTIVOS_REFERENCIA = {1: "Anula documento", 2: "Corrige texto", 3: "Corrige montos"}


def marca_de_tiempo(momento=None):
    """'2026-10-26T15:04:05' en la hora local (Chile): el SII rechaza horas adelantadas."""
    return (momento or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")


def numero_xml(valor):
    """Decimal del esquema del SII: sin notación científica, hasta 6 decimales, sin ceros de más."""
    texto = format(Decimal(str(valor)).quantize(Decimal("0.000001")).normalize(), "f")
    return texto


def _rut(valor, que):
    rut = limpiar_rut(valor)
    if not rut or not validar_rut(rut):
        raise ErrorSII(f"El RUT {que} no es válido{': ' + str(valor) if valor else ''}.")
    return rut


def calcular_totales(tipo, lineas, descuento_afecto=0, descuento_exento=0, tasa=19, netos=False, descuento_pct=0):
    """Totales del documento a partir de las líneas y los descuentos globales.

    Las líneas van con IVA (lo normal en Neji) o netas (`netos`). `descuento_pct`: descuento global en % sobre
    lo afecto (el «DESCUENTO GLOBAL ITEMES AFECTOS» del set de pruebas), redondeado al peso como el SII.
    """
    exento_lineas = sum(int(l["monto"]) for l in lineas if l.get("exento") or tipo in EXENTOS)
    afecto_lineas = sum(int(l["monto"]) for l in lineas if not (l.get("exento") or tipo in EXENTOS))
    if descuento_pct:
        descuento_afecto = redondear(Decimal(afecto_lineas) * Decimal(str(descuento_pct)) / 100)
    exento = exento_lineas - int(descuento_exento)
    afecto = afecto_lineas - int(descuento_afecto)
    if afecto < 0 or exento < 0:
        raise ErrorSII("El descuento no puede ser mayor que lo que se vende.")
    if netos:
        neto, iva = afecto, redondear(Decimal(afecto) * Decimal(str(tasa)) / 100)
        total = neto + iva + exento
    else:
        neto, iva = desglosar_iva(afecto, tasa) if afecto else (0, 0)
        total = afecto + exento
    return {"neto": neto, "iva": iva, "exento": exento, "total": total, "afecto": afecto,
            "descuento_afecto": int(descuento_afecto)}


def _validar(doc, caf):
    tipo, folio = doc["tipo"], doc["folio"]
    if tipo not in NOMBRES:
        raise ErrorSII(f"Neji no emite el documento tipo {tipo}.")
    if caf.tipo != tipo or not caf.contiene(folio):
        raise ErrorSII(f"El folio {folio} no está en los folios autorizados de {NOMBRES[tipo].lower()}.")
    emisor = doc["emisor"]
    if limpiar_rut(emisor.get("rut")) != caf.rut:
        raise ErrorSII(f"Los folios (CAF) son del RUT {caf.rut} y el negocio está configurado con "
                       f"{emisor.get('rut') or 'otro RUT'}.")
    for campo, nombre in (("razon_social", "la razón social"), ("giro", "el giro"),
                          ("direccion", "la dirección"), ("comuna", "la comuna")):
        if not texto_sii(emisor.get(campo)):
            raise ErrorSII(f"Falta {nombre} del negocio en Configuración → Boleta electrónica.")
    if tipo not in BOLETAS and not emisor.get("actecos"):
        raise ErrorSII("Falta el código de actividad económica (Acteco) del negocio en Configuración → Boleta electrónica.")
    lineas = doc["lineas"]
    if not lineas:
        raise ErrorSII("El documento no tiene productos.")
    if len(lineas) > MAX_LINEAS[tipo]:
        raise ErrorSII(f"La {NOMBRES[tipo].lower()} admite hasta {MAX_LINEAS[tipo]} líneas "
                       f"(esta venta tiene {len(lineas)}).")
    if tipo in (33, 39) and all(l.get("exento") for l in lineas):
        raise ErrorSII("Todos los productos son exentos: corresponde una boleta o factura exenta.")
    receptor = doc.get("receptor") or {}
    if tipo in NOTAS and not receptor.get("rut"):
        pass                     # nota de crédito de una boleta a consumidor final
    elif tipo not in BOLETAS:
        rut = _rut(receptor.get("rut"), "del cliente")
        if tipo not in NOTAS and rut == RUT_CONSUMIDOR_FINAL:
            raise ErrorSII("La factura necesita el RUT del cliente (no el de consumidor final).")
        if tipo not in NOTAS:
            for campo, nombre in (("razon_social", "la razón social"), ("giro", "el giro"),
                                  ("direccion", "la dirección"), ("comuna", "la comuna")):
                if not texto_sii(receptor.get(campo)):
                    raise ErrorSII(f"Para la factura falta {nombre} del cliente.")
    if tipo in NOTAS and not doc.get("referencias"):
        raise ErrorSII(f"La {NOMBRES[tipo].lower()} tiene que decir qué documento corrige.")
    for ref in doc.get("referencias") or []:
        if tipo not in BOLETAS and not (ref.get("tipo") and ref.get("folio") not in (None, "") and ref.get("fecha")):
            raise ErrorSII("Cada referencia necesita el tipo, el folio y la fecha del documento.")


def _sub(padre, etiqueta, texto=None, **atributos):
    from lxml import etree

    el = etree.SubElement(padre, etiqueta, **atributos)
    if texto is not None:
        el.text = str(texto)
    return el


def _encabezado(documento, doc, totales):
    tipo, emisor = doc["tipo"], doc["emisor"]
    boleta = tipo in BOLETAS
    enc = _sub(documento, "Encabezado")
    iddoc = _sub(enc, "IdDoc")
    _sub(iddoc, "TipoDTE", tipo)
    _sub(iddoc, "Folio", doc["folio"])
    _sub(iddoc, "FchEmis", doc["fecha"])
    if boleta:
        _sub(iddoc, "IndServicio", 3)          # boleta de ventas y servicios
    else:
        if totales["afecto"] and not doc.get("netos"):
            _sub(iddoc, "MntBruto", 1)         # las líneas van con IVA incluido
        if tipo in (33, 34):
            _sub(iddoc, "FmaPago", 2 if doc.get("credito") else 1)

    em = _sub(enc, "Emisor")
    _sub(em, "RUTEmisor", limpiar_rut(emisor["rut"]))
    if boleta:
        _sub(em, "RznSocEmisor", texto_sii(emisor["razon_social"], 100))
        _sub(em, "GiroEmisor", texto_sii(emisor["giro"], 80))
    else:
        _sub(em, "RznSoc", texto_sii(emisor["razon_social"], 100))
        _sub(em, "GiroEmis", texto_sii(emisor["giro"], 80))
        if texto_sii(emisor.get("telefono")):
            _sub(em, "Telefono", texto_sii(emisor["telefono"], 20))
        if correo_valido(emisor.get("email")):
            _sub(em, "CorreoEmisor", texto_sii(emisor["email"], 80))
        for acteco in list(emisor["actecos"])[:4]:
            _sub(em, "Acteco", int(acteco))
    if emisor.get("sucursal_sii"):
        _sub(em, "CdgSIISucur", int(emisor["sucursal_sii"]))
    _sub(em, "DirOrigen", texto_sii(emisor["direccion"], 70))
    _sub(em, "CmnaOrigen", texto_sii(emisor["comuna"], 20))
    if texto_sii(emisor.get("ciudad")):
        _sub(em, "CiudadOrigen", texto_sii(emisor["ciudad"], 20))

    receptor = doc.get("receptor") or {}
    rut_receptor = limpiar_rut(receptor.get("rut")) or RUT_CONSUMIDOR_FINAL
    razon = texto_sii(receptor.get("razon_social"), 100) or "Consumidor Final"
    rec = _sub(enc, "Receptor")
    _sub(rec, "RUTRecep", rut_receptor)
    _sub(rec, "RznSocRecep", razon)
    if not boleta and texto_sii(receptor.get("giro")):
        _sub(rec, "GiroRecep", texto_sii(receptor["giro"], 40))
    if correo_valido(receptor.get("email")):
        _sub(rec, "CorreoRecep", texto_sii(receptor["email"], 80))
    if texto_sii(receptor.get("direccion")):
        _sub(rec, "DirRecep", texto_sii(receptor["direccion"], 70))
    if texto_sii(receptor.get("comuna")):
        _sub(rec, "CmnaRecep", texto_sii(receptor["comuna"], 20))
    if texto_sii(receptor.get("ciudad")):
        _sub(rec, "CiudadRecep", texto_sii(receptor["ciudad"], 20))

    tot = _sub(enc, "Totales")
    if totales["afecto"]:
        _sub(tot, "MntNeto", totales["neto"])
    if totales["exento"] or tipo in EXENTOS:
        _sub(tot, "MntExe", totales["exento"])
    if totales["afecto"]:
        if not boleta:
            _sub(tot, "TasaIVA", doc.get("tasa_iva", 19))
        _sub(tot, "IVA", totales["iva"])
    _sub(tot, "MntTotal", totales["total"])
    return rut_receptor, razon


def _detalle(documento, doc):
    """Líneas en el orden del esquema: código, exento, nombre, descripción, cantidad, unidad, precio, descuento
    y monto. Una línea `solo_texto` (la nota que corrige el giro o un texto) lleva solo el nombre y monto 0."""
    tipo = doc["tipo"]
    for n, linea in enumerate(doc["lineas"], start=1):
        det = _sub(documento, "Detalle")
        _sub(det, "NroLinDet", n)
        codigo = texto_sii(linea.get("codigo"), 35)
        if codigo:
            cdg = _sub(det, "CdgItem")
            _sub(cdg, "TpoCodigo", "INT1")
            _sub(cdg, "VlrCodigo", codigo)
        if linea.get("exento") or tipo in EXENTOS:
            _sub(det, "IndExe", 1)
        _sub(det, "NmbItem", texto_sii(linea["nombre"], 80) or "Producto")
        if texto_sii(linea.get("descripcion")):
            _sub(det, "DscItem", texto_sii(linea["descripcion"], 1000))
        if not linea.get("solo_texto"):
            cantidad = Decimal(str(linea["cantidad"]))
            if cantidad > 0:
                _sub(det, "QtyItem", numero_xml(cantidad))
            if linea.get("unidad"):
                _sub(det, "UnmdItem", texto_sii(linea["unidad"], 4))
            if cantidad > 0 and Decimal(str(linea["precio"])) > 0:
                _sub(det, "PrcItem", numero_xml(linea["precio"]))
                if linea.get("descuento_pct"):
                    _sub(det, "DescuentoPct", numero_xml(linea["descuento_pct"]))
                if int(linea.get("descuento") or 0) > 0:
                    _sub(det, "DescuentoMonto", int(linea["descuento"]))
        _sub(det, "MontoItem", int(linea["monto"]))
        det.tail = "\n"


def _descuentos(documento, doc):
    """Descuentos globales: en pesos (los de una venta) o en % sobre lo afecto (los del set de pruebas)."""
    n = 0
    globales = ([(doc["descuento_pct"], False, "%")] if doc.get("descuento_pct") else
                [(doc.get("descuento_afecto", 0), False, "$")])
    globales.append((doc.get("descuento_exento", 0), True, "$"))
    for valor, exento, tipo_valor in globales:
        if Decimal(str(valor or 0)) <= 0:
            continue
        n += 1
        dr = _sub(documento, "DscRcgGlobal")
        _sub(dr, "NroLinDR", n)
        _sub(dr, "TpoMov", "D")
        _sub(dr, "GlosaDR", texto_sii(doc.get("glosa_descuento"), 45) or "Descuento")
        _sub(dr, "TpoValor", tipo_valor)
        _sub(dr, "ValorDR", numero_xml(valor) if tipo_valor == "%" else int(valor))
        if exento and doc["tipo"] not in EXENTOS:
            _sub(dr, "IndExeDR", 1)
        dr.tail = "\n"


def _referencias(documento, doc):
    """Documentos que se referencian: el corregido por una nota, o el caso del set de pruebas («SET»).

    En la boleta la referencia es más simple: código (p. ej. «SET») y razón («CASO-1»)."""
    boleta = doc["tipo"] in BOLETAS
    for n, ref in enumerate(doc.get("referencias") or [], start=1):
        el = _sub(documento, "Referencia")
        _sub(el, "NroLinRef", n)
        if boleta:
            if ref.get("codigo"):
                _sub(el, "CodRef", texto_sii(str(ref["codigo"]), 18))
            if texto_sii(ref.get("razon")):
                _sub(el, "RazonRef", texto_sii(ref["razon"], 90))
            el.tail = "\n"
            continue
        _sub(el, "TpoDocRef", ref["tipo"])
        _sub(el, "FolioRef", ref["folio"])
        _sub(el, "FchRef", ref["fecha"])
        if ref.get("codigo"):
            _sub(el, "CodRef", int(ref["codigo"]))
        razon = texto_sii(ref.get("razon") or MOTIVOS_REFERENCIA.get(ref.get("codigo"), ""), 90)
        if razon:
            _sub(el, "RazonRef", razon)
        el.tail = "\n"


def _timbre(doc, caf, totales, rut_receptor, razon, marca):
    """El TED: los datos principales firmados con la llave del CAF. Va en el PDF417 del ticket."""
    from lxml import etree

    dd = etree.Element("DD")
    _sub(dd, "RE", limpiar_rut(doc["emisor"]["rut"]))
    _sub(dd, "TD", doc["tipo"])
    _sub(dd, "F", doc["folio"])
    _sub(dd, "FE", doc["fecha"])
    _sub(dd, "RR", rut_receptor)
    _sub(dd, "RSR", texto_timbre(razon))
    _sub(dd, "MNT", totales["total"])
    _sub(dd, "IT1", texto_timbre(doc["lineas"][0]["nombre"]) or "Producto")
    dd.append(caf.elemento())
    _sub(dd, "TSTED", marca)
    # Se firma el DD «aplanado» (sin espacios entre etiquetas), en ISO-8859-1 y sin espacio de nombres.
    firma = caf.firmar(etree.tostring(dd, encoding="ISO-8859-1", xml_declaration=False))
    ted = etree.Element("TED", version="1.0")
    ted.append(dd)
    _sub(ted, "FRMT", firma, algoritmo="SHA1withRSA")
    return ted


def construir(doc, caf, firma, momento=None):
    """Documento listo para el SII.

    `doc`: {tipo, folio, fecha (AAAA-MM-DD), emisor {rut, razon_social, giro, actecos, direccion, comuna,
    ciudad, sucursal_sii, telefono, email}, receptor {rut, razon_social, giro, direccion, comuna, ciudad,
    email} o None (consumidor final), lineas [{nombre, codigo, cantidad, precio, monto, exento, unidad,
    descripcion, descuento_pct, descuento, solo_texto}], descuento_afecto, descuento_exento, descuento_pct,
    glosa_descuento, referencias [{tipo, folio, fecha, codigo, razon}], tasa_iva, credito, netos}.

    Devuelve {xml (bytes ISO-8859-1), ted (bytes), id, totales}.
    """
    from lxml import etree

    _validar(doc, caf)
    totales = calcular_totales(doc["tipo"], doc["lineas"], doc.get("descuento_afecto", 0),
                               doc.get("descuento_exento", 0), doc.get("tasa_iva", 19), bool(doc.get("netos")),
                               doc.get("descuento_pct") or 0)
    marca = marca_de_tiempo(momento)
    ident = f"F{doc['folio']}T{doc['tipo']}"
    documento = etree.Element("Documento", ID=ident)
    documento.text = "\n"
    rut_receptor, razon = _encabezado(documento, doc, totales)
    documento[0].tail = "\n"   # el Encabezado en su propia línea: el SII rechaza líneas de más de ~4000 letras
    _detalle(documento, doc)
    _descuentos(documento, doc)
    _referencias(documento, doc)
    ted = _timbre(doc, caf, totales, rut_receptor, razon, marca)
    documento.append(ted)
    ted.tail = "\n"
    _sub(documento, "TmstFirma", marca).tail = "\n"
    texto = etree.tostring(documento, encoding="unicode")
    # La raíz declara los mismos xmlns que el sobre: la firma vale igual suelta y dentro de EnvioBOLETA/EnvioDTE.
    raiz = etree.fromstring(f'<DTE xmlns="{NS_SII}" xmlns:xsi="{NS_XSI}" version="1.0">\n{texto}\n</DTE>'.encode())
    firma.firmar_xml(raiz, ident)
    xml = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n' + etree.tostring(
        raiz, encoding="ISO-8859-1", xml_declaration=False)
    return {"xml": xml, "ted": etree.tostring(ted, encoding="ISO-8859-1", xml_declaration=False),
            "id": ident, "totales": totales}
