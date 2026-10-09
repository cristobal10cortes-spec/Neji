"""Turnos de caja: apertura, entradas/salidas de efectivo y corte."""

from flask import jsonify

from ..auth import con_permiso, tiene_permiso, usuario_actual
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
@con_permiso("movimientos_caja")
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
@con_permiso("corte")
def cerrar(caja_id):
    datos = datos_json()
    contado = entero(datos.get("efectivo_contado"), "efectivo contado", minimo=0)
    con = get_db()
    with transaccion(con):
        turno_id = svc.cerrar_turno(con, caja_id, usuario_actual()["id"], contado, texto(datos, "nota"))
    return jsonify(turno=sin_costos(svc.resumen_turno(con, turno_id)))


@bp.get("/turnos")
@con_permiso("corte_general")
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
    if not tiene_permiso(usuario, "corte_general") and resumen["usuario_id"] != usuario["id"]:
        raise ErrorNegocio("Solo puedes ver tus propios turnos.", status=403)
    return jsonify(sin_costos(resumen))


# --- Corte general (desde la caja principal) ----------------------------------------------------

@bp.get("/caja/turnos-abiertos")
@con_permiso("corte_general")
def turnos_abiertos():
    return jsonify(sin_costos(svc.turnos_abiertos(get_db())))


@bp.post("/caja/<int:caja_id>/corte-general")
@con_permiso("corte_general")
def corte_general(caja_id):
    datos = datos_json()
    cortes = datos.get("cortes")
    if not isinstance(cortes, list):
        raise ErrorNegocio("Indica los turnos a cortar.")
    leidos = []
    for c in cortes:
        if not isinstance(c, dict):
            raise ErrorNegocio("Indica los turnos a cortar.")
        leidos.append({"turno_id": entero(c.get("turno_id"), "turno", minimo=1),
                       "efectivo_contado": entero(c.get("efectivo_contado"), "efectivo contado", minimo=0)})
    con = get_db()
    with transaccion(con):
        corte_id = svc.corte_general(con, caja_id, usuario_actual()["id"], leidos,
                                     texto(datos, "nota", max_largo=500))
    return jsonify(sin_costos(svc.resumen_corte_general(con, corte_id))), 201


@bp.get("/cortes-generales")
@con_permiso("corte_general")
def historial_cortes_generales():
    _, _, inicio, fin = rango_fechas()
    return jsonify(filas(get_db().execute(
        """SELECT g.*, c.nombre AS caja, u.nombre AS usuario,
                  (SELECT COUNT(*) FROM turnos WHERE corte_general_id = g.id) AS n_turnos,
                  (SELECT COALESCE(SUM(diferencia), 0) FROM turnos WHERE corte_general_id = g.id) AS diferencia,
                  (SELECT COALESCE(SUM(total), 0) FROM ventas
                    WHERE turno_id IN (SELECT id FROM turnos WHERE corte_general_id = g.id)) AS total_ventas
           FROM cortes_generales g JOIN cajas c ON c.id = g.caja_id JOIN usuarios u ON u.id = g.usuario_id
           WHERE g.fecha BETWEEN ? AND ? ORDER BY g.id DESC""", (inicio, fin))))


@bp.get("/cortes-generales/<int:corte_id>")
@con_permiso("corte_general")
def ver_corte_general(corte_id):
    return jsonify(sin_costos(svc.resumen_corte_general(get_db(), corte_id)))
