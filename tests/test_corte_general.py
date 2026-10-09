"""Corte general: desde la caja principal se cierran juntos los turnos de todas las cajas."""


def _vender(api, caja_id, producto, cantidad=1, **extra):
    return api.post("/api/ventas", {"caja_id": caja_id, "items": [{"producto_id": producto["id"], "cantidad": cantidad}],
                                    **extra}, esperado=201)


def test_corte_general_de_todas_las_cajas(api, productos):
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    cajas = {c["nombre"]: c for c in api.get("/api/cajas")}
    assert cajas["Caja 1"]["principal"] == 1 and cajas["Caja 2"]["principal"] == 0
    api.post("/api/caja/1/abrir", {"fondo_inicial": 10000}, esperado=201)
    # La caja 2 la atiende otro cajero.
    api.post("/api/usuarios", {"usuario": "cris", "nombre": "Cristóbal", "password": "1111", "rol": "cajero"},
             esperado=201)
    _vender(api, 1, productos["bebida"], 2)                     # 3.180 en la caja 1 (admin)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "cris", "password": "1111"})
    api.post("/api/caja/2/abrir", {"fondo_inicial": 5000}, esperado=201)
    _vender(api, 2, productos["huevos"], 2)                     # 500 en la caja 2
    api.get("/api/caja/turnos-abiertos", esperado=403)          # sin permiso de corte general
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "admin", "password": "1234"})

    abiertos = api.get("/api/caja/turnos-abiertos")
    assert [t["caja"] for t in abiertos] == ["Caja 1", "Caja 2"]
    esperado = {t["caja_id"]: t["efectivo_esperado"] for t in abiertos}
    assert esperado == {1: 13180, 2: 5500}

    # Solo desde la caja principal.
    cortes = [{"turno_id": t["id"], "efectivo_contado": t["efectivo_esperado"]} for t in abiertos]
    api.post("/api/caja/2/corte-general", {"cortes": cortes}, esperado=403)
    cortes[1]["efectivo_contado"] = 5400                         # faltan 100 en la caja 2
    corte = api.post("/api/caja/1/corte-general", {"cortes": cortes, "nota": "cierre del día"}, esperado=201)
    assert corte["totales"]["efectivo_esperado"] == 18680
    assert corte["totales"]["efectivo_contado"] == 18580 and corte["totales"]["diferencia"] == -100
    assert corte["totales"]["total_ventas"] == 3680 and corte["totales"]["n_ventas"] == 2
    assert {c["cajero"]: c["total"] for c in corte["por_cajero"]} == {"Dueño": 3180, "Cristóbal": 500}
    assert api.get("/api/caja/1/turno")["turno"] is None and api.get("/api/caja/2/turno")["turno"] is None

    # Queda en el historial y se puede volver a ver.
    historial = api.get("/api/cortes-generales")
    assert historial[0]["n_turnos"] == 2 and historial[0]["diferencia"] == -100
    assert api.get(f"/api/cortes-generales/{corte['id']}")["totales"]["diferencia"] == -100
    # Un turno ya cerrado no se puede volver a cortar.
    api.post("/api/caja/1/corte-general", {"cortes": cortes}, esperado=400)


def test_cambiar_caja_principal(api):
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    api.put("/api/cajas/1", {"principal": False}, esperado=400)          # debe quedar una principal
    api.put("/api/cajas/2", {"principal": True})
    cajas = {c["id"]: c["principal"] for c in api.get("/api/cajas")}
    assert cajas == {1: 0, 2: 1}
    api.put("/api/cajas/2", {"activa": False}, esperado=400)            # la principal no se desactiva


def test_corte_general_vacio_o_repetido(api, turno):
    api.post("/api/caja/1/corte-general", {"cortes": []}, esperado=400)
    api.post("/api/caja/1/corte-general",
             {"cortes": [{"turno_id": turno["id"], "efectivo_contado": 1}] * 2}, esperado=400)
    assert api.get("/api/caja/1/turno")["turno"] is not None            # nada quedó a medias
