"""Importa a Neji POS los datos de CORAND.ERP / Easy Pharma (archivo corand_erp_pro.db).

Trae productos (con principio activo, distribuidor y vencimiento), el vademécum, los
principios activos del recetario con su precio, las fórmulas magistrales y los datos
del negocio para el ticket. Todo ocurre en una sola transacción: si algo falla, no se
importa nada. Los usuarios no se importan porque CORAND guarda las contraseñas sin cifrar.
"""

import os
import shutil
import sqlite3
import tempfile

from ..chile import formatear_rut, redondear, validar_rut
from ..db import ahora, sin_acentos, transaccion
from ..validar import ErrorNegocio, fecha_flexible
from .farmacia import guardar_principios_producto, normalizar_nombre, obtener_o_crear, separar_principios
from .inventario import mover_existencia

UNIDADES_PRINCIPIO = {"mg": "mg", "mcg": "mcg", "ug": "mcg", "µg": "mcg", "g": "g", "gr": "g",
                      "grs": "g", "gramo": "g", "gramos": "g", "ml": "ml", "ui": "UI"}

CONFIG_NEGOCIO = {
    "ticket_empresa": "negocio_nombre",
    "ticket_direccion": "negocio_direccion",
    "ticket_telefono": "negocio_telefono",
    "ticket_correo": "negocio_email",
    "ticket_pie": "ticket_pie",
}

OPCIONES = ("productos", "existencias", "vademecum", "recetario", "negocio")


def unidad_forma(texto):
    """'Cápsulas' -> ('unidad', 'cápsula'), 'Gramos' -> ('g', 'gramo'), 'Mililitros' -> ('ml', 'ml')."""
    t = " ".join((texto or "").split()).lower().rstrip(".")
    if t in ("g", "gr", "grs") or t.startswith("gram"):
        return "g", "gramo"
    if t in ("ml", "cc", "cm3", "cm³") or t.startswith(("mili", "ml")):
        return "ml", "ml"
    if t in ("u", "un", "und", "uds", "unid", "unidad", "unidades"):
        return "unidad", "unidad"
    if t.startswith(("cáps", "caps", "cap")):
        return "unidad", "cápsula"
    if not t:
        return "unidad", "unidad"
    return "unidad", (t[:-1] if t.endswith("s") and len(t) > 3 else t)[:30]


def nombre_forma(texto):
    t = " ".join(str(texto or "").split())
    return (t[:1].upper() + t[1:].lower())[:60]


def _numero(valor):
    try:
        return float(str(valor).replace(",", ".")) if valor not in (None, "") else 0.0
    except ValueError:
        return 0.0


def _abrir_copia(ruta):
    """Copia el archivo a un temporal y lo abre en solo lectura (nunca se toca el original)."""
    if not os.path.isfile(ruta):
        raise ErrorNegocio("No se encontró el archivo de CORAND.ERP.")
    carpeta = tempfile.mkdtemp(prefix="neji-corand-")
    copia = os.path.join(carpeta, "corand.db")
    shutil.copyfile(ruta, copia)
    for sufijo in ("-wal", "-shm"):  # cambios aún no consolidados por CORAND (WAL)
        if os.path.isfile(ruta + sufijo):
            shutil.copyfile(ruta + sufijo, copia + sufijo)
    origen = sqlite3.connect(copia)
    origen.row_factory = sqlite3.Row
    try:
        tablas = {r[0] for r in origen.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        origen.execute("PRAGMA query_only = 1")
    except sqlite3.DatabaseError:
        origen.close()
        shutil.rmtree(carpeta, ignore_errors=True)
        raise ErrorNegocio("El archivo no es una base de datos válida.") from None
    if not tablas & {"inventario", "vademecum", "recetario_insumos", "recetario_formulas"}:
        origen.close()
        shutil.rmtree(carpeta, ignore_errors=True)
        raise ErrorNegocio("El archivo no parece ser de CORAND.ERP: no tiene inventario, vademecum "
                           "ni recetario.")
    return origen, tablas, carpeta


def _columnas(origen, tabla):
    return {r["name"] for r in origen.execute(f"PRAGMA table_info({tabla})")}


def importar(con, ruta, usuario_id, opciones=None):
    """Importa desde `ruta`. `opciones`: dict con productos, existencias, vademecum, recetario y
    negocio (todas activas por defecto). Devuelve un resumen con contadores y advertencias."""
    opciones = {k: True for k in OPCIONES} | (opciones or {})
    origen, tablas, carpeta = _abrir_copia(ruta)
    cache = {}  # principios activos ya buscados o creados: sin_acentos(nombre) -> id
    r = {"productos_creados": 0, "productos_actualizados": 0, "productos_con_principio": 0,
         "fichas_vademecum": 0, "precios_recetario": 0, "formas": 0, "datos_negocio": 0,
         "advertencias": []}
    avisar = r["advertencias"].append
    try:
        with transaccion(con):
            if opciones["vademecum"] and "vademecum" in tablas:
                _vademecum(con, origen, r, avisar, cache)
            if opciones["recetario"] and "recetario_insumos" in tablas:
                _precios_recetario(con, origen, r, avisar, cache)
            if opciones["recetario"] and "recetario_formulas" in tablas:
                _formas(con, origen, r)
            if opciones["productos"] and "inventario" in tablas:
                _productos(con, origen, r, avisar, usuario_id, opciones["existencias"], cache)
            if opciones["negocio"] and "configuracion" in tablas:
                _negocio(con, origen, r)
            if r["fichas_vademecum"] or r["precios_recetario"] or r["productos_con_principio"]:
                con.execute("UPDATE config SET valor = '1' WHERE clave = 'modulo_farmacia'")
    finally:
        origen.close()
        shutil.rmtree(carpeta, ignore_errors=True)
    r["advertencias"] = r["advertencias"][:200]
    return r


def _vademecum(con, origen, r, avisar, cache):
    columnas = _columnas(origen, "vademecum")
    adversos = "efectos_adversos" if "efectos_adversos" in columnas else "NULL"
    for fila in origen.execute(
            f"SELECT principio_activo, efecto_terapeutico, {adversos} AS efectos_adversos FROM vademecum"):
        clave = str(fila["principio_activo"] or "").strip()
        try:
            principios = separar_principios(clave)
        except ErrorNegocio as e:
            avisar(f"Ficha «{clave[:60]}» omitida: {e.mensaje}")
            continue
        if not principios:
            continue
        if len(principios) > 1:
            # Una ficha de CORAND escrita como «PARACETAMOL + CAFEINA» no corresponde a un solo
            # principio activo: cada uno debe tener su propia ficha.
            avisar(f"Ficha «{clave[:60]}» omitida: combina varios principios activos; "
                   "créela por separado para cada uno.")
            continue
        pid = obtener_o_crear(con, principios[0][0], cache)
        con.execute(
            """UPDATE principios_activos
               SET accion_terapeutica = COALESCE(NULLIF(?, ''), accion_terapeutica),
                   efectos_adversos = COALESCE(NULLIF(?, ''), efectos_adversos), actualizado = ?
               WHERE id = ?""",
            ((fila["efecto_terapeutico"] or "").strip()[:2000],
             (fila["efectos_adversos"] or "").strip()[:2000], ahora(), pid))
        r["fichas_vademecum"] += 1


def _precios_recetario(con, origen, r, avisar, cache):
    vistos = {}  # sin_acentos(nombre) -> (unidad, precio)
    for fila in origen.execute("SELECT nombre, unidad, precio FROM recetario_insumos"):
        nombre = normalizar_nombre(fila["nombre"])
        if not nombre:
            continue
        unidad = UNIDADES_PRINCIPIO.get((fila["unidad"] or "").strip().lower())
        precio = max(_numero(fila["precio"]), 0)
        if unidad is None:
            avisar(f"{nombre}: unidad «{fila['unidad']}» no reconocida; quedó sin precio de recetario.")
            obtener_o_crear(con, nombre, cache)
            continue
        clave = sin_acentos(nombre)
        if clave in vistos and vistos[clave] != (unidad, precio):
            avisar(f"{nombre} aparecía dos veces en el recetario con distinto precio; "
                   f"se usó {precio:g} por {unidad}.")
        vistos[clave] = (unidad, precio)
        con.execute("UPDATE principios_activos SET unidad_receta = ?, precio_receta = ?, actualizado = ? "
                    "WHERE id = ?", (unidad, precio, ahora(), obtener_o_crear(con, nombre, cache)))
    r["precios_recetario"] = len(vistos)


def _formas(con, origen, r):
    existentes = {f["nombre"].casefold(): f["id"] for f in con.execute("SELECT id, nombre FROM formas_magistrales")}
    for fila in origen.execute("SELECT nombre, precio_base, unidad, precio_unidad FROM recetario_formulas"):
        nombre = nombre_forma(fila["nombre"])
        if not nombre:
            continue
        unidad, nombre_unidad = unidad_forma(fila["unidad"])
        valores = (unidad, nombre_unidad, max(_numero(fila["precio_base"]), 0),
                   max(_numero(fila["precio_unidad"]), 0))
        if nombre.casefold() in existentes:
            con.execute("UPDATE formas_magistrales SET unidad = ?, nombre_unidad = ?, precio_base = ?, "
                        "precio_unidad = ?, activa = 1 WHERE id = ?",
                        valores + (existentes[nombre.casefold()],))
        else:
            existentes[nombre.casefold()] = con.execute(
                "INSERT INTO formas_magistrales (nombre, unidad, nombre_unidad, precio_base, precio_unidad) "
                "VALUES (?, ?, ?, ?, ?)", (nombre,) + valores).lastrowid
        r["formas"] += 1


def _departamento(con, nombre, cache):
    nombre = " ".join(str(nombre or "").split())[:60]
    if not nombre:
        return None
    clave = nombre.casefold()
    if clave not in cache:
        row = con.execute("SELECT id FROM departamentos WHERE nombre = ?", (nombre,)).fetchone()
        cache[clave] = row["id"] if row else con.execute(
            "INSERT INTO departamentos (nombre) VALUES (?)", (nombre,)).lastrowid
    return cache[clave]


def _productos(con, origen, r, avisar, usuario_id, actualizar_existencias, cache):
    columnas = _columnas(origen, "inventario")
    opcional = {c: (c if c in columnas else "NULL") for c in
                ("distribuidor", "departamento", "vencimiento", "principio_activo")}
    deps = {}
    fecha = ahora()
    for fila in origen.execute(
            f"""SELECT codigo, nombre, costo, precio_venta, stock,
                       {opcional['distribuidor']} AS distribuidor, {opcional['departamento']} AS departamento,
                       {opcional['vencimiento']} AS vencimiento, {opcional['principio_activo']} AS principio
                FROM inventario"""):
        codigo = str(fila["codigo"] or "").strip()
        if not codigo:
            continue
        if " " in codigo or len(codigo) > 40:
            avisar(f"Código «{codigo[:40]}» omitido: tiene espacios o es demasiado largo.")
            continue
        descripcion = " ".join(str(fila["nombre"] or codigo).split())[:120] or codigo
        try:
            vencimiento = fecha_flexible(fila["vencimiento"], "vencimiento")
        except ErrorNegocio:
            vencimiento = None
            avisar(f"{codigo}: fecha de vencimiento «{fila['vencimiento']}» no válida, se omitió.")
        valores = {
            "descripcion": descripcion,
            "precio_costo": max(redondear(_numero(fila["costo"])), 0),
            "precio_venta": max(redondear(_numero(fila["precio_venta"])), 0),
            "departamento_id": _departamento(con, fila["departamento"], deps),
            "proveedor": " ".join(str(fila["distribuidor"] or "").split())[:80] or None,
            "vencimiento": vencimiento,
        }
        existente = con.execute("SELECT * FROM productos WHERE codigo = ?", (codigo,)).fetchone()
        if existente:
            con.execute(f"UPDATE productos SET {', '.join(f'{k} = ?' for k in valores)}, activo = 1, "
                        "actualizado = ? WHERE id = ?", list(valores.values()) + [fecha, existente["id"]])
            producto_id = existente["id"]
            r["productos_actualizados"] += 1
        else:
            producto_id = con.execute(
                f"""INSERT INTO productos (codigo, {', '.join(valores)}, existencia, creado, actualizado)
                    VALUES (?, {', '.join('?' for _ in valores)}, 0, ?, ?)""",
                [codigo] + list(valores.values()) + [fecha, fecha]).lastrowid
            r["productos_creados"] += 1
        if actualizar_existencias or not existente:
            producto = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
            diferencia = round(_numero(fila["stock"]) - producto["existencia"], 3)
            if diferencia:
                mover_existencia(con, producto, diferencia, "inicial" if not existente else "ajuste",
                                 usuario_id, nota="Importado de CORAND.ERP")
        principio = str(fila["principio"] or "").strip()
        if principio:
            try:
                guardar_principios_producto(con, producto_id, principio, cache)
                r["productos_con_principio"] += 1
            except ErrorNegocio as e:
                avisar(f"{codigo}: principio activo «{principio[:60]}» no se pudo asignar ({e.mensaje})")


def _negocio(con, origen, r):
    datos = {f["clave"]: f["valor"] for f in origen.execute("SELECT clave, valor FROM configuracion")}
    for origen_clave, destino in CONFIG_NEGOCIO.items():
        valor = " ".join(str(datos.get(origen_clave) or "").split())[:500]
        if valor:
            con.execute("UPDATE config SET valor = ? WHERE clave = ?", (valor, destino))
            r["datos_negocio"] += 1
    rut = datos.get("ticket_rut") or ""
    if rut and validar_rut(rut):
        con.execute("UPDATE config SET valor = ? WHERE clave = 'negocio_rut'", (formatear_rut(rut),))
        r["datos_negocio"] += 1
