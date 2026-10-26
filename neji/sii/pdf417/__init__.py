"""Código de barras PDF417 del timbre electrónico.

La codificación es la del proyecto pdf417gen (Ivan Habunek, licencia MIT: LICENSE-pdf417gen.txt), sin su
parte de dibujo: el código lo dibuja Neji en el ticket (ESC/POS, controlador de Windows o la pantalla).
El SII pide nivel de seguridad (corrección de errores) 5 y que el texto vaya en ISO-8859-1.
"""

from .encoding import encode

MAX_FILAS = 90   # lo que admite PDF417


def matriz(datos, columnas=13, seguridad=5):
    """Bytes -> filas de módulos ('1' negro, '0' blanco). Si con esas columnas el código pasa de 90 filas, usa
    más columnas (más ancho y menos alto)."""
    if isinstance(datos, str):
        datos = datos.encode("iso-8859-1")
    for cols in range(max(1, columnas), 31):
        try:
            filas = encode(datos, columns=cols, security_level=seguridad)
        except ValueError:      # más de 90 filas con esas columnas
            continue
        if len(filas) <= MAX_FILAS:
            return ["".join(format(valor, "b") for valor in fila) for fila in filas]
    raise ValueError("El timbre es demasiado largo para un código PDF417.")


def ancho_en_modulos(columnas):
    return 17 * (columnas + 4) + 1


def pixeles(datos, ancho_puntos, modulo=2, alto_fila=5):
    """El timbre como imagen de 1 bit para una impresora térmica: filas de '0'/'1' de puntos (8 por mm).

    El SII pide un timbre de entre 2x5 y 4x9 cm. En 80 mm (576 puntos) va derecho: 12 columnas de módulos de
    2 puntos (0,25 mm) -> unos 6,8 x 3,5 cm. En 58 mm no cabe derecho con módulos legibles: va girado 90°
    (a lo largo del papel), unos 7,7 x 3,6 cm.
    """
    for columnas in range(12, 7, -1):
        if ancho_en_modulos(columnas) * modulo <= ancho_puntos:
            filas = matriz(datos, columnas)
            if len(filas) * alto_fila <= 40 * 8:      # no más de 4 cm de alto
                return [("".join(c * modulo for c in fila)) for fila in filas for _ in range(alto_fila)]
    # Girado: el largo del código va a lo largo del papel y las filas, a lo ancho.
    alto_fila = 6
    for columnas in range(14, 31):
        filas = matriz(datos, columnas)
        if len(filas) * alto_fila <= ancho_puntos:
            break
    else:
        alto_fila = max(1, ancho_puntos // len(filas))
    ancho = len(filas[0])
    girado = []
    for x in range(ancho):
        linea = "".join(fila[x] * alto_fila for fila in reversed(filas))
        girado += [linea] * modulo
    return girado
