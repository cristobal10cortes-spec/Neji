"""Entradas, salidas y ajustes de inventario; compras sugeridas; kardex general."""

import math
from datetime import date, timedelta

from flask import jsonify, request

from ..auth import solo_admin, usuario_actual
from ..db import ahora, config_activa, filas, get_db, transaccion
from ..validar import ErrorNegocio, booleano, cantidad, entero, texto
from ..servicios.inventario import mover_existencia
from . import bp, datos_json, rango_fechas


@bp.post("/inventario/movimiento")
@solo_admin
def movimiento_inventario():
    datos = datos_json()
    tipo = datos.get("tipo")
    if tipo not in ("entrada", "salida", "ajuste"):
        raise ErrorNegocio("El movimiento debe ser entrada, salida o ajuste.")
    con = get_db()
    with transaccion(con):
        producto = con.execute("SELECT * FROM productos WHERE id = ? AND activo = 1",
                               (entero(datos.get("producto_id"), "producto"),)).fetchone()
        if producto is None:
            raise ErrorNegocio("Producto no encontrado.", status=404)
        if not producto["usa_inventario"]:
            raise ErrorNegocio("Este producto no lleva control de inventario.")
        if tipo == "ajuste":
            nueva = cantidad(datos.get("cantidad"), "existencia real", minimo=0)
            delta = round(nueva - producto["existencia"], 3)
            if delta == 0:
                raise ErrorNegocio("La existencia ya es esa; no hay nada que ajustar.")
        else:
            delta = cantidad(datos.get("cantidad"), "cantidad", positiva=True)
            if tipo == "salida":
                delta = -delta
        if producto["tipo_venta"] == "unidad" and delta != int(delta):
            raise ErrorNegocio("Este producto se maneja por unidad: la cantidad debe ser entera.")

        costo = None
        if tipo == "entrada" and datos.get("costo_unitario") not in (None, ""):
            costo = entero(datos["costo_unitario"], "costo unitario", minimo=0)
            if booleano(datos.get("actualizar_costo", True)) and costo != producto["precio_costo"]:
                con.execute("UPDATE productos SET precio_costo = ?, actualizado = ? WHERE id = ?",
                            (costo, ahora(), producto["id"]))

        nueva = mover_existencia(
            con, producto, delta, tipo, usuario_actual()["id"],
            referencia=texto(datos, "referencia", max_largo=80), nota=texto(datos, "nota"),
            costo_unitario=costo,
            permitir_negativo=tipo != "salida" or config_activa(con, "permitir_stock_negativo"))
    return jsonify(existencia=nueva)


@bp.get("/inventario/sugeridos")
@solo_admin
def compras_sugeridas():
    """Productos en o bajo el mínimo, con lo vendido en 30 días y cuánto conviene comprar."""
    desde = (date.today() - timedelta(days=30)).isoformat() + " 00:00:00"
    productos = filas(get_db().execute(
        """SELECT p.id, p.codigo, p.descripcion, p.existencia, p.minimo, p.maximo, p.precio_costo,
                  p.tipo_venta, d.nombre AS departamento,
                  COALESCE((SELECT SUM(vi.cantidad - vi.cantidad_devuelta)
                            FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id
                            WHERE vi.producto_id = p.id AND v.fecha >= ?), 0) AS vendidos_30d
           FROM productos p LEFT JOIN departamentos d ON d.id = p.departamento_id
           WHERE p.activo = 1 AND p.usa_inventario = 1 AND p.existencia <= p.minimo
           ORDER BY d.nombre, p.descripcion""", (desde,)))
    for p in productos:
        objetivo = p["maximo"] if p["maximo"] else max(p["minimo"] * 2, p["vendidos_30d"])
        sugerido = max(objetivo - p["existencia"], 0)
        if p["tipo_venta"] == "unidad":
            sugerido = math.ceil(sugerido)
        p["sugerido"] = round(sugerido, 3)
        p["costo_estimado"] = round(p["sugerido"] * p["precio_costo"])
    return jsonify(productos)


@bp.get("/inventario/movimientos")
@solo_admin
def movimientos_inventario():
    _, _, inicio, fin = rango_fechas()
    condiciones, params = ["m.fecha BETWEEN ? AND ?"], [inicio, fin]
    if request.args.get("tipo"):
        condiciones.append("m.tipo = ?")
        params.append(request.args["tipo"])
    if request.args.get("producto_id"):
        condiciones.append("m.producto_id = ?")
        params.append(entero(request.args["producto_id"], "producto"))
    return jsonify(filas(get_db().execute(
        f"""SELECT m.*, p.codigo, p.descripcion, u.nombre AS usuario
            FROM movimientos_inventario m
            JOIN productos p ON p.id = m.producto_id
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE {' AND '.join(condiciones)} ORDER BY m.id DESC LIMIT 1000""", params)))


@bp.get("/inventario/resumen")
@solo_admin
def resumen_inventario():
    r = get_db().execute(
        """SELECT COUNT(*) AS productos,
                  COALESCE(SUM(CASE WHEN usa_inventario = 1 AND existencia > 0
                               THEN existencia * precio_costo END), 0) AS valor_costo,
                  COALESCE(SUM(CASE WHEN usa_inventario = 1 AND existencia > 0
                               THEN existencia * precio_venta END), 0) AS valor_venta,
                  COALESCE(SUM(usa_inventario = 1 AND existencia <= 0), 0) AS agotados,
                  COALESCE(SUM(usa_inventario = 1 AND existencia <= minimo), 0) AS bajo_minimo
           FROM productos WHERE activo = 1""").fetchone()
    datos = dict(r)
    datos["valor_costo"] = round(datos["valor_costo"])
    datos["valor_venta"] = round(datos["valor_venta"])
    return jsonify(datos)
