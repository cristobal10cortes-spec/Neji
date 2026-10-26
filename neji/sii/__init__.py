"""Boleta y factura electrónica con el SII (opcional).

Neji emite los documentos tributarios electrónicos (DTE) con la firma electrónica del dueño del negocio:

- ``firma.py``: la firma electrónica (.pfx / .p12) del dueño o de una persona autorizada ante el SII.
- ``caf.py``: los folios que autoriza el SII (archivo CAF de cada tipo de documento).
- ``dte.py``: arma, timbra (TED) y firma cada documento: boleta 39/41, factura 33/34, nota de débito 56 y
  nota de crédito 61.
- ``envio.py``: el sobre (EnvioBOLETA / EnvioDTE) que se sube al SII.
- ``conexion.py``: semilla, token, envío y consulta de estado contra los servidores del SII.
- ``pdf417/``: el código de barras del timbre que va impreso en el ticket (de pdf417gen, licencia MIT).
- ``autoprueba.py``: prueba rápida de que todo funciona en el equipo (NejiPOS.exe --prueba).
- ``demostracion.py``: el modo demostración (folios y firma de mentira; los documentos nunca van al SII).
- ``servicio.py``: lo que usa el resto de Neji (configuración, emitir al vender, enviar en segundo plano).
- Certificación ante el SII: ``set_pruebas.py`` (lee el set), ``certificacion.py`` (emite el set, la simulación
  y las boletas de prueba), ``libros.py`` (libros de compras y ventas), ``rcof.py`` (consumo de folios),
  ``intercambio.py`` (respuestas a un envío recibido) y ``muestras.py`` + ``pdf.py`` (muestras impresas).

Todo esto es opcional: si no se configura, Neji sigue vendiendo con su comprobante interno de siempre.
Necesita los módulos ``lxml`` y ``cryptography`` (vienen con NejiPOS.exe y en requirements.txt).
"""

NOMBRES = {
    33: "FACTURA ELECTRÓNICA",
    34: "FACTURA NO AFECTA O EXENTA ELECTRÓNICA",
    39: "BOLETA ELECTRÓNICA",
    41: "BOLETA NO AFECTA O EXENTA ELECTRÓNICA",
    56: "NOTA DE DÉBITO ELECTRÓNICA",
    61: "NOTA DE CRÉDITO ELECTRÓNICA",
}
TIPOS = tuple(NOMBRES)
BOLETAS = (39, 41)
FACTURAS = (33, 34)
NOTAS = (56, 61)
RUT_SII = "60803000-K"            # el SII como receptor de los sobres
RUT_CONSUMIDOR_FINAL = "66666666-6"
NS_SII = "http://www.sii.cl/SiiDte"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


class ErrorSII(Exception):
    """Problema con la facturación electrónica, con un mensaje que se puede mostrar tal cual.

    `definitivo`: el SII rechazó el sobre (esquema, firma): reintentarlo no sirve.
    """

    def __init__(self, mensaje, definitivo=False):
        super().__init__(mensaje)
        self.definitivo = definitivo


def falta_modulo():
    """'' si están lxml y cryptography; si no, el mensaje para mostrar."""
    faltan = []
    try:
        import lxml.etree  # noqa: F401
    except ImportError:
        faltan.append("lxml")
    try:
        import cryptography  # noqa: F401
    except ImportError:
        faltan.append("cryptography")
    if not faltan:
        return ""
    return ("Para la boleta electrónica faltan los módulos " + " y ".join(faltan)
            + " (pip install -r requirements.txt).")
