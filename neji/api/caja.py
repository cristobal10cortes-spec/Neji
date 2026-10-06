"""Turnos de caja: apertura, entradas/salidas de efectivo y corte."""

from flask import jsonify

from ..auth import solo_admin, usuario_actual
from ..db import filas, get_db, transaccion
from ..servicios import caja as svc
from ..validar import ErrorNegocio, entero, texto
from . import bp, datos_json, rango_fechas, sin_costos


@bp.get("/caja/<int:caja_id>/turno")
def turno_actual(caja_id):
    con = get_db()
    turno = svc.turno_abierto(con, caja_id)
    return jsonify(turno=sin_costos(svc.resumen_turno(con, turno["id"])) if turno else None)


@bp.post("/caja/<int:caja_id>/abrir")
def abrir(caja_id):
    fondo = entero(datos_json().get("fondo_inicial") or 0, "dinero inicial", minimo=0)
    con = get_db()
    with transaccion(con):
        turno_id = svc.abrir_turno(con, caja_id, usuario_actual()["id"], fondo)
    return jsonify(turno=sin_costos(svc.resumen_turno(con, turno_id))), 201


@bp.post("/caja/<int:caja_id>/movimiento")
def movimiento(caja_id):
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        turno = svc.exigir_turno(con, caja_id)
        svc.registrar_movimiento(
            con, turno["id"], datos.get("tipo"), entero(datos.get("monto"), "monto", minimo=1),
            texto(datos, "concepto", requerido=True, nombre="el concepto", max_largo=120),
            usuario_actual()["id"])
    return jsonify(turno=sin_costos(svc.resumen_turno(con, turno["id"]))), 201


@bp.post("/caja/<int:caja_id>/cerrar")
def cerrar(caja_id):
    datos = datos_json()
    contado = entero(datos.get("efectivo_contado"), "efectivo contado", minimo=0)
    con = get_db()
    with transaccion(con):
        turno_id = svc.cerrar_turno(con, caja_id, usuario_actual()["id"], contado, texto(datos, "nota"))
    return jsonify(turno=sin_costos(svc.resumen_turno(con, turno_id)))


@bp.get("/turnos")
@solo_admin
def historial_turnos():
    _, _, inicio, fin = rango_fechas()
    return jsonify(filas(get_db().execute(
        """SELECT t.*, c.nombre AS caja, u.nombre AS usuario,
                  (SELECT COALESCE(SUM(total), 0) FROM ventas WHERE turno_id = t.id) AS total_ventas,
                  (SELECT COUNT(*) FROM ventas WHERE turno_id = t.id) AS n_ventas
           FROM turnos t JOIN cajas c ON c.id = t.caja_id JOIN usuarios u ON u.id = t.usuario_id
           WHERE t.abierto BETWEEN ? AND ? ORDER BY t.id DESC""", (inicio, fin))))


@bp.get("/turnos/<int:turno_id>")
def ver_turno(turno_id):
    con = get_db()
    resumen = svc.resumen_turno(con, turno_id)
    usuario = usuario_actual()
    if usuario["rol"] != "admin" and resumen["usuario_id"] != usuario["id"]:
        raise ErrorNegocio("Solo puedes ver tus propios turnos.", status=403)
    return jsonify(sin_costos(resumen))
