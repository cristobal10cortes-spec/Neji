"""Catálogo de productos, importación/exportación CSV y kardex por producto."""

import csv
import io

from flask import Response, jsonify, request

from ..auth import solo_admin, usuario_actual
from ..db import ahora, fila, filas, get_db, sin_acentos, transaccion
from ..servicios.farmacia import (SQL_PRINCIPIOS_TEXTO, alternativas, guardar_principios_producto,
                                  principios_de_producto)
from ..servicios.inventario import mover_existencia
from ..validar import (ErrorNegocio, booleano, cantidad, celda_csv, entero, fecha_flexible,
                       leer_celda_csv, texto)
from . import bp, datos_json, sin_costos

COLUMNAS_CSV = ["codigo", "descripcion", "departamento", "tipo_venta", "precio_costo",
                "precio_venta", "precio_mayoreo", "cantidad_mayoreo", "usa_inventario",
                "existencia", "minimo", "maximo", "exento", "principio_activo", "proveedor",
                "vencimiento"]

SELECT_PRODUCTO = f"""
    SELECT p.*, d.nombre AS departamento, {SQL_PRINCIPIOS_TEXTO} AS principios
    FROM productos p LEFT JOIN departamentos d ON d.id = p.departamento_id
"""


def _con_principios(con, producto):
    """Agrega la ficha de cada principio activo (para el aviso del vademécum en la venta)."""
    if producto is not None:
        producto["principios_detalle"] = principios_de_producto(con, producto["id"])
    return producto


def _departamento_id(con, datos):
    """Acepta departamento_id o el nombre del departamento (lo crea si no existe)."""
    if datos.get("departamento_id") not in (None, ""):
        dep_id = entero(datos["departamento_id"], "departamento", minimo=1)
        if not con.execute("SELECT 1 FROM departamentos WHERE id = ?", (dep_id,)).fetchone():
            raise ErrorNegocio("El departamento no existe.")
        return dep_id
    nombre = texto(datos, "departamento", max_largo=60)
    if not nombre:
        return None
    row = con.execute("SELECT id FROM departamentos WHERE nombre = ?", (nombre,)).fetchone()
    if row:
        return row["id"]
    return con.execute("INSERT INTO departamentos (nombre) VALUES (?)", (nombre,)).lastrowid


def leer_producto(con, datos):
    tipo_venta = (datos.get("tipo_venta") or "unidad").strip().lower()
    if tipo_venta not in ("unidad", "granel"):
        raise ErrorNegocio("El tipo de venta debe ser unidad o granel.")
    p = {
        "codigo": texto(datos, "codigo", requerido=True, nombre="el código", max_largo=40),
        "descripcion": texto(datos, "descripcion", requerido=True, nombre="la descripción",
                             max_largo=120),
        "departamento_id": _departamento_id(con, datos),
        "tipo_venta": tipo_venta,
        "precio_costo": entero(datos.get("precio_costo") or 0, "precio de costo", minimo=0),
        "precio_venta": entero(datos.get("precio_venta"), "precio de venta", minimo=0),
        "precio_mayoreo": entero(datos.get("precio_mayoreo"), "precio de mayoreo", minimo=0,
                                 requerido=False),
        "cantidad_mayoreo": cantidad(datos.get("cantidad_mayoreo"), "cantidad para mayoreo",
                                     requerido=False),
        "usa_inventario": 1 if booleano(datos.get("usa_inventario", True)) else 0,
        "minimo": cantidad(datos.get("minimo") or 0, "mínimo", minimo=0),
        "maximo": cantidad(datos.get("maximo"), "máximo", minimo=0, requerido=False),
        "exento": 1 if booleano(datos.get("exento", False)) else 0,
        "proveedor": texto(datos, "proveedor", max_largo=80),
        "vencimiento": fecha_flexible(datos.get("vencimiento"), "vencimiento"),
    }
    if " " in p["codigo"]:
        raise ErrorNegocio("El código no puede tener espacios.")
    if p["cantidad_mayoreo"] is not None and p["cantidad_mayoreo"] <= 0:
        p["cantidad_mayoreo"] = None
    if p["precio_mayoreo"] is None:
        p["cantidad_mayoreo"] = None
    return p


def _guardar_nuevo(con, p, existencia, usuario_id):
    """Crea el producto (o reactiva uno borrado con el mismo código)."""
    previo = con.execute("SELECT * FROM productos WHERE codigo = ?", (p["codigo"],)).fetchone()
    fecha = ahora()
    campos = list(p)
    if previo is not None:
        if previo["activo"]:
            raise ErrorNegocio(f"Ya existe un producto con el código {p['codigo']}.")
        con.execute(
            f"UPDATE productos SET {', '.join(f'{c} = ?' for c in campos)}, activo = 1, "
            "actualizado = ? WHERE id = ?",
            [p[c] for c in campos] + [fecha, previo["id"]])
        producto_id = previo["id"]
        # Un producto reactivado parte sin los principios activos que tenía antes de borrarse.
        con.execute("DELETE FROM producto_principios WHERE producto_id = ?", (producto_id,))
    else:
        producto_id = con.execute(
            f"INSERT INTO productos ({', '.join(campos)}, existencia, creado, actualizado) "
            f"VALUES ({', '.join('?' for _ in campos)}, 0, ?, ?)",
            [p[c] for c in campos] + [fecha, fecha]).lastrowid
    producto = con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if existencia and producto["usa_inventario"]:
        diferencia = existencia - producto["existencia"]
        if diferencia:
            mover_existencia(con, producto, diferencia, "inicial", usuario_id,
                             nota="Existencia inicial")
    return producto_id


@bp.get("/productos")
def listar_productos():
    con = get_db()
    condiciones, params = ["p.activo = 1"], []
    q = (request.args.get("q") or "").strip()
    if q.startswith("%"):
        # Búsqueda por componente (como en CORAND.ERP): %paracetamol
        for palabra in q[1:].split()[:6]:
            condiciones.append(
                "(sin_acentos(p.descripcion) LIKE ? OR p.id IN (SELECT pp.producto_id "
                "FROM producto_principios pp JOIN principios_activos pa ON pa.id = pp.principio_id "
                "WHERE sin_acentos(pa.nombre) LIKE ?))")
            params += [f"%{sin_acentos(palabra)}%"] * 2
    else:
        for palabra in q.split()[:6]:
            condiciones.append("(sin_acentos(p.descripcion) LIKE ? OR p.codigo LIKE ?)")
            params += [f"%{sin_acentos(palabra)}%", f"{palabra}%"]
    if request.args.get("principio_id"):
        condiciones.append("p.id IN (SELECT producto_id FROM producto_principios WHERE principio_id = ?)")
        params.append(entero(request.args["principio_id"], "principio activo"))
    if request.args.get("departamento_id"):
        condiciones.append("p.departamento_id = ?")
        params.append(entero(request.args["departamento_id"], "departamento"))
    if booleano(request.args.get("bajo_minimo", "")):
        condiciones.append("p.usa_inventario = 1 AND p.existencia <= p.minimo")
    where = " AND ".join(condiciones)
    por_pagina = min(entero(request.args.get("por_pagina") or 50, "por_pagina", minimo=1), 500)
    pagina = entero(request.args.get("pagina") or 1, "página", minimo=1)
    total = con.execute(f"SELECT COUNT(*) FROM productos p WHERE {where}", params).fetchone()[0]
    productos = filas(con.execute(
        f"{SELECT_PRODUCTO} WHERE {where} ORDER BY p.descripcion LIMIT ? OFFSET ?",
        params + [por_pagina, (pagina - 1) * por_pagina]))
    return jsonify(productos=sin_costos(productos), total=total, pagina=pagina, por_pagina=por_pagina)


@bp.get("/productos/codigo/<path:codigo>")
def producto_por_codigo(codigo):
    con = get_db()
    producto = fila(con.execute(
        f"{SELECT_PRODUCTO} WHERE p.codigo = ? AND p.activo = 1", (codigo.strip(),)).fetchone())
    if producto is None:
        raise ErrorNegocio(f"No existe un producto con el código {codigo}.", status=404)
    return jsonify(sin_costos(_con_principios(con, producto)))


@bp.get("/productos/<int:producto_id>")
def ver_producto(producto_id):
    con = get_db()
    producto = fila(con.execute(f"{SELECT_PRODUCTO} WHERE p.id = ?", (producto_id,)).fetchone())
    if producto is None:
        raise ErrorNegocio("Producto no encontrado.", status=404)
    return jsonify(sin_costos(_con_principios(con, producto)))


@bp.get("/productos/<int:producto_id>/alternativas")
def alternativas_producto(producto_id):
    """Productos con el mismo principio activo (bioequivalentes, otras marcas)."""
    return jsonify(alternativas(get_db(), producto_id))


@bp.get("/productos/siguiente-codigo")
@solo_admin
def siguiente_codigo():
    """Código interno EAN-13 que empieza con 200 (rango de uso interno)."""
    con = get_db()
    ultimo = con.execute(
        "SELECT codigo FROM productos WHERE length(codigo) = 13 AND codigo GLOB '200[0-9]*' "
        "ORDER BY codigo DESC LIMIT 1").fetchone()
    base = int(ultimo["codigo"][:12]) + 1 if ultimo else 200000000001
    while True:
        cuerpo = str(base)
        suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(cuerpo))
        codigo = cuerpo + str((10 - suma % 10) % 10)
        if not con.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo,)).fetchone():
            return jsonify(codigo=codigo)
        base += 1


@bp.post("/productos")
@solo_admin
def crear_producto():
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        p = leer_producto(con, datos)
        existencia = cantidad(datos.get("existencia") or 0, "existencia")
        producto_id = _guardar_nuevo(con, p, existencia, usuario_actual()["id"])
        if "principios" in datos:
            guardar_principios_producto(con, producto_id, datos["principios"])
    producto = fila(con.execute(f"{SELECT_PRODUCTO} WHERE p.id = ?", (producto_id,)).fetchone())
    return jsonify(_con_principios(con, producto)), 201


@bp.put("/productos/<int:producto_id>")
@solo_admin
def editar_producto(producto_id):
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        if not con.execute("SELECT 1 FROM productos WHERE id = ? AND activo = 1",
                           (producto_id,)).fetchone():
            raise ErrorNegocio("Producto no encontrado.", status=404)
        p = leer_producto(con, datos)
        if con.execute("SELECT 1 FROM productos WHERE codigo = ? AND id <> ?",
                       (p["codigo"], producto_id)).fetchone():
            raise ErrorNegocio(f"Ya existe otro producto con el código {p['codigo']}.")
        con.execute(
            f"UPDATE productos SET {', '.join(f'{c} = ?' for c in p)}, actualizado = ? WHERE id = ?",
            list(p.values()) + [ahora(), producto_id])
        if "principios" in datos:
            guardar_principios_producto(con, producto_id, datos["principios"])
    producto = fila(con.execute(f"{SELECT_PRODUCTO} WHERE p.id = ?", (producto_id,)).fetchone())
    return jsonify(_con_principios(con, producto))


@bp.delete("/productos/<int:producto_id>")
@solo_admin
def borrar_producto(producto_id):
    con = get_db()
    with transaccion(con):
        vendido = con.execute("SELECT 1 FROM venta_items WHERE producto_id = ? LIMIT 1",
                              (producto_id,)).fetchone()
        if vendido:
            con.execute("UPDATE productos SET activo = 0, actualizado = ? WHERE id = ?",
                        (ahora(), producto_id))
        else:
            con.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
    return jsonify(ok=True)


@bp.get("/productos/<int:producto_id>/kardex")
def kardex(producto_id):
    return jsonify(sin_costos(filas(get_db().execute(
        """SELECT m.*, u.nombre AS usuario FROM movimientos_inventario m
           LEFT JOIN usuarios u ON u.id = m.usuario_id
           WHERE m.producto_id = ? ORDER BY m.id DESC LIMIT 500""", (producto_id,)))))


# --- CSV ---------------------------------------------------------------------

def _numero_csv(valor):
    if valor is None:
        return ""
    if isinstance(valor, float):
        return f"{valor:g}".replace(".", ",")
    return str(valor)


@bp.get("/productos/exportar")
@solo_admin
def exportar_productos():
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(COLUMNAS_CSV)
    for p in get_db().execute(f"{SELECT_PRODUCTO} WHERE p.activo = 1 ORDER BY p.descripcion"):
        escritor.writerow([
            celda_csv(p["codigo"]), celda_csv(p["descripcion"]), celda_csv(p["departamento"]), p["tipo_venta"],
            p["precio_costo"], p["precio_venta"], _numero_csv(p["precio_mayoreo"]),
            _numero_csv(p["cantidad_mayoreo"]), "si" if p["usa_inventario"] else "no",
            _numero_csv(p["existencia"]), _numero_csv(p["minimo"]), _numero_csv(p["maximo"]),
            "si" if p["exento"] else "no", celda_csv(p["principios"]), celda_csv(p["proveedor"]),
            p["vencimiento"] or "",
        ])
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=productos.csv"})


ALIAS_COLUMNAS = {
    "código": "codigo", "codigo de barras": "codigo", "código de barras": "codigo",
    "descripción": "descripcion", "nombre": "descripcion", "producto": "descripcion",
    "costo": "precio_costo", "precio costo": "precio_costo", "p. costo": "precio_costo",
    "precio": "precio_venta", "precio venta": "precio_venta", "p. venta": "precio_venta",
    "mayoreo": "precio_mayoreo", "precio mayoreo": "precio_mayoreo",
    "departamento": "departamento", "categoria": "departamento", "categoría": "departamento",
    "inventario": "existencia", "stock": "existencia", "existencias": "existencia",
    "inv. minimo": "minimo", "mínimo": "minimo", "inv. maximo": "maximo", "máximo": "maximo",
    "principio activo": "principio_activo", "principios activos": "principio_activo",
    "principio_activo": "principio_activo", "p. activo": "principio_activo",
    "componente": "principio_activo", "principios": "principio_activo",
    "distribuidor": "proveedor", "laboratorio": "proveedor", "proveedor": "proveedor",
    "fecha vencimiento": "vencimiento", "vence": "vencimiento", "caducidad": "vencimiento",
}


class _PuntoYComa(csv.excel):
    delimiter = ";"


@bp.post("/productos/importar")
@solo_admin
def importar_productos():
    """Crea o actualiza productos desde CSV (separado por ; o ,). Clave: el código."""
    archivo = request.files.get("archivo")
    if archivo is None:
        raise ErrorNegocio("Adjunta un archivo CSV.")
    contenido = archivo.read()
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            texto_csv = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialecto = csv.Sniffer().sniff(texto_csv.splitlines()[0] if texto_csv else "", delimiters=";,\t")
    except csv.Error:
        dialecto = _PuntoYComa
    lector = csv.DictReader(io.StringIO(texto_csv), dialect=dialecto)
    if not lector.fieldnames:
        raise ErrorNegocio("El archivo está vacío.")
    lector.fieldnames = [ALIAS_COLUMNAS.get(c.strip().lower(), c.strip().lower())
                         for c in lector.fieldnames]
    if "codigo" not in lector.fieldnames or "descripcion" not in lector.fieldnames:
        raise ErrorNegocio("El archivo debe tener al menos las columnas codigo y descripcion.")

    con = get_db()
    usuario_id = usuario_actual()["id"]
    creados = actualizados = 0
    errores = []
    for n, registro in enumerate(lector, start=2):
        registro = {k: leer_celda_csv((v or "").strip()) for k, v in registro.items() if k}
        if not any(registro.values()):
            continue
        try:
            with transaccion(con):
                existente = con.execute(
                    "SELECT * FROM productos WHERE codigo = ? AND activo = 1",
                    (registro.get("codigo"),)).fetchone()
                if existente is not None:
                    base = dict(existente)
                    base.pop("departamento_id")
                    base.update({k: v for k, v in registro.items() if v != ""})
                    if "departamento" not in registro or not registro["departamento"]:
                        base["departamento_id"] = existente["departamento_id"]
                    p = leer_producto(con, base)
                    con.execute(
                        f"UPDATE productos SET {', '.join(f'{c} = ?' for c in p)}, actualizado = ? "
                        "WHERE id = ?", list(p.values()) + [ahora(), existente["id"]])
                    if registro.get("existencia") and existente["usa_inventario"]:
                        nueva = cantidad(registro["existencia"], "existencia")
                        if nueva != existente["existencia"]:
                            mover_existencia(con, existente, nueva - existente["existencia"], "ajuste",
                                             usuario_id, nota="Importación CSV")
                    if registro.get("principio_activo"):
                        guardar_principios_producto(con, existente["id"], registro["principio_activo"])
                    actualizados += 1
                else:
                    if not registro.get("precio_venta"):
                        raise ErrorNegocio("Falta precio de venta.")
                    p = leer_producto(con, registro)
                    producto_id = _guardar_nuevo(
                        con, p, cantidad(registro.get("existencia") or 0, "existencia"), usuario_id)
                    if registro.get("principio_activo"):
                        guardar_principios_producto(con, producto_id, registro["principio_activo"])
                    creados += 1
        except ErrorNegocio as e:
            errores.append({"fila": n, "error": e.mensaje})
    return jsonify(creados=creados, actualizados=actualizados, errores=errores[:200])
