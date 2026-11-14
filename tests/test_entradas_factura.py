"""Entradas de mercadería con su factura: el producto se suma solo a la factura del proveedor."""

from datetime import date


def entrada(api, producto, cantidad, costo, proveedor="Droguería Central", factura="10240", esperado=200, **extra):
    datos = {"producto_id": producto["id"], "tipo": "entrada", "cantidad": cantidad, "costo_unitario": costo,
             "proveedor": proveedor, "factura": factura, **extra}
    return api.post("/api/inventario/movimiento", datos, esperado=esperado)


def factura_de(api, numero):
    return next(f for f in api.get("/api/proveedores/facturas?estado=todas")["facturas"] if f["numero"] == numero)


def test_la_entrada_pide_proveedor_factura_y_costo(api, productos):
    bebida = productos["bebida"]
    sin = {"producto_id": bebida["id"], "tipo": "entrada", "cantidad": 6, "costo_unitario": 900}
    assert "proveedor" in api.post("/api/inventario/movimiento", sin, esperado=400)["error"]
    assert "factura" in api.post("/api/inventario/movimiento", sin | {"proveedor": "CCU"}, esperado=400)["error"]
    r = api.post("/api/inventario/movimiento", sin | {"proveedor": "CCU", "factura": "1", "costo_unitario": ""},
                 esperado=400)
    assert "costo" in r["error"]
    # Nada quedó a medias: ni existencia ni factura.
    assert api.get(f"/api/productos/{bebida['id']}")["existencia"] == 24
    assert api.get("/api/proveedores/facturas?estado=todas")["facturas"] == []
    # Las salidas y los ajustes no piden factura.
    api.post("/api/inventario/movimiento", {"producto_id": bebida["id"], "tipo": "salida", "cantidad": 1})


def test_cada_producto_se_suma_a_su_factura(api, productos):
    r = entrada(api, productos["bebida"], 12, 950)
    assert r["existencia"] == 36
    f = r["factura"]
    assert (f["numero"], f["proveedor"], f["monto"], f["productos"], f["proveedor_nuevo"]) == (
        "10240", "Droguería Central", 11_400, 1, True)
    # El segundo producto de la misma factura (el proveedor escrito distinto) suma al mismo total.
    r = entrada(api, productos["huevos"], 30, 140, proveedor="drogueria central")
    assert (r["factura"]["monto"], r["factura"]["productos"], r["factura"]["proveedor_nuevo"]) == (15_600, 2, False)
    # Unidades bonificadas (costo $0) entran sin cambiar el total.
    assert entrada(api, productos["huevos"], 6, 0)["factura"]["monto"] == 15_600

    # En Proveedores queda por pagar, con la fecha de hoy y los productos que entraron.
    f = factura_de(api, "10240")
    assert (f["monto"], f["fecha"], f["pagada"], f["origen"]) == (15_600, date.today().isoformat(), None, "inventario")
    assert api.get("/api/proveedores")["resumen"]["por_pagar"] == 15_600
    detalle = api.get(f"/api/proveedores/facturas/{f['id']}")
    assert [(p["codigo"], p["cantidad"], p["costo_unitario"], p["importe"]) for p in detalle["productos"]] == [
        ("7801610001196", 12, 950, 11_400), ("HUEVO", 30, 140, 4_200), ("HUEVO", 6, 0, 0)]
    # En el kardex la entrada dice de qué factura vino.
    kardex = api.get(f"/api/productos/{productos['bebida']['id']}/kardex")
    assert kardex[0]["referencia"] == "Factura 10240 · Droguería Central"
    # Otra factura del mismo proveedor es otra factura.
    assert entrada(api, productos["bebida"], 1, 950, factura="10251")["factura"]["monto"] == 950


def test_factura_nueva_con_costo_cero_o_ya_pagada(api, productos):
    r = entrada(api, productos["bebida"], 6, 0, factura="B-1", esperado=400)
    assert "bonificadas" in r["error"]
    f = entrada(api, productos["bebida"], 6, 900, factura="B-1")["factura"]
    api.post("/api/proveedores/facturas/pagar", {"ids": [f["id"]]})
    r = entrada(api, productos["bebida"], 1, 900, factura="B-1", esperado=400)
    assert "ya está pagada" in r["error"]
    assert api.get(f"/api/productos/{productos['bebida']['id']}")["existencia"] == 30


def test_la_factura_ingresada_a_mano_respeta_su_total(api, productos):
    # Ingresada en Proveedores con su total: las entradas solo quedan unidas a ella.
    hecha = api.post("/api/proveedores/facturas", {"proveedor": "CCU", "numero": "77", "monto": 50_000}, esperado=201)
    assert entrada(api, productos["bebida"], 10, 950, proveedor="CCU", factura="77")["factura"]["monto"] == 50_000
    assert len(api.get(f"/api/proveedores/facturas/{hecha['id']}")["productos"]) == 1
    # Creada por una entrada y después corregido su total a mano: desde ahí manda lo escrito.
    f = entrada(api, productos["huevos"], 10, 150, proveedor="Avícola", factura="9")["factura"]
    api.put(f"/api/proveedores/facturas/{f['id']}", {"proveedor": "Avícola", "numero": "9", "monto": 1_785})
    assert entrada(api, productos["huevos"], 10, 150, proveedor="Avícola", factura="9")["factura"]["monto"] == 1_785
    # Cambiar solo el vencimiento no la saca de la suma automática.
    g = entrada(api, productos["huevos"], 1, 150, proveedor="Avícola", factura="10")["factura"]
    api.put(f"/api/proveedores/facturas/{g['id']}", {"proveedor": "Avícola", "numero": "10", "monto": 150,
                                                     "vence": "2099-01-31"})
    assert entrada(api, productos["huevos"], 1, 150, proveedor="Avícola", factura="10")["factura"]["monto"] == 300


def test_borrar_la_factura_deja_las_entradas(api, productos):
    f = entrada(api, productos["bebida"], 12, 950)["factura"]
    api.delete(f"/api/proveedores/facturas/{f['id']}")
    assert api.get(f"/api/productos/{productos['bebida']['id']}")["existencia"] == 36
    kardex = api.get(f"/api/productos/{productos['bebida']['id']}/kardex")
    assert kardex[0]["referencia"] == "Factura 10240 · Droguería Central"
    # Con el mismo número se crea de nuevo.
    assert entrada(api, productos["bebida"], 1, 950)["factura"]["monto"] == 950


def test_nombres_de_proveedores_para_la_entrada(api, productos):
    entrada(api, productos["bebida"], 1, 950, proveedor="Droguería Central")
    assert "Droguería Central" in api.get("/api/inventario/proveedores")


def test_filtro_por_existencia(api, productos):
    api.post("/api/inventario/movimiento", {"producto_id": productos["huevos"]["id"], "tipo": "ajuste", "cantidad": 0})
    codigos = lambda filtro: sorted(p["codigo"] for p in api.get(f"/api/productos?existencia={filtro}")["productos"])  # noqa: E731
    assert codigos("con") == ["7801610001196", "PAN"]
    assert codigos("agotados") == ["HUEVO"]                  # la recarga no lleva inventario: no sale en ninguno
    assert len(api.get("/api/productos?existencia=")["productos"]) == 4
    assert "existencia" in api.get("/api/productos?existencia=otra", esperado=400)["error"]
