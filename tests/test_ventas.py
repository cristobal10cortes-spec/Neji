def vender(api, items, esperado=201, **extra):
    datos = {"caja_id": 1, "items": items}
    datos.update(extra)
    return api.post("/api/ventas", datos, esperado=esperado)


def existencia(api, producto):
    return api.get(f"/api/productos/{producto['id']}")["existencia"]


def test_venta_sin_turno_pide_abrir_caja(api, productos):
    r = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1}], esperado=400)
    assert r["codigo"] == "sin_turno"


def test_venta_efectivo_con_redondeo_y_cambio(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2},
                         {"producto_id": productos["huevos"]["id"], "cantidad": 1}],
                   efectivo_recibido=5000)
    assert venta["total"] == 1590 * 2 + 250 == 3430
    assert venta["redondeo"] == 0
    assert venta["cambio"] == 1570
    assert venta["folio"] == 1
    assert venta["neto"] + venta["iva"] == venta["total"]
    assert existencia(api, productos["bebida"]) == 22

    venta = vender(api, [{"producto_id": productos["pan"]["id"], "cantidad": 0.755}],
                   efectivo_recibido=2000)
    assert venta["total"] == 1729  # 0,755 kg x $2.290
    assert venta["redondeo"] == 1  # se cobran $1.730
    assert venta["cambio"] == 270
    assert existencia(api, productos["pan"]) == 9.245


def test_efectivo_insuficiente(api, turno, productos):
    r = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1}],
               efectivo_recibido=1000, esperado=400)
    assert "Falta dinero" in r["error"]


def test_mayoreo_automatico_y_manual(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 6}])
    assert venta["items"][0]["tipo_precio"] == "mayoreo"
    assert venta["total"] == 6 * 1390

    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1,
                          "tipo_precio": "mayoreo"}])
    assert venta["items"][0]["precio_unitario"] == 1390


def test_precio_no_se_puede_falsificar(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1, "precio": 1}])
    assert venta["total"] == 1590


def test_unidad_no_acepta_decimales(api, turno, productos):
    r = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1.5}], esperado=400)
    assert "por unidad" in r["error"]


def test_articulo_comun_no_mueve_inventario(api, turno, productos):
    venta = vender(api, [{"descripcion": "Chicle", "cantidad": 3, "precio": 100,
                          "tipo_precio": "comun"}])
    assert venta["items"][0]["producto_id"] is None
    assert venta["total"] == 300


def test_stock_negativo_bloqueado_y_permitido(api, turno, productos):
    r = vender(api, [{"producto_id": productos["huevos"]["id"], "cantidad": 5}], esperado=400)
    assert "existencia suficiente" in r["error"]
    api.put("/api/config", {"permitir_stock_negativo": True})
    vender(api, [{"producto_id": productos["huevos"]["id"], "cantidad": 5}])
    assert existencia(api, productos["huevos"]) == -2


def test_pago_mixto(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 3}],
                   pagos={"debito": 3000}, efectivo_recibido=2000)
    # 4.770 total: 3.000 débito + 1.770 efectivo (se cobran 1.770)
    pagos = {p["metodo"]: p["monto"] for p in venta["pagos"]}
    assert pagos == {"debito": 3000, "efectivo": 1770}
    assert venta["cambio"] == 230


def test_pagos_no_pueden_superar_total(api, turno, productos):
    vender(api, [{"producto_id": productos["recarga"]["id"], "cantidad": 1}],
           pagos={"credito": 5000}, esperado=400)


def test_descuento_y_permiso_de_cajero(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2}], descuento=180)
    assert venta["total"] == 3000

    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1}], descuento=100,
           esperado=403)
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1, "tipo_precio": "manual",
                  "precio": 10}], esperado=403)
    api.put("/api/productos/1", {"codigo": "X", "descripcion": "X", "precio_venta": 1}, esperado=403)


def test_fiado_limite_y_abono(api, turno, productos):
    cliente = api.post("/api/clientes", {"nombre": "Doña Juanita", "rut": "11.111.111-1",
                                         "limite_credito": 5000}, esperado=201)
    assert cliente["rut"] == "11.111.111-1"
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2}],
           cliente_id=cliente["id"], pagos={"fiado": 3180})
    cliente = api.get(f"/api/clientes/{cliente['id']}")
    assert cliente["saldo"] == 3180 and cliente["credito_disponible"] == 1820

    r = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2}],
               cliente_id=cliente["id"], pagos={"fiado": 3180}, esperado=400)
    assert "límite de crédito" in r["error"]

    api.post(f"/api/clientes/{cliente['id']}/abono", {"monto": 2000, "caja_id": 1})
    assert api.get(f"/api/clientes/{cliente['id']}")["saldo"] == 1180
    api.post(f"/api/clientes/{cliente['id']}/abono", {"monto": 5000, "caja_id": 1}, esperado=400)


def test_fiado_requiere_cliente(api, turno, productos):
    r = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1}],
               pagos={"fiado": 1590}, esperado=400)
    assert "cliente" in r["error"]


def test_rut_invalido_rechazado(api):
    api.post("/api/clientes", {"nombre": "X", "rut": "12.345.678-9"}, esperado=400)


def test_devolucion_parcial_y_total(api, turno, productos):
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 3},
                         {"producto_id": productos["huevos"]["id"], "cantidad": 2}])
    bebida_item = venta["items"][0]

    venta = api.post(f"/api/ventas/{venta['id']}/devolucion",
                     {"caja_id": 1, "items": [{"venta_item_id": bebida_item["id"], "cantidad": 1}]},
                     esperado=201)
    assert venta["estado"] == "devuelta_parcial"
    assert venta["devuelto"] == 1590
    assert existencia(api, productos["bebida"]) == 22

    api.post(f"/api/ventas/{venta['id']}/devolucion",
             {"caja_id": 1, "items": [{"venta_item_id": bebida_item["id"], "cantidad": 3}]},
             esperado=400)

    venta = api.post(f"/api/ventas/{venta['id']}/devolucion", {"caja_id": 1, "todo": True},
                     esperado=201)
    assert venta["estado"] == "devuelta"
    assert venta["devuelto"] == venta["total"]
    assert existencia(api, productos["bebida"]) == 24
    assert existencia(api, productos["huevos"]) == 3


def test_devolucion_de_fiado_baja_la_deuda(api, turno, productos):
    cliente = api.post("/api/clientes", {"nombre": "Pedro", "sin_limite": True}, esperado=201)
    venta = vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2}],
                   cliente_id=cliente["id"], pagos={"fiado": 3180})
    api.post(f"/api/ventas/{venta['id']}/devolucion", {"caja_id": 1, "todo": True}, esperado=201)
    assert api.get(f"/api/clientes/{cliente['id']}")["saldo"] == 0


def test_corte_de_caja(api, turno, productos):
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 1}])  # 1.590 efectivo
    vender(api, [{"producto_id": productos["pan"]["id"], "cantidad": 0.755}])  # 1.729 -> 1.730
    vender(api, [{"producto_id": productos["recarga"]["id"], "cantidad": 1}],
           pagos={"debito": 1000})
    api.post("/api/caja/1/movimiento", {"tipo": "entrada", "monto": 5000, "concepto": "Sencillo"},
             esperado=201)
    api.post("/api/caja/1/movimiento", {"tipo": "salida", "monto": 2000, "concepto": "Proveedor pan"},
             esperado=201)
    t = api.get("/api/caja/1/turno")["turno"]
    assert t["por_metodo"]["efectivo"] == 1590 + 1729
    assert t["redondeo"] == 1
    assert t["por_metodo"]["debito"] == 1000
    assert t["efectivo_esperado"] == 10000 + 1590 + 1730 + 5000 - 2000
    assert t["n_ventas"] == 3

    cerrado = api.post("/api/caja/1/cerrar", {"efectivo_contado": 16300})["turno"]
    assert cerrado["estado"] == "cerrado"
    assert cerrado["diferencia"] == -20
    assert api.get("/api/caja/1/turno")["turno"] is None


def test_salida_mayor_al_efectivo(api, turno):
    api.post("/api/caja/1/movimiento", {"tipo": "salida", "monto": 999999, "concepto": "x"},
             esperado=400)


def test_cotizacion_no_mueve_inventario(api, turno, productos):
    cot = api.post("/api/cotizaciones", {"items": [{"producto_id": productos["bebida"]["id"],
                                                    "cantidad": 10}],
                                         "cliente_nombre": "Junta de vecinos"}, esperado=201)
    assert cot["folio"] == 1 and cot["total"] == 13900
    assert existencia(api, productos["bebida"]) == 24
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 10}], cotizacion_id=cot["id"])
    assert api.get(f"/api/cotizaciones/{cot['id']}")["estado"] == "vendida"


def test_reporte_ventas(api, turno, productos):
    vender(api, [{"producto_id": productos["bebida"]["id"], "cantidad": 2}])
    vender(api, [{"descripcion": "Chicle", "cantidad": 1, "precio": 200, "tipo_precio": "comun"}])
    r = api.get("/api/reportes/ventas")
    assert r["resumen"]["n_ventas"] == 2
    assert r["resumen"]["total"] == 3380
    assert r["resumen"]["ganancia"] == (1590 - 900) * 2 + 200
    deps = {d["departamento"]: d["total"] for d in r["por_departamento"]}
    assert deps == {"Bebidas": 3180, "Artículos comunes": 200}
    assert r["top_productos"][0]["descripcion"] == "Bebida cola 1.5L"
