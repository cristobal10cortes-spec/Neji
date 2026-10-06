"""Turnos de caja, entradas/salidas de efectivo y corte."""

from ..db import ahora, fila, filas
from ..validar import ErrorNegocio

# Nombre del departamento de una línea de venta (alias vi y d = departamentos).
SQL_DEPARTAMENTO_ITEM = """
    COALESCE(d.nombre, CASE WHEN vi.receta_id IS NOT NULL THEN 'Recetario magistral'
                            WHEN vi.producto_id IS NULL THEN 'Artículos comunes'
                            ELSE 'Sin departamento' END)
"""

# Ganancia de una línea de venta descontando lo devuelto y repartiendo el
# descuento general del ticket en proporción. Requiere alias vi (venta_items) y v (ventas).
SQL_GANANCIA_ITEM = """
    (vi.importe * (vi.cantidad - vi.cantidad_devuelta) / vi.cantidad)
      * (CASE WHEN v.subtotal > 0 THEN 1.0 * v.total / v.subtotal ELSE 1 END)
    - vi.precio_costo * (vi.cantidad - vi.cantidad_devuelta)
"""


def turno_abierto(con, caja_id):
    return fila(con.execute(
        "SELECT * FROM turnos WHERE caja_id = ? AND estado = 'abierto'", (caja_id,)
    ).fetchone())


def exigir_turno(con, caja_id):
    turno = turno_abierto(con, caja_id)
    if turno is None:
        raise ErrorNegocio("La caja no tiene un turno abierto. Abre el turno indicando "
                           "el dinero inicial en caja.", codigo="sin_turno")
    return turno


def exigir_caja(con, caja_id):
    caja = con.execute("SELECT * FROM cajas WHERE id = ? AND activa = 1", (caja_id,)).fetchone()
    if caja is None:
        raise ErrorNegocio("La caja indicada no existe o está desactivada.")
    return caja


def abrir_turno(con, caja_id, usuario_id, fondo_inicial):
    exigir_caja(con, caja_id)
    if turno_abierto(con, caja_id):
        raise ErrorNegocio("Esta caja ya tiene un turno abierto.")
    cur = con.execute(
        "INSERT INTO turnos (caja_id, usuario_id, abierto, fondo_inicial) VALUES (?, ?, ?, ?)",
        (caja_id, usuario_id, ahora(), fondo_inicial),
    )
    return cur.lastrowid


def registrar_movimiento(con, turno_id, tipo, monto, concepto, usuario_id):
    if tipo not in ("entrada", "salida"):
        raise ErrorNegocio("El tipo de movimiento debe ser entrada o salida.")
    if monto <= 0:
        raise ErrorNegocio("El monto debe ser mayor que cero.")
    if tipo == "salida":
        disponible = resumen_turno(con, turno_id)["efectivo_esperado"]
        if monto > disponible:
            raise ErrorNegocio(f"No hay suficiente efectivo en caja (hay ${disponible:,}).".replace(",", "."))
    cur = con.execute(
        "INSERT INTO movimientos_caja (turno_id, fecha, tipo, monto, concepto, usuario_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (turno_id, ahora(), tipo, monto, concepto, usuario_id),
    )
    return cur.lastrowid


def resumen_turno(con, turno_id):
    """Todo lo que pasó en el turno y el efectivo que debería haber en el cajón."""
    turno = fila(con.execute(
        """SELECT t.*, c.nombre AS caja, u.nombre AS usuario, uc.nombre AS usuario_cierre
           FROM turnos t
           JOIN cajas c ON c.id = t.caja_id
           JOIN usuarios u ON u.id = t.usuario_id
           LEFT JOIN usuarios uc ON uc.id = t.usuario_cierre_id
           WHERE t.id = ?""", (turno_id,)
    ).fetchone())
    if turno is None:
        raise ErrorNegocio("Turno no encontrado.", status=404)

    def valor(sql, *params):
        return con.execute(sql, params).fetchone()[0] or 0

    por_metodo = {m: 0 for m in ("efectivo", "debito", "credito", "transferencia", "fiado")}
    for r in con.execute(
        """SELECT p.metodo, SUM(p.monto) AS monto FROM venta_pagos p
           JOIN ventas v ON v.id = p.venta_id WHERE v.turno_id = ? GROUP BY p.metodo""",
        (turno_id,),
    ):
        por_metodo[r["metodo"]] = r["monto"]

    redondeo = valor("SELECT SUM(redondeo) FROM ventas WHERE turno_id = ?", turno_id)
    n_ventas = valor("SELECT COUNT(*) FROM ventas WHERE turno_id = ?", turno_id)
    total_ventas = valor("SELECT SUM(total) FROM ventas WHERE turno_id = ?", turno_id)
    ganancia = valor(
        f"""SELECT SUM({SQL_GANANCIA_ITEM})
           FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id WHERE v.turno_id = ?""",
        turno_id,
    )
    entradas = valor(
        "SELECT SUM(monto) FROM movimientos_caja WHERE turno_id = ? AND tipo = 'entrada'", turno_id)
    salidas = valor(
        "SELECT SUM(monto) FROM movimientos_caja WHERE turno_id = ? AND tipo = 'salida'", turno_id)
    abonos_efectivo = valor(
        "SELECT SUM(monto) FROM movimientos_cliente WHERE turno_id = ? AND tipo = 'abono' "
        "AND metodo = 'efectivo'", turno_id)
    abonos_otros = valor(
        "SELECT SUM(monto) FROM movimientos_cliente WHERE turno_id = ? AND tipo = 'abono' "
        "AND metodo <> 'efectivo'", turno_id)
    dev = con.execute(
        "SELECT COALESCE(SUM(monto), 0) AS total, COALESCE(SUM(monto_efectivo), 0) AS efectivo "
        "FROM devoluciones WHERE turno_id = ?", (turno_id,)
    ).fetchone()

    ventas_efectivo = por_metodo["efectivo"] + redondeo
    esperado = (turno["fondo_inicial"] + ventas_efectivo + abonos_efectivo
                + entradas - salidas - dev["efectivo"])

    departamentos = filas(con.execute(
        f"""SELECT {SQL_DEPARTAMENTO_ITEM} AS departamento,
                  SUM(vi.importe) AS total
           FROM venta_items vi JOIN ventas v ON v.id = vi.venta_id
           LEFT JOIN departamentos d ON d.id = vi.departamento_id
           WHERE v.turno_id = ? GROUP BY 1 ORDER BY 2 DESC""", (turno_id,)))
    movimientos = filas(con.execute(
        """SELECT m.*, u.nombre AS usuario FROM movimientos_caja m
           LEFT JOIN usuarios u ON u.id = m.usuario_id WHERE m.turno_id = ? ORDER BY m.id""",
        (turno_id,)))

    turno.update(
        n_ventas=n_ventas,
        total_ventas=total_ventas,
        ganancia=round(ganancia),
        por_metodo=por_metodo,
        redondeo=redondeo,
        ventas_efectivo=ventas_efectivo,
        abonos_efectivo=abonos_efectivo,
        abonos_otros=abonos_otros,
        entradas=entradas,
        salidas=salidas,
        devoluciones=dev["total"],
        devoluciones_efectivo=dev["efectivo"],
        departamentos=departamentos,
        movimientos=movimientos,
    )
    if turno["estado"] == "abierto":
        turno["efectivo_esperado"] = esperado
    return turno


def cerrar_turno(con, caja_id, usuario_id, efectivo_contado, nota=None):
    turno = exigir_turno(con, caja_id)
    resumen = resumen_turno(con, turno["id"])
    esperado = resumen["efectivo_esperado"]
    con.execute(
        """UPDATE turnos SET estado = 'cerrado', cerrado = ?, efectivo_esperado = ?,
                  efectivo_contado = ?, diferencia = ?, usuario_cierre_id = ?, nota = ?
           WHERE id = ?""",
        (ahora(), esperado, efectivo_contado, efectivo_contado - esperado, usuario_id, nota,
         turno["id"]),
    )
    return turno["id"]
