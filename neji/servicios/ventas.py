"""Cálculo y registro de ventas, cotizaciones y devoluciones."""

import json
from decimal import Decimal

from ..auth import tiene_permiso
from ..chile import desglosar_iva, redondear, redondear_efectivo
from ..db import ahora, fila, filas, leer_config, transaccion
from ..validar import ErrorNegocio, cantidad, entero, texto
from .caja import exigir_caja, exigir_turno, resumen_turno
from .clientes import exigir_cliente, mover_saldo
from .inventario import formatear_cantidad, mover_existencia
from .recetario import describir as describir_receta

METODOS_NO_EFECTIVO = ("debito", "credito", "transferencia", "fiado")
NOMBRE_METODO = {
    "efectivo": "efectivo",
    "debito": "débito",
    "credito": "crédito",
    "transferencia": "transferencia",
    "fiado": "fiado",
}


def pesos(monto):
    return "$" + f"{monto:,}".replace(",", ".")


def puede(usuario, con, permiso):
    return tiene_permiso(usuario, permiso)


def precio_para(producto, cant, tipo_precio):
    """Precio que corresponde a la línea. Aplica mayoreo automático por cantidad."""
    if tipo_precio == "mayoreo":
        if producto["precio_mayoreo"] is None:
            raise ErrorNegocio(f"«{producto['descripcion']}» no tiene precio de mayoreo.")
        return producto["precio_mayoreo"], "mayoreo"
    if (producto["precio_mayoreo"] is not None and producto["cantidad_mayoreo"]
            and cant >= producto["cantidad_mayoreo"]):
        return producto["precio_mayoreo"], "mayoreo"
    return producto["precio_venta"], "normal"


def linea_receta(con, item, n, cant, recetas_vistas):
    """Línea de una receta magistral: el precio sale del libro de recetas."""
    receta_id = entero(item.get("receta_id"), f"receta de la línea {n}", minimo=1)
    if receta_id in recetas_vistas:
        raise ErrorNegocio("La misma receta magistral está dos veces en el ticket.")
    recetas_vistas.add(receta_id)
    receta = con.execute("SELECT * FROM recetas_magistrales WHERE id = ?", (receta_id,)).fetchone()
    if receta is None:
        raise ErrorNegocio(f"La receta magistral de la línea {n} no existe.")
    if receta["estado"] != "pendiente":
        raise ErrorNegocio(f"La receta magistral N° {receta['folio']} ya está {receta['estado']}.")
    if cant != 1:
        raise ErrorNegocio("Cada receta magistral se vende una vez (cantidad 1).")
    return {
        "producto": None,
        "producto_id": None,
        "codigo": None,
        "descripcion": describir_receta(receta),
        "departamento_id": None,
        "cantidad": 1,
        "precio_unitario": receta["total"],
        "precio_costo": 0,
        "tipo_precio": "comun",
        "exento": 0,
        "receta_id": receta_id,
    }


def calcular_lineas(con, items, puede_cambiar_precio, permitir_recetas=True):
    """Arma las líneas con precios tomados de la base de datos (no del navegador)."""
    if not isinstance(items, list) or not items:
        raise ErrorNegocio("El ticket está vacío.")
    if len(items) > 1000:
        raise ErrorNegocio("El ticket tiene demasiadas líneas.")
    lineas, recetas_vistas = [], set()
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ErrorNegocio(f"La línea {n} no es válida.")
        tipo = item.get("tipo_precio") or "normal"
        if tipo not in ("normal", "mayoreo", "manual", "comun"):
            raise ErrorNegocio(f"Tipo de precio inválido en la línea {n}.")
        cant = cantidad(item.get("cantidad"), f"cantidad de la línea {n}", positiva=True)

        if item.get("receta_id") not in (None, ""):
            if not permitir_recetas:
                raise ErrorNegocio("Las recetas magistrales se presupuestan desde el Recetario "
                                   "(ahí puedes imprimir la receta con su precio).")
            linea = linea_receta(con, item, n, cant, recetas_vistas)
        elif item.get("producto_id") in (None, "") or tipo == "comun":
            linea = {
                "producto": None,
                "producto_id": None,
                "codigo": None,
                "descripcion": texto(item, "descripcion", max_largo=120) or "Artículo común",
                "departamento_id": None,
                "cantidad": cant,
                "precio_unitario": entero(item.get("precio"), f"precio de la línea {n}", minimo=1),
                "precio_costo": 0,
                "tipo_precio": "comun",
                "exento": 0,
            }
        else:
            producto = con.execute(
                "SELECT * FROM productos WHERE id = ? AND activo = 1", (item.get("producto_id"),)
            ).fetchone()
            if producto is None:
                raise ErrorNegocio(f"El producto de la línea {n} ya no existe.")
            if producto["tipo_venta"] == "unidad" and cant != int(cant):
                raise ErrorNegocio(
                    f"«{producto['descripcion']}» se vende por unidad: la cantidad debe ser entera.")
            if tipo == "manual":
                if not puede_cambiar_precio:
                    raise ErrorNegocio("No tienes permiso para cambiar precios.", status=403)
                precio = entero(item.get("precio"), f"precio de la línea {n}", minimo=0)
            else:
                precio, tipo = precio_para(producto, cant, tipo)
            linea = {
                "producto": producto,
                "producto_id": producto["id"],
                "codigo": producto["codigo"],
                "descripcion": producto["descripcion"],
                "departamento_id": producto["departamento_id"],
                "cantidad": cant,
                "precio_unitario": precio,
                "precio_costo": producto["precio_costo"],
                "tipo_precio": tipo,
                "exento": producto["exento"],
            }
        linea.setdefault("receta_id", None)
        linea["importe"] = redondear(Decimal(str(linea["cantidad"])) * linea["precio_unitario"])
        lineas.append(linea)
    return lineas


def calcular_totales(lineas, descuento, tasa_iva):
    subtotal = sum(l["importe"] for l in lineas)
    if descuento > subtotal:
        raise ErrorNegocio("El descuento no puede ser mayor que el subtotal.")
    total = subtotal - descuento
    exento_bruto = sum(l["importe"] for l in lineas if l["exento"])
    exento = redondear(Decimal(exento_bruto) * total / subtotal) if subtotal else 0
    neto, iva = desglosar_iva(total - exento, tasa_iva)
    return {"subtotal": subtotal, "descuento": descuento, "total": total,
            "exento": exento, "neto": neto, "iva": iva}


def leer_descuento(con, datos, usuario):
    descuento = entero(datos.get("descuento") or 0, "descuento", minimo=0)
    if descuento and not puede(usuario, con, "cambiar_precio"):
        raise ErrorNegocio("No tienes permiso para aplicar descuentos.", status=403)
    return descuento


def siguiente_folio(con, tabla):
    return con.execute(f"SELECT COALESCE(MAX(folio), 0) + 1 FROM {tabla}").fetchone()[0]


def registrar_venta(con, datos, usuario):
    caja_id = entero(datos.get("caja_id"), "caja", minimo=1)
    with transaccion(con):
        exigir_caja(con, caja_id)
        turno = exigir_turno(con, caja_id)
        config = leer_config(con)
        lineas = calcular_lineas(con, datos.get("items"),
                                 puede(usuario, con, "cambiar_precio"))
        t = calcular_totales(lineas, leer_descuento(con, datos, usuario),
                             int(config["iva_porcentaje"]))

        cliente = None
        if datos.get("cliente_id"):
            cliente = exigir_cliente(con, datos["cliente_id"])

        pagos_in = datos.get("pagos") or {}
        if not isinstance(pagos_in, dict):
            raise ErrorNegocio("Formato de pagos inválido.")
        pagos = {}
        for metodo in METODOS_NO_EFECTIVO:
            monto = entero(pagos_in.get(metodo) or 0, f"pago con {NOMBRE_METODO[metodo]}", minimo=0)
            if monto:
                pagos[metodo] = monto
        no_efectivo = sum(pagos.values())
        if no_efectivo > t["total"]:
            raise ErrorNegocio("Los pagos con tarjeta, transferencia o fiado superan el total.")

        efectivo = t["total"] - no_efectivo
        redondeo = recibido = cambio = 0
        if efectivo > 0:
            a_cobrar = redondear_efectivo(efectivo) if config["redondeo_efectivo"] == "1" else efectivo
            redondeo = a_cobrar - efectivo
            if datos.get("efectivo_recibido") in (None, ""):
                recibido = a_cobrar
            else:
                recibido = entero(datos.get("efectivo_recibido"), "efectivo recibido", minimo=0)
            if recibido < a_cobrar:
                raise ErrorNegocio(f"Falta dinero: se deben pagar {pesos(a_cobrar)} en efectivo.")
            cambio = recibido - a_cobrar
            pagos["efectivo"] = efectivo

        if pagos.get("fiado"):
            if cliente is None:
                raise ErrorNegocio("Para vender fiado debes elegir un cliente.")
            limite = cliente["limite_credito"]
            if limite is not None and cliente["saldo"] + pagos["fiado"] > limite:
                disponible = max(limite - cliente["saldo"], 0)
                raise ErrorNegocio(
                    f"{cliente['nombre']} supera su límite de crédito "
                    f"(disponible: {pesos(disponible)}).")

        cotizacion_id = None
        if datos.get("cotizacion_id"):
            cotizacion_id = entero(datos["cotizacion_id"], "cotización", minimo=1)
            if not con.execute("SELECT 1 FROM cotizaciones WHERE id = ?", (cotizacion_id,)).fetchone():
                raise ErrorNegocio("La cotización no existe.")
        folio = siguiente_folio(con, "ventas")
        fecha = ahora()
        venta_id = con.execute(
            """INSERT INTO ventas (folio, fecha, caja_id, turno_id, usuario_id, cliente_id,
                   subtotal, descuento, total, exento, neto, iva, redondeo,
                   efectivo_recibido, cambio, cotizacion_id, nota)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (folio, fecha, caja_id, turno["id"], usuario["id"], cliente["id"] if cliente else None,
             t["subtotal"], t["descuento"], t["total"], t["exento"], t["neto"], t["iva"], redondeo,
             recibido, cambio, cotizacion_id, texto(datos, "nota")),
        ).lastrowid

        permitir_negativo = config["permitir_stock_negativo"] == "1"
        for l in lineas:
            con.execute(
                """INSERT INTO venta_items (venta_id, producto_id, codigo, descripcion,
                       departamento_id, cantidad, precio_unitario, precio_costo, tipo_precio,
                       importe, exento, receta_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (venta_id, l["producto_id"], l["codigo"], l["descripcion"], l["departamento_id"],
                 l["cantidad"], l["precio_unitario"], l["precio_costo"], l["tipo_precio"],
                 l["importe"], l["exento"], l["receta_id"]),
            )
            if l["receta_id"] is not None:
                vendida = con.execute(
                    "UPDATE recetas_magistrales SET estado = 'vendida', venta_id = ? "
                    "WHERE id = ? AND estado = 'pendiente'", (venta_id, l["receta_id"])).rowcount
                if vendida != 1:
                    raise ErrorNegocio("La receta magistral ya fue vendida o anulada.")
            if l["producto"] is not None:
                mover_existencia(con, l["producto"], -l["cantidad"], "venta", usuario["id"],
                                 referencia=f"Venta {folio}", permitir_negativo=permitir_negativo)

        for metodo, monto in pagos.items():
            con.execute("INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
                        (venta_id, metodo, monto))

        if pagos.get("fiado"):
            mover_saldo(con, cliente["id"], "cargo", pagos["fiado"], usuario["id"],
                        turno_id=turno["id"], venta_id=venta_id, metodo="fiado",
                        nota=f"Venta {folio}")

        if cotizacion_id:
            con.execute("UPDATE cotizaciones SET estado = 'vendida' WHERE id = ? AND estado = 'vigente'",
                        (cotizacion_id,))
    return venta_id


def obtener_venta(con, venta_id):
    venta = fila(con.execute(
        """SELECT v.*, c.nombre AS caja, u.nombre AS usuario,
                  COALESCE(NULLIF(u.nombre_ticket, ''), u.nombre) AS atendio, cl.nombre AS cliente,
                  cl.rut AS cliente_rut, cl.saldo AS cliente_saldo
           FROM ventas v
           JOIN cajas c ON c.id = v.caja_id
           JOIN usuarios u ON u.id = v.usuario_id
           LEFT JOIN clientes cl ON cl.id = v.cliente_id
           WHERE v.id = ?""", (venta_id,)).fetchone())
    if venta is None:
        raise ErrorNegocio("Venta no encontrada.", status=404)
    venta["items"] = filas(con.execute(
        "SELECT * FROM venta_items WHERE venta_id = ? ORDER BY id", (venta_id,)))
    venta["pagos"] = filas(con.execute(
        "SELECT metodo, monto FROM venta_pagos WHERE venta_id = ? ORDER BY id", (venta_id,)))
    venta["devoluciones"] = filas(con.execute(
        """SELECT d.*, u.nombre AS usuario FROM devoluciones d
           JOIN usuarios u ON u.id = d.usuario_id WHERE d.venta_id = ? ORDER BY d.id""",
        (venta_id,)))
    return venta


def devolver(con, venta_id, datos, usuario):
    """Devolución parcial o total. El dinero sale del turno abierto de la caja indicada."""
    caja_id = entero(datos.get("caja_id"), "caja", minimo=1)
    reembolso = datos.get("reembolso") or "efectivo"
    if reembolso not in ("efectivo", "otro"):
        raise ErrorNegocio("Forma de reembolso inválida.")
    with transaccion(con):
        turno = exigir_turno(con, caja_id)
        venta = con.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        if venta is None:
            raise ErrorNegocio("Venta no encontrada.", status=404)
        if venta["estado"] == "devuelta":
            raise ErrorNegocio("Esta venta ya fue devuelta completa.")
        items = {i["id"]: i for i in con.execute(
            "SELECT * FROM venta_items WHERE venta_id = ?", (venta_id,))}

        pedidos = {}
        if datos.get("todo"):
            for i in items.values():
                pendiente = round(i["cantidad"] - i["cantidad_devuelta"], 3)
                if pendiente > 0:
                    pedidos[i["id"]] = pendiente
        else:
            for d in datos.get("items") or []:
                item_id = entero(d.get("venta_item_id"), "artículo", minimo=1)
                cant = cantidad(d.get("cantidad"), "cantidad a devolver", positiva=True)
                pedidos[item_id] = round(pedidos.get(item_id, 0) + cant, 3)
        if not pedidos:
            raise ErrorNegocio("Indica qué artículos se devuelven.")

        factor = Decimal(venta["total"]) / venta["subtotal"] if venta["subtotal"] else Decimal(1)
        detalle = []
        for item_id, cant in pedidos.items():
            item = items.get(item_id)
            if item is None:
                raise ErrorNegocio("Uno de los artículos no pertenece a esta venta.")
            pendiente = round(item["cantidad"] - item["cantidad_devuelta"], 3)
            if cant > pendiente:
                raise ErrorNegocio(
                    f"De «{item['descripcion']}» solo se pueden devolver {formatear_cantidad(pendiente)}.")
            monto = redondear(Decimal(item["importe"]) * Decimal(str(cant))
                              / Decimal(str(item["cantidad"])) * factor)
            detalle.append([item, cant, monto])

        restante = venta["total"] - venta["devuelto"]
        queda_algo = any(
            round(i["cantidad"] - i["cantidad_devuelta"] - pedidos.get(i["id"], 0), 3) > 0
            for i in items.values())
        total = sum(m for _, _, m in detalle)
        if not queda_algo:
            detalle[-1][2] += restante - total  # cuadra redondeos al devolver todo
            total = restante
        total = min(total, restante)

        fiado_pagado = con.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM venta_pagos WHERE venta_id = ? AND metodo = 'fiado'",
            (venta_id,)).fetchone()[0]
        fiado_devuelto = con.execute(
            "SELECT COALESCE(SUM(monto_fiado), 0) FROM devoluciones WHERE venta_id = ?",
            (venta_id,)).fetchone()[0]
        monto_fiado = min(total, fiado_pagado - fiado_devuelto) if venta["cliente_id"] else 0
        resto = total - monto_fiado
        monto_efectivo = monto_otro = 0
        if reembolso == "efectivo":
            config = leer_config(con)
            monto_efectivo = redondear_efectivo(resto) if config["redondeo_efectivo"] == "1" else resto
            disponible = resumen_turno(con, turno["id"])["efectivo_esperado"]
            if monto_efectivo > disponible:
                raise ErrorNegocio(f"No hay suficiente efectivo en caja para devolver "
                                   f"{pesos(monto_efectivo)} (hay {pesos(disponible)}).")
        else:
            monto_otro = resto

        devolucion_id = con.execute(
            """INSERT INTO devoluciones (venta_id, fecha, turno_id, usuario_id, monto,
                   monto_efectivo, monto_fiado, monto_otro, motivo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (venta_id, ahora(), turno["id"], usuario["id"], total, monto_efectivo, monto_fiado,
             monto_otro, texto(datos, "motivo")),
        ).lastrowid

        for item, cant, monto in detalle:
            con.execute(
                "INSERT INTO devolucion_items (devolucion_id, venta_item_id, cantidad, monto) "
                "VALUES (?, ?, ?, ?)", (devolucion_id, item["id"], cant, monto))
            con.execute("UPDATE venta_items SET cantidad_devuelta = cantidad_devuelta + ? WHERE id = ?",
                        (cant, item["id"]))
            if item["receta_id"] is not None and round(item["cantidad"] - item["cantidad_devuelta"] - cant, 3) <= 0:
                con.execute("UPDATE recetas_magistrales SET estado = 'anulada' WHERE id = ?",
                            (item["receta_id"],))
            if item["producto_id"] is not None:
                producto = con.execute("SELECT * FROM productos WHERE id = ?",
                                       (item["producto_id"],)).fetchone()
                if producto is not None:
                    mover_existencia(con, producto, cant, "devolucion", usuario["id"],
                                     referencia=f"Devolución venta {venta['folio']}")

        if monto_fiado:
            mover_saldo(con, venta["cliente_id"], "devolucion", monto_fiado, usuario["id"],
                        turno_id=turno["id"], venta_id=venta_id,
                        nota=f"Devolución venta {venta['folio']}")

        devuelto = venta["devuelto"] + total
        estado = "devuelta" if not queda_algo else "devuelta_parcial"
        con.execute("UPDATE ventas SET devuelto = ?, estado = ? WHERE id = ?",
                    (devuelto, estado, venta_id))
    return devolucion_id


def crear_cotizacion(con, datos, usuario):
    with transaccion(con):
        lineas = calcular_lineas(con, datos.get("items"),
                                 puede(usuario, con, "cambiar_precio"),
                                 permitir_recetas=False)
        config = leer_config(con)
        t = calcular_totales(lineas, leer_descuento(con, datos, usuario),
                             int(config["iva_porcentaje"]))
        cliente_id = None
        cliente_nombre = texto(datos, "cliente_nombre", max_largo=120)
        if datos.get("cliente_id"):
            cliente = exigir_cliente(con, datos["cliente_id"])
            cliente_id, cliente_nombre = cliente["id"], cliente["nombre"]
        guardadas = [{k: v for k, v in l.items() if k != "producto"} for l in lineas]
        return con.execute(
            """INSERT INTO cotizaciones (folio, fecha, usuario_id, cliente_id, cliente_nombre,
                   items, subtotal, descuento, total, nota)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (siguiente_folio(con, "cotizaciones"), ahora(), usuario["id"], cliente_id,
             cliente_nombre, json.dumps(guardadas, ensure_ascii=False), t["subtotal"],
             t["descuento"], t["total"], texto(datos, "nota")),
        ).lastrowid
