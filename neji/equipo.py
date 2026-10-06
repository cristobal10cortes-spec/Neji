"""Datos del equipo donde corre Neji POS: carpeta de datos y conexión de otras cajas."""

import os
import socket
import sqlite3


def ip_local():
    """IP de este equipo en la red local (la que deben usar las otras cajas)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def opcion_activada(ruta_db, clave):
    """Lee una opción sí/no de la configuración antes de iniciar el servidor."""
    try:
        con = sqlite3.connect(ruta_db)
        try:
            fila = con.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return fila is not None and fila[0] == "1"


def modo_red_configurado(ruta_db):
    """True si en Configuración → Cajas se permitió que otras cajas se conecten a este equipo."""
    return opcion_activada(ruta_db, "modo_red")


def anunciar(red, puerto, escritorio=False):
    """Deja anotado cómo se inició el servidor, para mostrarlo en Configuración."""
    os.environ["NEJI_RED"] = "1" if red else "0"
    os.environ["NEJI_PUERTO"] = str(puerto)
    os.environ["NEJI_ESCRITORIO"] = "1" if escritorio else "0"


def describir(carpeta_datos):
    red = os.environ.get("NEJI_RED") == "1"
    puerto = os.environ.get("NEJI_PUERTO") or "5000"
    return {
        "carpeta_datos": os.path.abspath(carpeta_datos),
        "escritorio": os.environ.get("NEJI_ESCRITORIO") == "1",
        "red_activa": red,
        "direccion_red": f"http://{ip_local()}:{puerto}" if red else None,
    }
