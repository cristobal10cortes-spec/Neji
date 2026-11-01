"""Máquina POS integrada: configuración por caja, cobros con el simulador y su uso (una sola vez) en la venta."""

import pytest

pytest.importorskip("cryptography")


def configurar(api, caja_id=1, resultado="aprobar", segundos=0, activo=True):
    return api.put(f"/api/pos/cajas/{caja_id}", {"proveedor": "simulador", "activo": activo,
                                                 "datos": {"resultado": resultado, "segundos": segundos}})


def cobrar(api, monto, metodo="debito", caja_id=1, esperado=201):
    return api.post("/api/pos/cobros", {"caja_id": caja_id, "monto": monto, "metodo": metodo}, esperado=esperado)


def items(productos, cantidad=1):
    return [{"producto_id": productos["bebida"]["id"], "cantidad": cantidad}]


def test_configuracion_por_caja(api):
    d = api.get("/api/pos")
    proveedores = {p["clave"]: p for p in d["proveedores"]}
    assert proveedores["simulador"]["disponible"] and not proveedores["klap"]["disponible"]
    assert "documentación" in proveedores["klap"]["nota"]
    assert [(c["caja_id"], c["proveedor"], c["activo"]) for c in d["cajas"]] == [(1, "", False)]
    assert api.get("/api/config")["pos"] == {}
    # Klap todavía no se puede elegir; el simulador sí.
    r = api.put("/api/pos/cajas/1", {"proveedor": "klap", "activo": True}, esperado=400)
    assert "todavía no se puede usar" in r["error"]
    api.put("/api/pos/cajas/1", {"proveedor": "simulador", "datos": {"segundos": 99}}, esperado=400)
    d = configurar(api, segundos=5)
    assert d["cajas"][0] == {"caja_id": 1, "nombre": "Caja 1", "caja_activa": True, "proveedor": "simulador",
                                  "activo": True, "datos": {"resultado": "aprobar", "segundos": 5}}
    assert api.get("/api/config")["pos"] == {"1": {"proveedor": "simulador", "nombre": "Simulador de pruebas"}}
    # Desactivada o sin máquina: la caja cobra a mano.
    configurar(api, activo=False)
    assert api.get("/api/config")["pos"] == {}
    api.put("/api/pos/cajas/1", {"proveedor": ""})
    assert api.get("/api/pos")["cajas"][0]["proveedor"] == ""


def test_venta_con_pago_aprobado_en_la_maquina(api, productos, turno):
    configurar(api)
    total = productos["bebida"]["precio_venta"]
    cobro = cobrar(api, total)
    assert (cobro["estado"], cobro["monto"], cobro["tarjeta"]) == ("aprobado", total, "4242")
    assert len(cobro["autorizacion"]) == 6
    venta = api.post("/api/ventas", {"caja_id": 1, "items": items(productos), "pagos": {"debito": total},
                                     "pos_cobro_id": cobro["id"]}, esperado=201)
    assert venta["pagos"] == [{"metodo": "debito", "monto": total, "autorizacion": cobro["autorizacion"],
                               "tarjeta": "4242"}]
    assert api.get(f"/api/pos/cobros/{cobro['id']}")["venta_id"] == venta["id"]
    # Un pago se usa una sola vez, y ya no se puede anular desde la máquina (se devuelve la venta).
    r = api.post("/api/ventas", {"caja_id": 1, "items": items(productos), "pagos": {"debito": total},
                                 "pos_cobro_id": cobro["id"]}, esperado=400)
    assert "ya se usó" in r["error"]
    r = api.post(f"/api/pos/cobros/{cobro['id']}/cancelar", esperado=400)
    assert "devolución" in r["error"]


def test_el_pago_tiene_que_cuadrar_con_la_venta(api, productos, turno):
    configurar(api)
    total = productos["bebida"]["precio_venta"]
    cobro = cobrar(api, total)
    datos = {"caja_id": 1, "items": items(productos), "pos_cobro_id": cobro["id"]}
    r = api.post("/api/ventas", datos | {"pagos": {"credito": total}}, esperado=400)
    assert "no coincide" in r["error"]
    r = api.post("/api/ventas", datos | {"items": items(productos, 2), "pagos": {"debito": total * 2}}, esperado=400)
    assert "no coincide" in r["error"]
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    api.post("/api/caja/2/abrir", {"fondo_inicial": 0}, esperado=201)
    r = api.post("/api/ventas", datos | {"caja_id": 2, "pagos": {"debito": total}}, esperado=400)
    assert "otra caja" in r["error"]
    # Si la venta falló, el mismo pago aprobado sirve al reintentar (no se cobra dos veces).
    venta = api.post("/api/ventas", datos | {"pagos": {"debito": total}}, esperado=201)
    assert venta["pagos"][0]["autorizacion"] == cobro["autorizacion"]


def test_rechazado_espera_y_cancelacion(api, productos, turno):
    configurar(api, resultado="rechazar")
    total = productos["bebida"]["precio_venta"]
    cobro = cobrar(api, total, "credito")
    assert (cobro["estado"], cobro["mensaje"]) == ("rechazado", "Tarjeta rechazada (simulador).")
    r = api.post("/api/ventas", {"caja_id": 1, "items": items(productos), "pagos": {"credito": total},
                                 "pos_cobro_id": cobro["id"]}, esperado=400)
    assert "no está aprobado" in r["error"]
    # Mientras espera la tarjeta se puede cancelar; aprobado y sin venta, se anula.
    configurar(api, segundos=30)
    esperando = cobrar(api, total)
    assert api.get(f"/api/pos/cobros/{esperando['id']}")["estado"] == "esperando"
    assert api.post(f"/api/pos/cobros/{esperando['id']}/cancelar")["estado"] == "cancelado"
    configurar(api)
    aprobado = cobrar(api, total)
    assert api.post(f"/api/pos/cobros/{aprobado['id']}/cancelar")["estado"] == "anulado"


def test_sin_maquina_no_se_cobra(api, productos, turno):
    r = cobrar(api, 1000, esperado=400)
    assert "Máquina POS" in r["error"]
    configurar(api)
    assert "débito o crédito" in cobrar(api, 1000, "efectivo", esperado=400)["error"]
    # Sin máquina, la venta con tarjeta sigue como siempre (a mano).
    total = productos["bebida"]["precio_venta"]
    venta = api.post("/api/ventas", {"caja_id": 1, "items": items(productos), "pagos": {"debito": total}},
                     esperado=201)
    assert venta["pagos"] == [{"metodo": "debito", "monto": total, "autorizacion": None, "tarjeta": None}]


def test_solo_el_administrador_configura(api):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    configurar(api)
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    api.get("/api/pos", esperado=403)
    api.put("/api/pos/cajas/1", {"proveedor": ""}, esperado=403)
    assert cobrar(api, 500)["estado"] == "aprobado"       # el cajero sí cobra con la máquina
