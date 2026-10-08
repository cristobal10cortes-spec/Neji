"""Reglas propias de Chile: RUT, IVA y redondeo de pagos en efectivo."""

import re
from decimal import ROUND_HALF_UP, Decimal


def redondear(valor):
    """Redondea al entero más cercano (0,5 sube), como se hace con pesos."""
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def limpiar_rut(rut):
    """'12.345.678-k' -> '12345678-K'. Devuelve '' si no tiene forma de RUT."""
    if not rut:
        return ""
    limpio = re.sub(r"[^0-9kK]", "", str(rut)).upper()
    if len(limpio) < 2:
        return ""
    return f"{limpio[:-1]}-{limpio[-1]}"


def calcular_dv(cuerpo):
    """Dígito verificador por módulo 11."""
    suma, factor = 0, 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def validar_rut(rut):
    limpio = limpiar_rut(rut)
    if not limpio:
        return False
    cuerpo, dv = limpio.split("-")
    if not cuerpo.isdigit() or not 1 <= len(cuerpo) <= 9:
        return False
    return calcular_dv(cuerpo) == dv


def formatear_rut(rut):
    """'123456785' -> '12.345.678-5'."""
    limpio = limpiar_rut(rut)
    if not limpio:
        return ""
    cuerpo, dv = limpio.split("-")
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv}"


def redondear_efectivo(monto):
    """Ley 20.956: si termina en 1 a 5 baja a la decena, si termina en 6 a 9 sube."""
    resto = monto % 10
    if resto == 0:
        return monto
    if resto <= 5:
        return monto - resto
    return monto + (10 - resto)


def desglosar_iva(monto_afecto, tasa=19):
    """Separa un monto con IVA incluido en (neto, iva)."""
    neto = redondear(Decimal(monto_afecto) * 100 / (100 + Decimal(str(tasa))))
    return neto, monto_afecto - neto
