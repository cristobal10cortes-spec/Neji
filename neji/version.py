"""Versión de Neji POS.

En NejiPOS.exe la deja la compilación en neji/version.txt (ver empaquetado/NejiPOS.spec). Al correr
desde el código fuente se usa NEJI_VERSION o «desarrollo».
"""

import os
from pathlib import Path


def version():
    try:
        escrita = Path(__file__).with_name("version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        escrita = ""
    return escrita or os.environ.get("NEJI_VERSION") or "desarrollo"


VERSION = version()
