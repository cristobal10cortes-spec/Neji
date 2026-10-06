"""Clientes, crédito (fiado) y abonos."""

from flask import jsonify, request

from ..auth import usuario_actual
from ..chile import formatear_rut, validar_rut
from ..db import ahora, filas, get_db, transaccion
from ..servicios.caja import exigir_turno
from ..servicios.clientes import credito_disponible, exigir_cliente, mover_saldo
from ..servicios.ventas import pesos
from ..validar import ErrorNegocio, booleano, entero, texto
from . import bp, datos_json

METODOS_ABONO = ("efectivo", "debito", "credito", "transferencia")


def _leer_cliente(con, datos, cliente_id=None):
    rut = texto(datos, "rut", max_largo=15)
    if rut:
        if not validar_rut(rut):
            raise ErrorNegocio("El RUT no es válido.")
        rut = formatear_rut(rut)
        repetido = con.execute("SELECT id FROM clientes WHERE rut = ? AND id IS NOT ?",
                               (rut, cliente_id)).fetchone()
        if repetido:
            raise ErrorNegocio("Ya existe un cliente con ese RUT.")
    email = texto(datos, "email", max_largo=120)
    if email and "@" not in email:
        raise ErrorNegocio("El correo no es válido.")
    return {
        "rut": rut,
        "nombre": texto(datos, "nombre", requerido=True, nombre="el nombre", max_largo=120),
        "telefono": texto(datos, "telefono", max_largo=30),
        "email": email,
        "direccion": texto(datos, "direccion", max_largo=200),
        "giro": texto(datos, "giro", max_largo=120),
        "notas": texto(datos, "notas"),
    }


def _leer_limite(datos):
    if booleano(datos.get("sin_limite", False)):
        return None
    return entero(datos.get("limite_credito") or 0, "límite de crédito", minimo=0)


def _con_credito(cliente):
    cliente = dict(cliente)
    cliente["credito_disponible"] = credito_disponible(cliente)
    return cliente


@bp.get("/clientes")
def listar_clientes():
    condiciones, params = ["activo = 1"], []
    for palabra in (request.args.get("q") or "").split()[:6]:
        condiciones.append("(nombre LIKE ? OR rut LIKE ? OR telefono LIKE ?)")
        params += [f"%{palabra}%", f"%{palabra}%", f"%{palabra}%"]
    if booleano(request.args.get("con_deuda", "")):
        condiciones.append("saldo > 0")
    clientes = get_db().execute(
        f"SELECT * FROM clientes WHERE {' AND '.join(condiciones)} ORDER BY nombre LIMIT 200", params)
    return jsonify([_con_credito(c) for c in clientes])


@bp.get("/clientes/<int:cliente_id>")
def ver_cliente(cliente_id):
    con = get_db()
    cliente = _con_credito(exigir_cliente(con, cliente_id))
    cliente["movimientos"] = filas(con.execute(
        """SELECT m.*, v.folio, u.nombre AS usuario FROM movimientos_cliente m
           LEFT JOIN ventas v ON v.id = m.venta_id
           LEFT JOIN usuarios u ON u.id = m.usuario_id
           WHERE m.cliente_id = ? ORDER BY m.id DESC LIMIT 300""", (cliente_id,)))
    return jsonify(cliente)


@bp.post("/clientes")
def crear_cliente():
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        c = _leer_cliente(con, datos)
        # Solo un administrador define el crédito; el cajero crea clientes sin fiado.
        c["limite_credito"] = _leer_limite(datos) if usuario_actual()["rol"] == "admin" else 0
        c["creado"] = ahora()
        cliente_id = con.execute(
            f"INSERT INTO clientes ({', '.join(c)}) VALUES ({', '.join('?' for _ in c)})",
            list(c.values())).lastrowid
    return jsonify(_con_credito(exigir_cliente(con, cliente_id))), 201


@bp.put("/clientes/<int:cliente_id>")
def editar_cliente(cliente_id):
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        exigir_cliente(con, cliente_id)
        c = _leer_cliente(con, datos, cliente_id)
        if usuario_actual()["rol"] == "admin" and ("limite_credito" in datos or "sin_limite" in datos):
            c["limite_credito"] = _leer_limite(datos)
        con.execute(f"UPDATE clientes SET {', '.join(f'{k} = ?' for k in c)} WHERE id = ?",
                    list(c.values()) + [cliente_id])
    return jsonify(_con_credito(exigir_cliente(con, cliente_id)))


@bp.delete("/clientes/<int:cliente_id>")
def borrar_cliente(cliente_id):
    if usuario_actual()["rol"] != "admin":
        raise ErrorNegocio("Solo un administrador puede eliminar clientes.", status=403)
    con = get_db()
    with transaccion(con):
        cliente = exigir_cliente(con, cliente_id)
        if cliente["saldo"] != 0:
            raise ErrorNegocio(f"El cliente tiene saldo pendiente ({pesos(cliente['saldo'])}).")
        con.execute("UPDATE clientes SET activo = 0, rut = NULL WHERE id = ?", (cliente_id,))
    return jsonify(ok=True)


@bp.post("/clientes/<int:cliente_id>/abono")
def abonar(cliente_id):
    datos = datos_json()
    metodo = datos.get("metodo") or "efectivo"
    if metodo not in METODOS_ABONO:
        raise ErrorNegocio("Forma de pago inválida.")
    monto = entero(datos.get("monto"), "monto", minimo=1)
    caja_id = entero(datos.get("caja_id"), "caja", minimo=1)
    con = get_db()
    with transaccion(con):
        turno = exigir_turno(con, caja_id)
        cliente = exigir_cliente(con, cliente_id)
        if monto > cliente["saldo"]:
            raise ErrorNegocio(f"El abono supera la deuda del cliente ({pesos(cliente['saldo'])}).")
        mover_saldo(con, cliente_id, "abono", monto, usuario_actual()["id"], turno_id=turno["id"],
                    metodo=metodo, nota=texto(datos, "nota"))
    return jsonify(_con_credito(exigir_cliente(con, cliente_id)))


@bp.get("/clientes/<int:cliente_id>/ventas")
def ventas_cliente(cliente_id):
    return jsonify(filas(get_db().execute(
        "SELECT id, folio, fecha, total, estado FROM ventas WHERE cliente_id = ? "
        "ORDER BY id DESC LIMIT 200", (cliente_id,))))
