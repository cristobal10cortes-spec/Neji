"""Protecciones de la parte web de Neji, para todas las respuestas y pedidos.

- Cabeceras: la página solo carga lo propio (Content-Security-Policy), no se puede meter dentro de otra
  página (clickjacking) y el navegador no adivina tipos de archivo.
- Pedidos que cambian algo (POST, PUT, DELETE): si el navegador dice de qué página vienen (Origin o Referer),
  tiene que ser la misma de Neji. Así otra página abierta en el mismo computador no puede usar la sesión
  (CSRF), además de la cookie SameSite.
- En el computador o la red local, la dirección pedida (Host) tiene que ser una IP, «localhost» o el nombre
  del equipo: así una página de internet no puede llegar a Neji con un dominio propio que apunte a
  127.0.0.1 (DNS rebinding). En internet (NEJI_WEB) se puede fijar el dominio con NEJI_DOMINIOS.
- Tamaño de los pedidos: los JSON, hasta 2 MB; los archivos (respaldos, inventario), hasta 200 MB.
"""

import ipaddress
import os
from urllib.parse import urlsplit

from flask import current_app, request

from .validar import ErrorNegocio

# 'unsafe-eval': la ventana de escritorio (pywebview) arma su puente con las impresoras con new Function(). Igual
# quedan prohibidos los scripts en línea y los de otros sitios, que es lo que aprovecharía una inyección.
POLITICA = ("default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'")
METODOS_QUE_CAMBIAN = {"POST", "PUT", "PATCH", "DELETE"}
MAX_JSON = 2 * 1024 * 1024
# Rutas que reciben archivos grandes (el resto, solo JSON chico).
CON_ARCHIVOS = {"api.restaurar_respaldo", "api.importar_productos", "api.subir_firma", "api.subir_caf",
                "api.certificar_intercambio"}


def _nombre_permitido(host):
    """IP, localhost, un nombre de equipo de la red (sin puntos) o un .local / .lan."""
    nombre = host.strip("[]").rstrip(".").lower()
    if not nombre:
        return False
    try:
        ipaddress.ip_address(nombre)
        return True
    except ValueError:
        pass
    if nombre == "localhost" or nombre.endswith((".localhost", ".local", ".lan", ".home.arpa")):
        return True
    return "." not in nombre


def _dominios_extra():
    return {d.strip().lower() for d in (os.environ.get("NEJI_DOMINIOS") or "").split(",") if d.strip()}


def host_permitido(host_con_puerto):
    host = urlsplit(f"//{host_con_puerto}").hostname or ""
    extra = _dominios_extra()
    if host.lower() in extra:
        return True
    if current_app.config.get("WEB"):
        # Detrás del proxy del hosting: si no se fijó el dominio, se acepta el que llega.
        return not extra or host.lower() in extra
    return _nombre_permitido(host)


def revisar_pedido():
    if not host_permitido(request.host):
        raise ErrorNegocio("Dirección no permitida. Abre Neji con la IP o el nombre del computador.", status=400)
    if request.method in METODOS_QUE_CAMBIAN:
        origen = request.headers.get("Origin") or request.headers.get("Referer")
        if origen and origen != "null":
            partes = urlsplit(origen)
            if partes.netloc.lower() != request.host.lower():
                raise ErrorNegocio("Pedido rechazado: no viene de la página de Neji.", status=403)
        elif origen == "null":
            raise ErrorNegocio("Pedido rechazado: no viene de la página de Neji.", status=403)


def limitar_tamano():
    if request.endpoint not in CON_ARCHIVOS:
        request.max_content_length = MAX_JSON


def cabeceras(respuesta):
    respuesta.headers.setdefault("Content-Security-Policy", POLITICA)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "same-origin")
    respuesta.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    respuesta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path.startswith("/api/"):
        respuesta.headers.setdefault("Cache-Control", "no-store")
    if current_app.config.get("WEB"):
        respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return respuesta


def init_app(app):
    app.before_request(limitar_tamano)
    app.before_request(revisar_pedido)
    app.after_request(cabeceras)
