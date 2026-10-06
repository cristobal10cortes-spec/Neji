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
        limpio = str(valor).strip().replace(" ", "")
        if "," in limpio:
            limpio = limpio.replace(".", "").replace(",", ".")
        try:
            numero = float(limpio)
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


def fecha(valor, nombre):
    if valor is None or valor == "":
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(valor)):
        raise ErrorNegocio(f"{nombre.capitalize()} debe tener formato AAAA-MM-DD.")
    return str(valor)
