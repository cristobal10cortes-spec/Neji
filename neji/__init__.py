"""Neji POS: punto de venta para negocios en Chile."""

import os
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from . import db, proteccion, respaldos, seguridad
from .validar import ErrorNegocio

RAIZ = Path(__file__).resolve().parent.parent
REVISAR_RESPALDO_CADA = 3600  # segundos


def _activado(variable):
    return (os.environ.get(variable) or "").strip().lower() in ("1", "si", "sí", "true", "yes")


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    datos = os.environ.get("NEJI_DATOS") or str(RAIZ / "datos")
    app.config.update(
        # En internet (NEJI_WEB=1): detrás del proxy HTTPS del hosting, cookie solo por HTTPS y la
        # primera configuración pide el código de instalación (NEJI_CODIGO_INSTALACION).
        WEB=_activado("NEJI_WEB"),
        MARCA=(os.environ.get("NEJI_MARCA") or "").strip(),
        CODIGO_INSTALACION=(os.environ.get("NEJI_CODIGO_INSTALACION") or "").strip(),
        SECRET_KEY=os.environ.get("NEJI_CLAVE_SECRETA") or None,
        DATOS=datos,
        DATABASE=os.path.join(datos, "neji.db"),
        RESPALDOS=os.path.join(datos, "respaldos"),
        RESPALDO_AUTOMATICO=True,
        SII_ENVIO_AUTOMATICO=True,   # el hilo que manda al SII las boletas emitidas (si está activo)
        PERMANENT_SESSION_LIFETIME=timedelta(hours=14),
        SESSION_COOKIE_SAMESITE="Lax",
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=200 * 1024 * 1024,  # archivos a importar
    )
    if config:
        app.config.update(config)
    if app.config["WEB"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True
    os.makedirs(app.config["DATOS"], exist_ok=True)
    app.secret_key = app.config.get("SECRET_KEY") or proteccion.clave_secreta(app.config["DATOS"], app.logger)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    db.init_app(app)
    seguridad.init_app(app)

    from .api import bp as api_bp
    app.register_blueprint(api_bp)

    @app.get("/")
    def inicio():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(ErrorNegocio)
    def _error_negocio(error):
        return jsonify(error=error.mensaje, codigo=error.codigo), error.status

    @app.errorhandler(HTTPException)
    def _error_http(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def _error_inesperado(error):
        app.logger.exception("Error inesperado")
        return jsonify(error="Ocurrió un error inesperado. El detalle quedó en el registro de Neji "
                             "(neji.log en la carpeta de datos, o la consola si se inició con run.py)."), 500

    if app.config["SII_ENVIO_AUTOMATICO"] and not app.config.get("TESTING"):
        from .sii.servicio import Enviador

        app.extensions["sii_enviador"] = Enviador(app.config["DATABASE"], app.secret_key).iniciar()

    if app.config["RESPALDO_AUTOMATICO"]:
        ultima_revision = {"t": 0.0}

        @app.before_request
        def _respaldo_diario():
            if time.monotonic() - ultima_revision["t"] < REVISAR_RESPALDO_CADA:
                return
            ultima_revision["t"] = time.monotonic()
            try:
                respaldos.respaldo_automatico(app)
            except Exception:
                app.logger.exception("No se pudo crear el respaldo automático")

    return app
