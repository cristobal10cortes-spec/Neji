import pytest

from neji.chile import (calcular_dv, desglosar_iva, formatear_rut, limpiar_rut, redondear_efectivo,
                        validar_rut)


@pytest.mark.parametrize("rut", ["76.086.428-5", "760864285", "11.111.111-1", "12.345.678-5",
                                 "5.126.663-3", "10.000.013-k", "10000013K"])
def test_rut_valido(rut):
    assert validar_rut(rut)


@pytest.mark.parametrize("rut", ["", None, "1", "12.345.678-9", "abc", "76.086.428-K"])
def test_rut_invalido(rut):
    assert not validar_rut(rut)


def test_formato_rut():
    assert limpiar_rut("12.345.678-k") == "12345678-K"
    assert formatear_rut("123456785") == "12.345.678-5"
    assert calcular_dv(10000013) == "K"


@pytest.mark.parametrize("monto,esperado", [
    (1990, 1990), (1991, 1990), (1995, 1990), (1996, 2000), (1999, 2000), (5, 0), (6, 10),
])
def test_redondeo_ley_20956(monto, esperado):
    assert redondear_efectivo(monto) == esperado


def test_desglose_iva():
    assert desglosar_iva(1190) == (1000, 190)
    neto, iva = desglosar_iva(1590)
    assert neto + iva == 1590 and neto == 1336
