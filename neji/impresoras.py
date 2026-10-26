"""Impresoras de tickets del computador: detectarlas e imprimir directo, sin cuadro de impresión.

Lo usa NejiPOS.exe (escritorio.py) en cada caja: la impresora es la del computador donde está la
ventana, aunque el servidor esté en otro equipo. Cualquier impresora con su controlador instalado en
Windows aparece sola (USB, red, puerto serie o paralelo).

Dos formas de imprimir:

- «escpos»: manda comandos ESC/POS por el controlador (datos RAW). Es el idioma de las impresoras
  térmicas de tickets (POS-80, POS-58, XP-80C, SLK, Epson TM, Bixolon, 3nStar...): es rápido, corta
  el papel y abre el cajón de dinero.
- «windows»: dibuja el texto con el controlador de Windows (GDI). Sirve con cualquier impresora.

El ticket llega como bloques (ver impresion.js, bloquesTicket) y aquí se arma en columnas.
"""

import logging
import re
import sys
import textwrap
import unicodedata

from . import impresora_usb

registro = logging.getLogger("neji.impresoras")

MODOS = ("escpos", "windows")
# Página de códigos de la impresora -> (códec de Python, número para ESC t n)
CODIGOS = {
    "cp850": ("cp850", 2),     # Multilingüe latino: la que traen casi todas (tildes, ñ, ¿, ¡, °)
    "cp858": ("cp858", 19),    # igual a la 850, con €
    "cp1252": ("cp1252", 16),  # Windows-1252
    "cp437": ("cp437", 0),     # la de fábrica de muchas impresoras (sin á/í/ó/ú mayúsculas)
}
COLUMNAS_POR_PAPEL = {"80": 48, "58": 32}

ESC, GS = b"\x1b", b"\x1d"
INICIAR = ESC + b"@"
NEGRITA = (ESC + b"E\x01", ESC + b"E\x00")
GRANDE = (GS + b"!\x11", GS + b"!\x00")              # doble alto y doble ancho
AVANZAR = ESC + b"d\x04"                              # 4 líneas, para que el corte no se coma el final
CORTAR = GS + b"V\x42\x00"                            # corte parcial
ABRIR_CAJON = ESC + b"p\x00\x19\xfa"                  # pulso al pin 2 (el cajón va conectado a la impresora)
# Muchas POS-58/POS-80 genéricas salen de fábrica en modo chino: las tildes y la ñ salen como letras
# chinas. FS . apaga ese modo (las que no lo tienen no hacen nada).
SIN_CHINO = b"\x1c\x2e"

# Nombres y controladores típicos de impresoras de tickets (con límites de palabra: «PostScript»,
# «Deposito» o «XP-2100» no son de tickets).
PATRON_TERMICA = re.compile(
    r"\bpos\b|\bpos-?\d|receipt|ticket|recibo|t[eé]rmica|thermal|\btm-|\btm\s?[tu]\d|\btsp\d|"
    r"\bxp-?(58|80|[qncetv]\d)|\bslk|\b(58|80)\s?mm|bixolon|\bsrp-|\bstar\s|sewoo|rongta|hprt|gprinter|"
    r"3nstar|xprinter|zjiang|\bct-s|\bepson\s?tm|digipos|ec-?line|jaltech|\bpt-?\d|\brpt?\d|\btp\d|"
    r"\bzj-?\d|\bgp-?\d|bematech|\bmp-\d+\s?th|generic\s*/\s*text only", re.IGNORECASE)
# Impresoras de oficina y de etiquetas que podrían coincidir por el nombre: nunca son «de tickets».
PATRON_OFICINA = re.compile(
    r"postscript|br-script|\bps\d?\b|\(ps\)|\bpcl|laserjet|deskjet|officejet|inkjet|ink tank|smart tank|"
    r"pixma|ecotank|workforce|\bepson\s+(xp|l\d|et-|wf-|stylus)|zdesigner|zebra|\btsc\b|godex|dymo|"
    r"\bql-\d|\bmfc-|\bdcp-", re.IGNORECASE)
# Marcas que no tienen modo chino: a estas no se les manda FS . salvo que se pida.
PATRON_SIN_MODO_CHINO = re.compile(r"epson|\bstar\b|\btsp|bixolon|\bsrp-|citizen|\bct-s|samsung|\btm-",
                                   re.IGNORECASE)
PATRON_VIRTUAL = re.compile(r"pdf|xps|onenote|fax|send to|enviar a|microsoft print|anydesk|teamviewer",
                            re.IGNORECASE)


# En el identificador IEEE 1284 de una impresora de tickets: «CMD:ESC/POS» (o ESCPOS, ESC POS)
PATRON_ESCPOS_1284 = re.compile(r"\bESC\s?/?\s?POS\b", re.IGNORECASE)


class ErrorImpresora(Exception):
    """Problema al imprimir, con un mensaje para mostrar en la caja."""


# --- Armar el ticket en columnas --------------------------------------------------------------------

def _texto(valor):
    return " ".join(str(valor or "").split())


def _partir(texto, ancho):
    # Sin espacios al final: textwrap los deja o no según la versión de Python (3.12 / 3.13).
    return [l.rstrip() for l in textwrap.wrap(texto, ancho, break_long_words=True, break_on_hyphens=False)] or [""]


class Timbre:
    """Renglón con el timbre electrónico del SII (el texto del TED, que se imprime como código PDF417)."""

    def __init__(self, ted):
        self.ted = str(ted or "")

    def pixeles(self, ancho_puntos):
        from .sii.pdf417 import pixeles

        return pixeles(self.ted.encode("iso-8859-1", "replace"), ancho_puntos)


def componer(bloques, columnas):
    """Bloques del ticket -> renglones (texto, negrita, grande) ya ajustados al ancho del papel.

    Un renglón grande usa letra de doble ancho: le caben la mitad de columnas. El timbre del SII queda como
    un renglón Timbre (una imagen).
    """
    renglones = []
    for b in bloques or []:
        tipo = b.get("tipo")
        negrita, grande = bool(b.get("negrita")), bool(b.get("grande"))
        ancho = max(columnas // 2 if grande else columnas, 8)
        if tipo == "timbre":
            if b.get("ted"):
                renglones.append(Timbre(b["ted"]))
        elif tipo == "linea":
            renglones.append(("-" * columnas, False, False))
        elif tipo == "espacio":
            renglones += [("", False, False)] * max(1, min(int(b.get("lineas") or 1), 10))
        elif tipo == "par":
            izq, der = _texto(b.get("izq")), _texto(b.get("der"))[:ancho]
            if len(izq) + len(der) + 1 <= ancho:
                renglones.append((izq + " " * (ancho - len(izq) - len(der)) + der, negrita, grande))
            else:
                partes = _partir(izq, ancho)
                ultima = partes.pop()
                renglones += [(p, negrita, grande) for p in partes]
                if len(ultima) + len(der) + 1 <= ancho:
                    renglones.append((ultima + " " * (ancho - len(ultima) - len(der)) + der, negrita, grande))
                else:
                    renglones += [(ultima, negrita, grande), (der.rjust(ancho), negrita, grande)]
        else:
            centro = b.get("alinear") == "centro"
            for parte in _partir(_texto(b.get("texto")), ancho):
                renglones.append((parte.center(ancho).rstrip() if centro else parte, negrita, grande))
    return renglones


# Lo que no existe en la página de códigos de la impresora (se usa igual en la vista previa: impresion.js).
REEMPLAZOS = {
    "—": "-", "–": "-", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'", "€": "EUR", "·": "-",
    "•": "-", "☎": "Tel", "✆": "Tel", "📞": "Tel", "✚": "+", "✓": "v", "✔": "v", "→": "->", "←": "<-",
    "★": "*", "☆": "*",
}


def _codificar(texto, codec):
    """Texto -> bytes de la impresora. Lo que no existe en esa página de códigos se aproxima."""
    salida = bytearray()
    for letra in texto:
        try:
            salida += letra.encode(codec)
            continue
        except UnicodeEncodeError:
            pass
        reemplazo = REEMPLAZOS.get(letra)
        if reemplazo is None:
            reemplazo = unicodedata.normalize("NFKD", letra).encode("ascii", "ignore").decode() or "?"
        salida += reemplazo.encode(codec, "replace")
    return bytes(salida)


def imagen_escpos(filas, ancho_puntos):
    """Imagen de 1 bit (filas de '0'/'1') -> GS v 0, centrada, en bandas (algunas impresoras no aguantan una
    imagen alta de una sola vez)."""
    if not filas:
        return b""
    izquierda = max(0, (ancho_puntos - len(filas[0])) // 2)
    bytes_fila = (izquierda + len(filas[0]) + 7) // 8
    datos = bytearray()
    for inicio in range(0, len(filas), 128):
        banda = filas[inicio:inicio + 128]
        datos += GS + b"v0\x00" + bytes([bytes_fila % 256, bytes_fila // 256, len(banda) % 256, len(banda) // 256])
        for fila in banda:
            bits = ("0" * izquierda + fila).ljust(bytes_fila * 8, "0")
            datos += int(bits, 2).to_bytes(bytes_fila, "big")
    return bytes(datos)


def escpos(renglones, cortar=True, cajon=False, codigo="cp850", sin_chino=False, ancho_puntos=576):
    """Renglones -> comandos ESC/POS listos para mandar a la impresora (`ancho_puntos`: 576 en 80 mm, 384 en
    58 mm; solo importa para centrar el timbre)."""
    codec, numero = CODIGOS.get(codigo, CODIGOS["cp850"])
    datos = bytearray(INICIAR + (SIN_CHINO if sin_chino else b"") + ESC + b"t" + bytes([numero]))
    if cajon:
        datos += ABRIR_CAJON
    for renglon in renglones:
        if isinstance(renglon, Timbre):
            datos += b"\n" + imagen_escpos(renglon.pixeles(ancho_puntos), ancho_puntos) + b"\n"
            continue
        texto, negrita, grande = renglon
        if negrita or grande:
            datos += NEGRITA[0]
        if grande:
            datos += GRANDE[0]
        datos += _codificar(texto, codec) + b"\n"
        if grande:
            datos += GRANDE[1]
        if negrita or grande:
            datos += NEGRITA[1]
    if renglones:
        datos += AVANZAR
        if cortar:
            datos += CORTAR
    return bytes(datos)


def leer_trabajo(trabajo):
    """Valida lo que manda la interfaz: {impresora, modo, columnas|papel, cortar, cajon, codigo, copias, bloques}."""
    if not isinstance(trabajo, dict):
        raise ErrorImpresora("Trabajo de impresión no válido.")
    nombre = str(trabajo.get("impresora") or "").strip()
    if not nombre:
        raise ErrorImpresora("No hay una impresora elegida.")
    modo = trabajo.get("modo") if trabajo.get("modo") in MODOS else "escpos"
    try:
        columnas = int(trabajo.get("columnas") or COLUMNAS_POR_PAPEL.get(str(trabajo.get("papel")), 48))
    except (TypeError, ValueError):
        columnas = 48
    try:
        copias = int(trabajo.get("copias") or 1)
    except (TypeError, ValueError):
        copias = 1
    bloques = trabajo.get("bloques") or []
    if not isinstance(bloques, list) or not all(isinstance(b, dict) for b in bloques):
        raise ErrorImpresora("El ticket no tiene un formato válido.")
    sin_chino = trabajo.get("sin_chino")
    if sin_chino is None:   # sin elegir: se apaga el modo chino en las genéricas (POS-58, POS-80, XP-...)
        sin_chino = not PATRON_SIN_MODO_CHINO.search(nombre)
    return {
        "impresora": nombre, "modo": modo, "columnas": max(16, min(columnas, 80)),
        "cortar": trabajo.get("cortar", True) is not False, "cajon": bool(trabajo.get("cajon")),
        "codigo": trabajo.get("codigo") if trabajo.get("codigo") in CODIGOS else "cp850",
        "copias": max(1, min(copias, 5)), "bloques": bloques, "sin_chino": bool(sin_chino),
        "usb_directo": trabajo.get("usb_directo", True) is not False,
        "papel_mm": 48 if columnas <= 32 else 72,
    }


def imprimir_trabajo(trabajo):
    """Imprime un ticket (o solo abre el cajón, si no trae bloques).

    Devuelve un aviso (texto) si el ticket salió pero el cajón no se pudo abrir, o None.
    """
    t = leer_trabajo(trabajo)
    renglones = componer(t["bloques"], t["columnas"])
    # Una impresora leída directo del USB no tiene controlador de Windows: siempre ESC/POS.
    modo = "escpos" if es_usb_directo(t["impresora"]) else t["modo"]
    aviso = None
    for copia in range(t["copias"] if renglones else 1):
        cajon = t["cajon"] and copia == 0
        if modo == "escpos" or not renglones:
            mandar_escpos(t["impresora"], escpos(renglones, t["cortar"], cajon, t["codigo"], t["sin_chino"],
                                                 t["papel_mm"] * 8),
                          usb_directo=t["usb_directo"])
        else:
            imprimir_windows(t["impresora"], renglones, t["columnas"], t["papel_mm"])
            if cajon:   # el controlador de Windows no abre el cajón: se manda el pulso aparte
                try:
                    mandar_escpos(t["impresora"], INICIAR + ABRIR_CAJON, "Cajón Neji POS", usb_directo=t["usb_directo"])
                except ErrorImpresora as e:
                    # El ticket ya salió: que falle el cajón no es un error de impresión.
                    aviso = f"El ticket se imprimió, pero no se pudo abrir el cajón: {e}"
    return aviso


# --- USB directo ---------------------------------------------------------------------------------------
# Una impresora USB se puede usar aunque no esté instalada en Windows («Nombre (USB directo)»). Y una que sí
# está instalada en un puerto USB recibe el ticket directo por el USB («forzado»), sin pasar por la cola de
# Windows: si su controlador no acepta ESC/POS o la cola quedó trabada, igual imprime. Si el USB no se puede
# abrir (lo está usando Windows), se usa la cola de siempre.

def es_usb_directo(nombre):
    return str(nombre).endswith(impresora_usb.SUFIJO)


def _usb():
    if sys.platform != "win32":
        return []
    try:
        return impresora_usb.listar()
    except Exception:  # noqa: BLE001 (sin SetupAPI, sin permisos...): se sigue con la cola de Windows
        registro.exception("No se pudieron leer las impresoras USB")
        return []


def es_de_tickets_usb(u):
    """Una USB sin controlador se elige sola para los tickets solo si su nombre o su identificador lo dicen (una
    de tinta sin controlador, p. ej. «EPSON L3150», nunca)."""
    cmd = impresora_usb.leer_1284(u.get("id_1284", "")).get("CMD", "")
    return not u["oficina"] and (clasificar(u["nombre"], "USB", "")["termica"] or bool(PATRON_ESCPOS_1284.search(cmd)))


def ruta_usb(nombre, impresoras_windows=None):
    """Ruta del USB de esa impresora: la de «X (USB directo)», o la del puerto USB donde está instalada «X»."""
    usb = _usb()
    if es_usb_directo(nombre):
        return next((u["ruta"] for u in usb if u["nombre"] + impresora_usb.SUFIJO == nombre), None)
    try:
        puerto = next((p["puerto"] for p in (impresoras_windows or _listar_windows()) if p["nombre"] == nombre), "")
    except ErrorImpresora:
        return None
    puerto = puerto.rstrip(":").upper()
    return next((u["ruta"] for u in usb if puerto.startswith("USB") and u["puerto"].upper() == puerto), None)


def mandar_escpos(nombre, datos, documento="Ticket Neji POS", usb_directo=True):
    """ESC/POS a la impresora: directo por USB si se puede, si no por la cola de Windows."""
    ruta = ruta_usb(nombre) if (usb_directo or es_usb_directo(nombre)) else None
    if es_usb_directo(nombre) and not ruta:
        raise ErrorImpresora(f"No se encontró la impresora «{nombre}». Revisa que esté encendida y conectada por USB.")
    if ruta:
        try:
            impresora_usb.escribir(ruta, datos)
            return
        except impresora_usb.ErrorAbrirUSB as e:
            if es_usb_directo(nombre):
                raise ErrorImpresora(str(e)) from None
            registro.info("USB directo no disponible para «%s» (%s): se usa la cola de Windows", nombre, e)
        except impresora_usb.ErrorUSB as e:
            raise ErrorImpresora(str(e)) from None
    imprimir_crudo(nombre, datos, documento)


# --- Windows -----------------------------------------------------------------------------------------

def _winspool():
    if sys.platform != "win32":
        raise ErrorImpresora("La impresión directa funciona en Windows, con NejiPOS.exe.")
    import ctypes
    from ctypes import wintypes

    w = ctypes.WinDLL("winspool.drv", use_last_error=True)
    w.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    w.EnumPrintersW.restype = wintypes.BOOL
    w.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    w.GetDefaultPrinterW.restype = wintypes.BOOL
    w.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    w.OpenPrinterW.restype = wintypes.BOOL
    w.ClosePrinter.argtypes = [wintypes.HANDLE]
    w.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    w.StartDocPrinterW.restype = wintypes.DWORD
    w.StartPagePrinter.argtypes = [wintypes.HANDLE]
    w.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    w.WritePrinter.restype = wintypes.BOOL
    w.EndPagePrinter.argtypes = [wintypes.HANDLE]
    w.EndDocPrinter.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, w


def _error_windows(ctypes, accion, nombre):
    codigo = ctypes.get_last_error()
    detalle = ctypes.FormatError(codigo).strip() if codigo else "error desconocido"
    if codigo == 1801:  # ERROR_INVALID_PRINTER_NAME
        return ErrorImpresora(f"No se encontró la impresora «{nombre}». Revisa que esté instalada y encendida.")
    if codigo == 1804:  # ERROR_INVALID_DATATYPE: controlador que no acepta ESC/POS directo
        return ErrorImpresora(f"La impresora «{nombre}» no acepta impresión directa (ESC/POS). Elige el modo "
                              "«Con el controlador de Windows» en Configuración → Impresora de tickets.")
    return ErrorImpresora(f"No se pudo {accion} en «{nombre}»: {detalle} (código {codigo}).")


def clasificar(nombre, puerto, controlador):
    """Qué tipo de impresora parece y cómo está conectada, para mostrarlo y elegir sola la de tickets."""
    texto = f"{nombre} {controlador}"
    virtual = bool(PATRON_VIRTUAL.search(texto)) or puerto.upper() in ("PORTPROMPT:", "NUL:", "XPSPORT:")
    p = puerto.upper()
    if p.startswith("USB"):
        conexion = "USB"
    elif p.startswith(("LPT", "COM")):
        conexion = p.rstrip(":")
    elif p.startswith(("IP_", "WSD", "TCP")) or re.match(r"^\d+\.\d+\.\d+\.\d+", p):
        conexion = "Red"
    elif p.startswith("\\\\") or nombre.startswith("\\\\"):
        conexion = "Compartida"
    else:
        conexion = puerto or "—"
    termica = not virtual and bool(PATRON_TERMICA.search(texto)) and not PATRON_OFICINA.search(texto)
    return {"virtual": virtual, "termica": termica, "conexion": conexion}


def listar():
    """Impresoras de este computador: las instaladas en Windows y las USB sin instalar («X (USB directo)»).

    [{nombre, puerto, controlador, conexion, termica, usb_directo, ...}]
    """
    try:
        impresoras, error = _listar_windows(), None
    except ErrorImpresora as e:
        impresoras, error = None, e   # p. ej. la Cola de impresión detenida: las USB directas igual funcionan
    usb = _usb()
    if impresoras is None:
        if not usb:
            raise error
        impresoras = []
    por_puerto = {p["puerto"].rstrip(":").upper(): p for p in impresoras}
    for u in usb:
        instalada = por_puerto.get(u["puerto"].upper()) if u["puerto"] else None
        if instalada:   # ya está en Windows: se imprime directo por su USB (ver mandar_escpos)
            instalada["usb_directo"] = True
            continue
        impresoras.append({
            "nombre": u["nombre"] + impresora_usb.SUFIJO, "puerto": u["puerto"] or "USB",
            "controlador": "Sin controlador: directo por USB", "predeterminada": False, "sin_conexion": False,
            "sin_papel": False, "con_error": False, "virtual": False, "conexion": "USB",
            "termica": es_de_tickets_usb(u), "usb_directo": True, "solo_usb": True,
        })
    impresoras.sort(key=lambda x: (not x["termica"], x["virtual"], not x["predeterminada"], bool(x.get("solo_usb")),
                                   x["nombre"].lower()))
    return impresoras


def _listar_windows():
    """Impresoras instaladas en Windows: [{nombre, puerto, controlador, conexion, termica, ...}]."""
    ctypes, wintypes, w = _winspool()

    class PRINTER_INFO_2W(ctypes.Structure):
        _fields_ = [(campo, wintypes.LPWSTR) for campo in (
            "pServerName", "pPrinterName", "pShareName", "pPortName", "pDriverName", "pComment", "pLocation")] + [
            ("pDevMode", ctypes.c_void_p), ("pSepFile", wintypes.LPWSTR), ("pPrintProcessor", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR), ("pParameters", wintypes.LPWSTR), ("pSecurityDescriptor", ctypes.c_void_p),
            ("Attributes", wintypes.DWORD), ("Priority", wintypes.DWORD), ("DefaultPriority", wintypes.DWORD),
            ("StartTime", wintypes.DWORD), ("UntilTime", wintypes.DWORD), ("Status", wintypes.DWORD),
            ("cJobs", wintypes.DWORD), ("AveragePPM", wintypes.DWORD)]

    banderas = 0x2 | 0x4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    necesario, cantidad = wintypes.DWORD(0), wintypes.DWORD(0)
    if not w.EnumPrintersW(banderas, None, 2, None, 0, ctypes.byref(necesario), ctypes.byref(cantidad)):
        codigo = ctypes.get_last_error()
        if codigo == 1722:   # RPC_S_SERVER_UNAVAILABLE: el servicio de impresión está detenido
            raise ErrorImpresora("El servicio «Cola de impresión» de Windows está detenido. Inícialo (Servicios → "
                                 "Cola de impresión → Iniciar) o reinicia el computador.")
        if codigo != 122:    # ERROR_INSUFFICIENT_BUFFER es lo esperado cuando sí hay impresoras
            raise _error_windows(ctypes, "leer las impresoras", "Windows")
    if not necesario.value:
        return []
    memoria = ctypes.create_string_buffer(necesario.value)
    if not w.EnumPrintersW(banderas, None, 2, ctypes.addressof(memoria), necesario, ctypes.byref(necesario),
                           ctypes.byref(cantidad)):
        raise _error_windows(ctypes, "leer las impresoras", "Windows")
    info = ctypes.cast(memoria, ctypes.POINTER(PRINTER_INFO_2W))

    tamano = wintypes.DWORD(0)
    w.GetDefaultPrinterW(None, ctypes.byref(tamano))
    predeterminada = ""
    if tamano.value:
        nombre = ctypes.create_unicode_buffer(tamano.value)
        if w.GetDefaultPrinterW(nombre, ctypes.byref(tamano)):
            predeterminada = nombre.value

    impresoras = []
    for i in range(cantidad.value):
        p = info[i]
        nombre, puerto, controlador = p.pPrinterName or "", p.pPortName or "", p.pDriverName or ""
        sin_conexion = bool(p.Attributes & 0x400) or bool(p.Status & (0x80 | 0x1000))  # WORK_OFFLINE / OFFLINE / NOT_AVAILABLE
        impresoras.append({
            "nombre": nombre, "puerto": puerto, "controlador": controlador,
            "predeterminada": nombre == predeterminada, "sin_conexion": sin_conexion,
            "sin_papel": bool(p.Status & 0x10), "con_error": bool(p.Status & 0x2),
            **clasificar(nombre, puerto, controlador),
        })
    return impresoras


def imprimir_crudo(nombre, datos, documento="Ticket Neji POS"):
    """Manda bytes tal cual a la impresora (ESC/POS), a través de su controlador."""
    ctypes, wintypes, w = _winspool()

    class DOC_INFO_1W(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    w.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1W)]
    manejador = wintypes.HANDLE()
    if not w.OpenPrinterW(nombre, ctypes.byref(manejador), None):
        raise _error_windows(ctypes, "abrir la impresora", nombre)
    try:
        doc = DOC_INFO_1W(documento, None, "RAW")
        if not w.StartDocPrinterW(manejador, 1, ctypes.byref(doc)):
            raise _error_windows(ctypes, "empezar a imprimir", nombre)
        try:
            w.StartPagePrinter(manejador)
            escritos = wintypes.DWORD(0)
            datos = bytes(datos)
            if not w.WritePrinter(manejador, datos, len(datos), ctypes.byref(escritos)) or escritos.value != len(datos):
                raise _error_windows(ctypes, "enviar el ticket", nombre)
            w.EndPagePrinter(manejador)
        finally:
            w.EndDocPrinter(manejador)
    finally:
        w.ClosePrinter(manejador)


def imprimir_windows(nombre, renglones, columnas, papel_mm=72):
    """Dibuja los renglones con el controlador de Windows: letra de ancho fijo que llena el papel."""
    ctypes, wintypes, _ = _winspool()
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    gdi.CreateDCW.restype = wintypes.HDC
    gdi.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    gdi.CreateFontW.restype = wintypes.HFONT
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi.StartPage.argtypes = gdi.EndPage.argtypes = gdi.EndDoc.argtypes = gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi.PatBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.DWORD]

    class DOCINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR), ("lpszOutput", wintypes.LPCWSTR),
                    ("lpszDatatype", wintypes.LPCWSTR), ("fwType", wintypes.DWORD)]

    gdi.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
    hdc = gdi.CreateDCW("WINSPOOL", nombre, None, None)
    if not hdc:
        raise _error_windows(ctypes, "abrir la impresora", nombre)
    fuentes = []
    try:
        ancho_px, alto_px = gdi.GetDeviceCaps(hdc, 8), gdi.GetDeviceCaps(hdc, 10)   # HORZRES, VERTRES
        px_por_mm = gdi.GetDeviceCaps(hdc, 88) / 25.4                                  # LOGPIXELSX
        # En una impresora de hojas (carta, oficio) el ticket mantiene su ancho de rollo.
        util = min(ancho_px, int(papel_mm * px_por_mm)) if px_por_mm else ancho_px
        letra = max(util // columnas, 4)
        alto = int(letra / 0.55)            # proporción de Consolas
        interlinea = int(alto * 1.12)

        def fuente(escala, peso):
            f = gdi.CreateFontW(-alto * escala, letra * escala, 0, 0, peso, 0, 0, 0, 1, 0, 0, 0, 0x31, "Consolas")
            fuentes.append(f)
            return f

        tipos = {(False, False): fuente(1, 400), (True, False): fuente(1, 700), (True, True): fuente(2, 700),
                 (False, True): fuente(2, 700)}
        doc = DOCINFOW(ctypes.sizeof(DOCINFOW), "Ticket Neji POS", None, None, 0)
        if gdi.StartDocW(hdc, ctypes.byref(doc)) <= 0:
            raise _error_windows(ctypes, "empezar a imprimir", nombre)
        try:
            gdi.StartPage(hdc)
            gdi.SetBkMode(hdc, 1)   # TRANSPARENT
            y = 0
            for renglon in renglones:
                if isinstance(renglon, Timbre):
                    # Cada punto de la imagen (8 por mm) se dibuja con el tamaño que tiene en esta impresora.
                    filas = renglon.pixeles(int(papel_mm * 8))
                    escala = (px_por_mm or 8) / 8
                    alto_img = int(len(filas) * escala) + interlinea
                    if y + alto_img > alto_px:
                        gdi.EndPage(hdc)
                        gdi.StartPage(hdc)
                        y = 0
                    x0 = max(0, int((util - len(filas[0]) * escala) / 2))
                    for i, fila in enumerate(filas):
                        y_fila, alto_fila = y + int(i * escala), max(1, int((i + 1) * escala) - int(i * escala))
                        for m in re.finditer("1+", fila):
                            x1, x2 = x0 + int(m.start() * escala), x0 + int(m.end() * escala)
                            gdi.PatBlt(hdc, x1, y_fila, max(1, x2 - x1), alto_fila, 0x00000042)   # BLACKNESS
                    y += alto_img
                    continue
                texto, negrita, grande = renglon
                paso = interlinea * (2 if grande else 1)
                if y + paso > alto_px:
                    gdi.EndPage(hdc)
                    gdi.StartPage(hdc)
                    y = 0
                gdi.SelectObject(hdc, tipos[(negrita, grande)])
                if texto:
                    gdi.TextOutW(hdc, 0, y, texto, len(texto))
                y += paso
            gdi.EndPage(hdc)
        finally:
            gdi.EndDoc(hdc)
    finally:
        # Primero se borra el DC: una fuente que sigue seleccionada en él no se puede borrar.
        gdi.DeleteDC(hdc)
        for f in fuentes:
            gdi.DeleteObject(f)
