"""Farmacia Piedra en PythonAnywhere (prueba gratis). Ver README, «Prueba gratis en PythonAnywhere».

En la pestaña Web, el archivo WSGI de PythonAnywhere queda solo con estas líneas (con tu código):

    import os, sys
    os.environ["NEJI_CODIGO_INSTALACION"] = "elige-un-codigo"
    sys.path.insert(0, os.path.expanduser("~/farmacia"))
    from wsgi_pythonanywhere import application
"""

import os
import time

os.environ.setdefault("NEJI_WEB", "1")
os.environ.setdefault("NEJI_MARCA", "Farmacia Piedra")
os.environ.setdefault("NEJI_DATOS", os.path.expanduser("~/farmacia-datos"))
os.environ.setdefault("NEJI_SIN_WAL", "1")          # el disco de PythonAnywhere es de red
os.environ["TZ"] = "America/Santiago"
time.tzset()

from neji import create_app  # noqa: E402

application = create_app()
