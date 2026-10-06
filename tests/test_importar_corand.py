"""Importación desde la base de CORAND.ERP (mismo esquema que crea su BaseDatos)."""

import io
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from neji import db

RAIZ = Path(__file__).resolve().parents[1]

ESQUEMA_CORAND = [
    "CREATE TABLE usuarios (usuario TEXT PRIMARY KEY, password TEXT NOT NULL, rol TEXT NOT NULL)",
    "CREATE TABLE departamentos (nombre TEXT PRIMARY KEY)",
    "CREATE TABLE inventario (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL, costo REAL NOT NULL, "
    "precio_venta REAL NOT NULL, stock INTEGER NOT NULL, distribuidor TEXT DEFAULT '', "
    "departamento TEXT DEFAULT 'General', vencimiento TEXT DEFAULT '', principio_activo TEXT DEFAULT '')",
    "CREATE TABLE vademecum (principio_activo TEXT PRIMARY KEY, efecto_terapeutico TEXT, "
    "efectos_adversos TEXT, imagen TEXT DEFAULT '')",
    "CREATE TABLE configuracion (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)",
    "CREATE TABLE recetario_insumos (nombre TEXT PRIMARY KEY, unidad TEXT, precio REAL)",
    "CREATE TABLE recetario_formulas (nombre TEXT PRIMARY KEY, precio_base REAL, unidad TEXT, precio_unidad REAL)",
]


@pytest.fixture
def corand(tmp_path):
    ruta = tmp_path / "corand_erp_pro.db"
    con = sqlite3.connect(ruta)
    for q in ESQUEMA_CORAND:
        con.execute(q)
    con.executemany("INSERT INTO inventario VALUES (?,?,?,?,?,?,?,?,?)", [
        ("7800001", "PARACETAMOL 500MG X 16 COMP", 300.4, 990, 25, "Droguería A", "BIOEQUIVALENTES", "2027-01-31", "PARACETAMOL"),
        ("7800002", "KITADOL 500MG X 24", 1500, 2990, 0, "Droguería B", "Marca", "", "PARACETAMOL"),
        ("7800003", "CREMA HIDRATANTE", 2000, 4990, 5, "", "Perfumeria", "fecha mala", ""),
        ("CON ESPACIO", "MAL CODIGO", 1, 1, 1, "", "General", "", ""),
    ])
    con.executemany("INSERT INTO vademecum (principio_activo, efecto_terapeutico, efectos_adversos) VALUES (?,?,?)", [
        ("PARACETAMOL", "Analgésico y antipirético", "Hepatotoxicidad en sobredosis"),
        ("losartan", "Antihipertensivo (ARA II)", ""),
    ])
    con.executemany("INSERT INTO recetario_insumos VALUES (?,?,?)", [
        ("Paracetamol", "mg", 0.1), ("Vitamina C", "gr", 38.87), ("Cafeina", "mg", 0.2),
        ("PARACETAMOL", "mg", 0.12), ("Colageno", "cucharadas", 5),
    ])
    con.executemany("INSERT INTO recetario_formulas VALUES (?,?,?,?)", [
        ("Cápsulas", 4100.0, "Cápsulas", 42.0), ("CREMAS", 4500.0, "Gramos", 2.5),
        ("PAPELILLOS", 3000.0, "Papelillos", 25.0),
    ])
    con.executemany("INSERT INTO configuracion VALUES (?,?)", [
        ("ticket_empresa", "FARMACIA DE PRUEBA"), ("ticket_direccion", "Calle 123"),
        ("ticket_telefono", "+56 9 1111 2222"), ("ticket_correo", "farmacia@ejemplo.cl"),
        ("ticket_pie", "Gracias por su compra"), ("ticket_rut", ""),
    ])
    con.execute("INSERT INTO usuarios VALUES ('admin', 'admin', 'Administrador')")
    con.commit()
    con.close()
    return ruta


def subir(api, ruta, **opciones):
    datos = {"archivo": (io.BytesIO(ruta.read_bytes()), "corand_erp_pro.db")}
    datos.update({k: "1" if v else "0" for k, v in opciones.items()})
    return api.http.post("/api/importar/corand", data=datos, content_type="multipart/form-data")


def test_importa_todo(api, corand):
    resp = subir(api, corand)
    assert resp.status_code == 200, resp.get_json()
    r = resp.get_json()
    assert (r["productos_creados"], r["productos_actualizados"], r["productos_con_principio"]) == (3, 0, 2)
    assert r["fichas_vademecum"] == 2 and r["formas"] == 3 and r["precios_recetario"] == 3
    avisos = " | ".join(r["advertencias"])
    assert "CON ESPACIO" in avisos and "cucharadas" in avisos and "fecha mala" in avisos
    assert "PARACETAMOL aparecía dos veces" in avisos

    p = api.get("/api/productos/codigo/7800001")
    assert (p["precio_costo"], p["precio_venta"], p["existencia"]) == (300, 990, 25)
    assert (p["departamento"], p["proveedor"], p["vencimiento"]) == ("BIOEQUIVALENTES", "Droguería A", "2027-01-31")
    assert p["principios"] == "PARACETAMOL"
    assert p["principios_detalle"][0]["accion_terapeutica"] == "Analgésico y antipirético"

    pa = {x["nombre"]: x for x in api.get("/api/principios")}
    assert pa["PARACETAMOL"]["precio_receta"] == 0.12 and pa["VITAMINA C"]["unidad_receta"] == "g"
    assert pa["LOSARTAN"]["accion_terapeutica"] == "Antihipertensivo (ARA II)"
    assert pa["COLAGENO"]["precio_receta"] is None

    formas = {f["nombre"]: f for f in api.get("/api/recetario/formas")}
    assert formas["Cápsulas"]["precio_base"] == 4100 and formas["Cápsulas"]["precio_unidad"] == 42
    assert formas["Cremas"]["unidad"] == "g"
    assert (formas["Papelillos"]["unidad"], formas["Papelillos"]["nombre_unidad"]) == ("unidad", "papelillo")

    config = api.get("/api/config")
    assert config["negocio_nombre"] == "FARMACIA DE PRUEBA" and config["modulo_farmacia"] == "1"
    assert config["negocio_email"] == "farmacia@ejemplo.cl"
    assert len(api.get("/api/respaldos")) == 1   # respaldo previo a la importación


def test_reimportar_actualiza_sin_duplicar(api, corand):
    subir(api, corand)
    r = subir(api, corand, existencias=False).get_json()
    assert (r["productos_creados"], r["productos_actualizados"]) == (0, 3)
    assert api.get("/api/productos?q=paracetamol")["total"] == 1
    assert len([x for x in api.get("/api/principios") if x["nombre"] == "PARACETAMOL"]) == 1


def test_solo_vademecum(api, corand):
    r = subir(api, corand, productos=False, recetario=False, negocio=False).get_json()
    assert r["productos_creados"] == 0 and r["fichas_vademecum"] == 2 and r["formas"] == 0
    assert api.get("/api/config")["negocio_nombre"] == "Almacén Prueba"


def test_archivo_que_no_es_corand(api, tmp_path):
    malo = tmp_path / "otra.db"
    con = sqlite3.connect(malo)
    con.execute("CREATE TABLE cosas (x)")
    con.commit()
    con.close()
    assert subir(api, malo).status_code == 400
    texto = tmp_path / "texto.db"
    texto.write_text("no soy una base de datos")
    assert subir(api, texto).status_code == 400


def test_cajero_no_puede_importar(api, corand):
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    assert subir(api, corand).status_code == 403


def test_migracion_de_base_antigua(tmp_path):
    """Una base creada con la primera versión de Neji recibe las columnas nuevas."""
    antiguo = subprocess.run(["git", "show", "6fecf6e:neji/schema.sql"], capture_output=True, text=True,
                             cwd=RAIZ)
    if antiguo.returncode != 0:
        pytest.skip("No está disponible el historial de git")
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript(antiguo.stdout)
    con.close()
    db.inicializar(str(ruta))
    con = sqlite3.connect(ruta)
    assert "receta_id" in {r[1] for r in con.execute("PRAGMA table_info(venta_items)")}
    assert {"proveedor", "vencimiento"} <= {r[1] for r in con.execute("PRAGMA table_info(productos)")}
    assert con.execute("SELECT COUNT(*) FROM formas_magistrales").fetchone()[0] == 3
    con.close()


def test_cli(tmp_path, corand):
    raiz = RAIZ
    datos = tmp_path / "datos_cli"
    entorno = {**os.environ, "NEJI_DATOS": str(datos)}
    sin_admin = subprocess.run([sys.executable, "importar_corand.py", str(corand)], cwd=raiz,
                               capture_output=True, text=True, env=entorno)
    assert sin_admin.returncode != 0 and "administrador" in sin_admin.stderr
    con = sqlite3.connect(datos / "neji.db")
    con.execute("INSERT INTO usuarios (usuario, nombre, password_hash, rol, creado) "
                "VALUES ('admin', 'Admin', 'x', 'admin', '2026-01-01 00:00:00')")
    con.commit()
    con.close()
    ok = subprocess.run([sys.executable, "importar_corand.py", str(corand), "--sin-negocio"], cwd=raiz,
                        capture_output=True, text=True, env=entorno)
    assert ok.returncode == 0, ok.stderr
    assert "Productos nuevos: 3" in ok.stdout and "Respaldo creado" in ok.stdout


def test_vademecum_combinado_y_duplicados_con_tilde(api, tmp_path, corand):
    con = sqlite3.connect(corand)
    con.executemany("INSERT INTO vademecum (principio_activo, efecto_terapeutico) VALUES (?,?)", [
        ("PARACETAMOL + CAFEINA", "Analgésico"), ("ácido fólico 5 mg", "Antianémico")])
    con.executemany("INSERT INTO recetario_insumos VALUES (?,?,?)", [
        ("ÁCIDO FÓLICO", "mg", 2.0), ("ACIDO FOLICO", "mg", 3.0)])
    con.commit()
    con.close()
    r = subir(api, corand).get_json()
    avisos = " | ".join(r["advertencias"])
    assert "PARACETAMOL + CAFEINA" in avisos and "combina varios" in avisos
    assert "ACIDO FOLICO aparecía dos veces" in avisos
    nombres = [p["nombre"] for p in api.get("/api/principios")]
    assert "PARACETAMOL + CAFEINA" not in nombres
    folico = [p for p in api.get("/api/principios?q=folico")]
    assert len(folico) == 1 and folico[0]["accion_terapeutica"] == "Antianémico"
    assert folico[0]["precio_receta"] == 3.0


@pytest.mark.parametrize("texto,esperado", [
    ("Cápsulas", ("unidad", "cápsula")), ("Gramos", ("g", "gramo")), ("gr.", ("g", "gramo")),
    ("Mililitros", ("ml", "ml")), ("cc", ("ml", "ml")), ("CM3", ("ml", "ml")),
    ("Unidades", ("unidad", "unidad")), ("un.", ("unidad", "unidad")), ("U", ("unidad", "unidad")),
    ("Papelillos", ("unidad", "papelillo")), ("", ("unidad", "unidad")),
    ("c.c.", ("ml", "ml")), ("Miligramos", ("unidad", "miligramo")), ("Jabones", ("unidad", "jabón")),
    ("Óvulos vaginales", ("unidad", "óvulo vaginal")), ("Sobres", ("unidad", "sobre")),
    ("Cápsulas de gelatina", ("unidad", "cápsula de gelatina")),
])
def test_unidad_forma(texto, esperado):
    from neji.servicios.importar_corand import unidad_forma

    assert unidad_forma(texto) == esperado


def test_producto_borrado_que_vuelve_sin_principio_anterior(api, turno, corand):
    p = api.post("/api/productos", {"codigo": "7800003", "descripcion": "IBUPROFENO 400 MG", "precio_venta": 1,
                                    "existencia": 5, "principios": "IBUPROFENO 400 mg"}, esperado=201)
    api.post("/api/ventas", {"caja_id": 1, "items": [{"producto_id": p["id"], "cantidad": 1}]}, esperado=201)
    api.delete(f"/api/productos/{p['id']}")   # con ventas: queda desactivado
    subir(api, corand)
    vuelto = api.get("/api/productos/codigo/7800003")   # en CORAND es CREMA HIDRATANTE, sin principio activo
    assert vuelto["id"] == p["id"] and vuelto["descripcion"] == "CREMA HIDRATANTE"
    assert vuelto["principios"] is None
