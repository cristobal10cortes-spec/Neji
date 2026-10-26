"""Textos que van en los documentos del SII: solo lo que el SII acepta, del largo que admite su esquema."""

import re
import unicodedata

# Lo tipográfico que no existe en ISO-8859-1 (la codificación de los DTE) se pasa a su par simple.
_REEMPLAZOS = {"—": "-", "–": "-", "‒": "-", "…": "...", "€": "EUR", "•": "-", "·": "-",
               "“": "", "”": "", "„": "", "‘": "", "’": "", "´": "", "`": "", '"': "", "'": ""}
# Lo que el plegado a ASCII no separa en letra + tilde.
_LIGADURAS = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "Œ": "OE", "œ": "oe", "Æ": "AE",
              "æ": "ae", "Ø": "O", "ø": "o", "Ð": "D", "ð": "d", "Þ": "TH", "þ": "th", "ß": "ss"}


def texto_sii(valor, largo=None):
    """Texto para un campo del DTE: sin comillas ni caracteres fuera de ISO-8859-1, sin espacios de más.

    Las comillas y apóstrofos se quitan (así lo hacen las implementaciones que el SII acepta); lo que no
    existe en ISO-8859-1 (emojis, guiones largos) haría que el SII rechace el sobre completo por esquema.
    """
    texto = " ".join("".join(_REEMPLAZOS.get(c, c) for c in str(valor or "")).split())  # tabs, NBSP...
    texto = "".join(c for c in texto if ord(c) <= 0xFF and (c.isprintable() or c == " "))
    texto = " ".join(texto.split())
    return texto[:largo].rstrip() if largo else texto


def texto_timbre(valor, largo=40):
    """Texto para el timbre (RSR, IT1): solo ASCII.

    El lector de PDF417 del SII no devuelve tal cual los bytes con tilde o ñ, y como el timbre va firmado,
    un acento hace que el SII lo rechace con «TED - Firma inválida». El documento conserva el texto real;
    esto es solo para el código de barras. Se corta después de plegar (ß -> ss alarga el texto).
    """
    texto = "".join(_LIGADURAS.get(c, c) for c in str(valor or ""))
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto_sii(texto)
    texto = "".join(c for c in texto if 0x20 <= ord(c) <= 0x7E)
    return " ".join(texto.split())[:largo].rstrip()


def correo_valido(valor):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(valor or "").strip()))
