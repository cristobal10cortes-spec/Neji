"""Proveedores y sus facturas por pagar: lo que se le debe a cada uno y lo que ya se pagó.

Cada factura se anota con su proveedor, número, fecha, vencimiento (si tiene plazo) y monto total. Las notas de
crédito del proveedor (por devoluciones) restan. «Por pagar» es todo lo que no se ha marcado como pagado; al
pagar se anota la fecha y cómo se pagó (se puede deshacer).
"""

from datetime import date, timedelta

from ..chile import formatear_rut, limpiar_rut, validar_rut
from ..db import ahora, sin_acentos
from ..validar import ErrorNegocio, entero, fecha, texto

TIPOS = {"factura": "Factura", "nota_credito": "Nota de crédito"}
MEDIOS = {"transferencia": "Transferencia", "cheque": "Cheque", "efectivo": "Efectivo", "otro": "Otro"}
ESTADOS = ("por_pagar", "pagada", "todas")
DIAS_POR_VENCER = 7
# Lo que suma o resta cada documento a la deuda.
CON_SIGNO = "CASE f.tipo WHEN 'nota_credito' THEN -f.monto ELSE f.monto END"


# --- Proveedores ------------------------------------------------------------------------------------------

def exigir_proveedor(con, proveedor_id):
    fila = con.execute("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio("Proveedor no encontrado.", status=404)
    return fila


def buscar_por_nombre(con, nombre):
    """El proveedor con ese nombre (sin importar mayúsculas ni tildes), o None."""
    clave = sin_acentos(nombre.strip())
    for fila in con.execute("SELECT * FROM proveedores"):
        if sin_acentos(fila["nombre"]) == clave:
            return fila
    return None


def leer_proveedor(con, datos, proveedor_id=None):
    nombre = texto(datos, "nombre", requerido=True, nombre="el nombre del proveedor", max_largo=80)
    otro = buscar_por_nombre(con, nombre)
    if otro is not None and otro["id"] != proveedor_id:
        raise ErrorNegocio(f"Ya existe el proveedor «{otro['nombre']}».")
    rut = texto(datos, "rut", nombre="el RUT", max_largo=15)
    if rut:
        if not validar_rut(limpiar_rut(rut)):
            raise ErrorNegocio("El RUT del proveedor no es válido.")
        rut = formatear_rut(limpiar_rut(rut))
    return {"nombre": nombre, "rut": rut, "contacto": texto(datos, "contacto", nombre="el contacto", max_largo=120),
            "notas": texto(datos, "notas", nombre="las notas", max_largo=500)}


def crear_proveedor(con, datos):
    p = leer_proveedor(con, datos) | {"creado": ahora()}
    return con.execute(f"INSERT INTO proveedores ({', '.join(p)}) VALUES ({', '.join('?' for _ in p)})",
                       list(p.values())).lastrowid


def proveedor_para_factura(con, datos):
    """El proveedor de una factura: por su id o por su nombre (si es nuevo, se crea). Devuelve (id, nuevo)."""
    if datos.get("proveedor_id"):
        proveedor = exigir_proveedor(con, entero(datos["proveedor_id"], "proveedor", minimo=1))
        if not proveedor["activo"]:
            con.execute("UPDATE proveedores SET activo = 1 WHERE id = ?", (proveedor["id"],))
        return proveedor["id"], False
    nombre = texto(datos, "proveedor", requerido=True, nombre="el proveedor", max_largo=80)
    existente = buscar_por_nombre(con, nombre)
    if existente is not None:
        if not existente["activo"]:
            con.execute("UPDATE proveedores SET activo = 1 WHERE id = ?", (existente["id"],))
        return existente["id"], False
    return crear_proveedor(con, {"nombre": nombre}), True


def listar_proveedores(con, hoy=None):
    """Los proveedores activos con lo que se les debe (por pagar y vencido)."""
    hoy = (hoy or date.today()).isoformat()
    filas = con.execute(
        f"""SELECT p.*,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL THEN {CON_SIGNO} END), 0) AS por_pagar,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' THEN 1 END), 0) AS n_por_pagar,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' AND f.vence < ? THEN f.monto END), 0)
                       AS vencido
            FROM proveedores p LEFT JOIN facturas_proveedor f ON f.proveedor_id = p.id
            WHERE p.activo = 1 GROUP BY p.id ORDER BY por_pagar DESC, p.nombre COLLATE NOCASE""", (hoy,))
    return [dict(f) for f in filas]


def borrar_proveedor(con, proveedor_id):
    """Lo saca de la lista (sus facturas quedan). No se puede si se le debe algo."""
    exigir_proveedor(con, proveedor_id)
    debe = con.execute(f"SELECT COALESCE(SUM({CON_SIGNO}), 0) FROM facturas_proveedor f "
                       "WHERE f.proveedor_id = ? AND f.pagada IS NULL", (proveedor_id,)).fetchone()[0]
    if debe:
        raise ErrorNegocio("Este proveedor tiene facturas por pagar: márcalas como pagadas o bórralas primero.")
    con.execute("UPDATE proveedores SET activo = 0 WHERE id = ?", (proveedor_id,))


def sugeridos(con):
    """Nombres para el campo «Proveedor»: los proveedores y los que tienen los productos (laboratorio/distribuidor)."""
    nombres = {sin_acentos(f["nombre"]): f["nombre"] for f in con.execute(
        "SELECT nombre FROM proveedores WHERE activo = 1")}
    for f in con.execute("SELECT DISTINCT TRIM(proveedor) AS nombre FROM productos "
                         "WHERE proveedor IS NOT NULL AND TRIM(proveedor) != ''"):
        nombres.setdefault(sin_acentos(f["nombre"]), f["nombre"])
    return sorted(nombres.values(), key=sin_acentos)


# --- Facturas ---------------------------------------------------------------------------------------------

def exigir_factura(con, factura_id):
    fila = con.execute("SELECT * FROM facturas_proveedor WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio("Factura no encontrada.", status=404)
    return fila


def leer_factura(con, datos, proveedor_id, factura_id=None):
    tipo = datos.get("tipo") or "factura"
    if tipo not in TIPOS:
        raise ErrorNegocio("El documento es una factura o una nota de crédito.")
    numero = texto(datos, "numero", requerido=True, nombre="el número de la factura", max_largo=30)
    emitida = fecha(datos.get("fecha"), "fecha") or date.today().isoformat()
    vence = fecha(datos.get("vence"), "vencimiento") if tipo == "factura" else None
    if vence and vence < emitida:
        raise ErrorNegocio("El vencimiento no puede ser antes de la fecha de la factura.")
    monto = entero(datos.get("monto"), "el monto", minimo=1)
    if monto > 10_000_000_000:
        raise ErrorNegocio("El monto es demasiado grande.")
    repetida = con.execute("SELECT id FROM facturas_proveedor WHERE proveedor_id = ? AND tipo = ? AND numero = ? "
                           "AND id IS NOT ?", (proveedor_id, tipo, numero, factura_id)).fetchone()
    if repetida:
        proveedor = exigir_proveedor(con, proveedor_id)["nombre"]
        raise ErrorNegocio(f"La {TIPOS[tipo].lower()} N° {numero} de {proveedor} ya está anotada.")
    return {"proveedor_id": proveedor_id, "tipo": tipo, "numero": numero, "fecha": emitida, "vence": vence,
            "monto": monto, "nota": texto(datos, "nota", nombre="la nota", max_largo=300)}


def crear_factura(con, datos, usuario_id):
    proveedor_id, nuevo = proveedor_para_factura(con, datos)
    f = leer_factura(con, datos, proveedor_id) | {"usuario_id": usuario_id, "creado": ahora()}
    factura_id = con.execute(f"INSERT INTO facturas_proveedor ({', '.join(f)}) VALUES ({', '.join('?' for _ in f)})",
                             list(f.values())).lastrowid
    return factura_id, nuevo


def editar_factura(con, factura_id, datos):
    exigir_factura(con, factura_id)
    proveedor_id, nuevo = proveedor_para_factura(con, datos)
    f = leer_factura(con, datos, proveedor_id, factura_id)
    con.execute(f"UPDATE facturas_proveedor SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?",
                list(f.values()) + [factura_id])
    return nuevo


def pagar(con, ids, fecha_pago=None, medio=None):
    """Marca como pagadas esas facturas (y descontadas esas notas de crédito). Devuelve cuántas y el total."""
    if not isinstance(ids, list) or not ids:
        raise ErrorNegocio("Elige las facturas que se pagaron.")
    ids = sorted({entero(i, "factura", minimo=1) for i in ids})
    pagada = fecha(fecha_pago, "fecha de pago") or date.today().isoformat()
    if medio not in (None, "") and medio not in MEDIOS:
        raise ErrorNegocio("Elige cómo se pagó: transferencia, cheque, efectivo u otro.")
    filas = [exigir_factura(con, i) for i in ids]
    ya = [f for f in filas if f["pagada"]]
    if ya:
        raise ErrorNegocio(f"La factura N° {ya[0]['numero']} ya está marcada como pagada.")
    con.executemany("UPDATE facturas_proveedor SET pagada = ?, medio_pago = ? WHERE id = ?",
                    [(pagada, medio or None, i) for i in ids])
    total = sum(-f["monto"] if f["tipo"] == "nota_credito" else f["monto"] for f in filas)
    return len(ids), total


def deshacer_pago(con, factura_id):
    exigir_factura(con, factura_id)
    con.execute("UPDATE facturas_proveedor SET pagada = NULL, medio_pago = NULL WHERE id = ?", (factura_id,))


def listar_facturas(con, estado="por_pagar", proveedor_id=None, q=None, hoy=None):
    """Las facturas (con su proveedor y si está vencida) y el total de la lista (las notas de crédito restan)."""
    if estado not in ESTADOS:
        raise ErrorNegocio("Estado no válido.")
    hoy = (hoy or date.today()).isoformat()
    condiciones, parametros = [], []
    if estado == "por_pagar":
        condiciones.append("f.pagada IS NULL")
    elif estado == "pagada":
        condiciones.append("f.pagada IS NOT NULL")
    if proveedor_id:
        condiciones.append("f.proveedor_id = ?")
        parametros.append(proveedor_id)
    if q:
        condiciones.append("(f.numero LIKE ? OR sin_acentos(p.nombre) LIKE ?)")
        parametros += [f"%{q.strip()}%", f"%{sin_acentos(q.strip())}%"]
    donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    orden = ("f.pagada DESC, f.id DESC" if estado == "pagada"
             else "COALESCE(f.vence, f.fecha), f.fecha, f.id")
    filas = con.execute(
        f"""SELECT f.*, p.nombre AS proveedor, {CON_SIGNO} AS con_signo,
                   (f.pagada IS NULL AND f.tipo = 'factura' AND f.vence IS NOT NULL AND f.vence < ?) AS vencida
            FROM facturas_proveedor f JOIN proveedores p ON p.id = f.proveedor_id
            {donde} ORDER BY {orden} LIMIT 2000""", [hoy] + parametros).fetchall()
    facturas = [dict(f) | {"vencida": bool(f["vencida"])} for f in filas]
    return facturas, sum(f["con_signo"] for f in facturas)


def resumen(con, hoy=None):
    """Para los recuadros de arriba: cuánto se debe en total, cuánto está vencido, cuánto vence en los próximos
    días y cuánto se pagó este mes."""
    dia = hoy or date.today()
    hoy_txt, limite = dia.isoformat(), (dia + timedelta(days=DIAS_POR_VENCER)).isoformat()
    r = con.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN f.pagada IS NULL THEN {CON_SIGNO} END), 0) AS por_pagar,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' THEN 1 END), 0) AS n_por_pagar,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' AND f.vence < ? THEN f.monto END), 0)
                       AS vencido,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' AND f.vence < ? THEN 1 END), 0)
                       AS n_vencidas,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' AND f.vence >= ? AND f.vence <= ?
                                THEN f.monto END), 0) AS por_vencer,
                   COALESCE(SUM(CASE WHEN f.pagada IS NULL AND f.tipo = 'factura' AND f.vence >= ? AND f.vence <= ?
                                THEN 1 END), 0) AS n_por_vencer,
                   COALESCE(SUM(CASE WHEN f.pagada >= ? THEN {CON_SIGNO} END), 0) AS pagado_mes
            FROM facturas_proveedor f""",
        (hoy_txt, hoy_txt, hoy_txt, limite, hoy_txt, limite, dia.replace(day=1).isoformat())).fetchone()
    return dict(r) | {"dias_por_vencer": DIAS_POR_VENCER}
