"""Un PDF mínimo, sin dependencias: texto en Helvetica, líneas, recuadros e imágenes de 1 bit (el timbre).

Lo justo para las muestras impresas que pide el SII en la certificación: una página por documento, con el texto como
texto (no como imagen) y el timbre PDF417 como imagen incrustada comprimida, que es lo que lee su revisión
automática. Las medidas van en milímetros desde la esquina superior izquierda.
"""

import zlib

PUNTOS_POR_MM = 72 / 25.4
CARTA = (215.9, 279.4)

# Anchos de las letras (Helvetica y Helvetica-Bold, en milésimas del tamaño), de los AFM de Adobe.
_ANCHOS = {
    False: [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
            556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
            500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469,
            556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
            278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
    True: [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
           556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
           556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584,
           556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
           333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
}
_COMO = str.maketrans("áéíóúüÁÉÍÓÚÜñÑ°ºª", "aeiouuAEIOUUnNooa")


def ancho(texto, tamano, negrita=False):
    """Ancho del texto en mm."""
    tabla = _ANCHOS[bool(negrita)]
    total = 0
    for c in str(texto).translate(_COMO):
        n = ord(c)
        total += tabla[n - 32] if 32 <= n < 127 else 556
    return total * tamano / 1000 / PUNTOS_POR_MM


def partir(texto, ancho_mm, tamano, negrita=False):
    """El texto en líneas que caben en ancho_mm (corta palabras demasiado largas)."""
    lineas, actual = [], ""
    for palabra in str(texto or "").split():
        prueba = f"{actual} {palabra}".strip()
        if ancho(prueba, tamano, negrita) <= ancho_mm:
            actual = prueba
            continue
        if actual:
            lineas.append(actual)
        while ancho(palabra, tamano, negrita) > ancho_mm and len(palabra) > 1:
            corte = len(palabra)
            while corte > 1 and ancho(palabra[:corte], tamano, negrita) > ancho_mm:
                corte -= 1
            lineas.append(palabra[:corte])
            palabra = palabra[corte:]
        actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _cadena(texto):
    datos = str(texto).encode("cp1252", "replace")
    return b"(" + datos.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _n(valor):
    return f"{valor:.2f}".rstrip("0").rstrip(".")


class Pagina:
    def __init__(self, ancho_mm=CARTA[0], alto_mm=CARTA[1]):
        self.ancho, self.alto = ancho_mm, alto_mm
        self._ops = []
        self.imagenes = []

    def _x(self, mm):
        return mm * PUNTOS_POR_MM

    def _y(self, mm):
        return (self.alto - mm) * PUNTOS_POR_MM

    def texto(self, x, y, texto, tamano=9, negrita=False, alinear="izq", color=(0, 0, 0)):
        """`y` es la línea base del texto."""
        if texto in (None, ""):
            return
        if alinear == "der":
            x -= ancho(texto, tamano, negrita)
        elif alinear == "centro":
            x -= ancho(texto, tamano, negrita) / 2
        fuente = "F2" if negrita else "F1"
        self._ops.append(f"{_n(color[0])} {_n(color[1])} {_n(color[2])} rg BT /{fuente} {_n(tamano)} Tf "
                         f"{_n(self._x(x))} {_n(self._y(y))} Td ".encode() + _cadena(texto) + b" Tj ET")

    def parrafo(self, x, y, texto, ancho_mm, tamano=9, negrita=False, interlineado=None, alinear="izq"):
        """Escribe el texto partido en líneas; devuelve la `y` de la línea siguiente."""
        paso = interlineado or tamano * 0.45
        for linea in partir(texto, ancho_mm, tamano, negrita):
            destino = x + (ancho_mm if alinear == "der" else ancho_mm / 2 if alinear == "centro" else 0)
            self.texto(destino, y, linea, tamano, negrita, alinear)
            y += paso
        return y

    def linea(self, x1, y1, x2, y2, grosor=0.2, color=(0, 0, 0)):
        self._ops.append(f"{_n(color[0])} {_n(color[1])} {_n(color[2])} RG {_n(grosor * PUNTOS_POR_MM)} w "
                         f"{_n(self._x(x1))} {_n(self._y(y1))} m {_n(self._x(x2))} {_n(self._y(y2))} l S".encode())

    def rectangulo(self, x, y, ancho_mm, alto_mm, grosor=0.2, color=(0, 0, 0)):
        self._ops.append(f"{_n(color[0])} {_n(color[1])} {_n(color[2])} RG {_n(grosor * PUNTOS_POR_MM)} w "
                         f"{_n(self._x(x))} {_n(self._y(y + alto_mm))} {_n(ancho_mm * PUNTOS_POR_MM)} "
                         f"{_n(alto_mm * PUNTOS_POR_MM)} re S".encode())

    def imagen_bits(self, x, y, ancho_mm, alto_mm, filas):
        """Imagen de 1 bit: `filas` de '0'/'1' ('1' negro), estirada a ancho_mm × alto_mm."""
        nombre = f"Im{len(self.imagenes) + 1}"
        self.imagenes.append((nombre, filas))
        self._ops.append(f"q {_n(ancho_mm * PUNTOS_POR_MM)} 0 0 {_n(alto_mm * PUNTOS_POR_MM)} "
                         f"{_n(self._x(x))} {_n(self._y(y + alto_mm))} cm /{nombre} Do Q".encode())


def _imagen(filas):
    """Objeto de imagen (DeviceGray, 1 bit, Flate) de filas de '0'/'1'. En la imagen 1 es blanco."""
    ancho_px, alto_px = len(filas[0]), len(filas)
    crudo = bytearray()
    for fila in filas:
        bits = fila.translate(str.maketrans("01", "10")).ljust((ancho_px + 7) // 8 * 8, "1")
        crudo += int(bits, 2).to_bytes(len(bits) // 8, "big")
    datos = zlib.compress(bytes(crudo), 9)
    cabecera = (f"<< /Type /XObject /Subtype /Image /Width {ancho_px} /Height {alto_px} /ColorSpace /DeviceGray "
                f"/BitsPerComponent 1 /Filter /FlateDecode /Length {len(datos)} >>")
    return cabecera.encode() + b"\nstream\n" + datos + b"\nendstream"


def documento(paginas, titulo="Documento"):
    """Las páginas como un PDF (bytes)."""
    objetos = []

    def agregar(contenido):
        objetos.append(contenido if isinstance(contenido, bytes) else contenido.encode("latin-1"))
        return len(objetos)

    catalogo = agregar(b"")          # se completa al final
    arbol = agregar(b"")
    fuente = agregar("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    negrita = agregar("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    hijas = []
    for pagina in paginas:
        imagenes = {nombre: agregar(_imagen(filas)) for nombre, filas in pagina.imagenes}
        contenido = zlib.compress(b"\n".join(pagina._ops), 9)
        flujo = agregar(f"<< /Length {len(contenido)} /Filter /FlateDecode >>\nstream\n".encode() + contenido
                        + b"\nendstream")
        recursos = f"/Font << /F1 {fuente} 0 R /F2 {negrita} 0 R >>"
        if imagenes:
            recursos += " /XObject << " + " ".join(f"/{n} {o} 0 R" for n, o in imagenes.items()) + " >>"
        hijas.append(agregar(f"<< /Type /Page /Parent {arbol} 0 R /MediaBox [0 0 {_n(pagina.ancho * PUNTOS_POR_MM)} "
                             f"{_n(pagina.alto * PUNTOS_POR_MM)}] /Resources << {recursos} >> "
                             f"/Contents {flujo} 0 R >>"))
    objetos[catalogo - 1] = f"<< /Type /Catalog /Pages {arbol} 0 R >>".encode()
    objetos[arbol - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{h} 0 R' for h in hijas)}] "
                          f"/Count {len(hijas)} >>").encode()
    info = agregar(b"<< /Title " + _cadena(titulo) + b" /Producer (Neji POS) >>")
    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posiciones = []
    for n, contenido in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{n} 0 obj\n".encode() + contenido + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posiciones)
    salida += (f"trailer\n<< /Size {len(objetos) + 1} /Root {catalogo} 0 R /Info {info} 0 R >>\n"
               f"startxref\n{inicio_xref}\n%%EOF\n").encode()
    return bytes(salida)
