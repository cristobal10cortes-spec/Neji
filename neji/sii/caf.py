"""El CAF (Código de Autorización de Folios): el archivo XML que da el SII con un rango de folios de un tipo
de documento y la llave con que se firma el timbre (TED) de cada uno."""

import base64
import re

from ..chile import limpiar_rut
from . import NOMBRES, ErrorSII


def leer_xml(datos):
    """Bytes de un XML -> elemento de lxml. Los archivos del SII vienen en ISO-8859-1 y a veces sin decirlo."""
    from lxml import etree

    if isinstance(datos, str):
        datos = datos.encode("utf-8")
    if b"<!DOCTYPE" in bytes(datos).upper() or b"<!ENTITY" in bytes(datos).upper():
        raise ErrorSII("El archivo no es un CAF del SII (trae declaraciones DOCTYPE o ENTITY).")
    parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
    try:
        return etree.fromstring(datos, parser)
    except etree.XMLSyntaxError:
        # Declarado como UTF-8 (o sin declaración) pero con tildes en ISO-8859-1.
        texto = datos.decode("latin-1")
        texto = re.sub(r"^\s*<\?xml[^>]*\?>", "", texto)
        try:
            return etree.fromstring(texto.encode("utf-8"), parser)
        except etree.XMLSyntaxError as e:
            raise ErrorSII(f"El archivo no es un XML válido: {e}") from None


def _entero_b64(texto):
    return int.from_bytes(base64.b64decode("".join((texto or "").split())), "big")


class Caf:
    def __init__(self, datos):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        raiz = leer_xml(datos)
        caf = raiz if raiz.tag == "CAF" else raiz.find("CAF")
        if raiz.tag != "AUTORIZACION" or caf is None or caf.find("DA") is None:
            raise ErrorSII("El archivo no es un CAF del SII (debe tener AUTORIZACION/CAF/DA).")
        da = caf.find("DA")
        try:
            self.rut = limpiar_rut(da.findtext("RE"))
            self.razon_social = (da.findtext("RS") or "").strip()
            self.tipo = int(da.findtext("TD"))
            self.desde = int(da.findtext("RNG/D"))
            self.hasta = int(da.findtext("RNG/H"))
            self.fecha = (da.findtext("FA") or "").strip()
        except (TypeError, ValueError):
            raise ErrorSII("El CAF está incompleto: falta el tipo de documento o el rango de folios.") from None
        if self.tipo not in NOMBRES:
            raise ErrorSII(f"Neji no emite el tipo de documento {self.tipo} (este CAF no sirve aquí). "
                           "Sirven: " + ", ".join(f"{t} ({n.lower()})" for t, n in NOMBRES.items()) + ".")
        if self.desde < 1 or self.hasta < self.desde:
            raise ErrorSII("El rango de folios del CAF no es válido.")
        pem = (raiz.findtext("RSASK") or "").strip()
        if not pem:
            raise ErrorSII("El CAF no trae la llave privada (RSASK). Descárgalo de nuevo desde el SII.")
        try:
            self.llave = load_pem_private_key(pem.encode(), password=None)
        except (ValueError, TypeError):
            raise ErrorSII("La llave del CAF (RSASK) está dañada. Descárgalo de nuevo desde el SII.") from None
        # La llave privada tiene que ser la pareja de la pública que autorizó el SII (RSAPK).
        publica = self.llave.public_key().public_numbers()
        if (publica.n, publica.e) != (_entero_b64(da.findtext("RSAPK/M")), _entero_b64(da.findtext("RSAPK/E"))):
            raise ErrorSII("La llave del CAF no corresponde a la autorizada por el SII. Descárgalo de nuevo.")
        from lxml import etree

        # El CAF va dentro del timbre tal como lo firmó el SII, sin espacios entre etiquetas (se leyó así).
        self._caf = caf
        self.xml_original = etree.tostring(raiz, encoding="ISO-8859-1", xml_declaration=True)

    def elemento(self):
        """Copia del elemento <CAF> para ponerla en el timbre."""
        import copy

        return copy.deepcopy(self._caf)

    @property
    def nombre(self):
        return NOMBRES[self.tipo]

    def contiene(self, folio):
        return self.desde <= folio <= self.hasta

    def firmar(self, datos):
        """SHA1withRSA con la llave del CAF (para el FRMT del timbre), en base64."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        return base64.b64encode(self.llave.sign(bytes(datos), padding.PKCS1v15(), hashes.SHA1())).decode()

    def resumen(self):
        return {"tipo": self.tipo, "nombre": self.nombre, "desde": self.desde, "hasta": self.hasta,
                "fecha": self.fecha, "rut": self.rut, "razon_social": self.razon_social}
