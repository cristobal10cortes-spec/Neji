"""Ventas, devoluciones y cotizaciones."""

import json

from flask import jsonify, request

from ..auth import con_permiso, usuario_actual
from ..db import fila, filas, get_db, transaccion
from ..servicios import ventas as svc
from ..validar import ErrorNegocio, entero
from . import bp, datos_json, rango_fechas, sin_costos


@bp.post("/ventas")
def crear_venta():
    con = get_db()
    venta_id = svc.registrar_venta(con, datos_json(), usuario_actual())
    return jsonify(sin_costos(svc.obtener_venta(con, venta_id))), 201


@bp.get("/ventas")
def listar_ventas():
    con = get_db()
    condiciones, params = [], []
    if request.args.get("folio"):
        condiciones.append("v.folio = ?")
        params.append(entero(request.args["folio"], "folio"))
    else:
        _, _, inicio, fin = rango_fechas()
        condiciones.append("v.fecha BETWEEN ? AND ?")
        params += [inicio, fin]
    for campo in ("cliente_id", "caja_id", "usuario_id"):
        if request.args.get(campo):
            condiciones.append(f"v.{campo} = ?")
            params.append(entero(request.args[campo], campo))
    ventas = filas(con.execute(
        f"""SELECT v.id, v.folio, v.fecha, v.total, v.devuelto, v.estado, v.cliente_id,
                   c.nombre AS caja, u.nombre AS usuario, cl.nombre AS cliente,
                   (SELECT GROUP_CONCAT(metodo, ',') FROM venta_pagos WHERE venta_id = v.id) AS metodos,
                   (SELECT COUNT(*) FROM venta_items WHERE venta_id = v.id) AS n_items
            FROM ventas v JOIN cajas c ON c.id = v.caja_id JOIN usuarios u ON u.id = v.usuario_id
            LEFT JOIN clientes cl ON cl.id = v.cliente_id
            WHERE {' AND '.join(condiciones)} ORDER BY v.id DESC LIMIT 1000""", params))
    return jsonify(ventas)


@bp.get("/ventas/<int:venta_id>")
def ver_venta(venta_id):
    return jsonify(sin_costos(svc.obtener_venta(get_db(), venta_id)))


@bp.get("/ventas/folio/<int:folio>")
def venta_por_folio(folio):
    con = get_db()
    row = con.execute("SELECT id FROM ventas WHERE folio = ?", (folio,)).fetchone()
    if row is None:
        raise ErrorNegocio(f"No existe la venta con folio {folio}.", status=404)
    return jsonify(sin_costos(svc.obtener_venta(con, row["id"])))


@bp.post("/ventas/<int:venta_id>/devolucion")
@con_permiso("cajero_puede_devolver")
def devolver_venta(venta_id):
    con = get_db()
    svc.devolver(con, venta_id, datos_json(), usuario_actual())
    return jsonify(sin_costos(svc.obtener_venta(con, venta_id))), 201


# --- Cotizaciones ------------------------------------------------------------

def _cotizacion(con, cotizacion_id):
    c = fila(con.execute(
        """SELECT q.*, u.nombre AS usuario, cl.rut AS cliente_rut FROM cotizaciones q
           JOIN usuarios u ON u.id = q.usuario_id LEFT JOIN clientes cl ON cl.id = q.cliente_id
           WHERE q.id = ?""", (cotizacion_id,)).fetchone())
    if c is None:
        raise ErrorNegocio("Cotización no encontrada.", status=404)
    c["items"] = json.loads(c["items"])
    return c


@bp.post("/cotizaciones")
def crear_cotizacion():
    con = get_db()
    cotizacion_id = svc.crear_cotizacion(con, datos_json(), usuario_actual())
    return jsonify(sin_costos(_cotizacion(con, cotizacion_id))), 201


@bp.get("/cotizaciones")
def listar_cotizaciones():
    condiciones, params = [], []
    estado = request.args.get("estado")
    if estado:
        condiciones.append("q.estado = ?")
        params.append(estado)
    if request.args.get("q"):
        condiciones.append("(q.cliente_nombre LIKE ? OR CAST(q.folio AS TEXT) = ?)")
        params += [f"%{request.args['q']}%", request.args["q"]]
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return jsonify(filas(get_db().execute(
        f"""SELECT q.id, q.folio, q.fecha, q.cliente_nombre, q.total, q.estado, u.nombre AS usuario
            FROM cotizaciones q JOIN usuarios u ON u.id = q.usuario_id {where}
            ORDER BY q.id DESC LIMIT 300""", params)))


@bp.get("/cotizaciones/<int:cotizacion_id>")
def ver_cotizacion(cotizacion_id):
    return jsonify(sin_costos(_cotizacion(get_db(), cotizacion_id)))


@bp.post("/cotizaciones/<int:cotizacion_id>/cancelar")
def cancelar_cotizacion(cotizacion_id):
    con = get_db()
    with transaccion(con):
        if con.execute("UPDATE cotizaciones SET estado = 'cancelada' WHERE id = ? AND estado = 'vigente'",
                       (cotizacion_id,)).rowcount == 0:
            raise ErrorNegocio("Solo se pueden cancelar cotizaciones vigentes.")
    return jsonify(sin_costos(_cotizacion(con, cotizacion_id)))
