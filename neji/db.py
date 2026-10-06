"""Conexión a SQLite y utilidades de transacción."""

import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import current_app, g

ESQUEMA = Path(__file__).with_name("schema.sql")

CONFIG_POR_DEFECTO = {
    "negocio_nombre": "Mi Negocio",
    "negocio_rut": "",
    "negocio_giro": "",
    "negocio_direccion": "",
    "negocio_telefono": "",
    "negocio_email": "",
    "ticket_encabezado": "",
    "ticket_pie": "¡Gracias por su compra!",
    "ticket_leyenda": "Comprobante interno de venta",
    "ticket_ancho": "80",
    "imprimir_automatico": "1",
    "iva_porcentaje": "19",
    "redondeo_efectivo": "1",
    "permitir_stock_negativo": "0",
    "cajero_puede_devolver": "0",
    "cajero_puede_cambiar_precio": "0",
    "respaldos_mantener": "10",
    "ultimo_respaldo": "",
    "modulo_farmacia": "0",
    "receta_redondeo": "1",
    "recetario_semilla": "0",
    "modo_red": "0",
    "impresion_directa": "0",
}

# Formas farmacéuticas iniciales del recetario (mismos valores que CORAND.ERP).
FORMAS_INICIALES = [
    # nombre, unidad, nombre_unidad, precio_base, precio_unidad, cantidad_sugerida
    ("Cápsulas", "unidad", "cápsula", 4000, 40, 30),
    ("Cremas", "g", "gramo", 4500, 2.5, 50),
    ("Lociones", "ml", "ml", 4000, 1, 100),
]


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sin_acentos(texto):
    """'Ácido Fólico' -> 'acido folico'. Para buscar sin importar tildes ni mayúsculas."""
    if texto is None:
        return None
    descompuesto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def conectar(ruta):
    con = sqlite3.connect(ruta, isolation_level=None, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.create_function("sin_acentos", 1, sin_acentos, deterministic=True)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def cerrar_db(_error=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


@contextmanager
def transaccion(con):
    """Transacción con bloqueo de escritura inmediato (evita choques entre cajas)."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def inicializar(ruta):
    con = conectar(ruta)
    try:
        con.executescript(ESQUEMA.read_text(encoding="utf-8"))
        migrar(con)
        for clave, valor in CONFIG_POR_DEFECTO.items():
            con.execute("INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))
        con.execute("INSERT OR IGNORE INTO cajas (id, nombre) VALUES (1, 'Caja 1')")
        sembrar_recetario(con)
    finally:
        con.close()


def _columnas(con, tabla):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({tabla})")}


def migrar(con):
    """Agrega a bases creadas con versiones anteriores las columnas nuevas."""
    if "receta_id" not in _columnas(con, "venta_items"):
        con.execute("ALTER TABLE venta_items ADD COLUMN receta_id INTEGER "
                    "REFERENCES recetas_magistrales(id)")
    productos = _columnas(con, "productos")
    for columna in ("proveedor", "vencimiento"):
        if columna not in productos:
            con.execute(f"ALTER TABLE productos ADD COLUMN {columna} TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_venta_items_receta ON venta_items(receta_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_productos_vencimiento ON productos(vencimiento)")


def sembrar_recetario(con):
    """Carga las formas farmacéuticas iniciales una sola vez (después se pueden editar o borrar)."""
    with transaccion(con):
        if con.execute("SELECT valor FROM config WHERE clave = 'recetario_semilla'").fetchone()[0] == "1":
            return
        for forma in FORMAS_INICIALES:
            con.execute(
                "INSERT OR IGNORE INTO formas_magistrales "
                "(nombre, unidad, nombre_unidad, precio_base, precio_unidad, cantidad_sugerida) "
                "VALUES (?, ?, ?, ?, ?, ?)", forma)
        con.execute("UPDATE config SET valor = '1' WHERE clave = 'recetario_semilla'")


def init_app(app):
    inicializar(app.config["DATABASE"])
    app.teardown_appcontext(cerrar_db)


def fila(row):
    return dict(row) if row is not None else None


def filas(rows):
    return [dict(r) for r in rows]


def leer_config(con):
    return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}


def config_activa(con, clave):
    row = con.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    return row is not None and row["valor"] == "1"
