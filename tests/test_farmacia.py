"""Vademécum y principios activos vinculados a los productos."""

import io

import pytest

from neji.servicios.farmacia import separar_principios
from neji.validar import ErrorNegocio


def test_separar_principios():
    assert separar_principios("paracetamol 500 mg + Cafeina 65mg") == [("PARACETAMOL", "500 mg"),
                                                                       ("CAFEINA", "65mg")]
    assert separar_principios("BETAMETASONA 0,05%; vitamina  d3 1000 UI") == [
        ("BETAMETASONA", "0,05%"), ("VITAMINA D3", "1000 UI")]
    assert separar_principios("AMOXICILINA 250mg/5ml") == [("AMOXICILINA", "250mg/5ml")]
    assert separar_principios("OMEGA 3") == [("OMEGA 3", None)]
    assert separar_principios("") == []
    with pytest.raises(ErrorNegocio):
        separar_principios("IBUPROFENO + ibuprofeno 400 mg")
    with pytest.raises(ErrorNegocio):
        separar_principios("ÁCIDO FÓLICO + acido folico")


@pytest.fixture
def farmacia(api):
    api.post("/api/principios", {"nombre": "Paracetamol", "accion_terapeutica": "Analgésico y antipirético",
                                 "efectos_adversos": "Hepatotoxicidad en sobredosis"}, esperado=201)

    def prod(codigo, descripcion, precio, existencia, principios):
        return api.post("/api/productos", {"codigo": codigo, "descripcion": descripcion,
                                           "precio_venta": precio, "existencia": existencia,
                                           "principios": principios}, esperado=201)
    return {
        "generico": prod("7800001", "PARACETAMOL 500MG X 16", 990, 25, "PARACETAMOL 500 mg"),
        "marca": prod("7800002", "KITADOL 500MG X 24", 2990, 0, "paracetamol 500 mg"),
        "combinado": prod("7800003", "PARACETAMOL + CAFEINA X 20", 1990, 5, "PARACETAMOL 500 mg + CAFEINA 65 mg"),
        "otro": prod("7800004", "IBUPROFENO 400MG X 20", 1490, 12, "IBUPROFENO 400 mg"),
    }


def test_producto_trae_ficha_del_vademecum(api, farmacia):
    p = api.get("/api/productos/codigo/7800001")
    assert p["principios"] == "PARACETAMOL 500 mg"
    assert p["principios_detalle"][0]["accion_terapeutica"] == "Analgésico y antipirético"
    assert api.get("/api/productos/codigo/7800003")["principios"] == "PARACETAMOL 500 mg + CAFEINA 65 mg"


def test_buscador_trae_la_ficha_del_vademecum(api, farmacia):
    sin = api.get("/api/productos?q=paracetamol")["productos"]
    assert all("principios_detalle" not in p for p in sin)
    con = {p["codigo"]: p for p in api.get("/api/productos?q=%25paracetamol&vademecum=1")["productos"]}
    assert con["7800001"]["principios_detalle"][0]["accion_terapeutica"] == "Analgésico y antipirético"
    assert [pa["nombre"] for pa in con["7800003"]["principios_detalle"]] == ["PARACETAMOL", "CAFEINA"]
    assert con["7800003"]["principios_detalle"][1]["concentracion"] == "65 mg"
    sin_principio = api.post("/api/productos", {"codigo": "999", "descripcion": "PARCHE FRIO",
                                                "precio_venta": 500}, esperado=201)
    r = api.get("/api/productos?q=parche&vademecum=1")["productos"]
    assert r[0]["id"] == sin_principio["id"] and r[0]["principios_detalle"] == []
    # Lo que se edita en el vademécum se ve igual en el buscador
    pa = con["7800001"]["principios_detalle"][0]
    api.put(f"/api/principios/{pa['id']}", {"nombre": "PARACETAMOL", "accion_terapeutica": "Analgésico",
                                            "notas": "Máximo 4 g al día"})
    nuevo = api.get("/api/productos?q=7800001&vademecum=1")["productos"][0]["principios_detalle"][0]
    assert nuevo["accion_terapeutica"] == "Analgésico" and nuevo["notas"] == "Máximo 4 g al día"


def test_busqueda_por_componente_con_porcentaje(api, farmacia):
    codigos = {p["codigo"] for p in api.get("/api/productos?q=%25paracetamol")["productos"]}
    assert codigos == {"7800001", "7800002", "7800003"}
    assert {p["codigo"] for p in api.get("/api/productos?q=%25cafe")["productos"]} == {"7800003"}
    # sin % busca por nombre o código, como siempre
    assert {p["codigo"] for p in api.get("/api/productos?q=kitadol")["productos"]} == {"7800002"}


def test_alternativas_mismo_principio_activo(api, farmacia):
    alt = api.get(f"/api/productos/{farmacia['marca']['id']}/alternativas")
    assert [a["codigo"] for a in alt] == ["7800001", "7800003"]
    assert alt[0]["equivalente"] is True and alt[0]["con_stock"] is True
    assert alt[1]["equivalente"] is False   # comparte paracetamol pero trae cafeína
    assert api.get(f"/api/productos/{farmacia['otro']['id']}/alternativas") == []


def test_vademecum_lista_y_ficha(api, farmacia):
    lista = {p["nombre"]: p for p in api.get("/api/principios")}
    assert set(lista) == {"PARACETAMOL", "CAFEINA", "IBUPROFENO"}
    assert lista["PARACETAMOL"]["productos"] == 3 and lista["PARACETAMOL"]["con_stock"] == 2
    ficha = api.get(f"/api/principios/{lista['PARACETAMOL']['id']}")
    assert [p["codigo"] for p in ficha["lista_productos"]] == ["7800001", "7800003", "7800002"]
    assert {p["nombre"] for p in api.get("/api/principios?q=analg")} == {"PARACETAMOL"}


def test_editar_y_borrar_principio(api, farmacia):
    pa = {p["nombre"]: p for p in api.get("/api/principios")}
    api.put(f"/api/principios/{pa['CAFEINA']['id']}", {"nombre": "cafeína", "accion_terapeutica": "Estimulante"})
    assert api.get(f"/api/principios/{pa['CAFEINA']['id']}")["nombre"] == "CAFEÍNA"
    r = api.delete(f"/api/principios/{pa['IBUPROFENO']['id']}", esperado=400)
    assert "1 producto" in r["error"]
    api.put(f"/api/productos/{farmacia['otro']['id']}", {"codigo": "7800004", "descripcion": "IBUPROFENO",
                                                         "precio_venta": 1490, "principios": ""})
    api.delete(f"/api/principios/{pa['IBUPROFENO']['id']}")
    api.post("/api/principios", {"nombre": "PARACETAMOL"}, esperado=400)
    api.post("/api/principios", {"nombre": "X", "precio_receta": 1}, esperado=400)  # falta unidad


def test_editar_producto_sin_principios_no_los_borra(api, farmacia):
    api.put(f"/api/productos/{farmacia['generico']['id']}",
            {"codigo": "7800001", "descripcion": "PARACETAMOL 500MG X 16", "precio_venta": 1090})
    assert api.get("/api/productos/codigo/7800001")["principios"] == "PARACETAMOL 500 mg"


def test_cajero_no_edita_vademecum(api, farmacia):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    assert api.get("/api/principios")
    api.post("/api/principios", {"nombre": "LORATADINA"}, esperado=403)
    alt = api.get(f"/api/productos/{farmacia['marca']['id']}/alternativas")
    assert "precio_costo" not in alt[0]


def test_csv_con_principio_proveedor_y_vencimiento(api):
    csv = ("Código;Descripción;Precio Venta;Principio Activo;Distribuidor;Vencimiento\n"
           "111;LOSARTAN 50MG X 30;2490;LOSARTAN 50 mg;Droguería Sur;31-01-2027\n"
           "222;CETIRIZINA 10MG;1990;cetirizina;;2027-03-15\n"
           "333;MALA FECHA;100;;;31-31-2027\n").encode("utf-8")
    r = api.http.post("/api/productos/importar", data={"archivo": (io.BytesIO(csv), "p.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["creados"] == 2 and r["errores"][0]["fila"] == 4
    p = api.get("/api/productos/codigo/111")
    assert (p["principios"], p["proveedor"], p["vencimiento"]) == ("LOSARTAN 50 mg", "Droguería Sur", "2027-01-31")
    exportado = api.http.get("/api/productos/exportar").get_data(as_text=True)
    assert "LOSARTAN 50 mg;Droguería Sur;2027-01-31" in exportado


def test_vencimientos(api):
    for codigo, venc, stock in (("A", "2020-01-01", 3), ("B", "2099-12-31", 1), ("C", "2021-06-01", 0)):
        api.post("/api/productos", {"codigo": codigo, "descripcion": codigo, "precio_venta": 100,
                                    "existencia": stock, "vencimiento": venc}, esperado=201)
    lista = api.get("/api/inventario/vencimientos?dias=365")
    assert [p["codigo"] for p in lista] == ["A"]
    assert lista[0]["dias_restantes"] < 0
    assert [p["codigo"] for p in api.get("/api/inventario/vencimientos?con_stock=0&dias=36500")] == ["A", "C", "B"]


def test_modulo_farmacia_en_setup(app):
    http = app.test_client()
    assert http.post("/api/setup", json={"negocio_nombre": "Farmacia", "usuario": "a", "password": "1234",
                                         "modulo_farmacia": True}).status_code == 200
    assert http.get("/api/config").get_json()["modulo_farmacia"] == "1"


def test_busquedas_sin_importar_tildes(api):
    api.post("/api/productos", {"codigo": "AF1", "descripcion": "ÁCIDO FÓLICO 1MG X 30", "precio_venta": 990,
                                "principios": "ácido fólico 1 mg"}, esperado=201)
    assert api.get("/api/productos?q=acido folico")["total"] == 1
    assert api.get("/api/productos?q=%25acido")["total"] == 1
    assert {p["nombre"] for p in api.get("/api/principios?q=folico")} == {"ÁCIDO FÓLICO"}
    # Mismo principio aunque se escriba sin tildes: no se duplica
    api.post("/api/productos", {"codigo": "AF2", "descripcion": "FOLIFER", "precio_venta": 1990,
                                "principios": "ACIDO FOLICO"}, esperado=201)
    assert len(api.get("/api/principios")) == 1
    api.post("/api/principios", {"nombre": "acido folico"}, esperado=400)
    api.post("/api/clientes", {"nombre": "José Muñoz"}, esperado=201)
    assert len(api.get("/api/clientes?q=jose munoz")) == 1


def test_concentracion_normalizada():
    from neji.servicios.farmacia import concentracion_normalizada as n

    assert n("500 mg") == n("500mg") == n("0,5 g") == n("0.5 gr") == n("500000 mcg") == "500mg"
    assert n("5000 ug") == n("5 mg")
    assert n("250 mg / 5 ml") == n("250mg/5ml")
    assert n("0,050%") == n("0.05%")
    assert n("") is None and n(None) is None
    # números a la chilena: '1.000 mg' son mil mg, no 1 mg
    assert n("1.000 mg") == n("1 g") == n("1000 mg") != n("1 mg")
    assert n("100.000 UI") == n("100000 UI") != n("100 UI")
    assert n("1.000 mcg") == n("1 mg")
    assert separar_principios("PENICILINA BENZATINA 1.200.000 UI") == [("PENICILINA BENZATINA", "1.200.000 UI")]


def test_alternativas_distinguen_la_dosis(api, farmacia):
    def prod(codigo, principios):
        return api.post("/api/productos", {"codigo": codigo, "descripcion": f"PRODUCTO {codigo}",
                                           "precio_venta": 500, "existencia": 3,
                                           "principios": principios}, esperado=201)
    prod("7800010", "PARACETAMOL 0,5 g")
    prod("7800011", "PARACETAMOL 1 g")
    prod("7800012", "PARACETAMOL")
    alt = {a["codigo"]: a for a in api.get(f"/api/productos/{farmacia['marca']['id']}/alternativas")}
    assert alt["7800001"]["coincidencia"] == "misma_dosis" and alt["7800001"]["equivalente"] is True
    assert alt["7800010"]["coincidencia"] == "misma_dosis"
    assert alt["7800011"]["coincidencia"] == "mismo_principio" and alt["7800011"]["equivalente"] is False
    assert alt["7800012"]["coincidencia"] == "mismo_principio"
    assert alt["7800003"]["coincidencia"] == "comparte"
    orden = [a["coincidencia"] for a in api.get(f"/api/productos/{farmacia['marca']['id']}/alternativas")]
    assert orden == sorted(orden, key=["misma_dosis", "mismo_principio", "comparte"].index)


def test_producto_reactivado_parte_sin_principios(api, turno, farmacia):
    # con ventas, borrar solo lo desactiva (queda en el historial) y el código puede volver a usarse
    api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": farmacia["otro"]["id"], "cantidad": 1}]},
             esperado=201)
    api.delete(f"/api/productos/{farmacia['otro']['id']}")
    api.post("/api/productos", {"codigo": "7800004", "descripcion": "OTRO PRODUCTO", "precio_venta": 100},
             esperado=201)
    reactivado = api.get("/api/productos/codigo/7800004")
    assert reactivado["id"] == farmacia["otro"]["id"] and reactivado["principios"] is None


def test_csv_exportado_no_ejecuta_formulas_y_se_reimporta(api):
    api.post("/api/productos", {"codigo": "555", "descripcion": "=1+2 CREMA", "precio_venta": 100,
                                "principios": "-ALFA"}, esperado=201)
    exportado = api.http.get("/api/productos/exportar").get_data(as_text=True)
    assert "'=1+2 CREMA" in exportado and "'-ALFA" in exportado
    r = api.http.post("/api/productos/importar",
                      data={"archivo": (io.BytesIO(exportado.encode("utf-8")), "p.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["actualizados"] == 1 and not r["errores"]
    assert api.get("/api/productos/codigo/555")["descripcion"] == "=1+2 CREMA"


def test_fecha_flexible_con_hora():
    from neji.validar import fecha_flexible

    assert fecha_flexible("2027-01-31 00:00:00", "vencimiento") == "2027-01-31"
    assert fecha_flexible("2027-01-31T10:00", "vencimiento") == "2027-01-31"


def test_csv_conserva_decimales(api):
    api.post("/api/productos", {"codigo": "G1", "descripcion": "QUESO GRANEL", "precio_venta": 9990,
                                "tipo_venta": "granel", "existencia": 1234.567, "maximo": 1234567},
             esperado=201)
    exportado = api.http.get("/api/productos/exportar").get_data(as_text=True)
    assert "1234,567" in exportado and "1234567" in exportado and "e+" not in exportado
    r = api.http.post("/api/productos/importar",
                      data={"archivo": (io.BytesIO(exportado.encode("utf-8")), "p.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["actualizados"] == 1
    p = api.get("/api/productos/codigo/G1")
    assert (p["existencia"], p["maximo"]) == (1234.567, 1234567)


def test_csv_con_montos_de_excel(api):
    csv = "codigo;descripcion;precio_costo;precio_venta;existencia\nC1;Leche;1.200,00;1.990,00;1.000,00\n"
    r = api.http.post("/api/productos/importar",
                      data={"archivo": (io.BytesIO(csv.encode("utf-8")), "p.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["creados"] == 1
    p = api.get("/api/productos/codigo/C1")
    assert (p["precio_costo"], p["precio_venta"], p["existencia"]) == (1200, 1990, 1000)
