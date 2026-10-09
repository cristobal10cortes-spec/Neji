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


def test_borrar_producto_no_reutiliza_su_id(api):
    # Aunque nunca se haya vendido, borrar solo lo desactiva: un ticket abierto en otra terminal que
    # aún lo tenga no puede terminar cobrando un producto nuevo con el mismo id.
    p = api.post("/api/productos", {"codigo": "Z1", "descripcion": "AMOXICILINA", "precio_venta": 3500},
                 esperado=201)
    api.delete(f"/api/productos/{p['id']}")
    assert api.get(f"/api/productos/{p['id']}")["activo"] == 0
    nuevo = api.post("/api/productos", {"codigo": "Y1", "descripcion": "DIAZEPAM", "precio_venta": 1500},
                     esperado=201)
    assert nuevo["id"] != p["id"]
    api.delete("/api/productos/999999", esperado=404)


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


def test_importar_csv_reemplaza_o_suma_existencias(api):
    import io

    def subir(texto, existencias):
        r = api.http.post("/api/productos/importar", data={
            "archivo": (io.BytesIO(texto.encode("utf-8")), "inventario.csv"), "existencias": existencias},
            content_type="multipart/form-data")
        assert r.status_code == 200, r.get_data(as_text=True)
        return r.get_json()

    assert subir("codigo;descripcion;precio_venta;existencia\nC1;CREMA;1000;10\n", "reemplazar")["creados"] == 1
    assert api.get("/api/productos/codigo/C1")["existencia"] == 10
    subir("codigo;descripcion;existencia\nC1;CREMA;4\n", "sumar")         # entrada de mercadería
    assert api.get("/api/productos/codigo/C1")["existencia"] == 14
    subir("codigo;descripcion;existencia\nC1;CREMA;7\n", "reemplazar")    # conteo
    assert api.get("/api/productos/codigo/C1")["existencia"] == 7
    r = subir("codigo;descripcion;existencia\nC1;CREMA;-2\n", "sumar")
    assert r["errores"] and api.get("/api/productos/codigo/C1")["existencia"] == 7
    tipos = [m["tipo"] for m in api.get(f"/api/productos/{api.get('/api/productos/codigo/C1')['id']}/kardex")]
    assert tipos[:2] == ["ajuste", "entrada"]


def test_importar_csv_de_excel_en_cp1252(api):
    """Excel en Windows guarda «CSV (delimitado por punto y coma)» en cp1252: comillas, guiones y € legibles."""
    import io
    contenido = "codigo;descripcion;precio_venta;existencia\nW1;Crema “Nivea” 50 ml – oferta €;1500;2\nW2;Pañal Ñuñoa;990;1\n"
    r = api.http.post("/api/productos/importar", data={"archivo": (io.BytesIO(contenido.encode("cp1252")), "excel.csv")},
                      content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert api.get("/api/productos/codigo/W1")["descripcion"] == "Crema “Nivea” 50 ml – oferta €"
    assert api.get("/api/productos/codigo/W2")["descripcion"] == "Pañal Ñuñoa"


def test_plantilla_csv_se_puede_importar_tal_cual(api):
    import io
    plantilla = api.http.get("/api/productos/plantilla.csv").get_data()
    r = api.http.post("/api/productos/importar", data={"archivo": (io.BytesIO(plantilla), "p.csv")},
                      content_type="multipart/form-data").get_json()
    assert r["creados"] == 2 and not r["errores"]
    assert api.get("/api/productos/codigo/PAN")["existencia"] == 15.5


def _entrar_como(api, usuario, clave="1111"):
    api.post("/api/logout")
    api.post("/api/login", {"usuario": usuario, "password": clave})


def test_permisos_por_usuario(api, turno, productos):
    catalogo = api.get("/api/permisos")
    assert [p["clave"] for p in catalogo][:3] == ["cambiar_precio", "articulo_comun", "devoluciones"]
    caja = api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    assert caja["permisos"]["movimientos_caja"] and caja["permisos"]["corte"]
    assert not caja["permisos"]["cambiar_precio"] and not caja["permisos"]["productos"]
    # Un cajero con permiso de descuentos y productos, pero sin reportes.
    api.put(f"/api/usuarios/{caja['id']}", {"permisos": {"cambiar_precio": True, "productos": True, "corte": False}})
    _entrar_como(api, "caja")
    yo = api.get("/api/estado")["usuario"]
    assert yo["permisos"]["cambiar_precio"] and not yo["permisos"]["reportes"]
    api.post("/api/ventas", {"caja_id": 1, "descuento": 100,
                             "items": [{"producto_id": productos["bebida"]["id"], "cantidad": 1}]}, esperado=201)
    api.put(f"/api/productos/{productos['huevos']['id']}",
            {"codigo": "HUEVO", "descripcion": "Huevo color", "precio_venta": 260})
    assert "precio_costo" in api.get("/api/productos/codigo/HUEVO")   # quien edita productos ve el costo
    api.get("/api/reportes/ventas", esperado=403)
    api.post("/api/caja/1/cerrar", {"efectivo_contado": 0}, esperado=403)   # sin permiso de corte
    api.post("/api/caja/1/movimiento", {"tipo": "entrada", "monto": 100, "concepto": "sencillo"}, esperado=201)
    api.get("/api/turnos", esperado=403)
    api.get("/api/usuarios", esperado=403)


def test_permisos_desconocidos_se_ignoran_y_admin_los_tiene_todos(api):
    u = api.post("/api/usuarios", {"usuario": "x", "password": "1111", "rol": "cajero",
                                   "permisos": {"reportes": "si", "borrar_todo": True}}, esperado=201)
    assert u["permisos"]["reportes"] is True and "borrar_todo" not in u["permisos"]
    api.put(f"/api/usuarios/{u['id']}", {"permisos": "todo"}, esperado=400)
    admin = api.get("/api/estado")["usuario"]
    assert all(admin["permisos"].values())


def test_nombre_en_el_ticket(api, turno, productos):
    api.put("/api/usuarios/1", {"nombre_ticket": "Cajero 1 · Cristóbal Araya Cortés"})
    venta = api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": productos["pan"]["id"],
                                                              "cantidad": 1}]}, esperado=201)
    assert venta["atendio"] == "Cajero 1 · Cristóbal Araya Cortés" and venta["usuario"] == "Dueño"
    api.put("/api/usuarios/1", {"nombre_ticket": ""})            # vacío: vuelve a su nombre
    assert api.get(f"/api/ventas/{venta['id']}")["atendio"] == "Dueño"


def test_migracion_pasa_las_opciones_de_cajeros_a_cada_usuario(app, api):
    import json

    from neji.db import conectar, migrar
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    con = conectar(app.config["DATABASE"])
    con.execute("ALTER TABLE usuarios DROP COLUMN permisos")       # base de una versión anterior
    con.execute("UPDATE config SET valor = '1' WHERE clave = 'cajero_puede_devolver'")
    migrar(con)
    permisos = {u: json.loads(p) if p else None
                for u, p in con.execute("SELECT usuario, permisos FROM usuarios").fetchall()}
    con.close()
    assert permisos["caja"]["devoluciones"] is True and permisos["caja"]["cambiar_precio"] is False
    assert permisos["admin"] is None


def _cajero(api, usuario="caja", **permisos):
    api.post("/api/usuarios", {"usuario": usuario, "password": "1111", "rol": "cajero", "permisos": permisos},
             esperado=201)


def test_cotizacion_con_descuento_la_vende_un_cajero_sin_permiso_de_precios(api, turno, productos):
    cot = api.post("/api/cotizaciones", {"descuento": 200, "items": [
        {"producto_id": productos["bebida"]["id"], "cantidad": 1},
        {"descripcion": "Bolsa de regalo", "precio": 300, "cantidad": 1, "tipo_precio": "comun"}]}, esperado=201)
    _cajero(api, articulo_comun=False)
    _entrar_como(api, "caja")
    items = [{"producto_id": productos["bebida"]["id"], "cantidad": 1},
             {"descripcion": "Bolsa de regalo", "precio": 300, "cantidad": 1, "tipo_precio": "comun"}]
    # Más descuento que el de la cotización, o un artículo común distinto: no.
    api.post("/api/ventas", {"caja_id": 1, "cotizacion_id": cot["id"], "descuento": 300, "items": items}, esperado=403)
    otro = items[:1] + [{**items[1], "precio": 1}]
    api.post("/api/ventas", {"caja_id": 1, "cotizacion_id": cot["id"], "descuento": 200, "items": otro}, esperado=403)
    venta = api.post("/api/ventas", {"caja_id": 1, "cotizacion_id": cot["id"], "descuento": 200, "items": items},
                     esperado=201)
    assert venta["descuento"] == 200
    # Ya vendida: su descuento deja de valer.
    api.post("/api/ventas", {"caja_id": 1, "cotizacion_id": cot["id"], "descuento": 200, "items": items[:1]},
             esperado=403)


def test_articulo_comun_tiene_su_permiso(api, turno, productos):
    comun = [{"descripcion": "CREMA", "precio": 1, "cantidad": 1, "tipo_precio": "comun"}]
    api.post("/api/ventas", {"caja_id": 1, "items": [{**comun[0], "producto_id": productos["pan"]["id"]}]},
             esperado=400)                                        # producto del catálogo disfrazado de común
    _cajero(api, articulo_comun=False)
    _entrar_como(api, "caja")
    api.post("/api/ventas", {"caja_id": 1, "items": comun}, esperado=403)
    api.post("/api/cotizaciones", {"items": comun}, esperado=403)
    yo = api.get("/api/estado")["usuario"]
    assert yo["permisos"]["articulo_comun"] is False


def test_productos_ve_costos_pero_no_ganancias(api, turno, productos):
    _cajero(api, productos=True)
    _entrar_como(api, "caja")
    venta = api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": productos["pan"]["id"], "cantidad": 1}]},
                     esperado=201)
    assert "precio_costo" in venta["items"][0]
    assert "ganancia" not in api.get("/api/caja/1/turno")["turno"]


def test_csv_sin_permiso_de_inventario_no_cambia_el_stock(api):
    import io
    api.post("/api/productos", {"codigo": "C1", "descripcion": "CREMA", "precio_venta": 1000, "existencia": 4},
             esperado=201)
    _cajero(api, productos=True)
    _entrar_como(api, "caja")
    r = api.http.post("/api/productos/importar", data={
        "archivo": (io.BytesIO(b"codigo;descripcion;precio_venta;existencia\nC1;CREMA;;999\nC2;JABON;500;5\n"), "x.csv")},
        content_type="multipart/form-data").get_json()
    assert r["actualizados"] == 1 and r["creados"] == 1
    assert "permiso de inventario" in r["errores"][0]["error"]
    assert api.get("/api/productos/codigo/C1")["existencia"] == 4
    assert api.get("/api/productos/codigo/C2")["existencia"] == 5   # un producto nuevo sí parte con su stock


def test_corte_solo_del_turno_propio(api, productos):
    api.post("/api/cajas", {"nombre": "Caja 2"}, esperado=201)
    _cajero(api, "ana")
    _cajero(api, "beto")
    _entrar_como(api, "ana")
    api.post("/api/caja/2/abrir", {"fondo_inicial": 1000}, esperado=201)
    _entrar_como(api, "beto")
    ajeno = api.get("/api/caja/2/turno")["turno"]
    assert ajeno["ajeno"] is True and "efectivo_esperado" not in ajeno and ajeno["usuario"] == "ana"
    api.post("/api/ventas", {"caja_id": 2, "items": [{"producto_id": productos["pan"]["id"], "cantidad": 1}]},
             esperado=201)                                         # relevo: vender en el turno sí
    api.post("/api/caja/2/cerrar", {"efectivo_contado": 0}, esperado=403)
    _entrar_como(api, "ana")
    assert "efectivo_esperado" in api.get("/api/caja/2/turno")["turno"]
    api.post("/api/caja/2/cerrar", {"efectivo_contado": 3290})


def test_admin_que_pasa_a_cajero_no_conserva_todo(api):
    otro = api.post("/api/usuarios", {"usuario": "jefa", "password": "1111", "rol": "admin"}, esperado=201)
    assert all(otro["permisos"].values()) and not otro["permisos_cajero"]["reportes"]


def test_caja_principal_siempre_activa_al_migrar(app, api):
    from neji.db import inicializar
    api.post("/api/cajas", {"nombre": "Mesón"}, esperado=201)
    from neji.db import conectar
    con = conectar(app.config["DATABASE"])
    con.execute("UPDATE cajas SET activa = 0 WHERE id = 1")      # base vieja con la caja 1 desactivada
    con.close()
    inicializar(app.config["DATABASE"])
    assert {c["nombre"]: c["principal"] for c in api.get("/api/cajas")} == {"Caja 1": 0, "Mesón": 1}
