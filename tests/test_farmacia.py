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
