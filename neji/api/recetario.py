"""Recetario magistral: formas farmacéuticas, calculadora y libro de recetas."""

import csv
import io
import json

from flask import Response, jsonify, request

from ..auth import solo_admin, usuario_actual
from ..chile import formatear_rut, validar_rut
from ..db import fila, filas, get_db, sin_acentos, transaccion
from ..servicios import recetario as svc
from ..validar import ErrorNegocio, booleano, celda_csv, texto
from . import bp, datos_json, rango_fechas

NOMBRE_UNIDAD = {"unidad": "unidad", "g": "gramo", "ml": "ml"}


def _leer_forma(datos):
    unidad = datos.get("unidad") or "unidad"
    if unidad not in svc.UNIDADES_FORMA:
        raise ErrorNegocio("La medida debe ser unidad (cápsulas, papelillos...), g o ml.")
    sugerida = svc.numero(datos.get("cantidad_sugerida") or 30, "cantidad sugerida", positivo=True,
                          maximo=svc.MAX_CANTIDAD, decimales=3)
    if unidad == "unidad" and sugerida != sugerida.to_integral_value():
        raise ErrorNegocio("La cantidad sugerida debe ser entera cuando se mide en unidades.")
    return {
        "nombre": texto(datos, "nombre", requerido=True, nombre="el nombre", max_largo=60),
        "unidad": unidad,
        "nombre_unidad": (texto(datos, "nombre_unidad", max_largo=30) or NOMBRE_UNIDAD[unidad]).lower(),
        "precio_base": float(svc.numero(datos.get("precio_base") or 0, "valor base", minimo=0,
                                        maximo=svc.MAX_PRECIO)),
        "precio_unidad": float(svc.numero(datos.get("precio_unidad") or 0, "precio por unidad",
                                          minimo=0, maximo=svc.MAX_PRECIO, decimales=6)),
        "cantidad_sugerida": float(sugerida),
        "activa": 1 if booleano(datos.get("activa", True)) else 0,
    }


@bp.get("/recetario/formas")
def listar_formas():
    todas = booleano(request.args.get("todas", ""))
    return jsonify(filas(get_db().execute(
        f"SELECT * FROM formas_magistrales {'' if todas else 'WHERE activa = 1'} ORDER BY nombre")))


@bp.post("/recetario/formas")
@solo_admin
def crear_forma():
    datos = _leer_forma(datos_json())
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM formas_magistrales WHERE nombre = ?", (datos["nombre"],)).fetchone():
            raise ErrorNegocio("Ya existe una forma farmacéutica con ese nombre.")
        nuevo = con.execute(
            f"INSERT INTO formas_magistrales ({', '.join(datos)}) VALUES ({', '.join('?' for _ in datos)})",
            list(datos.values())).lastrowid
    return jsonify(fila(con.execute("SELECT * FROM formas_magistrales WHERE id = ?", (nuevo,)).fetchone())), 201


@bp.put("/recetario/formas/<int:forma_id>")
@solo_admin
def editar_forma(forma_id):
    datos = _leer_forma(datos_json())
    con = get_db()
    with transaccion(con):
        if not con.execute("SELECT 1 FROM formas_magistrales WHERE id = ?", (forma_id,)).fetchone():
            raise ErrorNegocio("Forma farmacéutica no encontrada.", status=404)
        if con.execute("SELECT 1 FROM formas_magistrales WHERE nombre = ? AND id <> ?",
                       (datos["nombre"], forma_id)).fetchone():
            raise ErrorNegocio("Ya existe otra forma farmacéutica con ese nombre.")
        con.execute(f"UPDATE formas_magistrales SET {', '.join(f'{k} = ?' for k in datos)} WHERE id = ?",
                    list(datos.values()) + [forma_id])
    return jsonify(fila(con.execute("SELECT * FROM formas_magistrales WHERE id = ?", (forma_id,)).fetchone()))


@bp.post("/recetario/calcular")
def calcular_receta():
    return jsonify(svc.calcular(get_db(), datos_json()))


@bp.post("/recetario/recetas")
def crear_receta():
    con = get_db()
    receta_id = svc.crear(con, datos_json(), usuario_actual())
    return jsonify(svc.obtener(con, receta_id)), 201


def _filtro_recetas():
    condiciones, params = [], []
    q = (request.args.get("q") or "").strip()
    rut = formatear_rut(q) if validar_rut(q) else None
    if q.isdecimal() and q.isascii() and len(q) <= 9:
        condiciones.append("(r.folio = ? OR r.rut_paciente = ?)")
        params += [int(q), rut]
    elif rut:
        condiciones.append("r.rut_paciente = ?")
        params.append(rut)
    else:
        _, _, inicio, fin = rango_fechas()
        condiciones.append("r.fecha BETWEEN ? AND ?")
        params += [inicio, fin]
        for palabra in q.split()[:6]:
            condiciones.append("(sin_acentos(r.paciente) LIKE ? OR sin_acentos(r.medico) LIKE ? "
                               "OR r.rut_paciente LIKE ?)")
            params += [f"%{sin_acentos(palabra)}%"] * 2 + [f"%{palabra}%"]
    estado = request.args.get("estado")
    if estado:
        if estado not in ("pendiente", "vendida", "anulada"):
            raise ErrorNegocio("Estado inválido.")
        condiciones.append("r.estado = ?")
        params.append(estado)
    return " AND ".join(condiciones), params


@bp.get("/recetario/recetas")
def listar_recetas():
    where, params = _filtro_recetas()
    recetas = filas(get_db().execute(
        f"""SELECT r.id, r.folio, r.fecha, r.forma, r.unidad, r.nombre_unidad, r.cantidad, r.total,
                   r.estado, r.paciente, r.medico, u.nombre AS usuario, v.folio AS venta_folio
            FROM recetas_magistrales r JOIN usuarios u ON u.id = r.usuario_id
            LEFT JOIN ventas v ON v.id = r.venta_id
            WHERE {where} ORDER BY r.id DESC LIMIT 1000""", params))
    for r in recetas:
        r["descripcion"] = svc.describir(r)
    return jsonify(recetas)


@bp.get("/recetario/recetas/<int:receta_id>")
def ver_receta(receta_id):
    return jsonify(svc.obtener(get_db(), receta_id))


@bp.post("/recetario/recetas/<int:receta_id>/anular")
def anular_receta(receta_id):
    con = get_db()
    svc.anular(con, receta_id)
    return jsonify(svc.obtener(con, receta_id))


def _composicion(componentes):
    partes = []
    for c in componentes:
        partes.append(f"{c['nombre']} {svc.numero_texto(c['dosis'])} {c['unidad']}")
    return " + ".join(partes)


@bp.get("/recetario/recetas.csv")
@solo_admin
def exportar_recetas():
    """Libro recetario en CSV (para respaldo o fiscalización)."""
    where, params = _filtro_recetas()
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(["folio", "fecha", "paciente", "rut_paciente", "medico", "forma", "cantidad",
                       "unidad", "composicion_por_unidad", "indicaciones", "neto", "iva", "total",
                       "estado", "folio_venta", "preparo"])
    for r in get_db().execute(
            f"""SELECT r.*, u.nombre AS usuario, v.folio AS venta_folio
                FROM recetas_magistrales r JOIN usuarios u ON u.id = r.usuario_id
                LEFT JOIN ventas v ON v.id = r.venta_id WHERE {where} ORDER BY r.folio""", params):
        escritor.writerow([
            r["folio"], r["fecha"], celda_csv(r["paciente"]), r["rut_paciente"] or "", celda_csv(r["medico"]),
            celda_csv(r["forma"]), svc.numero_texto(r["cantidad"]), celda_csv(r["nombre_unidad"]),
            celda_csv(_composicion(json.loads(r["componentes"]))), celda_csv(r["indicaciones"]),
            r["neto"], r["iva"], r["total"], r["estado"], r["venta_folio"] or "", celda_csv(r["usuario"]),
        ])
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=libro_recetario.csv"})
