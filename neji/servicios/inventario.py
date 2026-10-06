"""Movimientos de existencia (kardex)."""

from ..db import ahora
from ..validar import ErrorNegocio


def formatear_cantidad(valor):
    return f"{valor:g}".replace(".", ",")


def mover_existencia(con, producto, cantidad, tipo, usuario_id, referencia=None, nota=None,
                     costo_unitario=None, permitir_negativo=True):
    """Suma `cantidad` (negativa para sacar) a la existencia y deja registro en el kardex.

    `producto` es una fila de productos. Debe llamarse dentro de una transacción.
    """
    if not producto["usa_inventario"]:
        return None
    anterior = con.execute(
        "SELECT existencia FROM productos WHERE id = ?", (producto["id"],)
    ).fetchone()["existencia"]
    nueva = round(anterior + cantidad, 3)
    if nueva < 0 and not permitir_negativo:
        raise ErrorNegocio(
            f"No hay existencia suficiente de «{producto['descripcion']}» "
            f"(hay {formatear_cantidad(anterior)})."
        )
    fecha = ahora()
    con.execute(
        "UPDATE productos SET existencia = ?, actualizado = ? WHERE id = ?",
        (nueva, fecha, producto["id"]),
    )
    con.execute(
        """INSERT INTO movimientos_inventario
           (producto_id, fecha, tipo, cantidad, existencia_anterior, existencia_nueva,
            costo_unitario, referencia, usuario_id, nota)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (producto["id"], fecha, tipo, cantidad, anterior, nueva,
         costo_unitario if costo_unitario is not None else producto["precio_costo"],
         referencia, usuario_id, nota),
    )
    return nueva
