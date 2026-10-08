"""Recetario magistral: precio de cápsulas, cremas, lociones y otras fórmulas.

Misma fórmula que la calculadora de CORAND.ERP:

    subtotal de cada principio activo = precio por unidad × dosis por unidad de forma × cantidad
    neto  = suma de principios activos + precio por cápsula/gramo/ml × cantidad + valor base
    total = neto + IVA

Además convierte unidades (500 mg = 0,5 g), acepta porcentajes en cremas y lociones
(2 % = 0,02 g por gramo) y calcula cuánto pesar de cada principio activo.
"""

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..chile import desglosar_iva, formatear_rut, validar_rut
from ..db import ahora, fila, leer_config, transaccion
from ..validar import ErrorNegocio, entero, numero_texto, texto, texto_a_numero

UNIDADES_PRINCIPIO = ("mcg", "mg", "g", "ml", "UI")
UNIDADES_DOSIS = UNIDADES_PRINCIPIO + ("%",)
UNIDADES_FORMA = ("unidad", "g", "ml")
FAMILIA = {"mcg": "masa", "mg": "masa", "g": "masa", "ml": "volumen", "UI": "UI"}
EN_BASE = {"mcg": Decimal("0.000001"), "mg": Decimal("0.001"), "g": Decimal(1), "ml": Decimal(1),
           "UI": Decimal(1)}
PASOS_REDONDEO = (1, 10, 50, 100)
MAX_COMPONENTES = 30
MAX_CANTIDAD = Decimal(100000)
MAX_PRECIO = Decimal(10) ** 9
MAX_TOTAL = 10 ** 12


def numero(valor, nombre, positivo=False, minimo=None, maximo=None, decimales=4):
    """Lee un número exacto (Decimal) escrito a la chilena: '0,5', '5.000' (cinco mil), '1.5', 2."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise ErrorNegocio(f"Falta {nombre}.")
    if isinstance(valor, bool):
        raise ErrorNegocio(f"{nombre.capitalize()} no es válido.")
    texto_num = texto_a_numero(valor) if isinstance(valor, str) else str(valor)
    try:
        d = Decimal(texto_num)
    except InvalidOperation:
        raise ErrorNegocio(f"{nombre.capitalize()} no es un número válido.") from None
    if not d.is_finite():
        raise ErrorNegocio(f"{nombre.capitalize()} no es válido.")
    if d.adjusted() > 15:
        raise ErrorNegocio(f"{nombre.capitalize()} es demasiado grande.")
    d = d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    if positivo and d <= 0:
        raise ErrorNegocio(f"{nombre.capitalize()} debe ser mayor que cero.")
    if minimo is not None and d < minimo:
        raise ErrorNegocio(f"{nombre.capitalize()} debe ser al menos {minimo}.")
    if maximo is not None and d > maximo:
        raise ErrorNegocio(f"{nombre.capitalize()} es demasiado grande.")
    return d


def _plano(d, decimales=4):
    """Decimal -> float redondeado, para JSON."""
    return float(d.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP))


def convertir(dosis, unidad, unidad_principio, unidad_forma, nombre):
    """Cantidad del principio activo (en su unidad de precio) por cada cápsula, gramo o ml."""
    if unidad == "%":
        if unidad_forma not in ("g", "ml"):
            raise ErrorNegocio(f"El porcentaje de {nombre} solo se usa en fórmulas medidas en "
                               "gramos o ml (cremas, geles, lociones).")
        if FAMILIA[unidad_principio] == "UI":
            raise ErrorNegocio(f"{nombre} se cobra por UI: indica la dosis en UI, no en %.")
        return dosis / 100 / EN_BASE[unidad_principio]
    if FAMILIA[unidad] != FAMILIA[unidad_principio]:
        raise ErrorNegocio(f"No se puede convertir {unidad} a {unidad_principio} en {nombre}.")
    return dosis * EN_BASE[unidad] / EN_BASE[unidad_principio]


def paso_redondeo(config):
    try:
        paso = int(config.get("receta_redondeo") or 1)
    except ValueError:
        paso = 1
    return paso if paso in PASOS_REDONDEO else 1


def calcular(con, datos):
    """Calcula la receta sin guardarla. Devuelve el detalle completo."""
    if not isinstance(datos, dict):
        raise ErrorNegocio("Datos inválidos.")
    forma = con.execute("SELECT * FROM formas_magistrales WHERE id = ? AND activa = 1",
                        (entero(datos.get("forma_id"), "forma farmacéutica", minimo=1),)).fetchone()
    if forma is None:
        raise ErrorNegocio("La forma farmacéutica no existe o está desactivada.")
    cantidad = numero(datos.get("cantidad"), f"cantidad de {forma['nombre_unidad']}", positivo=True,
                      maximo=MAX_CANTIDAD, decimales=3)
    if forma["unidad"] == "unidad" and cantidad != cantidad.to_integral_value():
        raise ErrorNegocio(f"La cantidad de {forma['nombre_unidad']} debe ser un número entero.")

    componentes_in = datos.get("componentes") or []
    if not isinstance(componentes_in, list):
        raise ErrorNegocio("Formato de componentes inválido.")
    if len(componentes_in) > MAX_COMPONENTES:
        raise ErrorNegocio(f"Una receta puede tener como máximo {MAX_COMPONENTES} principios activos.")

    componentes, vistos, suma = [], set(), Decimal(0)
    for n, c in enumerate(componentes_in, 1):
        if not isinstance(c, dict):
            raise ErrorNegocio(f"El componente {n} no es válido.")
        principio_id = entero(c.get("principio_id"), f"principio activo de la fila {n}", minimo=1)
        if principio_id in vistos:
            raise ErrorNegocio("Hay un principio activo repetido en la receta.")
        vistos.add(principio_id)
        pa = con.execute("SELECT * FROM principios_activos WHERE id = ?", (principio_id,)).fetchone()
        if pa is None:
            raise ErrorNegocio(f"El principio activo de la fila {n} no existe.")
        if pa["precio_receta"] is None or not pa["unidad_receta"]:
            raise ErrorNegocio(f"«{pa['nombre']}» no tiene precio para el recetario. "
                               "Defínelo en Recetario → Configuración.")
        dosis = numero(c.get("dosis"), f"dosis de {pa['nombre']}", positivo=True, maximo=Decimal(10) ** 9)
        unidad = c.get("unidad") or pa["unidad_receta"]
        if unidad not in UNIDADES_DOSIS:
            raise ErrorNegocio(f"Unidad de dosis inválida para {pa['nombre']}.")
        por_unidad = convertir(dosis, unidad, pa["unidad_receta"], forma["unidad"], pa["nombre"])
        precio = Decimal(str(pa["precio_receta"]))
        subtotal = precio * por_unidad * cantidad
        if subtotal > MAX_TOTAL:
            raise ErrorNegocio(f"El subtotal de {pa['nombre']} es demasiado grande. Revisa la dosis y la cantidad.")
        suma += subtotal
        componentes.append({
            "principio_id": pa["id"],
            "nombre": pa["nombre"],
            "dosis": _plano(dosis),
            "unidad": unidad,
            "unidad_precio": pa["unidad_receta"],
            "precio_unidad": float(precio),
            "por_unidad": _plano(por_unidad, 6),
            "cantidad_total": _plano(por_unidad * cantidad, 6),
            "subtotal": _plano(subtotal, 2),
        })

    precio_base = Decimal(str(forma["precio_base"]))
    precio_unidad = Decimal(str(forma["precio_unidad"]))
    costo_unidades = precio_unidad * cantidad
    neto_exacto = suma + costo_unidades + precio_base
    if neto_exacto > MAX_TOTAL:
        raise ErrorNegocio("El total de la receta es demasiado grande. Revisa dosis y cantidades.")

    config = leer_config(con)
    iva_porcentaje = int(config.get("iva_porcentaje") or 19)
    paso = paso_redondeo(config)
    bruto = neto_exacto * (1 + Decimal(iva_porcentaje) / 100)
    total = int((bruto / paso).quantize(Decimal(1), rounding=ROUND_HALF_UP) * paso)
    neto, iva = desglosar_iva(total, iva_porcentaje)

    return {
        "forma_id": forma["id"],
        "forma": forma["nombre"],
        "unidad": forma["unidad"],
        "nombre_unidad": forma["nombre_unidad"],
        "cantidad": _plano(cantidad, 3),
        "componentes": componentes,
        "precio_base": float(precio_base),
        "precio_unidad": float(precio_unidad),
        "suma_principios": _plano(suma, 2),
        "costo_unidades": _plano(costo_unidades, 2),
        "neto_exacto": _plano(neto_exacto, 2),
        "iva_porcentaje": iva_porcentaje,
        "redondeo": paso,
        "neto": neto,
        "iva": iva,
        "total": total,
    }


_SIN_TILDE = str.maketrans("áéíóú", "aeiou")


def _plural_palabra(p):
    if len(p) <= 2 or not any(v in p for v in "aeiouáéíóú") or p.endswith(("s", "x")):
        return p  # abreviaturas (g, ml, gr), "de", palabras ya en plural
    if p.endswith(("l", "n", "r", "d", "z", "j")):
        base = p[:-1] + "c" if p.endswith("z") else p
        return base[:-2] + base[-2:].translate(_SIN_TILDE) + "es"  # jabón -> jabones
    return p + "s"


PREPOSICIONES = {"a", "al", "con", "de", "del", "en", "para", "por", "sin"}


def unidad_plural(cantidad, unidad, nombre_unidad):
    """'cápsula blanda' -> 'cápsulas blandas', 'jabón' -> 'jabones', 'g' -> 'g'.

    Solo cambia lo que va antes de una preposición: 'cápsula de gelatina' -> 'cápsulas de gelatina'.
    """
    if unidad == "ml" or cantidad == 1:
        return nombre_unidad
    palabras = nombre_unidad.split(" ")
    corte = next((i for i, p in enumerate(palabras) if p.lower() in PREPOSICIONES), len(palabras))
    return " ".join([_plural_palabra(p) for p in palabras[:corte]] + palabras[corte:])


def describir(receta):
    """'Receta magistral N° 12 · Cápsulas × 30 cápsulas'."""
    cantidad = receta["cantidad"]
    cantidad_txt = numero_texto(cantidad)
    return (f"Receta magistral N° {receta['folio']} · {receta['forma']} × {cantidad_txt} "
            f"{unidad_plural(cantidad, receta['unidad'], receta['nombre_unidad'])}")


def crear(con, datos, usuario):
    """Calcula y guarda la receta en el libro (estado pendiente)."""
    rut = texto(datos, "rut_paciente", max_largo=15)
    if rut:
        if not validar_rut(rut):
            raise ErrorNegocio("El RUT del paciente no es válido.")
        rut = formatear_rut(rut)
    with transaccion(con):
        r = calcular(con, datos)
        if r["total"] <= 0:
            raise ErrorNegocio("El total de la receta debe ser mayor que cero.")
        if r["total"] > MAX_TOTAL:
            raise ErrorNegocio("El total de la receta es demasiado grande. Revisa dosis y cantidades.")
        folio = con.execute("SELECT COALESCE(MAX(folio), 0) + 1 FROM recetas_magistrales").fetchone()[0]
        return con.execute(
            """INSERT INTO recetas_magistrales (folio, fecha, usuario_id, forma_id, forma, unidad,
                   nombre_unidad, cantidad, componentes, precio_base, precio_unidad, suma_principios,
                   costo_unidades, neto, iva, total, paciente, rut_paciente, medico, indicaciones)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (folio, ahora(), usuario["id"], r["forma_id"], r["forma"], r["unidad"], r["nombre_unidad"],
             r["cantidad"], json.dumps(r["componentes"], ensure_ascii=False), r["precio_base"],
             r["precio_unidad"], r["suma_principios"], r["costo_unidades"], r["neto"], r["iva"],
             r["total"], texto(datos, "paciente", max_largo=120), rut,
             texto(datos, "medico", max_largo=120), texto(datos, "indicaciones", max_largo=1000)),
        ).lastrowid


def obtener(con, receta_id):
    r = fila(con.execute(
        """SELECT r.*, u.nombre AS usuario, v.folio AS venta_folio
           FROM recetas_magistrales r JOIN usuarios u ON u.id = r.usuario_id
           LEFT JOIN ventas v ON v.id = r.venta_id WHERE r.id = ?""", (receta_id,)).fetchone())
    if r is None:
        raise ErrorNegocio("Receta no encontrada.", status=404)
    r["componentes"] = json.loads(r["componentes"])
    r["descripcion"] = describir(r)
    return r


def anular(con, receta_id):
    with transaccion(con):
        if con.execute("UPDATE recetas_magistrales SET estado = 'anulada' "
                       "WHERE id = ? AND estado = 'pendiente'", (receta_id,)).rowcount == 0:
            raise ErrorNegocio("Solo se pueden anular recetas pendientes. Si ya se vendió, "
                               "haz la devolución desde el historial de ventas.")
