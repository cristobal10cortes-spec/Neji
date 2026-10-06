"""Vademécum: principios activos, su ficha clínica y los productos que los contienen."""

from flask import jsonify, request

from ..auth import solo_admin
from ..db import ahora, fila, filas, get_db, transaccion
from ..servicios.farmacia import SQL_PRINCIPIOS_TEXTO, normalizar_nombre
from ..servicios.recetario import UNIDADES_PRINCIPIO, numero
from ..validar import ErrorNegocio, booleano, entero, texto
from . import bp, datos_json, sin_costos

SQL_CONTEOS = """
    (SELECT COUNT(*) FROM producto_principios pp JOIN productos p ON p.id = pp.producto_id
     WHERE pp.principio_id = pa.id AND p.activo = 1) AS productos,
    (SELECT COUNT(*) FROM producto_principios pp JOIN productos p ON p.id = pp.producto_id
     WHERE pp.principio_id = pa.id AND p.activo = 1
       AND (p.usa_inventario = 0 OR p.existencia > 0)) AS con_stock
"""


def _leer_principio(datos):
    nombre = normalizar_nombre(datos.get("nombre"))
    if not nombre:
        raise ErrorNegocio("Falta el nombre del principio activo.")
    if len(nombre) > 120:
        raise ErrorNegocio("El nombre del principio activo es demasiado largo.")
    unidad = texto(datos, "unidad_receta", max_largo=5)
    precio = datos.get("precio_receta")
    precio = None if precio in (None, "") else float(numero(precio, "precio por unidad", minimo=0, decimales=6))
    if unidad and unidad not in UNIDADES_PRINCIPIO:
        raise ErrorNegocio("La unidad del recetario debe ser mcg, mg, g, ml o UI.")
    if (precio is None) != (unidad is None):
        raise ErrorNegocio("Para usarlo en el recetario indica la unidad y el precio por unidad "
                           "(o deja ambos vacíos).")
    return {
        "nombre": nombre,
        "accion_terapeutica": texto(datos, "accion_terapeutica", max_largo=2000),
        "efectos_adversos": texto(datos, "efectos_adversos", max_largo=2000),
        "contraindicaciones": texto(datos, "contraindicaciones", max_largo=2000),
        "notas": texto(datos, "notas", max_largo=4000),
        "unidad_receta": unidad,
        "precio_receta": precio,
    }


@bp.get("/principios")
def listar_principios():
    condiciones, params = [], []
    for palabra in (request.args.get("q") or "").split()[:6]:
        condiciones.append("(pa.nombre LIKE ? OR pa.accion_terapeutica LIKE ?)")
        params += [f"%{palabra}%", f"%{palabra}%"]
    if booleano(request.args.get("recetario", "")):
        condiciones.append("pa.precio_receta IS NOT NULL")
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    limite = min(entero(request.args.get("limite") or 1000, "límite", minimo=1), 5000)
    principios = filas(get_db().execute(
        f"""SELECT pa.*, {SQL_CONTEOS} FROM principios_activos pa {where}
            ORDER BY pa.nombre LIMIT ?""", params + [limite]))
    if booleano(request.args.get("con_stock", "")):
        principios = [p for p in principios if p["con_stock"]]
    return jsonify(principios)


@bp.get("/principios/<int:principio_id>")
def ver_principio(principio_id):
    con = get_db()
    pa = fila(con.execute(f"SELECT pa.*, {SQL_CONTEOS} FROM principios_activos pa WHERE pa.id = ?",
                          (principio_id,)).fetchone())
    if pa is None:
        raise ErrorNegocio("Principio activo no encontrado.", status=404)
    pa["lista_productos"] = sin_costos(filas(con.execute(
        f"""SELECT p.id, p.codigo, p.descripcion, p.precio_venta, p.existencia, p.usa_inventario,
                   p.tipo_venta, pp.concentracion, d.nombre AS departamento,
                   {SQL_PRINCIPIOS_TEXTO} AS principios
            FROM producto_principios pp JOIN productos p ON p.id = pp.producto_id
            LEFT JOIN departamentos d ON d.id = p.departamento_id
            WHERE pp.principio_id = ? AND p.activo = 1
            ORDER BY (p.usa_inventario = 1 AND p.existencia <= 0), p.precio_venta, p.descripcion""",
        (principio_id,))))
    return jsonify(pa)


@bp.post("/principios")
@solo_admin
def crear_principio():
    datos = _leer_principio(datos_json())
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM principios_activos WHERE nombre = ?", (datos["nombre"],)).fetchone():
            raise ErrorNegocio(f"Ya existe el principio activo {datos['nombre']}.")
        fecha = ahora()
        datos.update(creado=fecha, actualizado=fecha)
        nuevo = con.execute(
            f"INSERT INTO principios_activos ({', '.join(datos)}) VALUES ({', '.join('?' for _ in datos)})",
            list(datos.values())).lastrowid
    return ver_principio(nuevo), 201


@bp.put("/principios/<int:principio_id>")
@solo_admin
def editar_principio(principio_id):
    datos = _leer_principio(datos_json())
    con = get_db()
    with transaccion(con):
        if not con.execute("SELECT 1 FROM principios_activos WHERE id = ?", (principio_id,)).fetchone():
            raise ErrorNegocio("Principio activo no encontrado.", status=404)
        if con.execute("SELECT 1 FROM principios_activos WHERE nombre = ? AND id <> ?",
                       (datos["nombre"], principio_id)).fetchone():
            raise ErrorNegocio(f"Ya existe otro principio activo llamado {datos['nombre']}.")
        datos["actualizado"] = ahora()
        con.execute(f"UPDATE principios_activos SET {', '.join(f'{k} = ?' for k in datos)} WHERE id = ?",
                    list(datos.values()) + [principio_id])
    return ver_principio(principio_id)


@bp.delete("/principios/<int:principio_id>")
@solo_admin
def borrar_principio(principio_id):
    con = get_db()
    with transaccion(con):
        usados = con.execute("SELECT COUNT(*) FROM producto_principios WHERE principio_id = ?",
                             (principio_id,)).fetchone()[0]
        if usados:
            raise ErrorNegocio(f"Está asignado a {usados} producto(s). Quítalo de esos productos antes "
                               "de eliminarlo.")
        con.execute("DELETE FROM principios_activos WHERE id = ?", (principio_id,))
    return jsonify(ok=True)
