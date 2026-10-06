"""Errores de negocio y lectura segura de datos de entrada."""

import re


class ErrorNegocio(Exception):
    """Error que se muestra tal cual al usuario (HTTP 400 por defecto)."""

    def __init__(self, mensaje, status=400, codigo=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status
        self.codigo = codigo


def texto(datos, campo, requerido=False, nombre=None, max_largo=500):
    valor = datos.get(campo)
    valor = "" if valor is None else str(valor).strip()
    if requerido and not valor:
        raise ErrorNegocio(f"Falta {nombre or campo}.")
    if len(valor) > max_largo:
        raise ErrorNegocio(f"{(nombre or campo).capitalize()} es demasiado largo.")
    return valor or None


def entero(valor, nombre, minimo=None, requerido=True):
    """Lee un monto en pesos. Acepta '1.990', '$1990', 1990 o '1990,00'."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if requerido:
            raise ErrorNegocio(f"Falta {nombre}.")
        return None
    if isinstance(valor, bool):
        raise ErrorNegocio(f"{nombre.capitalize()} no es válido.")
    if isinstance(valor, (int, float)):
        numero = valor
    else:
        limpio = re.sub(r"[$\s]", "", str(valor))
        if re.fullmatch(r"-?\d+([.,]\d{1,2})", limpio):
            numero = float(limpio.replace(",", "."))
        else:
            limpio = limpio.replace(".", "").replace(",", "")
            if not re.fullmatch(r"-?\d+", limpio):
                raise ErrorNegocio(f"{nombre.capitalize()} no es un número válido.")
            numero = int(limpio)
    if isinstance(numero, float):
        if numero != numero or numero in (float("inf"), float("-inf")):
            raise ErrorNegocio(f"{nombre.capitalize()} no es válido.")
        numero = int(round(numero))
    if minimo is not None and numero < minimo:
        raise ErrorNegocio(f"{nombre.capitalize()} debe ser al menos {minimo}.")
    return numero


# "5.000" o "1.234.567" (con o sin ",5"): en Chile el punto separa miles y la coma es decimal.
PATRON_MILES = re.compile(r"[1-9]\d{0,2}(\.\d{3})+(,\d+)?")


def texto_a_numero(texto):
    """Normaliza un número escrito a la chilena para float()/Decimal(): '5.000' -> '5000',
    '0,755' -> '0.755', '1.234,5' -> '1234.5'. '1.5' y '0.500' se leen con punto decimal."""
    s = str(texto).strip().replace(" ", "").replace("$", "")
    if PATRON_MILES.fullmatch(s) or "," in s:
        s = s.replace(".", "").replace(",", ".")
    return s


def celda_csv(valor):
    """Evita que Excel interprete como fórmula un texto que empieza con = + - @."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def leer_celda_csv(texto):
    """Inverso de celda_csv: "'=SUMA" -> "=SUMA" al volver a importar un CSV exportado."""
    return texto[1:] if texto[:1] == "'" and texto[1:2] in ("=", "+", "-", "@") else texto


def cantidad(valor, nombre="cantidad", minimo=None, requerido=True, positiva=False):
    """Lee una cantidad con hasta 3 decimales. Acepta coma o punto decimal."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if requerido:
            raise ErrorNegocio(f"Falta {nombre}.")
        return None
    if isinstance(valor, bool):
        raise ErrorNegocio(f"{nombre.capitalize()} no es válida.")
    if isinstance(valor, (int, float)):
        numero = float(valor)
    else:
        try:
            numero = float(texto_a_numero(valor))
        except ValueError:
            raise ErrorNegocio(f"{nombre.capitalize()} no es un número válido.") from None
    if numero != numero or numero in (float("inf"), float("-inf")):
        raise ErrorNegocio(f"{nombre.capitalize()} no es válida.")
    numero = round(numero, 3)
    if positiva and numero <= 0:
        raise ErrorNegocio(f"{nombre.capitalize()} debe ser mayor que cero.")
    if minimo is not None and numero < minimo:
        raise ErrorNegocio(f"{nombre.capitalize()} debe ser al menos {minimo}.")
    return numero


def booleano(valor):
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true", "si", "sí", "s", "x", "yes")
    return bool(valor)


def fecha_flexible(valor, nombre):
    """Acepta AAAA-MM-DD, DD-MM-AAAA o DD/MM/AAAA. Devuelve AAAA-MM-DD o None."""
    from datetime import date

    if valor is None or not str(valor).strip():
        return None
    s = re.split(r"[ T]", str(valor).strip(), maxsplit=1)[0]
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        a, mes, d = (int(x) for x in m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
        if not m:
            raise ErrorNegocio(f"{nombre.capitalize()} debe ser una fecha (AAAA-MM-DD o DD-MM-AAAA).")
        d, mes, a = (int(x) for x in m.groups())
    try:
        return date(a, mes, d).isoformat()
    except ValueError:
        raise ErrorNegocio(f"{nombre.capitalize()} no es una fecha válida.") from None


def fecha(valor, nombre):
    if valor is None or valor == "":
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(valor)):
        raise ErrorNegocio(f"{nombre.capitalize()} debe tener formato AAAA-MM-DD.")
    return str(valor)
