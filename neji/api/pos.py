"""Máquina POS integrada: configuración por caja y cobros (ver neji/pos.py)."""

from flask import current_app, jsonify

from .. import pos
from ..auth import solo_admin, usuario_actual
from ..db import get_db, transaccion
from ..validar import entero
from . import bp, datos_json


@bp.get("/pos")
@solo_admin
def ver_pos():
    con = get_db()
    return jsonify(proveedores=pos.proveedores(), cajas=pos.configuracion(con))


@bp.put("/pos/cajas/<int:caja_id>")
@solo_admin
def guardar_pos(caja_id):
    con = get_db()
    with transaccion(con):
        pos.guardar(con, caja_id, datos_json(), current_app.secret_key)
    return ver_pos()


@bp.post("/pos/cobros")
def iniciar_cobro():
    """Manda el monto a la máquina de la caja. Lo usa el cobro de la venta (y la prueba en Configuración)."""
    datos = datos_json()
    con = get_db()
    cobro = pos.iniciar(con, entero(datos.get("caja_id"), "caja", minimo=1),
                        entero(datos.get("monto"), "monto", minimo=1), str(datos.get("metodo") or ""),
                        usuario_actual(), current_app.secret_key)
    return jsonify(cobro), 201


@bp.get("/pos/cobros/<int:cobro_id>")
def consultar_cobro(cobro_id):
    return jsonify(pos.consultar(get_db(), cobro_id, current_app.secret_key))


@bp.post("/pos/cobros/<int:cobro_id>/cancelar")
def cancelar_cobro(cobro_id):
    return jsonify(pos.cancelar(get_db(), cobro_id, current_app.secret_key))
