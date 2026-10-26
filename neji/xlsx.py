"""Lectura de planillas Excel (.xlsx) sin librerías extra: la primera hoja como filas de texto.

Sirve para importar el inventario tal como lo exporta eleventa u otro sistema, sin pasarlo a CSV. Un .xlsx es
un .zip con XML: las celdas de texto están en sharedStrings.xml y las de la hoja, en worksheets/sheetN.xml.
Los números se entregan a la chilena (coma decimal, sin miles ni notación científica) y las fechas como
AAAA-MM-DD, igual que en un CSV de Neji.
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .validar import ErrorNegocio, numero_texto

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PAQUETE = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_DESCOMPRIMIDO = 200 * 1024 * 1024     # un .zip que se infla de más no se abre
MAX_FILAS = 200_000
# Formatos de fecha de fábrica de Excel (numFmtId).
FORMATOS_FECHA = set(range(14, 18)) | {22, 27, 30, 36, 45, 46, 47, 50, 57}

es_xlsx = lambda contenido: contenido[:4] == b"PK\x03\x04"          # noqa: E731
es_xls_antiguo = lambda contenido: contenido[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # noqa: E731


def _xml(paquete, nombre):
    datos = paquete.read(nombre)
    if b"<!DOCTYPE" in datos[:2048].upper():      # sin entidades: ninguna planilla real las trae
        raise ErrorNegocio("La planilla Excel no se puede leer.")
    return ET.fromstring(datos)


def _columna(referencia):
    """'C12' -> 2 (columna desde 0)."""
    n = 0
    for letra in re.match(r"[A-Z]+", referencia).group():
        n = n * 26 + ord(letra) - 64
    return n - 1


def _texto(elemento):
    """Texto de una celda de texto (con o sin partes con formato distinto)."""
    return "".join(t.text or "" for t in elemento.iter(f"{NS}t"))


def _formato_es_fecha(codigo):
    codigo = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", codigo or "").lower()
    return bool(re.search(r"[dy]", codigo)) or ("m" in codigo and "0" not in codigo and "#" not in codigo)


def _estilos_fecha(paquete):
    """Índices de estilo de celda (atributo s) que muestran una fecha."""
    try:
        estilos = _xml(paquete, "xl/styles.xml")
    except KeyError:
        return set()
    propios = {int(f.get("numFmtId")): f.get("formatCode") for f in estilos.iter(f"{NS}numFmt")}
    fechas = set()
    xfs = estilos.find(f"{NS}cellXfs")
    for i, xf in enumerate(xfs if xfs is not None else []):
        formato = int(xf.get("numFmtId") or 0)
        if formato in FORMATOS_FECHA or (formato in propios and _formato_es_fecha(propios[formato])):
            fechas.add(i)
    return fechas


def _primera_hoja(paquete):
    libro = _xml(paquete, "xl/workbook.xml")
    hoja = libro.find(f"{NS}sheets/{NS}sheet")
    if hoja is None:
        raise ErrorNegocio("La planilla Excel no tiene hojas.")
    relaciones = _xml(paquete, "xl/_rels/workbook.xml.rels")
    destino = next((r.get("Target") for r in relaciones.iter(f"{NS_PAQUETE}Relationship")
                    if r.get("Id") == hoja.get(f"{NS_REL}id")), "worksheets/sheet1.xml")
    destino = destino.lstrip("/")
    ruta = destino if destino.startswith("xl/") else f"xl/{destino}"
    fecha_1904 = (libro.find(f"{NS}workbookPr") is not None
                  and libro.find(f"{NS}workbookPr").get("date1904") in ("1", "true"))
    return ruta, fecha_1904


def _numero(valor, es_fecha, fecha_1904):
    try:
        numero = Decimal(valor)
    except InvalidOperation:
        return valor
    if es_fecha and 0 < numero < 2_958_466:
        base = date(1904, 1, 1) if fecha_1904 else date(1899, 12, 30)
        return (base + timedelta(days=int(numero))).isoformat()
    if numero == numero.to_integral_value():
        return str(int(numero))
    return numero_texto(numero)


def leer_xlsx(contenido):
    """Bytes de un .xlsx -> filas (listas de texto) de su primera hoja, sin las filas vacías del final."""
    try:
        paquete = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile:
        raise ErrorNegocio("El archivo no es una planilla Excel (.xlsx) válida.") from None
    if sum(i.file_size for i in paquete.infolist()) > MAX_DESCOMPRIMIDO:
        raise ErrorNegocio("La planilla Excel es demasiado grande.")
    try:
        ruta, fecha_1904 = _primera_hoja(paquete)
        try:
            compartidos = [_texto(si) for si in _xml(paquete, "xl/sharedStrings.xml").iter(f"{NS}si")]
        except KeyError:
            compartidos = []
        fechas = _estilos_fecha(paquete)
        hoja = _xml(paquete, ruta)
    except (KeyError, ET.ParseError):
        raise ErrorNegocio("El archivo no es una planilla Excel (.xlsx) válida.") from None

    filas = []
    for fila in hoja.iter(f"{NS}row"):
        celdas = {}
        for posicion, celda in enumerate(fila.iter(f"{NS}c")):
            referencia = celda.get("r")
            columna = _columna(referencia) if referencia else posicion
            tipo, valor = celda.get("t"), celda.findtext(f"{NS}v")
            if tipo == "s":
                texto = compartidos[int(valor)] if valor and valor.isdigit() and int(valor) < len(compartidos) else ""
            elif tipo == "inlineStr":
                texto = _texto(celda.find(f"{NS}is")) if celda.find(f"{NS}is") is not None else ""
            elif tipo == "b":
                texto = "si" if valor == "1" else "no"
            elif tipo in ("str", "e") or valor is None:
                texto = (valor or "") if tipo != "e" else ""
            else:
                texto = _numero(valor, int(celda.get("s") or 0) in fechas, fecha_1904)
            celdas[columna] = texto
        if celdas:
            numero_fila = int(fila.get("r") or len(filas) + 1)
            while len(filas) < numero_fila - 1:        # filas vacías salteadas en el XML
                filas.append([])
            filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)])
        if len(filas) > MAX_FILAS:
            raise ErrorNegocio(f"La planilla tiene más de {MAX_FILAS} filas.")
    while filas and not any(x.strip() for x in filas[-1]):
        filas.pop()
    return filas
