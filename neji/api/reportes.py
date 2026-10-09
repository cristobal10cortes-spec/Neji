"""Reportes de ventas para el administrador."""

import csv
import io

from flask import Response, jsonify

from ..auth import con_permiso
from ..db import filas, get_db
from ..servicios.caja import SQL_DEPARTAMENTO_ITEM, SQL_GANANCIA_ITEM
from ..validar import celda_csv, numero_texto
from . import bp, rango_fechas

# Importe neto de devoluciones y con el descuento del ticket repartido.
SQL_IMPORTE_ITEM = """
    (vi.importe * (vi.cantidad - vi.cantidad_devuelta) / vi.cantidad)
      * (CASE WHEN v.subtotal > 0 THEN 1.0 * v.total / v.subtotal ELSE 1 END)
"""


@bp.get("/reportes/ventas")
@con_permiso("reportes")
def reporte_ventas():
    desde, hasta, inicio, fin = rango_fechas()
    con = get_db()
    rango = (inicio, fin)

    r = dict(con.execute(
        """SELECT COUNT(*) AS n_ventas, COALESCE(SUM(total), 0) AS bruto,
                  COALESCE(SUM(devuelto), 0) AS devuelto, COALESCE(SUM(descuento), 0) AS descuentos,
                  COALESCE(SUM(neto), 0) AS neto, COALESCE(SUM(iva), 0) AS iva,
                  COALESCE(SUM(exento), 0) AS exento, COALESCE(SUM(redondeo), 0) AS redondeo
           FROM ventas WHERE fecha BETWEEN ? AND ?""", rango).fetchone())
    r["total"] = r["bruto"] - r["devuelto"]
    r["ticket_promedio"] = round(r["bruto"] / r["n_ventas"]) if r["n_ventas"] else 0
    ganancia = con.execute(
        f"""SELECT COALESCE(SUM({SQL_GANANCIA_ITEM}), 0) FROM venta_items vi
            JOIN ventas v ON v.id = vi.venta_id WHERE v.fecha BETWEEN ? AND ?""", rango).fetchone()[0]
    r["ganancia"] = round(ganancia)
    r["margen"] = round(100 * ganancia / r["total"], 1) if r["total"] else 0

    por_metodo = filas(con.execute(
        """SELECT p.metodo, SUM(p.monto) AS total, COUNT(DISTINCT p.venta_id) AS n_ventas
           FROM venta_pagos p JOIN ventas v ON v.id = p.venta_id
           WHERE v.fecha BETWEEN ? AND ? GROUP BY p.metodo ORDER BY 2 DESC""", rango))
    por_dia = filas(con.execute(
        """SELECT substr(fecha, 1, 10) AS dia, COUNT(*) AS n_ventas, SUM(total - devuelto) AS total
           FROM ventas WHERE fecha BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""", rango))
    por_hora = filas(con.execute(
        """SELECT CAST(substr(fecha, 12, 2) AS INTEGER) AS hora, COUNT(*) AS n_ventas,
                  SUM(total - devuelto) AS total
           FROM ventas WHERE fecha BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""", rango))
    por_departamento = filas(con.execute(
        f"""SELECT {SQL_DEPARTAMENTO_ITEM} AS departamento,
                   ROUND(SUM({SQL_IMPORTE_ITEM})) AS total, ROUND(SUM({SQL_GANANCIA_ITEM})) AS ganancia
            FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id
            LEFT JOIN departamentos d ON d.id = vi.departamento_id
            WHERE v.fecha BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC""", rango))
    por_cajero = filas(con.execute(
        """SELECT u.nombre AS cajero, COUNT(*) AS n_ventas, SUM(v.total - v.devuelto) AS total
           FROM ventas v JOIN usuarios u ON u.id = v.usuario_id
           WHERE v.fecha BETWEEN ? AND ? GROUP BY u.id ORDER BY 3 DESC""", rango))
    top_productos = filas(con.execute(
        f"""SELECT vi.codigo,
                   CASE WHEN vi.receta_id IS NOT NULL THEN 'Recetas magistrales' ELSE vi.descripcion END
                     AS descripcion,
                   SUM(vi.cantidad - vi.cantidad_devuelta) AS cantidad,
                   ROUND(SUM({SQL_IMPORTE_ITEM})) AS total, ROUND(SUM({SQL_GANANCIA_ITEM})) AS ganancia
            FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id
            WHERE v.fecha BETWEEN ? AND ?
            GROUP BY CASE WHEN vi.receta_id IS NOT NULL THEN 'receta'
                          WHEN vi.producto_id IS NOT NULL THEN 'p' || vi.producto_id
                          ELSE 'c' || vi.descripcion END
            HAVING cantidad > 0 ORDER BY total DESC LIMIT 30""", rango))

    return jsonify(desde=desde, hasta=hasta, resumen=r, por_metodo=por_metodo, por_dia=por_dia,
                   por_hora=por_hora, por_departamento=por_departamento, por_cajero=por_cajero,
                   top_productos=top_productos)


@bp.get("/reportes/ventas.csv")
@con_permiso("reportes")
def exportar_ventas():
    desde, hasta, inicio, fin = rango_fechas()
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(["folio", "fecha", "caja", "cajero", "cliente", "codigo", "descripcion",
                       "cantidad", "precio_unitario", "tipo_precio", "importe", "cantidad_devuelta",
                       "total_ticket", "estado"])
    for r in get_db().execute(
            """SELECT v.folio, v.fecha, c.nombre AS caja, u.nombre AS cajero, cl.nombre AS cliente,
                      vi.codigo, vi.descripcion, vi.cantidad, vi.precio_unitario, vi.tipo_precio,
                      vi.importe, vi.cantidad_devuelta, v.total, v.estado
               FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id
               JOIN cajas c ON c.id = v.caja_id JOIN usuarios u ON u.id = v.usuario_id
               LEFT JOIN clientes cl ON cl.id = v.cliente_id
               WHERE v.fecha BETWEEN ? AND ? ORDER BY v.folio, vi.id""", (inicio, fin)):
        escritor.writerow([
            r["folio"], r["fecha"], celda_csv(r["caja"]), celda_csv(r["cajero"]), celda_csv(r["cliente"]),
            celda_csv(r["codigo"]), celda_csv(r["descripcion"]), numero_texto(r["cantidad"]),
            r["precio_unitario"],
            r["tipo_precio"], r["importe"], numero_texto(r["cantidad_devuelta"]),
            r["total"], r["estado"],
        ])
    nombre = f"ventas_{desde}_{hasta}.csv"
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})
