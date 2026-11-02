"""Proveedores de boleta electrónica: otra empresa, autorizada por el SII, emite la boleta por el negocio.

Es una de las tres formas de emitir (Configuración → Boleta electrónica → «¿Quién emite la boleta?»):

- «neji»: Neji firma y timbra con la firma y los folios del negocio, y envía al SII (el negocio se certifica).
- «proveedor» (este módulo): Neji le manda la venta al proveedor por internet y el proveedor devuelve el
  documento ya timbrado (folio, XML y timbre), que Neji guarda e imprime igual que los suyos. El proveedor se
  encarga de inscribir y certificar al negocio ante el SII, de los folios y del envío al SII.
- «maquina»: la máquina POS del local entrega la boleta; Neji no emite nada (para no emitir dos boletas).

Cada proveedor es un «conector» con la misma forma (como las máquinas POS en neji/pos.py): sus campos de
configuración (la llave de su API...), validar y emitir. Hoy están pendientes hasta tener la documentación de su
API; para agregar uno basta con escribir su conector y ponerlo en CONECTORES: el resto (configuración, emitir al
vender o al devolver, guardar, imprimir con el timbre, emitir después desde el historial) ya está hecho.

La boleta se le pide al proveedor DESPUÉS de guardar la venta (nada de red dentro de la transacción de la venta):
si el proveedor no responde, la venta queda con su comprobante interno y la boleta se emite después desde el
historial de ventas.
"""

import copy
import json

from . import ErrorSII

AMBIENTE = "proveedor"                    # sii_documentos.ambiente de lo que emite un proveedor
AMBIENTE_PRUEBAS = "proveedor_pruebas"    # lo emitido en el ambiente de pruebas del proveedor: no vale
AMBIENTES = (AMBIENTE, AMBIENTE_PRUEBAS)
TIEMPO_MAXIMO = 15                        # segundos que se espera al proveedor (los conectores lo usan)


class Proveedor:
    """Lo que tiene que hacer cada proveedor.

    `campos`: su configuración, igual que en las máquinas POS: {clave, etiqueta, tipo (texto | numero | opciones |
    secreto), ayuda?, opciones?, opcional?}. Los «secreto» (llaves de API) se guardan cifrados y nunca vuelven a
    la pantalla.
    """

    clave = ""
    nombre = ""
    disponible = True
    nota = ""
    web = ""
    campos = ()

    def validar(self, datos):
        """Revisa y normaliza la configuración (sin los secretos, que se guardan aparte). Devuelve el dict."""
        return {}

    def pruebas(self, config):
        """True si emite en el ambiente de pruebas del proveedor (los documentos no valen)."""
        return False

    def emitir(self, doc, config):
        """Pide el documento al proveedor y devuelve {folio, xml (bytes del DTE timbrado), ted? , externo?}.

        `doc` es lo mismo con lo que Neji arma sus documentos: tipo (39, 41, 33, 34, 61), fecha, emisor, receptor,
        lineas [{nombre, codigo, cantidad, precio, monto, exento}], descuento_afecto, descuento_exento, tasa_iva,
        credito, referencias (la nota de crédito) y «referencia»: un identificador único de Neji (p. ej.
        «venta-15»), para que el proveedor no emita dos veces lo mismo si se reintenta.
        Si no trae el «ted» (el timbre), se saca del XML. Lanza ErrorSII con un mensaje para la caja.
        """
        raise ErrorSII(f"{self.nombre} todavía no está disponible.")


class Pendiente(Proveedor):
    """Un proveedor que se va a integrar cuando entregue la documentación de su API."""

    disponible = False

    def __init__(self, clave, nombre, nota, web=""):
        self.clave, self.nombre, self.nota, self.web = clave, nombre, nota, web


CONECTORES = {c.clave: c for c in (
    Pendiente("openfactura", "OpenFactura (Haulmer)",
              "Pendiente: falta la documentación de la API de OpenFactura y una cuenta de prueba.",
              "https://www.openfactura.cl"),
    Pendiente("superfactura", "SuperFactura",
              "Pendiente: falta la documentación de la API de SuperFactura y una cuenta de prueba.",
              "https://superfactura.cl"),
    Pendiente("simplefactura", "SimpleFactura",
              "Pendiente: falta la documentación de la API de SimpleFactura y una cuenta de prueba.",
              "https://www.simplefactura.cl"),
    Pendiente("libredte", "LibreDTE",
              "Pendiente: falta integrar la API de LibreDTE y una cuenta de prueba.",
              "https://www.libredte.cl"),
)}

# Máquinas POS que pueden entregar la boleta ellas mismas (según el plan que tenga contratado el negocio).
MAQUINAS_CON_BOLETA = ("Klap", "TUU (Haulmer)", "Mercado Pago", "Transbank", "Getnet")


def lista():
    return [{"clave": c.clave, "nombre": c.nombre, "disponible": c.disponible, "nota": c.nota, "web": c.web,
             "campos": list(c.campos)} for c in CONECTORES.values()]


def datos_guardados(cfg):
    """La configuración guardada del proveedor elegido (los secretos, cifrados)."""
    try:
        datos = json.loads(cfg.get("proveedor_datos") or "{}")
    except ValueError:
        datos = {}
    return datos if isinstance(datos, dict) else {}


def elegido(cfg):
    """El conector del proveedor elegido, o None."""
    return CONECTORES.get(cfg.get("proveedor") or "")


def faltan(cfg):
    """Lo que falta del proveedor para poder emitir (lista de textos)."""
    conector = elegido(cfg)
    if conector is None:
        return ["elegir el proveedor de boleta electrónica"]
    if not conector.disponible:
        return [f"{conector.nombre} todavía no se puede usar ({conector.nota[0].lower()}{conector.nota[1:]})"]
    datos = datos_guardados(cfg)
    return [f"{campo['etiqueta'].lower()} de {conector.nombre}" for campo in conector.campos
            if not campo.get("opcional") and datos.get(campo["clave"]) in (None, "")]


def ambiente(cfg):
    conector = elegido(cfg)
    if conector is not None and conector.disponible and conector.pruebas(datos_guardados(cfg)):
        return AMBIENTE_PRUEBAS
    return AMBIENTE


def publico(cfg):
    """La configuración para la pantalla: sin los secretos (solo si están guardados)."""
    conector = elegido(cfg)
    datos = datos_guardados(cfg)
    for campo in conector.campos if conector else ():
        if campo["tipo"] == "secreto":
            datos[campo["clave"] + "_guardada"] = bool(datos.pop(campo["clave"], None))
    return {"proveedor": conector.clave if conector else "", "datos": datos}


def preparar(cfg, proveedor, entrada, cifrar):
    """Valida la configuración nueva del proveedor y devuelve el JSON para guardar. `cifrar(texto)` cifra los
    secretos; un secreto vacío deja el que estaba (si es el mismo proveedor)."""
    conector = CONECTORES.get(proveedor)
    if conector is None:
        raise ErrorSII("Ese proveedor de boleta electrónica no existe.")
    if not conector.disponible:
        raise ErrorSII(f"{conector.nombre} todavía no se puede usar: {conector.nota}")
    if not isinstance(entrada, dict):
        raise ErrorSII("Formato de configuración inválido.")
    datos = conector.validar(entrada)
    previos = datos_guardados(cfg) if cfg.get("proveedor") == proveedor else {}
    for campo in conector.campos:
        if campo["tipo"] == "secreto":
            valor = str(entrada.get(campo["clave"]) or "").strip()
            datos[campo["clave"]] = cifrar(valor) if valor else previos.get(campo["clave"], "")
    return json.dumps(datos)


def para_emitir(cfg, descifrar):
    """(conector, configuración con los secretos descifrados) para emitir. Lanza ErrorSII si no se puede."""
    falta = faltan(cfg)
    if falta:
        raise ErrorSII("Falta " + "; ".join(falta) + ".")
    conector = elegido(cfg)
    datos = datos_guardados(cfg)
    for campo in conector.campos:
        if campo["tipo"] == "secreto" and datos.get(campo["clave"]):
            try:
                datos[campo["clave"]] = descifrar(datos[campo["clave"]])
            except Exception:  # noqa: BLE001 (otra clave de Neji: p. ej. se restauró en otro computador)
                raise ErrorSII(f"No se puede leer la {campo['etiqueta'].lower()} guardada de {conector.nombre} "
                               "(¿se restauró un respaldo en otro computador?). Vuelve a escribirla en "
                               "Configuración → Boleta electrónica.") from None
    return conector, datos


def ted_del_xml(xml):
    """El timbre (TED) del documento timbrado, como lo guarda Neji (texto ISO-8859-1)."""
    from lxml import etree

    from . import NS_SII

    try:
        raiz = etree.fromstring(bytes(xml))
    except etree.XMLSyntaxError:
        raise ErrorSII("El proveedor devolvió un documento que no se puede leer.") from None
    ted = raiz.find(f".//{{{NS_SII}}}TED")
    if ted is None:
        ted = raiz.find(".//TED")
    if ted is None:
        raise ErrorSII("El documento que devolvió el proveedor no trae el timbre electrónico.")
    # Como el de Neji: el TED solo, sin el espacio de nombres del documento (es lo que va en el PDF417).
    copia = copy.deepcopy(ted)
    copia.tail = None
    for elemento in copia.iter():
        if isinstance(elemento.tag, str) and elemento.tag.startswith("{"):
            elemento.tag = elemento.tag.split("}", 1)[1]
    etree.cleanup_namespaces(copia)
    return etree.tostring(copia, encoding="iso-8859-1", xml_declaration=False).decode("iso-8859-1")
