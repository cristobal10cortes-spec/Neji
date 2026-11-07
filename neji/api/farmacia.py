"""Vademécum: principios activos, su ficha clínica y los productos que los contienen."""

import csv
import io
from pathlib import Path

from flask import Response, jsonify, request

from ..auth import con_permiso
from ..db import ahora, fila, filas, get_db, sin_acentos, transaccion
from ..servicios.farmacia import SQL_PRINCIPIOS_TEXTO, clave_base, normalizar_nombre
from ..servicios.recetario import MAX_PRECIO, UNIDADES_PRINCIPIO, numero
from ..validar import ErrorNegocio, booleano, celda_csv, entero, leer_celda_csv, texto
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
    precio = None if precio in (None, "") else float(numero(precio, "precio por unidad", minimo=0,
                                                             maximo=MAX_PRECIO, decimales=6))
    if unidad and unidad not in UNIDADES_PRINCIPIO:
        raise ErrorNegocio("La unidad del recetario debe ser mcg, mg, g, ml o UI.")
    if (precio is None) != (unidad is None):
        raise ErrorNegocio("Para usarlo en el recetario indica la unidad y el precio por unidad "
                           "(o deja ambos vacíos).")
    return {
        "nombre": nombre,
        "accion_terapeutica": texto(datos, "accion_terapeutica", max_largo=2000),
        "dosis": texto(datos, "dosis", max_largo=2000),
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
        condiciones.append("(sin_acentos(pa.nombre) LIKE ? OR sin_acentos(pa.accion_terapeutica) LIKE ?)")
        params += [f"%{sin_acentos(palabra)}%"] * 2
    if booleano(request.args.get("recetario", "")):
        condiciones.append("pa.precio_receta IS NOT NULL")
    if booleano(request.args.get("con_stock", "")):
        condiciones.append("""EXISTS (SELECT 1 FROM producto_principios pp JOIN productos p ON p.id = pp.producto_id
                                      WHERE pp.principio_id = pa.id AND p.activo = 1
                                        AND (p.usa_inventario = 0 OR p.existencia > 0))""")
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    limite = min(entero(request.args.get("limite") or 1000, "límite", minimo=1), 10000)
    return jsonify(filas(get_db().execute(
        f"""SELECT pa.*, {SQL_CONTEOS} FROM principios_activos pa {where}
            ORDER BY sin_acentos(pa.nombre) LIMIT ?""", params + [limite])))


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
@con_permiso("vademecum")
def crear_principio():
    datos = _leer_principio(datos_json())
    con = get_db()
    with transaccion(con):
        previo = con.execute("SELECT nombre FROM principios_activos WHERE sin_acentos(nombre) = sin_acentos(?)",
                             (datos["nombre"],)).fetchone()
        if previo:
            raise ErrorNegocio(f"Ya existe el principio activo {previo['nombre']}.")
        fecha = ahora()
        datos.update(creado=fecha, actualizado=fecha)
        nuevo = con.execute(
            f"INSERT INTO principios_activos ({', '.join(datos)}) VALUES ({', '.join('?' for _ in datos)})",
            list(datos.values())).lastrowid
    return ver_principio(nuevo), 201


@bp.put("/principios/<int:principio_id>")
@con_permiso("vademecum")
def editar_principio(principio_id):
    datos = _leer_principio(datos_json())
    con = get_db()
    with transaccion(con):
        if not con.execute("SELECT 1 FROM principios_activos WHERE id = ?", (principio_id,)).fetchone():
            raise ErrorNegocio("Principio activo no encontrado.", status=404)
        previo = con.execute("SELECT nombre FROM principios_activos "
                             "WHERE sin_acentos(nombre) = sin_acentos(?) AND id <> ?",
                             (datos["nombre"], principio_id)).fetchone()
        if previo:
            raise ErrorNegocio(f"Ya existe otro principio activo llamado {previo['nombre']}.")
        datos["actualizado"] = ahora()
        con.execute(f"UPDATE principios_activos SET {', '.join(f'{k} = ?' for k in datos)} WHERE id = ?",
                    list(datos.values()) + [principio_id])
    return ver_principio(principio_id)


@bp.delete("/principios/<int:principio_id>")
@con_permiso("vademecum")
def borrar_principio(principio_id):
    con = get_db()
    with transaccion(con):
        usados = con.execute(
            "SELECT COUNT(*) FROM producto_principios pp JOIN productos p ON p.id = pp.producto_id "
            "WHERE pp.principio_id = ? AND p.activo = 1", (principio_id,)).fetchone()[0]
        if usados:
            raise ErrorNegocio(f"Está asignado a {usados} producto(s). Quítalo de esos productos antes "
                               "de eliminarlo.")
        # Vínculos de productos eliminados (que siguen en el historial de ventas)
        con.execute("DELETE FROM producto_principios WHERE principio_id = ?", (principio_id,))
        con.execute("DELETE FROM principios_activos WHERE id = ?", (principio_id,))
    return jsonify(ok=True)


# --- Importar y exportar el vademécum (Excel o CSV) ------------------------------------------------------
# La planilla tiene una fila por principio activo. Al importar se busca cada uno por su nombre (sin importar
# tildes, mayúsculas ni la sal: «LOSARTÁN» completa la ficha de «LOSARTAN POTASICO»); si no existe, se crea.
# «completar» solo llena lo que está vacío (lo que la farmacia ya escribió se respeta); «reemplazar» pone lo
# del archivo encima. Una celda vacía nunca borra lo que había.

COLUMNAS_VADEMECUM = [
    ("nombre", "Principio activo"), ("accion_terapeutica", "Para qué sirve"), ("dosis", "Dosis habitual"),
    ("efectos_adversos", "Efectos adversos"), ("contraindicaciones", "Contraindicaciones y precauciones"),
    ("notas", "Notas"), ("unidad_receta", "Unidad recetario"), ("precio_receta", "Precio recetario"),
]
CAMPOS_FICHA = ("accion_terapeutica", "dosis", "efectos_adversos", "contraindicaciones", "notas")
ALIAS_VADEMECUM = {sin_acentos(k): v for k, v in {
    "principio activo": "nombre", "principio": "nombre", "nombre": "nombre", "principios activos": "nombre",
    "p. activo": "nombre", "farmaco": "nombre", "droga": "nombre", "medicamento": "nombre",
    "para que sirve": "accion_terapeutica", "accion terapeutica": "accion_terapeutica",
    "accion / uso terapeutico": "accion_terapeutica", "uso terapeutico": "accion_terapeutica",
    "accion": "accion_terapeutica", "uso": "accion_terapeutica", "indicaciones": "accion_terapeutica",
    "indicacion": "accion_terapeutica",
    "dosis habitual": "dosis", "dosis": "dosis", "posologia": "dosis", "dosificacion": "dosis",
    "efectos adversos": "efectos_adversos", "reacciones adversas": "efectos_adversos",
    "efectos secundarios": "efectos_adversos",
    "contraindicaciones y precauciones": "contraindicaciones", "contraindicaciones e interacciones": "contraindicaciones",
    "contraindicaciones": "contraindicaciones", "precauciones": "contraindicaciones",
    "notas": "notas", "nota": "notas", "observaciones": "notas",
    "otros nombres": "otros_nombres", "sinonimos": "otros_nombres", "alias": "otros_nombres",
    "unidad recetario": "unidad_receta", "precio recetario": "precio_receta",
}.items()} | {c: c for c, _ in COLUMNAS_VADEMECUM} | {"otros_nombres": "otros_nombres"}
MODOS_IMPORTAR = ("completar", "reemplazar")
VADEMECUM_BASE = Path(__file__).resolve().parent.parent / "static" / "referencia" / "vademecum_base.csv"


def _filas_vademecum(contenido):
    """Planilla (Excel o CSV) -> [(fila, {columna: texto})], desde la fila de los títulos."""
    from ..xlsx import es_xls_antiguo, es_xlsx, leer_xlsx
    from .productos import _filas_csv

    if es_xls_antiguo(contenido):
        raise ErrorNegocio("Es una planilla de Excel antigua (.xls): ábrela en Excel y guárdala como «Libro de "
                           "Excel (.xlsx)» o como CSV, y súbela de nuevo.")
    filas_planilla = leer_xlsx(contenido) if es_xlsx(contenido) else _filas_csv(contenido)
    for inicio, f in enumerate(filas_planilla[:10]):
        titulos = [ALIAS_VADEMECUM.get(sin_acentos((c or "").strip().lower()), "") for c in f]
        if "nombre" in titulos:
            break
    else:
        raise ErrorNegocio("No se encontró la columna «Principio activo». La primera fila debe tener los títulos: "
                           "Principio activo, Para qué sirve, Dosis habitual, Efectos adversos, "
                           "Contraindicaciones y precauciones, Notas.")
    return [(n, {t: leer_celda_csv((f[i] if i < len(f) else "").strip()) for i, t in enumerate(titulos) if t})
            for n, f in enumerate(filas_planilla[inicio + 1:], start=inicio + 2)]


def importar_vademecum(con, registros, modo="completar", crear=True):
    """Crea o completa principios activos desde las filas de una planilla. Dentro de una transacción."""
    if modo not in MODOS_IMPORTAR:
        raise ErrorNegocio("Elige si se completa lo vacío o se reemplaza.")
    por_nombre, por_base = {}, {}

    def recordar(pa):
        por_nombre.setdefault(sin_acentos(pa["nombre"]), []).append(dict(pa))
        por_base.setdefault(clave_base(pa["nombre"]), []).append(por_nombre[sin_acentos(pa["nombre"])][-1])

    for pa in con.execute("SELECT * FROM principios_activos"):
        recordar(pa)
    creados = actualizados = sin_cambios = 0
    errores = []
    for n, r in registros:
        if not any(r.values()):
            continue
        try:
            datos = _leer_principio({k: v for k, v in r.items() if k != "otros_nombres"})
        except ErrorNegocio as e:
            errores.append({"fila": n, "error": e.mensaje})
            continue
        nombres = [datos["nombre"]] + [normalizar_nombre(x) for x in (r.get("otros_nombres") or "").split("|")
                                       if x.strip()]
        destino = [pa for x in nombres for pa in por_nombre.get(sin_acentos(x), [])]
        if not destino:
            destino = [pa for x in nombres for pa in por_base.get(clave_base(x), [])]
        ficha = {k: datos[k] for k in CAMPOS_FICHA if datos[k]}
        if datos["unidad_receta"]:
            ficha |= {"unidad_receta": datos["unidad_receta"], "precio_receta": datos["precio_receta"]}
        if not destino:
            if not crear:
                continue
            fecha = ahora()
            nuevo = {"nombre": datos["nombre"], **ficha, "creado": fecha, "actualizado": fecha}
            nuevo["id"] = con.execute(
                f"INSERT INTO principios_activos ({', '.join(nuevo)}) VALUES ({', '.join('?' for _ in nuevo)})",
                list(nuevo.values())).lastrowid
            recordar(nuevo)
            creados += 1
            continue
        for pa in {id(p): p for p in destino}.values():
            cambios = {k: v for k, v in ficha.items()
                       if v != pa.get(k) and (modo == "reemplazar" or pa.get(k) in (None, ""))}
            if ficha.get("unidad_receta") and ("unidad_receta" in cambios) != ("precio_receta" in cambios):
                cambios.pop("unidad_receta", None)       # la unidad y el precio del recetario van juntos
                cambios.pop("precio_receta", None)
            if not cambios:
                sin_cambios += 1
                continue
            con.execute(f"UPDATE principios_activos SET {', '.join(f'{k} = ?' for k in cambios)}, actualizado = ? "
                        "WHERE id = ?", list(cambios.values()) + [ahora(), pa["id"]])
            pa.update(cambios)
            actualizados += 1
    return {"creados": creados, "actualizados": actualizados, "sin_cambios": sin_cambios, "errores": errores[:200]}


@bp.post("/principios/importar")
@con_permiso("vademecum")
def importar_principios():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        raise ErrorNegocio("Adjunta la planilla del vademécum (Excel o CSV).")
    registros = _filas_vademecum(archivo.read())
    con = get_db()
    with transaccion(con):
        resultado = importar_vademecum(con, registros, request.form.get("modo") or "completar",
                                       crear=booleano(request.form.get("crear", "1")))
    return jsonify(resultado)


@bp.post("/principios/base")
@con_permiso("vademecum")
def cargar_vademecum_base():
    """El vademécum base de Neji (principios activos comunes en lenguaje simple): crea los que falten y completa
    (o reemplaza) las fichas."""
    registros = _filas_vademecum(VADEMECUM_BASE.read_bytes())
    con = get_db()
    with transaccion(con):
        resultado = importar_vademecum(con, registros, (datos_json().get("modo") or "completar"))
    return jsonify(resultado)


@bp.get("/principios/exportar")
@con_permiso("vademecum")
def exportar_principios():
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow([titulo for _, titulo in COLUMNAS_VADEMECUM])
    for pa in get_db().execute("SELECT * FROM principios_activos ORDER BY sin_acentos(nombre)"):
        escritor.writerow([celda_csv(pa[c]) if c not in ("precio_receta",) else
                           ("" if pa[c] is None else str(pa[c]).replace(".", ",")) for c, _ in COLUMNAS_VADEMECUM])
    return Response("\ufeff" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=vademecum.csv"})
