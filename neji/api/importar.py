"""Importación de datos desde otros sistemas (por ahora CORAND.ERP / Easy Pharma)."""

import os
import tempfile

from flask import current_app, jsonify, request

from .. import respaldos
from ..auth import solo_admin, usuario_actual
from ..db import ahora, get_db, leer_config
from ..servicios import importar_corand
from ..validar import ErrorNegocio, booleano
from . import bp


@bp.post("/importar/corand")
@solo_admin
def importar_desde_corand():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        raise ErrorNegocio("Adjunta el archivo corand_erp_pro.db.")
    opciones = {k: booleano(request.form.get(k, "1")) for k in importar_corand.OPCIONES}
    con = get_db()
    # Respaldo antes de importar, por si hay que volver atrás.
    respaldos.crear_respaldo(current_app.config["DATABASE"], current_app.config["RESPALDOS"],
                             int(leer_config(con).get("respaldos_mantener") or 10))
    con.execute("UPDATE config SET valor = ? WHERE clave = 'ultimo_respaldo'", (ahora(),))
    descriptor, ruta = tempfile.mkstemp(suffix=".db", dir=current_app.config["DATOS"])
    try:
        with os.fdopen(descriptor, "wb") as destino:
            archivo.save(destino)
        resumen = importar_corand.importar(con, ruta, usuario_actual()["id"], opciones)
    finally:
        os.remove(ruta)
    return jsonify(resumen)
