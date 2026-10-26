"""Modo demostración: la boleta (y la factura) con su timbre, sin el SII.

Sirve para ver y mostrar cómo sale el ticket con el timbre electrónico antes de que el SII autorice al negocio.
Neji inventa en este computador unos folios (CAF) y una firma con la misma forma que los reales, y emite igual
que siempre (al vender, al devolver, la factura), pero:

- los documentos quedan en su propio ambiente («demostracion»), con su propia numeración. El envío al SII solo
  trabaja con los de certificación o producción, así que nunca salen de este computador;
- el ticket dice «DEMOSTRACIÓN · SIN VALOR TRIBUTARIO» y no invita a verificarlo en sii.cl;
- no toca la firma, los folios ni el ambiente que estén configurados: al apagarlo, todo sigue como estaba.

Los datos del emisor son los de Configuración → Boleta electrónica; lo que falte se toma de Configuración →
Negocio o queda uno de ejemplo.
"""

import base64
import secrets
from datetime import date
from xml.sax.saxutils import escape

from ..chile import limpiar_rut, validar_rut
from . import ErrorSII

AMBIENTE = "demostracion"
RUT_EJEMPLO = "11111111-1"
HASTA = 99_999_999                # folios de sobra: el CAF de demostración no se acaba
_cafs = {}
_firma = []


def _es_primo(n):
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


def _primo(bits):
    while True:
        candidato = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if candidato % 3 != 1 and _es_primo(candidato):
            return candidato


def _llave_caf():
    """RSA de 512 bits con exponente 3, como las llaves de los CAF del SII (así el timbre mide lo mismo que el
    real). cryptography ya no genera llaves así de cortas, pero sí las usa."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    while True:
        p, q = _primo(256), _primo(256)
        if p != q and (p * q).bit_length() == 512:
            break
    d = pow(3, -1, (p - 1) * (q - 1))
    return rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p),
                                 rsa.RSAPublicNumbers(3, p * q)).private_key()


def caf(rut, razon_social, tipo):
    """Folios de demostración (del 1 al HASTA) de ese emisor y tipo: uno por proceso, armado como los del SII."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    from .caf import Caf
    from .textos import texto_sii

    clave = (rut, razon_social, tipo)
    if clave not in _cafs:
        llave = _llave_caf()
        numeros = llave.public_key().public_numbers()
        b64 = lambda n: base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode()  # noqa: E731
        da = (f"<DA><RE>{rut}</RE><RS>{escape(texto_sii(razon_social, 40))}</RS><TD>{tipo}</TD>"
              f"<RNG><D>1</D><H>{HASTA}</H></RNG><FA>{date.today().isoformat()}</FA>"
              f"<RSAPK><M>{b64(numeros.n)}</M><E>{b64(numeros.e)}</E></RSAPK><IDK>0</IDK></DA>")
        # Lo firma su propia llave (el SII lo firma con la suya; nadie verifica esta).
        frma = base64.b64encode(llave.sign(da.encode("latin-1"), padding.PKCS1v15(), hashes.SHA1())).decode()
        privada = llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()).decode()
        xml = (f'<?xml version="1.0" encoding="ISO-8859-1"?>\n<AUTORIZACION>\n<CAF version="1.0">\n{da}\n'
               f'<FRMA algoritmo="SHA1withRSA">{frma}</FRMA>\n</CAF>\n<RSASK>{privada}</RSASK>\n</AUTORIZACION>\n')
        _cafs[clave] = Caf(xml.encode("latin-1"))
    return _cafs[clave]


def firma():
    """Una firma de mentira (no es la del dueño ni la de nadie), creada en este proceso."""
    from .autoprueba import pfx_temporal
    from .firma import Firma

    if not _firma:
        clave = secrets.token_hex(8)
        _firma.append(Firma(pfx_temporal(clave, nombre="Firma de demostracion Neji", dias=3650), clave))
    return _firma[0]


def emisor(con, cfg, de_ejemplo=None):
    """Los datos del emisor: los del SII, o los del negocio, o de ejemplo (la boleta igual sale completa).
    `de_ejemplo` (lista) recibe el nombre de los que quedaron de ejemplo."""
    from ..db import leer_config
    from .servicio import actecos, emisor as emisor_sii

    negocio = leer_config(con)
    datos = emisor_sii(cfg)

    def elegir(nombre, opciones, ejemplo):
        valor = next((x for x in opciones if x), None)
        if valor is None and de_ejemplo is not None:
            de_ejemplo.append(nombre)
        return valor or ejemplo

    ruts = [limpiar_rut(r) for r in (cfg.get("rut"), negocio.get("negocio_rut")) if r]
    datos["rut"] = elegir("el RUT", [r for r in ruts if validar_rut(r)], RUT_EJEMPLO)
    datos["razon_social"] = elegir("la razón social", [cfg.get("razon_social"), negocio.get("negocio_nombre")],
                                   "NEGOCIO DE DEMOSTRACION")
    datos["giro"] = elegir("el giro", [cfg.get("giro"), negocio.get("negocio_giro")], "COMERCIO")
    datos["direccion"] = elegir("la dirección", [cfg.get("direccion"), negocio.get("negocio_direccion")],
                                "SIN DIRECCION")
    datos["comuna"] = elegir("la comuna", [cfg.get("comuna"), cfg.get("ciudad")], "SIN COMUNA")
    datos["actecos"] = actecos(cfg) or [477310]
    return datos


def tomar_folio(con, tipo, datos_emisor):
    """El folio siguiente de demostración de ese tipo y sus folios (CAF)."""
    ultimo = con.execute("SELECT MAX(folio) FROM sii_documentos WHERE ambiente = ? AND tipo = ?",
                         (AMBIENTE, tipo)).fetchone()[0] or 0
    if ultimo >= HASTA:
        raise ErrorSII("Se acabaron los folios de demostración.")
    return ultimo + 1, caf(datos_emisor["rut"], datos_emisor["razon_social"], tipo)


def bloqueo(cfg):
    """Por qué no se puede encender ahora (o None)."""
    if cfg.get("activo") == "1" and cfg.get("ambiente") == "produccion":
        return ("La boleta electrónica está funcionando en producción: con el modo demostración las ventas saldrían "
                "sin boleta válida. Si de verdad quieres probar, desactívala primero.")
    return None


def estado(con, cfg):
    de_ejemplo = []
    datos = emisor(con, cfg, de_ejemplo)
    documentos = con.execute("SELECT COUNT(*) FROM sii_documentos WHERE ambiente = ?", (AMBIENTE,)).fetchone()[0]
    return {"activo": cfg.get("demo") == "1", "documentos": documentos, "bloqueo": bloqueo(cfg),
            "emisor": {"rut": datos["rut"], "razon_social": datos["razon_social"]}, "de_ejemplo": de_ejemplo}
