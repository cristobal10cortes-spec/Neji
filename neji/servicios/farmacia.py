"""Principios activos: ficha de vademécum, vínculo con productos y alternativas."""

import re
from decimal import Decimal, InvalidOperation

from ..db import ahora, filas, sin_acentos
from ..validar import ErrorNegocio, texto_a_numero

# "PARACETAMOL 500 mg", "AMOXICILINA 250mg/5ml", "BETAMETASONA 0,05%", "VITAMINA D3 1000 UI",
# "PENICILINA BENZATINA 1.200.000 UI"
_CONCENTRACION = re.compile(
    r"^(?P<nombre>.+?)\s+(?P<conc>(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:mcg|ug|µg|mg|gr|g|ml|ui|%)"
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


# Sales y formas que no cambian qué principio activo es: «LOSARTÁN POTÁSICO», «CLORHIDRATO DE TRAMADOL» y
# «AMLODIPINO BESILATO» llevan la misma ficha que LOSARTÁN, TRAMADOL y AMLODIPINO.
_SALES = re.compile(
    r"\b(clorhidrato|bromhidrato|besilato|maleato|mesilato|fumarato|succinato|tartrato|potasico|potasica|"
    r"sodico|sodica|calcico|calcica|magnesico|magnesica|trihidrato|dihidrato|monohidrato|hemihidrato|"
    r"sesquihidrato|anhidro|anhidra|micronizado|micronizada)\b")


def clave_base(nombre):
    """El nombre sin tildes, mayúsculas ni sal: para encontrar la ficha de «LOSARTAN POTASICO» en «LOSARTÁN»."""
    texto = _SALES.sub(" ", sin_acentos(nombre or ""))
    texto = re.sub(r"^\s*de\b|\bde\s*$", " ", re.sub(r"\s+", " ", texto).strip())
    return re.sub(r"\s+", " ", texto).strip()


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


def separar_alias(texto):
    """«KITADOL | acetaminofeno» -> ['KITADOL', 'ACETAMINOFENO'] (sin repetidos)."""
    vistos, resultado = set(), []
    for parte in str(texto or "").split("|"):
        alias = normalizar_nombre(parte)
        if alias and sin_acentos(alias) not in vistos:
            vistos.add(sin_acentos(alias))
            resultado.append(alias)
    return resultado


# --- Reconocer principios activos ----------------------------------------------------------------------------
# Un principio activo se encuentra por su nombre (sin tildes ni mayúsculas), por sus otros nombres (sinónimos,
# marcas: «KITADOL») o por su nombre sin la sal (LOSARTAN POTASICO -> LOSARTÁN). En la descripción de un producto
# («KITADOL 500 MG PARACETAMOL X 24 COMP») se buscan todos esos nombres y la concentración que los acompaña.

_UNIDADES = {"mcg": "mcg", "ug": "mcg", "mg": "mg", "g": "g", "gr": "g", "ml": "ml", "ui": "UI", "%": "%"}
_CONC_TEXTO = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(mcg|ug|mg|gr|g|ml|ui|%)(?![a-z])"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(ml|g|dosis)(?![a-z]))?")
MIN_LARGO_NOMBRE = 4          # nombres más cortos (siglas) no se buscan dentro de una descripción


class Reconocedor:
    """Los principios activos del vademécum, para encontrarlos por nombre o dentro de una descripción."""

    def __init__(self, con):
        self.nombres, self.exacto, self.alias, self.base, self.terminos = {}, {}, {}, {}, {}
        self._patron = None
        for pa in con.execute("SELECT id, nombre, otros_nombres FROM principios_activos ORDER BY id"):
            self.agregar(pa["id"], pa["nombre"], pa["otros_nombres"])

    def agregar(self, principio_id, nombre, otros=None):
        self.nombres[principio_id] = nombre
        self.exacto.setdefault(sin_acentos(nombre), principio_id)
        self.base.setdefault(clave_base(nombre), principio_id)
        self.terminos.setdefault(_termino(nombre), principio_id)
        for alias in separar_alias(otros):
            self.alias.setdefault(sin_acentos(alias), principio_id)
            self.base.setdefault(clave_base(alias), principio_id)
            self.terminos.setdefault(_termino(alias), principio_id)
        self._patron = None

    def buscar(self, nombre):
        """Id del principio activo con ese nombre (o uno de sus otros nombres, o sin la sal), o None."""
        clave = sin_acentos(normalizar_nombre(nombre))
        return self.exacto.get(clave) or self.alias.get(clave) or self.base.get(clave_base(nombre))

    def detectar(self, descripcion):
        """[{nombre, concentracion}] de los principios activos que nombra la descripción, en orden."""
        texto = _termino(descripcion)
        if self._patron is None:
            terminos = sorted((t for t in self.terminos if len(t) >= MIN_LARGO_NOMBRE), key=len, reverse=True)
            self._patron = re.compile(r"(?<![a-z0-9])(" + "|".join(map(re.escape, terminos)) + r")(?![a-z0-9])"
                                      ) if terminos else False
        if not self._patron or not texto:
            return []
        encontrados, vistos = [], set()
        for m in self._patron.finditer(texto):
            principio_id = self.terminos[m.group(1)]
            if principio_id not in vistos:
                vistos.add(principio_id)
                encontrados.append((principio_id, m.start(), m.end()))
        if not encontrados:
            return []
        # El volumen del envase («120 ML») no es la concentración; «160 MG/5 ML» sí.
        dosis = [m for m in _CONC_TEXTO.finditer(texto) if m.group(2) != "ml" or m.group(4)]
        antes_primero = bool(dosis) and dosis[0].start() < encontrados[0][1]
        resultado = []
        for i, (principio_id, inicio, fin) in enumerate(encontrados[:20]):
            desde = encontrados[i - 1][2] if i else 0
            hasta = encontrados[i + 1][1] if i + 1 < len(encontrados) else len(texto)
            despues = next((d for d in dosis if fin <= d.start() < hasta), None)
            antes = next((d for d in reversed(dosis) if desde <= d.start() and d.end() <= inicio), None)
            elegida = (antes or despues) if antes_primero else (despues or antes)
            resultado.append({"nombre": self.nombres[principio_id],
                              "concentracion": _texto_dosis(elegida) if elegida else None})
        return resultado


def _termino(texto):
    """Texto para buscar: sin tildes, en minúsculas y con espacios simples (deja números, % , . / +)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%.,/+ ]", " ", sin_acentos(str(texto or "")))).strip()


def _texto_dosis(m):
    numero, unidad = m.group(1), _UNIDADES[m.group(2)]
    base = f"{numero}%" if unidad == "%" else f"{numero} {unidad}"
    if m.group(4):
        base += f"/{(m.group(3) or '') + ' ' if m.group(3) else ''}{_UNIDADES.get(m.group(4), m.group(4))}"
    return base


def obtener_o_crear(con, nombre, cache=None):
    """Id del principio activo con ese nombre; lo crea si no existe. También lo encuentra por sus otros nombres
    o sin la sal: «LOSARTAN POTASICO» queda unido al LOSARTÁN del vademécum.

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
    reconocedor = cache.get(Reconocedor) if cache is not None else None
    if row:
        principio_id = row["id"]
    else:
        if reconocedor is None:
            reconocedor = Reconocedor(con)
            if cache is not None:
                cache[Reconocedor] = reconocedor
        principio_id = reconocedor.buscar(nombre)
        if principio_id is None:
            fecha = ahora()
            principio_id = con.execute(
                "INSERT INTO principios_activos (nombre, creado, actualizado) VALUES (?, ?, ?)",
                (nombre, fecha, fecha)).lastrowid
            reconocedor.agregar(principio_id, nombre)
    if cache is not None:
        cache[clave] = principio_id
    return principio_id


def reconocedor_de(con, cache):
    """El Reconocedor guardado en `cache` (se arma una vez por importación)."""
    if Reconocedor not in cache:
        cache[Reconocedor] = Reconocedor(con)
    return cache[Reconocedor]


def vincular_por_descripcion(con, producto_id, descripcion, cache):
    """Une el producto a los principios activos que nombra su descripción. Devuelve el texto vinculado o None."""
    detectados = reconocedor_de(con, cache).detectar(descripcion)
    if not detectados:
        return None
    guardar_principios_producto(con, producto_id, detectados, cache)
    return " + ".join(d["nombre"] + (f" {d['concentracion']}" if d["concentracion"] else "") for d in detectados)


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
    return principios_de_productos(con, [producto_id])[producto_id]


def principios_de_productos(con, ids):
    """Ficha del vademécum de cada principio activo de varios productos: {producto_id: [...]}."""
    resultado = {i: [] for i in ids}
    if not ids:
        return resultado
    for pa in filas(con.execute(
            f"""SELECT pp.producto_id, pa.id, pa.nombre, pp.concentracion, pa.accion_terapeutica, pa.dosis,
                       pa.efectos_adversos, pa.contraindicaciones, pa.notas
                FROM producto_principios pp JOIN principios_activos pa ON pa.id = pp.principio_id
                WHERE pp.producto_id IN ({', '.join('?' for _ in ids)})
                ORDER BY pp.producto_id, pp.orden""", list(ids))):
        resultado[pa.pop("producto_id")].append(pa)
    return resultado


_EN_MG = {"mcg": Decimal("0.001"), "mg": Decimal(1), "g": Decimal(1000)}


def _numero_limpio(m):
    try:
        return format(Decimal(m.group()).normalize(), "f")
    except InvalidOperation:
        return m.group()


def concentracion_normalizada(texto):
    """'500 mg', '500mg', '0,5 g' y '1.000 mcg'... -> en mg; '250 mg/5 ml' -> '250mg/5ml'.

    Los números se leen a la chilena, igual que en el resto del sistema: '1.000 mg' son mil mg.
    None si no hay dato."""
    s = sin_acentos(texto or "").replace(" ", "")
    if not s:
        return None
    s = re.sub(r"\d+(?:[.,]\d+)*", lambda m: texto_a_numero(m.group()), s)
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
