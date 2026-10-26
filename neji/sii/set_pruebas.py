"""El set de pruebas de la certificación del SII: lectura del texto que entrega el SII.

El postulante descarga del sitio del SII (ambiente de certificación) un texto con los casos que debe emitir:

    SET BASICO - NUMERO DE ATENCION: 4670590

    CASO 4670590-1
    ==============
    DOCUMENTO   FACTURA ELECTRONICA

    ITEM                CANTIDAD    PRECIO UNITARIO
    Cajón AFECTO        123         923

    CASO 4670590-5
    ==============
    DOCUMENTO           NOTA DE CREDITO ELECTRONICA
    REFERENCIA          FACTURA ELECTRONICA CORRESPONDIENTE A CASO 4670590-1
    RAZON REFERENCIA    CORRIGE GIRO DEL RECEPTOR

y además los sets de los libros (ventas y compras). El de boletas es otro texto, con casos «CASO-1». Aquí solo
se lee el texto; los documentos se arman en certificacion.py.

La forma del texto se tomó de las instrucciones del SII y de implementaciones que ya pasaron la certificación
(dte-sii de Devlas SpA, licencia MIT; LibreDTE).
"""

import re
from decimal import Decimal, InvalidOperation
from itertools import combinations

from . import ErrorSII

SEPARADOR = re.compile(r"\t+|\s{2,}")
CABECERA_SET = re.compile(r"^SET\s+(.+?)\s*[-:]\s*N[UÚ]MERO\s+DE\s+ATENCI[^\d:]*[:\s]*(\d+)", re.I)
CABECERA_CASO = re.compile(r"^CASO\s+(\d+)-(\d+)\s*$", re.I)


def _numero(texto):
    """'123', '1.5', '2,5' -> Decimal (None si no es un número)."""
    texto = (texto or "").strip().replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):          # 1.234.567 (miles)
        texto = texto.replace(".", "")
    texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def tipo_de_set(nombre):
    n = nombre.upper()
    if "LIBRO DE COMPRAS" in n and "EXENTO" in n:
        return "libro_compras_exentos"
    if "LIBRO DE COMPRAS" in n:
        return "libro_compras"
    if "LIBRO DE VENTAS" in n:
        return "libro_ventas"
    if "LIBRO DE GUIAS" in n or "GUIA" in n:
        return "guia"
    if "EXENTA" in n or "NO AFECTA" in n:
        return "exenta"
    if "EXPORTACION" in n:
        return "exportacion"
    if "FACTURA DE COMPRA" in n:
        return "factura_compra"
    if "LIQUIDACION" in n:
        return "liquidacion"
    if "BASICO" in n or "BÁSICO" in n:
        return "basico"
    return "otro"


def tipo_de_documento(texto):
    """Nombre del documento en el set -> código del SII (None si Neji no lo emite)."""
    t = (texto or "").upper().replace("É", "E").replace("Í", "I").replace("Ó", "O")
    if "EXPORTACION" in t or "LIQUIDACION" in t or "FACTURA DE COMPRA" in t or "GUIA" in t:
        return None
    if "NOTA DE CREDITO" in t:
        return 61
    if "NOTA DE DEBITO" in t:
        return 56
    if "FACTURA" in t and ("EXENTA" in t or "NO AFECTA" in t):
        return 34
    if "FACTURA" in t:
        return 33
    return None


def codigo_referencia(razon):
    """Razón de la referencia -> CodRef: 1 anula, 2 corrige texto (giro, dirección...), 3 corrige montos."""
    r = (razon or "").upper()
    if "ANULA" in r:
        return 1
    if "CORRIGE" in r and ("GIRO" in r or "TEXTO" in r or "DIRECCION" in r or "DIRECCIÓN" in r or "RAZON" in r):
        return 2
    if "DEVOLUCION" in r or "DEVOLUCIÓN" in r or "MODIFICA" in r or "MONTO" in r or "CORRIGE" in r:
        return 3
    return 1


def columnas_de(linea):
    """La fila de títulos de los ítems ('ITEM  CANTIDAD  PRECIO UNITARIO') -> ['nombre', 'cantidad', 'precio']."""
    partes = [p.strip().upper() for p in SEPARADOR.split(linea) if p.strip()]
    if not partes or not re.match(r"^(ITEM|DETALLE|NOMBRE)", partes[0]):
        return None
    columnas = []
    for p in partes:
        if re.match(r"^(ITEM|DETALLE|NOMBRE)", p):
            columnas.append("nombre")
        elif "CANT" in p:
            columnas.append("cantidad")
        elif "UNIDAD" in p:
            columnas.append("unidad")
        elif "DESC" in p:
            columnas.append("descuento")
        elif "PRECIO" in p or "VALOR" in p or "MONTO" in p:
            columnas.append("precio")
        else:
            columnas.append("otro")
    return columnas


def _encaja(partes, columnas):
    """¿Cada valor calza con su columna? (números donde van números, una unidad de medida donde va la unidad)."""
    for columna, valor in zip(columnas[1:], partes[1:]):
        if columna == "unidad":
            if not re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóú.]{1,10}", valor):
                return False
        elif _numero(valor.rstrip("%")) is None:
            return False
    return True


def _ordenar(partes, columnas):
    """Calza los valores de una línea con las columnas de la fila de títulos.

    Las columnas de descuento y unidad pueden venir vacías en una línea. Y al copiar el set desde la página, un
    nombre largo puede quedar pegado a la cantidad con un solo espacio ('ASESORIA FINANCIERA 1'): se separa."""
    partes = list(partes)
    while True:
        if len(partes) <= len(columnas):
            opcionales = [c for c in columnas if c in ("descuento", "unidad")]
            for quitar in range(len(opcionales) + 1):
                if len(columnas) - quitar != len(partes):
                    continue
                for omitidas in combinations(opcionales, quitar):
                    restantes = list(columnas)
                    for c in omitidas:
                        restantes.remove(c)
                    if _encaja(partes, restantes):
                        return partes, restantes
        m = re.match(r"^(.*\S)\s+(\d+(?:[.,]\d+)?%?)$", partes[0])
        if not m or len(partes) >= len(columnas):
            return None
        partes[0:1] = [m.group(1), m.group(2)]


def _item(partes, razon, columnas=None):
    """Una línea de ítem del caso -> {nombre, cantidad, precio, unidad, descuento_pct}.

    Con la fila de títulos del caso, cada valor va a su columna; sin ella, se deduce por la forma."""
    item = {"nombre": partes[0], "cantidad": None, "precio": None, "unidad": None, "descuento_pct": None}
    ordenado = _ordenar(partes, columnas) if columnas and len(columnas) > 1 and columnas[0] == "nombre" else None
    if ordenado:
        partes, columnas = ordenado
        item["nombre"] = partes[0]
        for columna, valor in zip(columnas[1:], partes[1:]):
            if columna == "unidad":
                item["unidad"] = valor.rstrip(".")[:4]
            elif columna == "cantidad":
                item["cantidad"] = _numero(valor)
            elif columna == "precio":
                item["precio"] = _numero(valor)
            elif columna == "descuento":
                item["descuento_pct"] = _numero(valor.rstrip("%"))
        return item if item["cantidad"] is not None or item["precio"] is not None else None
    valores = partes[1:]
    if len(valores) == 1:
        valor = _numero(valores[0])
        if valor is None:
            return None
        # En una nota que modifica montos el número es el precio; en una devolución, la cantidad.
        if "MONTO" in (razon or "").upper():
            item["precio"] = valor
        else:
            item["cantidad"] = valor
        return item
    numeros = []
    for v in valores:
        if v.endswith("%") and _numero(v[:-1]) is not None:
            item["descuento_pct"] = _numero(v[:-1])
        elif _numero(v) is not None:
            numeros.append(_numero(v))
        elif re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóú.]{1,6}", v):
            item["unidad"] = v.rstrip(".")[:4]
        else:
            return None
    if len(numeros) >= 2:
        item["cantidad"], item["precio"] = numeros[0], numeros[1]
    elif len(numeros) == 1:
        item["cantidad"] = numeros[0]
    else:
        return None
    return item


def leer_set(texto):
    """Texto del set de pruebas -> [{nombre, tipo, numero_atencion, casos: [...], libro: [...], factor}].

    Cada caso: {id ('4670590-1'), numero, documento, tipo_dte, items, referencia_caso, referencia_texto, razon,
    descuento_pct, lineas (texto original)}. El libro de compras: [{documento, tpo_doc, folio, observacion,
    exento, afecto}].
    """
    sets = []
    actual = caso = documento_libro = columnas = None
    for linea_original in (texto or "").replace("\r", "").split("\n"):
        linea = linea_original.strip()
        cabecera = CABECERA_SET.match(linea)
        if cabecera:
            actual = {"nombre": cabecera.group(1).strip(), "tipo": tipo_de_set(cabecera.group(1)),
                      "numero_atencion": cabecera.group(2), "casos": [], "libro": [], "factor": None,
                      "instrucciones": []}
            sets.append(actual)
            caso = documento_libro = None
            continue
        if actual is None or not linea:
            continue
        nuevo_caso = CABECERA_CASO.match(linea)
        if nuevo_caso:
            caso = {"id": f"{nuevo_caso.group(1)}-{nuevo_caso.group(2)}", "numero": int(nuevo_caso.group(2)),
                    "documento": None, "tipo_dte": None, "items": [], "referencia_caso": None,
                    "referencia_texto": None, "razon": None, "descuento_pct": None, "lineas": []}
            columnas = None
            actual["casos"].append(caso)
            documento_libro = None
            continue
        if re.fullmatch(r"[=\-_]{3,}", linea):
            continue
        if caso is not None:
            caso["lineas"].append(linea)
            m = re.match(r"^DOCUMENTO\s*[:\t ]\s*(.+)$", linea, re.I)
            if m:
                caso["documento"] = m.group(1).strip()
                caso["tipo_dte"] = tipo_de_documento(caso["documento"])
                continue
            m = re.match(r"^REFERENCIA\s*[:\t ]\s*(.+)$", linea, re.I)
            if m:
                caso["referencia_texto"] = m.group(1).strip()
                ref = re.search(r"CASO\s+(\d+-\d+)", caso["referencia_texto"], re.I)
                caso["referencia_caso"] = ref.group(1) if ref else None
                continue
            m = re.match(r"^RAZ[OÓ]N\s+REFERENCIA\s*[:\t ]\s*(.+)$", linea, re.I)
            if m:
                caso["razon"] = m.group(1).strip()
                continue
            m = re.match(r"^DESCUENTO\s+GLOBAL.*?(\d+(?:[.,]\d+)?)\s*%", linea, re.I)
            if m:
                caso["descuento_pct"] = _numero(m.group(1))
                continue
            titulos = columnas_de(linea)
            if titulos and len(titulos) > 1 and "otro" not in titulos[1:] and len(set(titulos)) == len(titulos):
                columnas = titulos
                continue
            if re.match(r"^ITEM\s*$", linea, re.I):
                continue
            partes = [p.strip() for p in SEPARADOR.split(linea) if p.strip()]
            if len(partes) >= 2 and ":" not in partes[0]:
                item = _item(partes, caso["razon"], columnas)
                if item:
                    caso["items"].append(item)
            continue
        # Fuera de un caso: libro de compras (documentos recibidos) e instrucciones de los libros.
        if actual["tipo"] in ("libro_compras", "libro_compras_exentos"):
            m = re.search(r"FACTOR\s+DE\s+PROPORCIONALIDAD.*?(\d+[.,]\d+)", linea, re.I)
            if m:
                actual["factor"] = _numero(m.group(1))
                continue
            if re.search(r"TIPO\s+DOCUMENTO", linea, re.I) or re.search(r"MONTO\s+EXENTO", linea, re.I):
                continue
            partes = [p.strip() for p in SEPARADOR.split(linea) if p.strip()]
            m = re.match(r"^((?:FACTURA|NOTA)[A-ZÁÉÍÓÚ ]*?)\s+(\d+)$", " ".join(partes[:2]) if len(partes) >= 2 else "",
                         re.I)
            if len(partes) >= 2 and m and partes[1].isdigit():
                documento_libro = {"documento": partes[0].upper(), "tpo_doc": tipo_libro(partes[0]),
                                   "folio": int(partes[1]), "observacion": None, "exento": None, "afecto": None}
                actual["libro"].append(documento_libro)
                # Formato en columnas: TIPO  FOLIO  [EXENTO]  [AFECTO]
                montos = [_numero(p) for p in partes[2:]]
                if len(montos) == 1 and montos[0] is not None and (
                        "EXENT" in partes[0].upper() or (actual["tipo"] == "libro_compras_exentos"
                                                         and "DEBITO" in partes[0].upper())):
                    documento_libro["exento"] = int(montos[0])      # una sola cifra en un documento exento
                elif montos and all(x is not None for x in montos):
                    _poner_montos(documento_libro, montos)
                continue
            if documento_libro is not None and re.fullmatch(r"OBS:\s*(.+)", linea, re.I):
                documento_libro["observacion"] = re.sub(r"^OBS:\s*", "", linea, flags=re.I)
                continue
            if documento_libro is not None:
                numeros = [_numero(p) for p in partes]
                if numeros and all(x is not None for x in numeros):
                    # Una sola cifra con mucha sangría es el afecto; dos, exento y afecto.
                    if len(numeros) == 1:
                        sangria = len(linea_original) - len(linea_original.lstrip())
                        if sangria and sangria < 20 and "EXENT" in (documento_libro["observacion"] or "").upper():
                            documento_libro["exento"] = int(numeros[0])
                        else:
                            documento_libro["afecto"] = int(numeros[0])
                    else:
                        _poner_montos(documento_libro, numeros)
                    continue
                if documento_libro["observacion"] is None:
                    documento_libro["observacion"] = linea
                    continue
        actual["instrucciones"].append(linea)
    if not sets:
        raise ErrorSII("El texto no parece un set de pruebas del SII (no tiene «SET ... NUMERO DE ATENCION»).")
    return sets


def _poner_montos(documento, montos):
    if len(montos) >= 2:
        documento["exento"], documento["afecto"] = int(montos[0]), int(montos[1])
    else:
        documento["afecto"] = int(montos[0])


def tipo_libro(texto):
    """Documento del libro de compras -> TpoDoc del libro (30 factura papel, 33, 34, 46, 60, 61, 55, 56)."""
    t = (texto or "").upper().replace("É", "E").replace("Ó", "O")
    electronica = "ELECTRONIC" in t
    if "FACTURA DE COMPRA" in t:
        return 46
    if "NOTA DE CREDITO" in t:
        return 61 if electronica else 60
    if "NOTA DE DEBITO" in t:
        return 56 if electronica else 55
    if "FACTURA" in t and ("EXENTA" in t or "NO AFECTA" in t):
        return 34 if electronica else 32
    if "FACTURA" in t:
        return 33 if electronica else 30
    return None


# --- Set de boletas -------------------------------------------------------------------------------------

def leer_set_boletas(texto):
    """Texto del set de pruebas de boletas -> [{numero, items: [{nombre, cantidad, precio, unidad, exento}]}].

    Casos «CASO-1» (o «CASO 1»), una cabecera «Item  Cantidad  Precio» y ítems con precio al público (con IVA).
    Una observación como «Se debe informar en el XML Unidad de medida en Kg.» pide la unidad del ítem.
    """
    casos, caso = [], None
    for linea_original in (texto or "").replace("\r", "").split("\n"):
        linea = linea_original.strip()
        m = re.match(r"^CASO\s*-?\s*(\d+)\s*$", linea, re.I)
        if m:
            caso = {"numero": int(m.group(1)), "items": [], "observaciones": []}
            casos.append(caso)
            continue
        if caso is None or not linea or re.fullmatch(r"[=\-_]{3,}", linea):
            continue
        if re.match(r"^OBSERVACI", linea, re.I):
            caso["observaciones"].append(re.sub(r"^OBSERVACI[OÓ]N(ES)?\s*:?\s*", "", linea, flags=re.I).strip('" '))
            continue
        if re.search(r"\bitem\b", linea, re.I) and re.search(r"cantidad", linea, re.I):
            continue
        partes = [p.strip() for p in SEPARADOR.split(linea) if p.strip()]
        if len(partes) >= 3:
            cantidad, precio = _numero(partes[1]), _numero(partes[-1])
            unidad = partes[2] if len(partes) >= 4 and _numero(partes[2]) is None else None
            if cantidad is not None and precio is not None:
                caso["items"].append({"nombre": partes[0], "cantidad": cantidad, "precio": precio, "unidad": unidad,
                                      "exento": "exent" in partes[0].lower()})
    for caso in casos:
        for obs in caso["observaciones"]:
            m = re.search(r"unidad de medida\s+(?:en\s+)?([A-Za-z]{1,4})\.?\s*$", obs, re.I)
            if m and caso["items"] and not caso["items"][0]["unidad"]:
                caso["items"][0]["unidad"] = m.group(1)
    if not casos:
        raise ErrorSII("El texto no parece el set de pruebas de boletas (no tiene casos «CASO-1»).")
    return casos
