"""Principios activos: ficha de vademécum, vínculo con productos y alternativas."""

import re
from decimal import Decimal, InvalidOperation

from ..db import ahora, filas, sin_acentos
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
        if sin_acentos(nombre) in vistos:
            raise ErrorNegocio(f"El principio activo {nombre} está repetido.")
        vistos.add(sin_acentos(nombre))
        resultado.append((nombre, conc))
    if len(resultado) > 20:
        raise ErrorNegocio("Un producto puede tener como máximo 20 principios activos.")
    return resultado


def obtener_o_crear(con, nombre, cache=None):
    """Id del principio activo con ese nombre; lo crea si no existe.

    `cache` (opcional, un dict) evita repetir la búsqueda al importar miles de productos.
    """
    nombre = normalizar_nombre(nombre)
    if not nombre:
        raise ErrorNegocio("Falta el nombre del principio activo.")
    clave = sin_acentos(nombre)
    if cache is not None and clave in cache:
        return cache[clave]
    # Sin importar tildes: "ÁCIDO FÓLICO" y "ACIDO FOLICO" son el mismo principio activo.
    row = con.execute("SELECT id FROM principios_activos WHERE sin_acentos(nombre) = ? "
                      "ORDER BY id LIMIT 1", (clave,)).fetchone()
    if row:
        principio_id = row["id"]
    else:
        fecha = ahora()
        principio_id = con.execute(
            "INSERT INTO principios_activos (nombre, creado, actualizado) VALUES (?, ?, ?)",
            (nombre, fecha, fecha)).lastrowid
    if cache is not None:
        cache[clave] = principio_id
    return principio_id


def guardar_principios_producto(con, producto_id, entrada, cache=None):
    """Reemplaza los principios activos del producto. Debe llamarse dentro de una transacción."""
    principios = separar_principios(entrada)
    con.execute("DELETE FROM producto_principios WHERE producto_id = ?", (producto_id,))
    for orden, (nombre, conc) in enumerate(principios):
        con.execute(
            "INSERT INTO producto_principios (producto_id, principio_id, concentracion, orden) "
            "VALUES (?, ?, ?, ?)", (producto_id, obtener_o_crear(con, nombre, cache), conc, orden))
    return principios


def principios_de_producto(con, producto_id):
    return filas(con.execute(
        """SELECT pa.id, pa.nombre, pp.concentracion, pa.accion_terapeutica, pa.efectos_adversos,
                  pa.contraindicaciones, pa.notas
           FROM producto_principios pp JOIN principios_activos pa ON pa.id = pp.principio_id
           WHERE pp.producto_id = ? ORDER BY pp.orden""", (producto_id,)))


_EN_MG = {"mcg": Decimal("0.001"), "mg": Decimal(1), "g": Decimal(1000)}


def _numero_limpio(m):
    try:
        return format(Decimal(m.group()).normalize(), "f")
    except InvalidOperation:
        return m.group()


def concentracion_normalizada(texto):
    """'500 mg', '500mg' y '0,5 g' -> '500mg'; '250 mg/5 ml' -> '250mg/5ml'. None si no hay dato."""
    s = sin_acentos(texto or "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    s = re.sub(r"(?<![a-z])(ug|µg|μg)", "mcg", s)
    s = re.sub(r"(?<=\d)grs?(?![a-z])", "g", s)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(mcg|mg|g)", s)
    if m:
        mg = (Decimal(m[1]) * _EN_MG[m[2]]).normalize()
        return format(mg, "f") + "mg"
    return re.sub(r"\d+(?:\.\d+)?", _numero_limpio, s)


# Qué tan parecida es una alternativa al producto original (de más a menos).
COINCIDENCIAS = ("misma_dosis", "mismo_principio", "comparte")


def alternativas(con, producto_id):
    """Otros productos con los mismos principios activos, de lo más parecido a lo menos:

    - misma_dosis: la misma combinación de principios activos y la misma concentración;
    - mismo_principio: la misma combinación, pero la dosis es distinta o no está registrada;
    - comparte: solo comparte alguno de los principios activos.

    Dentro de cada grupo van primero los que tienen stock y los más baratos.
    """
    propios = {r["principio_id"]: concentracion_normalizada(r["concentracion"]) for r in con.execute(
        "SELECT principio_id, concentracion FROM producto_principios WHERE producto_id = ?", (producto_id,))}
    if not propios:
        return []
    marcas = ",".join("?" for _ in propios)
    candidatos = filas(con.execute(
        f"""SELECT p.id, p.codigo, p.descripcion, p.precio_venta, p.existencia, p.usa_inventario,
                   p.tipo_venta, d.nombre AS departamento, {SQL_PRINCIPIOS_TEXTO} AS principios
            FROM productos p LEFT JOIN departamentos d ON d.id = p.departamento_id
            WHERE p.activo = 1 AND p.id <> ?
              AND p.id IN (SELECT producto_id FROM producto_principios WHERE principio_id IN ({marcas}))""",
        [producto_id] + list(propios)))
    composicion = {}
    if candidatos:
        ids = [c["id"] for c in candidatos]
        for r in con.execute(
                f"SELECT producto_id, principio_id, concentracion FROM producto_principios "
                f"WHERE producto_id IN ({','.join('?' for _ in ids)})", ids):
            composicion.setdefault(r["producto_id"], {})[r["principio_id"]] = \
                concentracion_normalizada(r["concentracion"])
    for c in candidatos:
        suya = composicion.get(c["id"], {})
        if suya.keys() != propios.keys():
            c["coincidencia"] = "comparte"
        elif None not in propios.values() and suya == propios:
            c["coincidencia"] = "misma_dosis"
        else:
            c["coincidencia"] = "mismo_principio"
        c["equivalente"] = c["coincidencia"] == "misma_dosis"
        c["con_stock"] = (not c["usa_inventario"]) or c["existencia"] > 0
    candidatos.sort(key=lambda c: (COINCIDENCIAS.index(c["coincidencia"]), not c["con_stock"],
                                   c["precio_venta"], c["descripcion"]))
    return candidatos[:50]
