"""La firma electrónica del dueño (archivo .pfx / .p12) y la firma XML (XMLDSig) como la pide el SII.

La firma de un documento se calcula sobre el elemento canonicalizado (C14N inclusiva 1.0) *en su contexto*:
los espacios de nombres de los ancestros entran en el cálculo. Por eso el DTE declara en su raíz los mismos
xmlns que el sobre (ver dte.py): así su firma vale igual suelto y dentro de EnvioBOLETA / EnvioDTE.
"""

import base64
import copy
import hashlib
from datetime import datetime, timezone

from ..chile import limpiar_rut, validar_rut
from . import ErrorSII

DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
ENVUELTA = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
# Las firmas chilenas (E-Cert, E-Sign, Acepta...) llevan el RUT del titular en esta extensión.
OID_RUT = "1.3.6.1.4.1.8321.1"


def envolver(texto, ancho=64):
    return "\n".join(texto[i:i + ancho] for i in range(0, len(texto), ancho))


def base64_entero(numero):
    largo = max(1, (numero.bit_length() + 7) // 8)
    return base64.b64encode(numero.to_bytes(largo, "big")).decode()


def _rut_del_certificado(cert):
    from cryptography import x509

    candidatos = []
    try:
        alternativos = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for nombre in alternativos:
            if isinstance(nombre, x509.OtherName) and nombre.type_id.dotted_string == OID_RUT:
                valor = nombre.value
                # IA5String en DER: 0x16, largo, texto.
                if len(valor) > 2 and valor[0] == 0x16:
                    valor = valor[2:2 + valor[1]]
                candidatos.append(valor.decode("latin-1", "replace"))
    except x509.ExtensionNotFound:
        pass
    candidatos += [a.value for a in cert.subject.get_attributes_for_oid(x509.NameOID.SERIAL_NUMBER)]
    for candidato in candidatos:
        rut = limpiar_rut(candidato)
        if rut and validar_rut(rut):
            return rut
    return ""


def _nombre(nombre_x509):
    from cryptography import x509

    for oid in (x509.NameOID.COMMON_NAME, x509.NameOID.ORGANIZATION_NAME):
        valores = nombre_x509.get_attributes_for_oid(oid)
        if valores:
            return str(valores[0].value).strip()
    return ""


class Firma:
    """Firma electrónica cargada desde el .pfx/.p12 y su contraseña."""

    def __init__(self, pfx, clave):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12

        if not pfx:
            raise ErrorSII("Falta el archivo de la firma electrónica (.pfx o .p12).")
        intentos = [(clave or "").encode("utf-8")]
        if not clave:
            intentos.append(None)
        llave = cert = None
        for intento in intentos:
            try:
                llave, cert, _ = pkcs12.load_key_and_certificates(bytes(pfx), intento)
                break
            except (ValueError, TypeError):
                continue
        else:
            raise ErrorSII("La contraseña de la firma no es correcta, o el archivo no es una firma "
                           "electrónica (.pfx o .p12).")
        if llave is None or cert is None:
            raise ErrorSII("El archivo no trae la llave privada de la firma: exporta la firma «con la llave "
                           "privada» (archivo .pfx o .p12).")
        if not isinstance(llave, rsa.RSAPrivateKey):
            raise ErrorSII("La firma debe ser RSA (como las de E-Cert, E-Sign, Acepta o CertiNet).")
        self.llave, self.certificado = llave, cert
        self.rut = _rut_del_certificado(cert)
        self.nombre = _nombre(cert.subject)
        self.emisor = _nombre(cert.issuer)
        self.desde = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(tzinfo=timezone.utc)
        self.vence = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)

    @property
    def vigente(self):
        return self.desde <= datetime.now(timezone.utc) <= self.vence

    def resumen(self):
        return {"rut": self.rut, "nombre": self.nombre, "emisor": self.emisor,
                "vence": self.vence.date().isoformat(), "vigente": self.vigente}

    def exigir_vigente(self):
        if not self.vigente:
            raise ErrorSII(f"La firma electrónica de {self.nombre} venció el {self.vence.date():%d-%m-%Y}: "
                           "renuévala y súbela de nuevo en Configuración → Boleta electrónica.")

    def firmar_bytes(self, datos):
        """SHA1withRSA (PKCS#1 v1.5) en base64."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        return base64.b64encode(self.llave.sign(bytes(datos), padding.PKCS1v15(), hashes.SHA1())).decode()

    def certificado_base64(self):
        from cryptography.hazmat.primitives.serialization import Encoding

        return base64.b64encode(self.certificado.public_bytes(Encoding.DER)).decode()

    def firmar_xml(self, raiz, referencia=""):
        """Agrega <Signature> al final de `raiz` (un elemento de lxml), firmando el elemento con ID=referencia
        (o todo el documento si no hay referencia, como la semilla del token)."""
        from lxml import etree

        if referencia:
            encontrados = raiz.xpath("//*[@ID=$id]", id=referencia)
            if len(encontrados) != 1:
                raise ErrorSII(f"No se encontró el elemento {referencia} para firmar.")
            objetivo = encontrados[0]
        else:
            objetivo = raiz
        digest = base64.b64encode(hashlib.sha1(c14n(objetivo)).digest()).decode()

        def sub(padre, nombre, texto=None, **atributos):
            el = etree.SubElement(padre, f"{{{DS}}}{nombre}", **atributos)
            el.text = texto
            return el

        firma = etree.SubElement(raiz, f"{{{DS}}}Signature", nsmap={None: DS})
        info = sub(firma, "SignedInfo")
        sub(info, "CanonicalizationMethod", Algorithm=C14N)
        sub(info, "SignatureMethod", Algorithm=RSA_SHA1)
        ref = sub(info, "Reference", URI=f"#{referencia}" if referencia else "")
        sub(sub(ref, "Transforms"), "Transform", Algorithm=ENVUELTA)
        sub(ref, "DigestMethod", Algorithm=SHA1)
        sub(ref, "DigestValue", digest)
        # Se firma SignedInfo canonicalizado ya en su lugar: con los xmlns que hereda (los mismos que calcula
        # quien verifica).
        valor = self.firmar_bytes(c14n(info))
        sub(firma, "SignatureValue", envolver(valor))
        publica = self.llave.public_key().public_numbers()
        clave = sub(firma, "KeyInfo")
        rsa_valor = sub(sub(clave, "KeyValue"), "RSAKeyValue")
        sub(rsa_valor, "Modulus", envolver(base64_entero(publica.n)))
        sub(rsa_valor, "Exponent", base64_entero(publica.e))
        sub(sub(clave, "X509Data"), "X509Certificate", envolver(self.certificado_base64()))
        # El salto de línea después de la firma solo si queda fuera de lo firmado: dentro (la semilla del token),
        # quien verifica quita la firma pero no ese texto, y el digest ya no calzaría.
        if objetivo is not raiz:
            firma.tail = "\n"
        return raiz


def c14n(el):
    """C14N 1.0 inclusiva de `el` en su contexto (la de CanonicalizationMethod).

    No sirve etree.tostring(el, method="c14n") cuando `el` no es la raíz: lxml les pone xmlns="" a sus nietos (lo
    hacen lxml 5.3 y 6.1), el digest y la firma ya no calzan con los que calcula el SII y rechaza el documento.
    Como raíz de un documento propio, con los xmlns que hereda declarados en él, sale bien, y para la C14N inclusiva
    es lo mismo. Comprobado con DTE reales aceptados por el SII (tests/test_sii_nucleo.py).
    """
    from lxml import etree

    if el.getparent() is None:
        return etree.tostring(el, method="c14n")
    copia = etree.Element(el.tag, nsmap=el.nsmap)
    for clave, valor in el.attrib.items():
        copia.set(clave, valor)
    copia.text = el.text
    for hijo in el:
        copia.append(copy.deepcopy(hijo))
    return etree.tostring(copia, method="c14n")


def _quitar_dejando_texto(el):
    """Saca `el` del árbol y deja el texto que lo seguía (en lxml ese texto es parte del elemento)."""
    padre, anterior = el.getparent(), el.getprevious()
    if el.tail:
        if anterior is not None:
            anterior.tail = (anterior.tail or "") + el.tail
        else:
            padre.text = (padre.text or "") + el.tail
    padre.remove(el)


def verificar_xml(raiz):
    """Comprueba las firmas XMLDSig que tenga `raiz` (la propia y las de los DTE de un sobre).

    Devuelve la cantidad de firmas verificadas; lanza ErrorSII si alguna no calza. Sirve para revisar lo que
    se va a mandar al SII antes de mandarlo (y en las pruebas).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    ns = {"ds": DS}
    arbol = raiz.getroottree()
    firmas = raiz.xpath("//ds:Signature", namespaces=ns)
    for firma in firmas:
        ref = firma.find(f"{{{DS}}}SignedInfo/{{{DS}}}Reference")
        uri = ref.get("URI") or ""
        # Transform enveloped-signature: si la firma está dentro de lo firmado, se calcula sin ella (sin ese
        # elemento, pero con el texto que lo sigue), en una copia del documento entero (mismo contexto).
        copia = copy.deepcopy(arbol.getroot())
        if uri:
            encontrados = copia.xpath("//*[@ID=$id]", id=uri[1:])
            if len(encontrados) != 1:
                raise ErrorSII(f"La firma apunta a {uri}, que no está en el documento.")
            objetivo = encontrados[0]
        else:
            objetivo = copia
        propia = copia.getroottree().xpath(arbol.getpath(firma))[0]
        if any(x is objetivo for x in propia.iterancestors()):
            _quitar_dejando_texto(propia)
        digest = base64.b64encode(hashlib.sha1(c14n(objetivo)).digest()).decode()
        if digest != "".join(ref.findtext(f"{{{DS}}}DigestValue").split()):
            raise ErrorSII(f"La firma de {uri or 'el documento'} no calza con su contenido (digest).")
        cert = x509.load_der_x509_certificate(base64.b64decode(
            "".join(firma.findtext(f".//{{{DS}}}X509Certificate").split())))
        valor = base64.b64decode("".join(firma.findtext(f"{{{DS}}}SignatureValue").split()))
        info = c14n(firma.find(f"{{{DS}}}SignedInfo"))
        try:
            cert.public_key().verify(valor, info, padding.PKCS1v15(), hashes.SHA1())
        except Exception as e:  # noqa: BLE001 (InvalidSignature y otros)
            raise ErrorSII(f"La firma de {uri or 'el documento'} no es válida.") from e
    return len(firmas)
