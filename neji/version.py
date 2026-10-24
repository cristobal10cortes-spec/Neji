"""Versión de Neji POS.

En NejiPOS.exe la deja la compilación en neji/version.txt (ver empaquetado/NejiPOS.spec). Al correr
desde el código fuente se usa NEJI_VERSION o «desarrollo».
"""

import os
import sys
from pathlib import Path


def version():
    try:
        escrita = Path(__file__).with_name("version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        escrita = ""
    if escrita:
        return escrita
    if getattr(sys, "frozen", False):   # compilado sin version.txt: no se inventa una versión
        return "desconocida"
    return os.environ.get("NEJI_VERSION") or "desarrollo"


def numeros(version):
    """«0.1.14» -> (0, 1, 14) para comparar; None si no es un número de versión."""
    partes = str(version or "").split(".")
    return tuple(int(p) for p in partes) if partes and all(p.isdigit() for p in partes) else None


VERSION = version()
