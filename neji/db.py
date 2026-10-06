"""Conexión a SQLite y utilidades de transacción."""

import sqlite3
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
}


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar(ruta):
    con = sqlite3.connect(ruta, isolation_level=None, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
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
        for clave, valor in CONFIG_POR_DEFECTO.items():
            con.execute("INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))
        con.execute("INSERT OR IGNORE INTO cajas (id, nombre) VALUES (1, 'Caja 1')")
    finally:
        con.close()


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
