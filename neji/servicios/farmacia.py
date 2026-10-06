"""Principios activos: ficha de vademécum, vínculo con productos y alternativas."""

import re

from ..db import ahora, filas
from ..validar import ErrorNegocio

# "PARACETAMOL 500 mg", "AMOXICILINA 250mg/5ml", "BETAMETASONA 0,05%", "VITAMINA D3 1000 UI"
_CONCENTRACION = re.compile(
    r"^(?P<nombre>.+?)\s+(?P<conc>\d+(?:[.,]\d+)?\s*(?:mcg|ug|µg|mg|gr|g|ml|ui|%)"
    r"(?:\s*/\s*\d*(?:[.,]\d+)?\s*(?:ml|g|dosis|comp|tab|caps|gotas))?)$",
    re.IGNORECASE,
)

# Texto con varios principios activos en un mismo producto. Se agrega a la consulta
# de productos (alias p) y devuelve, en orden, "PARACETAMOL 500 mg + CAFEINA 65 mg".
SQL_PRINCIPIOS_TEXTO = """
    (SELECT GROUP_CONCAT(x, ' + ') FROM (
        SELECT pa.nombre || COALESCE(' ' || pp.concentracion, '') AS x
        FROM producto_principios pp JOIN principios_activos pa ON pa.id = pp.principio_id
        WHERE pp.producto_id = p.id ORDER BY pp.orden))
"""


def normalizar_nombre(nombre):
    return re.sub(r"\s+", " ", str(nombre or "")).strip().upper()


def separar_principios(entrada):
    """'PARACETAMOL 500 mg + CAFEINA' -> [('PARACETAMOL', '500 mg'), ('CAFEINA', None)].

    Acepta texto (separado por + o ;) o una lista de textos o de {nombre, concentracion}.
    """
    if entrada is None:
        return []
    if isinstance(entrada, str):
        partes = re.split(r"[+;\n]", entrada)
    elif isinstance(entrada, list):
        partes = entrada
    else:
        raise ErrorNegocio("Formato de principios activos inválido.")
    resultado, vistos = [], set()
    for parte in partes:
        if isinstance(parte, dict):
            nombre = normalizar_nombre(parte.get("nombre"))
            conc = re.sub(r"\s+", " ", str(parte.get("concentracion") or "")).strip() or None
        else:
            texto = re.sub(r"\s+", " ", str(parte or "")).strip()
            if not texto:
                continue
            m = _CONCENTRACION.match(texto)
            nombre, conc = (normalizar_nombre(m["nombre"]), m["conc"].strip()) if m else (normalizar_nombre(texto), None)
        if not nombre:
            continue
        if len(nombre) > 120 or (conc and len(conc) > 40):
            raise ErrorNegocio("El nombre o la concentración del principio activo es demasiado largo.")
        if nombre in vistos:
            raise ErrorNegocio(f"El principio activo {nombre} está repetido.")
        vistos.add(nombre)
        resultado.append((nombre, conc))
    if len(resultado) > 20:
        raise ErrorNegocio("Un producto puede tener como máximo 20 principios activos.")
    return resultado


def obtener_o_crear(con, nombre):
    """Id del principio activo con ese nombre; lo crea si no existe."""
    nombre = normalizar_nombre(nombre)
    if not nombre:
        raise ErrorNegocio("Falta el nombre del principio activo.")
    row = con.execute("SELECT id FROM principios_activos WHERE nombre = ?", (nombre,)).fetchone()
    if row:
        return row["id"]
    fecha = ahora()
    return con.execute(
        "INSERT INTO principios_activos (nombre, creado, actualizado) VALUES (?, ?, ?)",
        (nombre, fecha, fecha)).lastrowid


def guardar_principios_producto(con, producto_id, entrada):
    """Reemplaza los principios activos del producto. Debe llamarse dentro de una transacción."""
    principios = separar_principios(entrada)
    con.execute("DELETE FROM producto_principios WHERE producto_id = ?", (producto_id,))
    for orden, (nombre, conc) in enumerate(principios):
        con.execute(
            "INSERT INTO producto_principios (producto_id, principio_id, concentracion, orden) "
            "VALUES (?, ?, ?, ?)", (producto_id, obtener_o_crear(con, nombre), conc, orden))
    return principios


def principios_de_producto(con, producto_id):
    return filas(con.execute(
        """SELECT pa.id, pa.nombre, pp.concentracion, pa.accion_terapeutica, pa.efectos_adversos,
                  pa.contraindicaciones, pa.notas
           FROM producto_principios pp JOIN principios_activos pa ON pa.id = pp.principio_id
           WHERE pp.producto_id = ? ORDER BY pp.orden""", (producto_id,)))


def alternativas(con, producto_id):
    """Otros productos con los mismos principios activos (primero los que tienen exactamente
    la misma combinación, después los que comparten alguno), con stock primero y más baratos antes."""
    propios = [r["principio_id"] for r in con.execute(
        "SELECT principio_id FROM producto_principios WHERE producto_id = ?", (producto_id,))]
    if not propios:
        return []
    marcas = ",".join("?" for _ in propios)
    candidatos = filas(con.execute(
        f"""SELECT p.id, p.codigo, p.descripcion, p.precio_venta, p.existencia, p.usa_inventario,
                   p.tipo_venta, d.nombre AS departamento, {SQL_PRINCIPIOS_TEXTO} AS principios,
                   (SELECT COUNT(*) FROM producto_principios x
                    WHERE x.producto_id = p.id AND x.principio_id IN ({marcas})) AS comunes,
                   (SELECT COUNT(*) FROM producto_principios x WHERE x.producto_id = p.id) AS total_pa
            FROM productos p LEFT JOIN departamentos d ON d.id = p.departamento_id
            WHERE p.activo = 1 AND p.id <> ?
              AND p.id IN (SELECT producto_id FROM producto_principios WHERE principio_id IN ({marcas}))""",
        propios + [producto_id] + propios))
    for c in candidatos:
        c["equivalente"] = c["comunes"] == len(propios) == c["total_pa"]
        c["con_stock"] = (not c["usa_inventario"]) or c["existencia"] > 0
    candidatos.sort(key=lambda c: (not c["equivalente"], not c["con_stock"], c["precio_venta"],
                                   c["descripcion"]))
    return candidatos[:50]
