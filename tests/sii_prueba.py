"""Firma y CAF de prueba (generados al vuelo) para las pruebas de la boleta electrónica.

Tienen la misma forma que los reales: la firma lleva el RUT del titular en la extensión que usan E-Cert,
E-Sign y Acepta; el CAF trae DA, FRMA (firmada por un «SII» de prueba), RSASK y RSAPUBK.
"""

import base64
from datetime import datetime, timedelta, timezone
from functools import lru_cache

RUT_EMPRESA = "76354771-K"
RUT_FIRMANTE = "13185095-6"


@lru_cache(maxsize=None)
def _llave(bits=2048, semilla=0):
    from cryptography.hazmat.primitives.asymmetric import rsa

    if bits >= 1024:
        return rsa.generate_private_key(public_exponent=65537, key_size=bits)
    # Los CAF del SII usan RSA de 512 bits con exponente 3: cryptography ya no los genera, pero sí los usa.
    import secrets

    def es_primo(n):
        if n % 2 == 0:
            return False
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(40):
            x = pow(secrets.randbelow(n - 3) + 2, d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                return False
        return True

    def primo(b):
        while True:
            c = secrets.randbits(b) | (1 << (b - 1)) | 1
            if c % 3 != 1 and es_primo(c):
                return c

    p, q = primo(bits // 2), primo(bits // 2)
    d = pow(3, -1, (p - 1) * (q - 1))
    return rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p),
                                 rsa.RSAPublicNumbers(3, p * q)).private_key()


def pfx_de_prueba(clave="1234", rut=RUT_FIRMANTE, vencida=False, sin_rut=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    llave = _llave(2048, 1)
    nombre = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
                        x509.NameAttribute(NameOID.COMMON_NAME, "Dueño de Prueba"),
                        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "dueno@ejemplo.cl")])
    emisor = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA de Prueba Firma Electronica")])
    ahora = datetime.now(timezone.utc)
    desde, hasta = (ahora - timedelta(days=800), ahora - timedelta(days=30)) if vencida else (
        ahora - timedelta(days=1), ahora + timedelta(days=365))
    constructor = (x509.CertificateBuilder().subject_name(nombre).issuer_name(emisor)
                   .public_key(llave.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(desde).not_valid_after(hasta))
    if not sin_rut:
        valor = rut.encode()
        constructor = constructor.add_extension(x509.SubjectAlternativeName([
            x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.8321.1"), bytes([0x16, len(valor)]) + valor)]),
            critical=False)
    cert = constructor.sign(llave, hashes.SHA256())
    cifrado = (serialization.BestAvailableEncryption(clave.encode()) if clave
               else serialization.NoEncryption())
    return pkcs12.serialize_key_and_certificates(b"firma", llave, cert, None, cifrado)


def caf_de_prueba(tipo=39, desde=1, hasta=100, rut=RUT_EMPRESA, razon="FARMACIA DE PRUEBA SPA"):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    llave = _llave(512, tipo)
    numeros = llave.public_key().public_numbers()
    b64 = lambda n: base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode()
    da = (f"<DA><RE>{rut}</RE><RS>{razon}</RS><TD>{tipo}</TD><RNG><D>{desde}</D><H>{hasta}</H></RNG>"
          f"<FA>2026-10-01</FA><RSAPK><M>{b64(numeros.n)}</M><E>{b64(numeros.e)}</E></RSAPK><IDK>100</IDK></DA>")
    sii = _llave(512, 999)
    frma = base64.b64encode(sii.sign(da.encode("latin-1"), padding.PKCS1v15(), hashes.SHA1())).decode()
    privada = llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()).decode()
    publica = llave.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    xml = (f'<?xml version="1.0"?>\n<AUTORIZACION>\n<CAF version="1.0">\n{da}\n'
           f'<FRMA algoritmo="SHA1withRSA">{frma}</FRMA>\n</CAF>\n<RSASK>{privada}</RSASK>\n'
           f"<RSAPUBK>{publica}</RSAPUBK>\n</AUTORIZACION>\n")
    return xml.encode("latin-1")


EMISOR = {"rut": RUT_EMPRESA, "razon_social": "Farmacia de Prueba SpA", "giro": "Venta de productos farmacéuticos",
          "actecos": [477310], "direccion": "Av. Balmaceda 1234", "comuna": "La Serena", "ciudad": "La Serena",
          "telefono": "+56 51 2123456", "email": "contacto@farmacia.cl"}


def validar_esquema(xml, raiz="EnvioBOLETA"):
    """Valida contra los XSD oficiales del SII (tests/sii_xsd)."""
    from pathlib import Path

    from lxml import etree

    nombre = {"EnvioBOLETA": "EnvioBOLETA_v11.xsd", "EnvioDTE": "EnvioDTE_v10.xsd", "DTE": "DTE_v10.xsd"}[raiz]
    esquema = etree.XMLSchema(etree.parse(str(Path(__file__).with_name("sii_xsd") / nombre)))
    doc = etree.fromstring(xml)
    if not esquema.validate(doc):
        raise AssertionError("\n".join(str(e) for e in esquema.error_log))
    return doc
