import io


def test_setup_solo_una_vez_y_login(app):
    http = app.test_client()
    assert http.get("/api/estado").get_json()["configurado"] is False
    assert http.get("/api/productos").status_code == 401
    assert http.post("/api/setup", json={"negocio_nombre": "X", "usuario": "a",
                                         "password": "1234"}).status_code == 200
    assert http.post("/api/setup", json={"negocio_nombre": "Y", "usuario": "b",
                                         "password": "1234"}).status_code == 409
    http.post("/api/logout")
    assert http.post("/api/login", json={"usuario": "a", "password": "mala"}).status_code == 401
    assert http.post("/api/login", json={"usuario": "A", "password": "1234"}).status_code == 200


def test_cajero_no_entra_a_reportes(api):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    api.get("/api/reportes/ventas", esperado=403)
    api.put("/api/config", {"negocio_nombre": "Otro"}, esperado=403)


def test_cajero_no_ve_costos(api, turno, productos):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    assert "precio_costo" not in api.get("/api/productos/codigo/PAN")
    assert "precio_costo" not in api.get("/api/productos")["productos"][0]
    venta = api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": productos["pan"]["id"],
                                                              "cantidad": 1}]}, esperado=201)
    assert "precio_costo" not in venta["items"][0]
    assert "ganancia" not in api.get("/api/caja/1/turno")["turno"]


def test_no_se_puede_quitar_ultimo_admin(api):
    api.put("/api/usuarios/1", {"rol": "cajero"}, esperado=400)


def test_codigo_interno_ean13(api):
    codigo = api.get("/api/productos/siguiente-codigo")["codigo"]
    assert codigo == "2000000000015"
    api.post("/api/productos", {"codigo": codigo, "descripcion": "A", "precio_venta": 1}, esperado=201)
    assert api.get("/api/productos/siguiente-codigo")["codigo"] == "2000000000022"


def test_producto_duplicado_y_reactivar(api, turno):
    p = api.post("/api/productos", {"codigo": "A1", "descripcion": "A", "precio_venta": 100,
                                    "existencia": 5}, esperado=201)
    api.post("/api/productos", {"codigo": "A1", "descripcion": "B", "precio_venta": 1}, esperado=400)
    api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": p["id"], "cantidad": 1}]},
             esperado=201)
    api.delete(f"/api/productos/{p['id']}")
    api.get("/api/productos/codigo/A1", esperado=404)
    nuevo = api.post("/api/productos", {"codigo": "A1", "descripcion": "Nuevo", "precio_venta": 200},
                     esperado=201)
    assert nuevo["id"] == p["id"] and nuevo["descripcion"] == "Nuevo"


def test_busqueda_productos(api, productos):
    r = api.get("/api/productos?q=cola bebida")
    assert [p["codigo"] for p in r["productos"]] == ["7801610001196"]
    assert api.get("/api/productos/codigo/PAN")["descripcion"] == "Pan batido"
    assert api.get("/api/productos?q=780161")["total"] == 1


def test_inventario_movimientos_y_kardex(api, productos):
    bebida = productos["bebida"]
    api.post("/api/inventario/movimiento", {"producto_id": bebida["id"], "tipo": "entrada",
                                            "cantidad": 12, "costo_unitario": 950})
    assert api.get(f"/api/productos/{bebida['id']}")["precio_costo"] == 950
    api.post("/api/inventario/movimiento", {"producto_id": bebida["id"], "tipo": "salida",
                                            "cantidad": 2, "nota": "Merma"})
    r = api.post("/api/inventario/movimiento", {"producto_id": bebida["id"], "tipo": "ajuste",
                                                "cantidad": 30})
    assert r["existencia"] == 30
    tipos = [m["tipo"] for m in api.get(f"/api/productos/{bebida['id']}/kardex")]
    assert tipos == ["ajuste", "salida", "entrada", "inicial"]


def test_compras_sugeridas(api, productos):
    api.post("/api/inventario/movimiento", {"producto_id": productos["bebida"]["id"],
                                            "tipo": "ajuste", "cantidad": 4})
    sugeridos = {p["codigo"]: p for p in api.get("/api/inventario/sugeridos")}
    assert "7801610001196" in sugeridos
    assert sugeridos["7801610001196"]["sugerido"] == 8  # mínimo 6 x 2 - 4
    assert "REC" not in sugeridos


def test_importar_y_exportar_csv(api, productos):
    csv = ("Código;Descripción;Precio Venta;Costo;Departamento;Stock;tipo_venta\n"
           "111;Arroz 1kg;1.490;1.000;Abarrotes;20;unidad\n"
           "PAN;Pan batido;2.390;;;;\n"
           "222;Sin precio;;;;;\n"
           "333;Queso;9.990;6.000;Fiambrería;1,5;granel\n").encode("utf-8")
    r = api.http.post("/api/productos/importar",
                      data={"archivo": (io.BytesIO(csv), "productos.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["creados"] == 2 and r["actualizados"] == 1
    assert r["errores"][0]["fila"] == 4
    arroz = api.get("/api/productos/codigo/111")
    assert arroz["precio_venta"] == 1490 and arroz["existencia"] == 20
    assert arroz["departamento"] == "Abarrotes"
    pan = api.get("/api/productos/codigo/PAN")
    assert pan["precio_venta"] == 2390 and pan["departamento"] == "Panadería"
    assert api.get("/api/productos/codigo/333")["existencia"] == 1.5

    exportado = api.http.get("/api/productos/exportar").get_data(as_text=True)
    assert exportado.startswith("﻿codigo;descripcion")
    assert "Arroz 1kg" in exportado


def test_respaldos(api, app):
    nombre = api.post("/api/respaldos", esperado=201)["nombre"]
    assert [r["nombre"] for r in api.get("/api/respaldos")] == [nombre]
    assert api.http.get(f"/api/respaldos/{nombre}").status_code == 200
    assert api.http.get("/api/respaldos/..%2Fneji.db").status_code == 404
