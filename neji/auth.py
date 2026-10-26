"""Sesión de usuario y permisos.

El administrador puede todo. Cada cajero tiene sus propios permisos (Configuración → Usuarios).
"""

import hashlib
import json
from functools import wraps

from flask import g, session

from .db import fila, get_db
from .validar import ErrorNegocio, booleano

# clave, qué permite, si un cajero nuevo lo tiene, solo con el módulo farmacia
PERMISOS = [
    ("cambiar_precio", "Cambiar precios y aplicar descuentos en la venta", False, False),
    ("articulo_comun", "Vender artículos comunes (sin registrar, con precio libre)", True, False),
    ("devoluciones", "Hacer devoluciones", False, False),
    ("movimientos_caja", "Registrar entradas y salidas de efectivo", True, False),
    ("corte", "Hacer el corte de su caja (el turno que abrió)", True, False),
    ("corte_general", "Corte general de todas las cajas, cortes de otros cajeros e historial", False, False),
    ("clientes_credito", "Dar crédito (límite) a clientes y borrarlos", False, False),
    ("productos", "Crear, editar e importar productos (ve los costos)", False, False),
    ("inventario", "Inventario: entradas, ajustes y compras sugeridas (ve los costos)", False, False),
    ("reportes", "Ver reportes, costos y ganancias", False, False),
    ("vademecum", "Editar el vademécum y los precios del recetario", False, True),
]
CLAVES_PERMISOS = [p[0] for p in PERMISOS]
PERMISOS_POR_DEFECTO = {clave: defecto for clave, _, defecto, _ in PERMISOS}
# Quien maneja productos, inventario o reportes necesita ver los costos; la ganancia, solo reportes.
PERMISOS_CON_COSTOS = ("reportes", "productos", "inventario")


def leer_permisos(datos, actuales=None):
    """Permisos de un cajero desde lo que manda el formulario: solo claves conocidas, sí/no."""
    permisos = dict(actuales or PERMISOS_POR_DEFECTO)
    if datos is None:
        return permisos
    if not isinstance(datos, dict):
        raise ErrorNegocio("Los permisos no son válidos.")
    for clave in CLAVES_PERMISOS:
        if clave in datos:
            permisos[clave] = booleano(datos[clave])
    return permisos


def permisos_de(usuario):
    """Todos los permisos (clave -> bool) de una fila de usuarios. El administrador los tiene todos."""
    if usuario["rol"] == "admin":
        return {clave: True for clave in CLAVES_PERMISOS}
    try:
        guardados = json.loads(usuario["permisos"] or "{}")
    except (TypeError, ValueError):
        guardados = {}
    return {clave: bool(guardados.get(clave, defecto)) for clave, defecto in PERMISOS_POR_DEFECTO.items()}


def sello(password_hash):
    """Marca de la contraseña con la que se inició la sesión: si después se cambia, la sesión deja de valer."""
    return hashlib.sha256(f"neji-sesion:{password_hash}".encode()).hexdigest()[:24]


def usuario_actual():
    if "usuario" not in g:
        g.usuario = None
        usuario_id = session.get("usuario_id")
        if usuario_id:
            usuario = fila(get_db().execute(
                "SELECT id, usuario, nombre, nombre_ticket, rol, permisos, password_hash FROM usuarios "
                "WHERE id = ? AND activo = 1", (usuario_id,)).fetchone())
            if usuario is not None and session.get("sello") != sello(usuario.pop("password_hash")):
                usuario = None          # cambió la contraseña (o es una sesión de antes): hay que volver a entrar
            if usuario is not None:
                usuario["permisos"] = permisos_de(usuario)
            g.usuario = usuario
    return g.usuario


def exigir_login():
    usuario = usuario_actual()
    if usuario is None:
        raise ErrorNegocio("Debes iniciar sesión.", status=401, codigo="sin_sesion")
    return usuario


def tiene_permiso(usuario, clave):
    return usuario["rol"] == "admin" or bool(usuario["permisos"].get(clave))


def ve_costos(usuario):
    return any(tiene_permiso(usuario, clave) for clave in PERMISOS_CON_COSTOS)


def solo_admin(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if exigir_login()["rol"] != "admin":
            raise ErrorNegocio("Solo un administrador puede hacer esto.", status=403)
        return vista(*args, **kwargs)
    return envoltura


def con_permiso(clave):
    """Admin siempre; un cajero, solo si tiene ese permiso."""
    assert clave in CLAVES_PERMISOS, clave

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not tiene_permiso(exigir_login(), clave):
                raise ErrorNegocio("No tienes permiso para hacer esto.", status=403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador
