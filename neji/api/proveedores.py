"""Proveedores y sus facturas por pagar (permiso «proveedores»)."""

from flask import jsonify, request

from ..auth import con_permiso, usuario_actual
from ..db import get_db, transaccion
from ..servicios import proveedores as svc
from ..validar import entero
from . import bp, datos_json


@bp.get("/proveedores")
@con_permiso("proveedores")
def listar_proveedores():
    con = get_db()
    return jsonify({"proveedores": svc.listar_proveedores(con), "sugeridos": svc.sugeridos(con),
                    "resumen": svc.resumen(con), "tipos": svc.TIPOS, "medios": svc.MEDIOS})


@bp.post("/proveedores")
@con_permiso("proveedores")
def crear_proveedor():
    con = get_db()
    with transaccion(con):
        proveedor_id = svc.crear_proveedor(con, datos_json())
    return jsonify(dict(svc.exigir_proveedor(con, proveedor_id))), 201


@bp.put("/proveedores/<int:proveedor_id>")
@con_permiso("proveedores")
def editar_proveedor(proveedor_id):
    con = get_db()
    with transaccion(con):
        svc.exigir_proveedor(con, proveedor_id)
        p = svc.leer_proveedor(con, datos_json(), proveedor_id)
        con.execute(f"UPDATE proveedores SET {', '.join(f'{k} = ?' for k in p)} WHERE id = ?",
                    list(p.values()) + [proveedor_id])
    return jsonify(dict(svc.exigir_proveedor(con, proveedor_id)))


@bp.delete("/proveedores/<int:proveedor_id>")
@con_permiso("proveedores")
def borrar_proveedor(proveedor_id):
    con = get_db()
    with transaccion(con):
        svc.borrar_proveedor(con, proveedor_id)
    return jsonify(ok=True)


@bp.get("/proveedores/facturas")
@con_permiso("proveedores")
def listar_facturas():
    proveedor_id = entero(request.args.get("proveedor_id"), "proveedor", minimo=1, requerido=False)
    facturas, total = svc.listar_facturas(get_db(), request.args.get("estado") or "por_pagar", proveedor_id,
                                          (request.args.get("q") or "").strip()[:60] or None)
    return jsonify({"facturas": facturas, "total": total})


@bp.post("/proveedores/facturas")
@con_permiso("proveedores")
def crear_factura():
    con = get_db()
    with transaccion(con):
        factura_id, nuevo = svc.crear_factura(con, datos_json(), usuario_actual()["id"])
    return jsonify(_factura(con, factura_id) | {"proveedor_nuevo": nuevo}), 201


@bp.put("/proveedores/facturas/<int:factura_id>")
@con_permiso("proveedores")
def editar_factura(factura_id):
    con = get_db()
    with transaccion(con):
        nuevo = svc.editar_factura(con, factura_id, datos_json())
    return jsonify(_factura(con, factura_id) | {"proveedor_nuevo": nuevo})


@bp.delete("/proveedores/facturas/<int:factura_id>")
@con_permiso("proveedores")
def borrar_factura(factura_id):
    con = get_db()
    with transaccion(con):
        svc.exigir_factura(con, factura_id)
        con.execute("DELETE FROM facturas_proveedor WHERE id = ?", (factura_id,))
    return jsonify(ok=True)


@bp.post("/proveedores/facturas/pagar")
@con_permiso("proveedores")
def pagar_facturas():
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        cuantas, total = svc.pagar(con, datos.get("ids"), datos.get("fecha"), datos.get("medio"))
    return jsonify({"pagadas": cuantas, "total": total})


@bp.post("/proveedores/facturas/<int:factura_id>/por-pagar")
@con_permiso("proveedores")
def deshacer_pago(factura_id):
    con = get_db()
    with transaccion(con):
        svc.deshacer_pago(con, factura_id)
    return jsonify(_factura(con, factura_id))


def _factura(con, factura_id):
    factura = dict(svc.exigir_factura(con, factura_id))
    return factura | {"proveedor": svc.exigir_proveedor(con, factura["proveedor_id"])["nombre"]}
