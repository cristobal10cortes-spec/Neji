"""Respaldo automático de la base de datos (estilo eleventa: guarda las últimas N copias)."""

import os
import sqlite3
from datetime import datetime, timedelta

from .db import ahora, conectar

PREFIJO = "neji-"


def crear_respaldo(ruta_db, carpeta, mantener=10):
    os.makedirs(carpeta, exist_ok=True)
    base = f"{PREFIJO}{datetime.now():%Y%m%d-%H%M%S}"
    nombre, n = f"{base}.db", 1
    while os.path.exists(os.path.join(carpeta, nombre)):
        n += 1
        nombre = f"{base}-{n}.db"
    origen = sqlite3.connect(ruta_db)
    destino = sqlite3.connect(os.path.join(carpeta, nombre))
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    limpiar(carpeta, mantener)
    return nombre


def listar(carpeta):
    if not os.path.isdir(carpeta):
        return []
    respaldos = []
    for nombre in os.listdir(carpeta):
        if nombre.startswith(PREFIJO) and nombre.endswith(".db"):
            ruta = os.path.join(carpeta, nombre)
            respaldos.append({
                "nombre": nombre,
                "tamano": os.path.getsize(ruta),
                "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return sorted(respaldos, key=lambda r: r["nombre"], reverse=True)


def limpiar(carpeta, mantener):
    for r in listar(carpeta)[max(int(mantener), 1):]:
        os.remove(os.path.join(carpeta, r["nombre"]))


def respaldo_automatico(app, cada=timedelta(hours=24)):
    """Crea un respaldo si el último tiene más de `cada`. Devuelve el nombre o None."""
    con = conectar(app.config["DATABASE"])
    try:
        filas = dict(con.execute(
            "SELECT clave, valor FROM config WHERE clave IN ('ultimo_respaldo', 'respaldos_mantener')"
        ).fetchall())
        ultimo = filas.get("ultimo_respaldo") or ""
        if ultimo:
            try:
                if datetime.now() - datetime.strptime(ultimo, "%Y-%m-%d %H:%M:%S") < cada:
                    return None
            except ValueError:
                pass
        nombre = crear_respaldo(app.config["DATABASE"], app.config["RESPALDOS"],
                                int(filas.get("respaldos_mantener") or 10))
        con.execute("UPDATE config SET valor = ? WHERE clave = 'ultimo_respaldo'", (ahora(),))
        return nombre
    finally:
        con.close()
