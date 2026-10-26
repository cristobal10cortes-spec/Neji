"""Cálculo y registro de ventas, cotizaciones y devoluciones."""

import json
import logging
from decimal import Decimal

from ..auth import tiene_permiso
from ..chile import desglosar_iva, redondear, redondear_efectivo
from ..db import ahora, fila, filas, leer_config, transaccion
from ..validar import ErrorNegocio, cantidad, entero, texto
from .caja import exigir_caja, exigir_turno, resumen_turno
from .clientes import exigir_cliente, mover_saldo
from .inventario import formatear_cantidad, mover_existencia
from .recetario import describir as describir_receta

registro = logging.getLogger("neji.ventas")

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


def calcular_lineas(con, items, puede_cambiar_precio, permitir_recetas=True, puede_comun=True, comunes_permitidos=()):
    """Arma las líneas con precios tomados de la base de datos (no del navegador).

    Un artículo común lleva el precio que escribe la caja: sin el permiso solo se aceptan los de la
    cotización que se está vendiendo (`comunes_permitidos`: pares descripción, precio).
    """
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
            if item.get("producto_id") not in (None, ""):
                raise ErrorNegocio(f"La línea {n} no puede ser un producto del catálogo y un artículo común a la vez.")
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
            if not puede_comun and (linea["descripcion"], linea["precio_unitario"]) not in comunes_permitidos:
                raise ErrorNegocio("No tienes permiso para vender artículos comunes (precio libre).", status=403)
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


def leer_descuento(con, datos, usuario, cotizacion=None):
    descuento = entero(datos.get("descuento") or 0, "descuento", minimo=0)
    # Al vender una cotización, su descuento ya lo autorizó quien la hizo: se acepta hasta ese monto.
    autorizado = cotizacion["descuento"] if cotizacion is not None else 0
    if descuento > autorizado and not puede(usuario, con, "cambiar_precio"):
        raise ErrorNegocio("No tienes permiso para aplicar descuentos.", status=403)
    return descuento


def cotizacion_vigente(con, datos):
    """La cotización vigente que se está vendiendo (cotizacion_id), o None."""
    if not datos.get("cotizacion_id"):
        return None
    return con.execute("SELECT * FROM cotizaciones WHERE id = ? AND estado = 'vigente'",
                       (entero(datos["cotizacion_id"], "cotización", minimo=1),)).fetchone()


def comunes_de(cotizacion):
    """Artículos comunes (descripción, precio) de una cotización."""
    if cotizacion is None:
        return set()
    return {(l["descripcion"], l["precio_unitario"]) for l in json.loads(cotizacion["items"])
            if l.get("producto_id") is None and l.get("receta_id") is None}


def siguiente_folio(con, tabla):
    return con.execute(f"SELECT COALESCE(MAX(folio), 0) + 1 FROM {tabla}").fetchone()[0]


def _secreto():
    from flask import current_app

    return current_app.secret_key


def _emitir_documento(con, venta_id, documento, avisos, tasa_iva):
    """Boleta o factura electrónica de la venta (si el SII está activo), dentro de la transacción de la venta.

    Si la boleta no se puede emitir, la venta queda con su comprobante interno y se avisa. La factura pedida,
    en cambio, no se vende sin ella.
    """
    from ..sii import ErrorSII
    from ..sii import servicio as sii

    if not sii.activo(con):
        if documento == "factura":
            raise ErrorNegocio("La factura electrónica no está activada (Configuración → Boleta electrónica).")
        return
    con.execute("SAVEPOINT documento_sii")
    try:
        sii.emitir_venta(con, venta_id, documento, _secreto(), tasa_iva)
        con.execute("RELEASE documento_sii")
    except Exception as e:  # noqa: BLE001 (que una falla de la boleta no impida vender)
        con.execute("ROLLBACK TO documento_sii")
        con.execute("RELEASE documento_sii")
        if not isinstance(e, ErrorSII):
            registro.exception("Error al emitir el documento electrónico de la venta %s", venta_id)
        if documento == "factura":
            raise ErrorNegocio(f"No se pudo emitir la factura: {e}") from None
        if avisos is not None:
            avisos.append(f"La venta quedó registrada, pero sin boleta electrónica: {e}")
        return
    if avisos is not None:
        cfg = sii.leer(con)
        quedan = {}
        for f in sii.folios(con, cfg["ambiente"]):
            quedan[f["tipo"]] = quedan.get(f["tipo"], 0) + f["disponibles"]
        for tipo, n in quedan.items():
            if tipo in (39, 33) and n <= 20:
                avisos.append(f"Quedan {n} folios de {sii.NOMBRES[tipo].lower()}: pide más al SII.")


def registrar_venta(con, datos, usuario, avisos=None):
    """Registra la venta. `avisos` (lista) recibe lo que hay que advertir a la caja (p. ej. sin boleta)."""
    caja_id = entero(datos.get("caja_id"), "caja", minimo=1)
    documento = datos.get("documento") or "boleta"
    if documento not in ("boleta", "factura"):
        raise ErrorNegocio("El documento debe ser boleta o factura.")
    with transaccion(con):
        exigir_caja(con, caja_id)
        turno = exigir_turno(con, caja_id)
        config = leer_config(con)
        cotizacion = cotizacion_vigente(con, datos)
        lineas = calcular_lineas(con, datos.get("items"),
                                 puede(usuario, con, "cambiar_precio"),
                                 puede_comun=puede(usuario, con, "articulo_comun"),
                                 comunes_permitidos=comunes_de(cotizacion))
        t = calcular_totales(lineas, leer_descuento(con, datos, usuario, cotizacion),
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
        _emitir_documento(con, venta_id, documento, avisos, int(config["iva_porcentaje"]))
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
    from ..sii import servicio as sii

    venta["documentos"] = sii.documentos_de_venta(con, venta_id)
    return venta


def devolver(con, venta_id, datos, usuario, avisos=None):
    """Devolución parcial o total. El dinero sale del turno abierto de la caja indicada.

    Si la venta tiene boleta o factura electrónica, se emite la nota de crédito.
    """
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
        _emitir_nota_credito(con, devolucion_id, avisos)
    return devolucion_id


def _emitir_nota_credito(con, devolucion_id, avisos):
    from ..sii import servicio as sii

    if not sii.activo(con):
        return
    con.execute("SAVEPOINT nota_credito_sii")
    try:
        sii.emitir_nota_credito(con, devolucion_id, _secreto(), int(leer_config(con)["iva_porcentaje"]))
        con.execute("RELEASE nota_credito_sii")
    except Exception as e:  # noqa: BLE001 (la devolución se hace igual)
        con.execute("ROLLBACK TO nota_credito_sii")
        con.execute("RELEASE nota_credito_sii")
        registro.warning("Sin nota de crédito para la devolución %s: %s", devolucion_id, e)
        if avisos is not None:
            avisos.append(f"La devolución quedó registrada, pero sin nota de crédito electrónica: {e}")


def crear_cotizacion(con, datos, usuario):
    with transaccion(con):
        lineas = calcular_lineas(con, datos.get("items"),
                                 puede(usuario, con, "cambiar_precio"),
                                 permitir_recetas=False,
                                 puede_comun=puede(usuario, con, "articulo_comun"))
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
