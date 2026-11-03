"""Proveedores: anotar sus facturas, ver cuánto se les debe y marcar los pagos."""

from datetime import date, timedelta

from neji.db import conectar
from neji.servicios import proveedores as svc


def anotar(api, proveedor, numero, monto, esperado=201, **extra):
    return api.post("/api/proveedores/facturas",
                    {"proveedor": proveedor, "numero": numero, "monto": monto, **extra}, esperado=esperado)


def dias(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_anotar_facturas_y_ver_el_total_por_pagar(api, productos):
    vacio = api.get("/api/proveedores")
    assert vacio["proveedores"] == [] and vacio["resumen"]["por_pagar"] == 0
    f1 = anotar(api, "Droguería Ñuñoa", "10234", "1.250.000", vence=dias(10))
    assert f1["proveedor_nuevo"] is True and f1["proveedor"] == "Droguería Ñuñoa" and f1["monto"] == 1_250_000
    # El mismo proveedor escrito distinto (mayúsculas, sin tilde) no se duplica.
    f2 = anotar(api, "drogueria ñuñoa", "10240", 380_500, fecha=dias(-33), vence=dias(-3))
    assert f2["proveedor_nuevo"] is False and f2["proveedor_id"] == f1["proveedor_id"]
    anotar(api, "Laboratorio Chile", "A-77", 99_990)
    # Una nota de crédito del proveedor (devolución) resta.
    anotar(api, "Droguería Ñuñoa", "NC-5", 30_500, tipo="nota_credito")

    r = api.get("/api/proveedores")
    assert r["resumen"] | {"pagado_mes": 0} == {
        "por_pagar": 1_250_000 + 380_500 + 99_990 - 30_500, "n_por_pagar": 3,
        "vencido": 380_500, "n_vencidas": 1, "por_vencer": 0, "n_por_vencer": 0,
        "pagado_mes": 0, "dias_por_vencer": 7}
    por_proveedor = {p["nombre"]: (p["por_pagar"], p["n_por_pagar"], p["vencido"]) for p in r["proveedores"]}
    assert por_proveedor == {"Droguería Ñuñoa": (1_600_000, 2, 380_500), "Laboratorio Chile": (99_990, 1, 0)}
    assert r["proveedores"][0]["nombre"] == "Droguería Ñuñoa"          # el que más se le debe, primero

    lista = api.get("/api/proveedores/facturas")
    assert lista["total"] == 1_699_990
    assert [f["numero"] for f in lista["facturas"]][0] == "10240"       # la vencida primero
    assert next(f for f in lista["facturas"] if f["numero"] == "10240")["vencida"] is True
    assert next(f for f in lista["facturas"] if f["numero"] == "NC-5")["con_signo"] == -30_500
    # Solo las de un proveedor, y buscando por número.
    solo = api.get(f"/api/proveedores/facturas?proveedor_id={f1['proveedor_id']}")
    assert solo["total"] == 1_600_000 and len(solo["facturas"]) == 3
    assert [f["numero"] for f in api.get("/api/proveedores/facturas?q=A-7")["facturas"]] == ["A-77"]
    assert [f["numero"] for f in api.get("/api/proveedores/facturas?q=laboratorio")["facturas"]] == ["A-77"]


def test_datos_que_no_valen(api):
    anotar(api, "Droguería Ñuñoa", "10234", 1000)
    r = anotar(api, "DROGUERIA ÑUÑOA", "10234", 5000, esperado=400)
    assert "ya está anotada" in r["error"]
    assert "número" in anotar(api, "X", "", 1000, esperado=400)["error"]
    assert "monto" in anotar(api, "X", "1", 0, esperado=400)["error"]
    assert "proveedor" in anotar(api, "", "1", 100, esperado=400)["error"]
    r = anotar(api, "X", "2", 100, esperado=400, fecha="2026-11-10", vence="2026-11-01")
    assert "vencimiento" in r["error"]
    # El mismo número en otro proveedor sí se puede.
    anotar(api, "Otro Proveedor", "10234", 1000)
    assert "RUT" in api.post("/api/proveedores", {"nombre": "Con RUT", "rut": "11.111.111-2"}, esperado=400)["error"]
    p = api.post("/api/proveedores", {"nombre": "Con RUT", "rut": "761234567"}, esperado=400)
    assert "RUT" in p["error"]
    ok = api.post("/api/proveedores", {"nombre": "Con RUT", "rut": "11111111-1", "contacto": "Juan +569"},
                  esperado=201)
    assert ok["rut"] == "11.111.111-1"
    assert "Ya existe" in api.post("/api/proveedores", {"nombre": "con rut"}, esperado=400)["error"]


def test_pagar_y_deshacer(api):
    a = anotar(api, "Droguería Ñuñoa", "1", 100_000)
    b = anotar(api, "Droguería Ñuñoa", "2", 50_000)
    nc = anotar(api, "Droguería Ñuñoa", "NC-1", 20_000, tipo="nota_credito")
    c = anotar(api, "Laboratorio Chile", "9", 10_000)
    # Se seleccionan varias y se pagan juntas: la nota de crédito se descuenta.
    r = api.post("/api/proveedores/facturas/pagar", {"ids": [a["id"], b["id"], nc["id"]], "medio": "transferencia"})
    assert r == {"pagadas": 3, "total": 130_000}
    assert api.get("/api/proveedores")["resumen"]["por_pagar"] == 10_000
    assert api.get("/api/proveedores")["resumen"]["pagado_mes"] == 130_000
    pagadas = api.get("/api/proveedores/facturas?estado=pagada")
    assert pagadas["total"] == 130_000 and {f["medio_pago"] for f in pagadas["facturas"]} == {"transferencia"}
    assert api.get("/api/proveedores/facturas?estado=todas")["total"] == 140_000
    # No se paga dos veces.
    r = api.post("/api/proveedores/facturas/pagar", {"ids": [a["id"]]}, esperado=400)
    assert "ya está marcada como pagada" in r["error"]
    assert "Elige" in api.post("/api/proveedores/facturas/pagar", {"ids": []}, esperado=400)["error"]
    assert "Elige cómo" in api.post("/api/proveedores/facturas/pagar", {"ids": [c["id"]], "medio": "trueque"},
                                    esperado=400)["error"]
    # Deshacer: vuelve a «por pagar».
    vuelta = api.post(f"/api/proveedores/facturas/{a['id']}/por-pagar")
    assert vuelta["pagada"] is None and vuelta["proveedor"] == "Droguería Ñuñoa"
    assert api.get("/api/proveedores")["resumen"]["por_pagar"] == 110_000


def test_editar_borrar_y_quitar_proveedor(api):
    f = anotar(api, "Droguería Ñuñoa", "1", 100_000)
    e = api.put(f"/api/proveedores/facturas/{f['id']}", {"proveedor": "Droguería Ñuñoa", "numero": "1",
                                                          "monto": 99_000, "vence": dias(5)})
    assert e["monto"] == 99_000 and e["vence"] == dias(5)
    assert api.get("/api/proveedores")["resumen"]["por_vencer"] == 99_000
    # No se quita un proveedor al que se le debe.
    r = api.delete(f"/api/proveedores/{f['proveedor_id']}", esperado=400)
    assert "por pagar" in r["error"]
    api.delete(f"/api/proveedores/facturas/{f['id']}")
    api.delete(f"/api/proveedores/{f['proveedor_id']}")
    assert api.get("/api/proveedores")["proveedores"] == []
    # Si vuelve a facturar, vuelve a la lista (el mismo proveedor, no uno nuevo).
    otra = anotar(api, "Droguería Ñuñoa", "2", 1000)
    assert otra["proveedor_id"] == f["proveedor_id"] and otra["proveedor_nuevo"] is False
    api.get(f"/api/proveedores/facturas/{999}", esperado=405)


def test_sugiere_los_proveedores_de_los_productos(api):
    api.post("/api/productos", {"codigo": "1", "descripcion": "Paracetamol", "precio_venta": 990,
                                "proveedor": "Laboratorio Chile"}, esperado=201)
    anotar(api, "laboratorio chile", "5", 1000)
    anotar(api, "Droguería Ñuñoa", "6", 1000)
    assert api.get("/api/proveedores")["sugeridos"] == ["Droguería Ñuñoa", "laboratorio chile"]


def test_solo_con_el_permiso(api):
    caja = api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    assert caja["permisos"]["proveedores"] is False
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    api.get("/api/proveedores", esperado=403)
    anotar(api, "X", "1", 100, esperado=403)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "admin", "password": "1234"})
    api.put(f"/api/usuarios/{caja['id']}", {"permisos": {"proveedores": True}})
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    anotar(api, "X", "1", 100)


def test_vencidas_segun_el_dia(app, api):
    anotar(api, "Droguería Ñuñoa", "1", 1000, fecha="2026-10-01", vence="2026-10-31")
    con = conectar(app.config["DATABASE"])
    try:
        assert svc.resumen(con, hoy=date(2026, 10, 30))["por_vencer"] == 1000
        assert svc.resumen(con, hoy=date(2026, 11, 1))["vencido"] == 1000
        facturas, _ = svc.listar_facturas(con, hoy=date(2026, 10, 31))
        assert facturas[0]["vencida"] is False                          # el día que vence aún no está vencida
    finally:
        con.close()
