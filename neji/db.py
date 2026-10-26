"""Conexión a SQLite y utilidades de transacción."""

import json
import os
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
    "ticket_diseno": "",   # líneas del encabezado y del pie (JSON); vacío = el ticket de siempre
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
    # WAL necesita memoria compartida en el mismo disco: en discos de red (PythonAnywhere) se apaga
    # con NEJI_SIN_WAL=1 y se usa el diario de siempre.
    con.execute("PRAGMA journal_mode = DELETE" if os.environ.get("NEJI_SIN_WAL") == "1"
                else "PRAGMA journal_mode = WAL")
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
        # Siempre hay una caja principal activa (la del corte general): la primera activa, si nadie eligió otra.
        con.execute("UPDATE cajas SET principal = 0 WHERE activa = 0")
        con.execute("UPDATE cajas SET principal = 1 WHERE id = (SELECT MIN(id) FROM cajas WHERE activa = 1) "
                    "AND NOT EXISTS (SELECT 1 FROM cajas WHERE principal = 1)")
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
    if "principal" not in _columnas(con, "cajas"):
        con.execute("ALTER TABLE cajas ADD COLUMN principal INTEGER NOT NULL DEFAULT 0")
    if "corte_general_id" not in _columnas(con, "turnos"):
        con.execute("ALTER TABLE turnos ADD COLUMN corte_general_id INTEGER REFERENCES cortes_generales(id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_turnos_corte_general ON turnos(corte_general_id)")
    clientes = _columnas(con, "clientes")
    for columna in ("comuna", "ciudad"):     # para la factura electrónica
        if columna not in clientes:
            con.execute(f"ALTER TABLE clientes ADD COLUMN {columna} TEXT")
    documentos = _columnas(con, "sii_documentos")
    for columna in ("correo_receptor", "correo_estado", "correo_glosa", "correo_enviado"):   # versión 0.1.30
        if columna not in documentos:
            con.execute(f"ALTER TABLE sii_documentos ADD COLUMN {columna} TEXT")
    usuarios = _columnas(con, "usuarios")
    if "nombre_ticket" not in usuarios:
        con.execute("ALTER TABLE usuarios ADD COLUMN nombre_ticket TEXT")
    if "permisos" not in usuarios:
        con.execute("ALTER TABLE usuarios ADD COLUMN permisos TEXT")
        # Antes los permisos de los cajeros eran opciones generales: cada cajero parte con lo mismo que tenía.
        opcion = dict(con.execute("SELECT clave, valor FROM config WHERE clave IN "
                                  "('cajero_puede_cambiar_precio', 'cajero_puede_devolver')").fetchall())
        permisos = {"cambiar_precio": opcion.get("cajero_puede_cambiar_precio") == "1",
                    "devoluciones": opcion.get("cajero_puede_devolver") == "1",
                    "movimientos_caja": True, "corte": True}
        con.execute("UPDATE usuarios SET permisos = ? WHERE rol = 'cajero'", (json.dumps(permisos),))


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
