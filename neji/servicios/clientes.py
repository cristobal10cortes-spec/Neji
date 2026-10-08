"""Cuenta corriente de clientes (fiado)."""

from ..db import ahora
from ..validar import ErrorNegocio


def exigir_cliente(con, cliente_id):
    cliente = con.execute(
        "SELECT * FROM clientes WHERE id = ? AND activo = 1", (cliente_id,)
    ).fetchone()
    if cliente is None:
        raise ErrorNegocio("Cliente no encontrado.", status=404)
    return cliente


def mover_saldo(con, cliente_id, tipo, monto, usuario_id, turno_id=None, venta_id=None,
                metodo=None, nota=None):
    """`cargo` aumenta la deuda; `abono` y `devolucion` la disminuyen."""
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    saldo = con.execute("SELECT saldo FROM clientes WHERE id = ?", (cliente_id,)).fetchone()["saldo"]
    nuevo = saldo + monto if tipo == "cargo" else saldo - monto
    con.execute("UPDATE clientes SET saldo = ? WHERE id = ?", (nuevo, cliente_id))
    con.execute(
        """INSERT INTO movimientos_cliente
           (cliente_id, fecha, tipo, monto, saldo_nuevo, metodo, venta_id, turno_id, usuario_id, nota)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cliente_id, ahora(), tipo, monto, nuevo, metodo, venta_id, turno_id, usuario_id, nota),
    )
    return nuevo


def credito_disponible(cliente):
    if cliente["limite_credito"] is None:
        return None
    return cliente["limite_credito"] - cliente["saldo"]
