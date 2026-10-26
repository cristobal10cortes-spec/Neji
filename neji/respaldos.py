"""Respaldo automático de la base de datos (estilo eleventa: guarda las últimas N copias)."""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from .db import ahora, conectar, inicializar
from .validar import ErrorNegocio

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


TABLAS_NECESARIAS = {"config", "usuarios", "productos", "ventas"}


def restaurar(ruta_db, carpeta, archivo, mantener=10):
    """Copia un respaldo subido sobre la base de datos en uso. Devuelve el respaldo de lo anterior."""
    os.makedirs(carpeta, exist_ok=True)
    fd, temporal = tempfile.mkstemp(suffix=".db", dir=carpeta)
    os.close(fd)
    try:
        archivo.save(temporal)
        try:
            origen = sqlite3.connect(f"file:{temporal}?mode=ro", uri=True)
            try:
                ok = origen.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                tablas = {r[0] for r in origen.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                origen.close()
        except sqlite3.DatabaseError:
            raise ErrorNegocio("El archivo no es un respaldo de Neji (debe ser un archivo .db).") from None
        if not ok:
            raise ErrorNegocio("El respaldo está dañado y no se puede usar.")
        if not TABLAS_NECESARIAS <= tablas:
            raise ErrorNegocio("El archivo no es un respaldo de Neji (debe ser un archivo .db).")
        if not usuarios_en(temporal):
            raise ErrorNegocio("El respaldo no tiene usuarios: no podrías entrar después de restaurarlo.")
        quitar_extras(temporal)
        previo = crear_respaldo(ruta_db, carpeta, max(int(mantener), 1) + 1)
        origen = sqlite3.connect(temporal)
        destino = conectar(ruta_db)
        try:
            origen.backup(destino)
        finally:
            destino.close()
            origen.close()
        inicializar(ruta_db)   # un respaldo de una versión anterior recibe las columnas nuevas
        return previo
    finally:
        try:
            os.remove(temporal)
        except OSError:
            pass


def usuarios_en(ruta):
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM usuarios WHERE activo = 1").fetchone()[0] > 0
    finally:
        con.close()


def quitar_extras(ruta):
    """Neji no usa triggers ni vistas: si un respaldo los trae (un archivo preparado para que, por ejemplo, un
    trigger cambie permisos o precios a escondidas), se quitan antes de restaurarlo."""
    con = sqlite3.connect(ruta)
    try:
        extras = con.execute("SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall()
        for tipo, nombre in extras:
            con.execute(f'DROP {"TRIGGER" if tipo == "trigger" else "VIEW"} IF EXISTS "{nombre.replace(chr(34), chr(34) * 2)}"')
        con.commit()
        return len(extras)
    finally:
        con.close()
