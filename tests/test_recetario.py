"""Recetario magistral. Los totales esperados salieron de ejecutar la calculadora
de CORAND.ERP con los mismos precios (ver docs/analisis-corand.md)."""

import pytest

# Precios semilla de CORAND.ERP (recetario_insumos)
PRINCIPIOS = {
    "PARACETAMOL": ("mg", 0.1),
    "BIOTINA": ("mcg", 1.0),
    "VITAMINA C": ("g", 38.87),
    "ALOE VERA": ("mg", 0.3),
    "CAFEINA": ("mg", 0.2),
}


@pytest.fixture
def recetario(api):
    ids = {}
    for nombre, (unidad, precio) in PRINCIPIOS.items():
        ids[nombre] = api.post("/api/principios", {"nombre": nombre, "unidad_receta": unidad,
                                                   "precio_receta": precio}, esperado=201)["id"]
    formas = {f["nombre"]: f for f in api.get("/api/recetario/formas")}
    return {"pa": ids, "formas": formas}


def calcular(api, recetario, forma, cantidad, componentes, esperado=200):
    datos = {
        "forma_id": recetario["formas"][forma]["id"],
        "cantidad": cantidad,
        "componentes": [
            {"principio_id": recetario["pa"][c[0]], "dosis": c[1], **({"unidad": c[2]} if len(c) > 2 else {})}
            for c in componentes
        ],
    }
    return api.post("/api/recetario/calcular", datos, esperado=esperado)


def test_formas_iniciales_como_corand(recetario):
    f = recetario["formas"]
    assert (f["Cápsulas"]["precio_base"], f["Cápsulas"]["precio_unidad"], f["Cápsulas"]["unidad"]) == (4000, 40, "unidad")
    assert (f["Cremas"]["precio_base"], f["Cremas"]["precio_unidad"], f["Cremas"]["unidad"]) == (4500, 2.5, "g")
    assert (f["Lociones"]["precio_base"], f["Lociones"]["precio_unidad"], f["Lociones"]["unidad"]) == (4000, 1, "ml")


@pytest.mark.parametrize("forma,cantidad,componentes,total_corand", [
    ("Cápsulas", 30, [("PARACETAMOL", 500), ("CAFEINA", 50)], 8330),
    ("Cremas", 50, [("ALOE VERA", 10)], 5682),            # CORAND: 5682,25
    ("Cápsulas", 60, [("VITAMINA C", 0.5)], 9004),         # CORAND: 9003,659
    ("Cápsulas", 30, [("BIOTINA", 5000)], 184688),
    ("Lociones", 100, [], 4879),
    ("Cápsulas", 45, [("PARACETAMOL", 333.33), ("CAFEINA", 12.5)], 8821),  # CORAND: 8820,857
])
def test_mismos_totales_que_corand(api, recetario, forma, cantidad, componentes, total_corand):
    r = calcular(api, recetario, forma, cantidad, componentes)
    assert r["total"] == total_corand
    assert r["neto"] + r["iva"] == r["total"]


def test_detalle_del_calculo(api, recetario):
    r = calcular(api, recetario, "Cápsulas", 30, [("PARACETAMOL", 500), ("CAFEINA", 50)])
    assert r["suma_principios"] == 1800
    assert r["costo_unidades"] == 1200
    assert r["precio_base"] == 4000
    assert (r["neto"], r["iva"], r["total"]) == (7000, 1330, 8330)
    para = r["componentes"][0]
    assert para["subtotal"] == 1500
    assert para["cantidad_total"] == 15000  # 15.000 mg de paracetamol a pesar


def test_conversion_de_unidades(api, recetario):
    en_gramos = calcular(api, recetario, "Cápsulas", 60, [("VITAMINA C", 0.5, "g")])
    en_mg = calcular(api, recetario, "Cápsulas", 60, [("VITAMINA C", 500, "mg")])
    assert en_gramos["total"] == en_mg["total"] == 9004
    biotina_mg = calcular(api, recetario, "Cápsulas", 30, [("BIOTINA", 5, "mg")])
    assert biotina_mg["total"] == 184688


def test_porcentaje_en_cremas(api, recetario):
    # 2 % de aloe vera = 0,02 g = 20 mg por gramo de crema
    por_ciento = calcular(api, recetario, "Cremas", 50, [("ALOE VERA", "2", "%")])
    por_gramo = calcular(api, recetario, "Cremas", 50, [("ALOE VERA", 20)])
    assert por_ciento["total"] == por_gramo["total"]
    r = calcular(api, recetario, "Cápsulas", 30, [("ALOE VERA", 1, "%")], esperado=400)
    assert "gramos o ml" in r["error"]


def test_errores_de_validacion(api, recetario):
    calcular(api, recetario, "Cápsulas", 30, [("PARACETAMOL", 500, "ml")], esperado=400)
    calcular(api, recetario, "Cápsulas", 30.5, [("PARACETAMOL", 500)], esperado=400)
    calcular(api, recetario, "Cápsulas", 30, [("PARACETAMOL", 0)], esperado=400)
    calcular(api, recetario, "Cápsulas", 30, [("PARACETAMOL", 1), ("PARACETAMOL", 2)], esperado=400)
    sin_precio = api.post("/api/principios", {"nombre": "MINOXIDIL"}, esperado=201)
    r = api.post("/api/recetario/calcular", {
        "forma_id": recetario["formas"]["Cremas"]["id"], "cantidad": 50,
        "componentes": [{"principio_id": sin_precio["id"], "dosis": 5}]}, esperado=400)
    assert "no tiene precio" in r["error"]


def test_redondeo_configurable(api, recetario):
    api.put("/api/config", {"receta_redondeo": "10"})
    assert calcular(api, recetario, "Cápsulas", 45, [("PARACETAMOL", 333.33), ("CAFEINA", 12.5)])["total"] == 8820
    api.put("/api/config", {"receta_redondeo": "100"})
    assert calcular(api, recetario, "Cremas", 50, [("ALOE VERA", 10)])["total"] == 5700
    api.put("/api/config", {"receta_redondeo": "7"}, esperado=400)


def guardar(api, recetario, **extra):
    datos = {"forma_id": recetario["formas"]["Cápsulas"]["id"], "cantidad": 30,
             "componentes": [{"principio_id": recetario["pa"]["PARACETAMOL"], "dosis": 500},
                             {"principio_id": recetario["pa"]["CAFEINA"], "dosis": 50}],
             "paciente": "María Soto", "rut_paciente": "11111111-1", "medico": "Dr. Pérez",
             "indicaciones": "1 cápsula cada 8 horas"}
    datos.update(extra)
    return api.post("/api/recetario/recetas", datos, esperado=201)


def test_receta_se_vende_en_el_punto_de_venta(api, turno, recetario, productos):
    receta = guardar(api, recetario)
    assert receta["folio"] == 1 and receta["estado"] == "pendiente"
    assert receta["rut_paciente"] == "11.111.111-1"
    assert receta["descripcion"] == "Receta magistral N° 1 · Cápsulas × 30 cápsulas"

    venta = api.post("/api/ventas", {"caja_id": 1, "items": [
        {"receta_id": receta["id"], "cantidad": 1, "precio": 1},   # el precio del navegador se ignora
        {"producto_id": productos["bebida"]["id"], "cantidad": 1}]}, esperado=201)
    assert venta["total"] == 8330 + 1590
    linea = venta["items"][0]
    assert linea["receta_id"] == receta["id"] and linea["producto_id"] is None
    assert api.get(f"/api/recetario/recetas/{receta['id']}")["estado"] == "vendida"

    r = api.post("/api/ventas", {"caja_id": 1, "items": [{"receta_id": receta["id"], "cantidad": 1}]},
                 esperado=400)
    assert "ya está vendida" in r["error"]

    reporte = api.get("/api/reportes/ventas")
    deps = {d["departamento"]: d["total"] for d in reporte["por_departamento"]}
    assert deps["Recetario magistral"] == 8330
    turno_actual = api.get("/api/caja/1/turno")["turno"]
    assert any(d["departamento"] == "Recetario magistral" for d in turno_actual["departamentos"])


def test_receta_no_se_vende_dos_veces_en_un_ticket_ni_con_cantidad(api, turno, recetario):
    receta = guardar(api, recetario)
    api.post("/api/ventas", {"caja_id": 1, "items": [{"receta_id": receta["id"], "cantidad": 1},
                                                     {"receta_id": receta["id"], "cantidad": 1}]},
             esperado=400)
    api.post("/api/ventas", {"caja_id": 1, "items": [{"receta_id": receta["id"], "cantidad": 2}]},
             esperado=400)
    api.post("/api/cotizaciones", {"items": [{"receta_id": receta["id"], "cantidad": 1}]}, esperado=400)


def test_devolucion_de_receta_la_anula(api, turno, recetario):
    receta = guardar(api, recetario)
    venta = api.post("/api/ventas", {"caja_id": 1, "items": [{"receta_id": receta["id"], "cantidad": 1}]},
                     esperado=201)
    api.post(f"/api/ventas/{venta['id']}/devolucion", {"caja_id": 1, "todo": True}, esperado=201)
    assert api.get(f"/api/recetario/recetas/{receta['id']}")["estado"] == "anulada"


def test_libro_de_recetas_y_anular(api, recetario):
    r1 = guardar(api, recetario)
    r2 = guardar(api, recetario, paciente="Juan Rojas")
    assert [r["folio"] for r in api.get("/api/recetario/recetas")] == [2, 1]
    assert [r["folio"] for r in api.get("/api/recetario/recetas?q=rojas")] == [2]
    assert [r["folio"] for r in api.get("/api/recetario/recetas?q=1")] == [1]
    api.post(f"/api/recetario/recetas/{r1['id']}/anular")
    api.post(f"/api/recetario/recetas/{r1['id']}/anular", esperado=400)
    assert [r["folio"] for r in api.get("/api/recetario/recetas?estado=pendiente")] == [r2["folio"]]
    libro = api.http.get("/api/recetario/recetas.csv").get_data(as_text=True)
    assert "PARACETAMOL 500 mg + CAFEINA 50 mg" in libro and "Juan Rojas" in libro


def test_rut_paciente_invalido(api, recetario):
    api.post("/api/recetario/recetas", {
        "forma_id": recetario["formas"]["Cápsulas"]["id"], "cantidad": 30, "componentes": [],
        "rut_paciente": "12.345.678-9"}, esperado=400)


def test_formas_solo_admin_y_validaciones(api, recetario):
    nueva = api.post("/api/recetario/formas", {"nombre": "Papelillos", "unidad": "unidad",
                                               "nombre_unidad": "papelillo", "precio_base": 3000,
                                               "precio_unidad": 25}, esperado=201)
    assert nueva["nombre_unidad"] == "papelillo"
    api.post("/api/recetario/formas", {"nombre": "papelillos", "unidad": "unidad"}, esperado=400)
    api.put(f"/api/recetario/formas/{nueva['id']}", {"nombre": "Papelillos", "unidad": "litros"},
            esperado=400)
    api.put(f"/api/recetario/formas/{nueva['id']}", {"nombre": "Papelillos", "unidad": "unidad",
                                                     "activa": False})
    assert "Papelillos" not in {f["nombre"] for f in api.get("/api/recetario/formas")}
    assert "Papelillos" in {f["nombre"] for f in api.get("/api/recetario/formas?todas=1")}

    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    api.post("/api/recetario/formas", {"nombre": "Óvulos", "unidad": "unidad"}, esperado=403)
    # el cajero sí puede calcular y guardar recetas
    guardar(api, recetario)


def test_numeros_con_punto_de_miles_y_coma_decimal():
    from neji.servicios.recetario import numero

    assert numero("5.000", "dosis") == 5000
    assert numero("1.234,5", "dosis") == 1234.5
    assert numero("0,5", "dosis") == 0.5
    assert numero("1.5", "dosis") == 1.5       # un solo punto con menos de 3 decimales: decimal
    assert numero("0.500", "dosis") == 0.5     # parte entera 0: nunca es punto de miles


def test_numeros_gigantes_se_rechazan(api, recetario):
    calcular(api, recetario, "Cápsulas", "1e20", [], esperado=400)
    calcular(api, recetario, "Cápsulas", 30, [("PARACETAMOL", "9" * 30)], esperado=400)
    # cada valor dentro de su límite, pero el producto no cabe: error claro, no un 500
    api.put(f"/api/principios/{recetario['pa']['BIOTINA']}", {"nombre": "BIOTINA", "unidad_receta": "mcg",
                                                              "precio_receta": "1.000.000"})
    r = calcular(api, recetario, "Cremas", "100.000", [("BIOTINA", "1.000.000.000", "g")], esperado=400)
    assert "demasiado grande" in r["error"]
    forma = recetario["formas"]["Cápsulas"]
    api.put(f"/api/recetario/formas/{forma['id']}", {"nombre": "Cápsulas", "unidad": "unidad",
                                                    "precio_base": "1e30"}, esperado=400)
    api.put(f"/api/recetario/formas/{forma['id']}", {"nombre": "Cápsulas", "unidad": "unidad",
                                                    "cantidad_sugerida": "30,5"}, esperado=400)


def test_plural_de_la_forma():
    from neji.servicios.recetario import unidad_plural

    assert unidad_plural(30, "unidad", "cápsula") == "cápsulas"
    assert unidad_plural(30, "unidad", "cápsula blanda") == "cápsulas blandas"
    assert unidad_plural(10, "unidad", "jabón") == "jabones"
    assert unidad_plural(10, "unidad", "unidad") == "unidades"
    assert unidad_plural(5, "unidad", "luz") == "luces"
    assert unidad_plural(50, "g", "g") == "g"
    assert unidad_plural(100, "ml", "ml") == "ml"
    assert unidad_plural(1, "unidad", "cápsula") == "cápsula"
    assert unidad_plural(20, "unidad", "óvulos") == "óvulos"
    assert unidad_plural(30, "unidad", "cápsula de gelatina") == "cápsulas de gelatina"
    assert unidad_plural(3, "unidad", "óvulo vaginal") == "óvulos vaginales"


def test_libro_busca_por_rut_y_csv_sin_formulas(api, recetario):
    guardar(api, recetario, rut_paciente="12.345.678-5", paciente="=HYPERLINK(\"http://x\")")
    guardar(api, recetario, rut_paciente="11111111-1", paciente="Otra")
    assert [r["folio"] for r in api.get("/api/recetario/recetas?q=12345678-5")] == [1]
    assert [r["folio"] for r in api.get("/api/recetario/recetas?q=12.345.678-5")] == [1]
    libro = api.http.get("/api/recetario/recetas.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in libro and ";=HYPERLINK" not in libro
