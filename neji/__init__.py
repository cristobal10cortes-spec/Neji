"""Neji POS: punto de venta para negocios en Chile."""

import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from . import db, respaldos
from .validar import ErrorNegocio

RAIZ = Path(__file__).resolve().parent.parent
REVISAR_RESPALDO_CADA = 3600  # segundos


def _clave_secreta(carpeta):
    ruta = Path(carpeta) / ".clave_secreta"
    if not ruta.exists():
        ruta.write_text(secrets.token_hex(32), encoding="utf-8")
    return ruta.read_text(encoding="utf-8").strip()


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    datos = os.environ.get("NEJI_DATOS") or str(RAIZ / "datos")
    app.config.update(
        DATOS=datos,
        DATABASE=os.path.join(datos, "neji.db"),
        RESPALDOS=os.path.join(datos, "respaldos"),
        RESPALDO_AUTOMATICO=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=14),
        SESSION_COOKIE_SAMESITE="Lax",
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)
    os.makedirs(app.config["DATOS"], exist_ok=True)
    app.secret_key = app.config.get("SECRET_KEY") or _clave_secreta(app.config["DATOS"])
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    db.init_app(app)

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
        return jsonify(error="Ocurrió un error inesperado. Revisa la consola del servidor."), 500

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
