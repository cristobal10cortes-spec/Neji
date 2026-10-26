"""Prueba rápida de que la boleta electrónica funciona en este equipo: firma electrónica (cryptography), XML
firmado y verificado (lxml) y timbre PDF417. La usa ``NejiPOS.exe --prueba`` (la compilación en GitHub)."""

from datetime import datetime, timedelta, timezone

RUT_PRUEBA = "11111111-1"


def pfx_temporal(clave, nombre="Prueba Neji", dias=1):
    """Una firma electrónica de mentira, con la forma de las reales (RUT del titular en la extensión del SII).
    También la usa el modo demostración (demostracion.py)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)])
    ahora = datetime.now(timezone.utc)
    rut = RUT_PRUEBA.encode()
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(llave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
            .not_valid_after(ahora + timedelta(days=dias))
            .add_extension(x509.SubjectAlternativeName([x509.OtherName(
                x509.ObjectIdentifier("1.3.6.1.4.1.8321.1"), bytes([0x16, len(rut)]) + rut)]), critical=False)
            .sign(llave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"prueba", llave, cert, None,
                                                 serialization.BestAvailableEncryption(clave.encode()))


def probar():
    """Devuelve un resumen; lanza una excepción si algo no funciona."""
    from . import NS_SII, falta_modulo

    falta = falta_modulo()
    if falta:
        raise RuntimeError(falta)
    from lxml import etree

    from .firma import Firma, verificar_xml
    from .pdf417 import matriz, pixeles

    firma = Firma(pfx_temporal("prueba"), "prueba")
    if firma.rut != RUT_PRUEBA:
        raise RuntimeError(f"la firma de prueba trae el RUT {firma.rut!r}")
    raiz = etree.fromstring(f'<SetDTE xmlns="{NS_SII}" ID="SetDoc"><Caratula>Ñandú y Peña</Caratula></SetDTE>'.encode())
    firma.firmar_xml(raiz, "SetDoc")
    verificadas = verificar_xml(etree.fromstring(etree.tostring(raiz, encoding="ISO-8859-1")))
    ted = "<TED version=\"1.0\"><DD><RE>11111111-1</RE><TD>39</TD><F>1</F></DD></TED>".encode("iso-8859-1")
    filas = matriz(ted, 12)
    return {"firma": firma.rut, "firmas_verificadas": verificadas, "pdf417": f"{len(filas)} filas",
            "timbre_80mm": len(pixeles(ted, 576)), "timbre_58mm": len(pixeles(ted, 384))}
