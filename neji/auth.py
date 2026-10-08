"""Sesión de usuario y permisos (administrador / cajero)."""

from functools import wraps

from flask import g, session

from .db import config_activa, fila, get_db
from .validar import ErrorNegocio


def usuario_actual():
    if "usuario" not in g:
        g.usuario = None
        usuario_id = session.get("usuario_id")
        if usuario_id:
            g.usuario = fila(get_db().execute(
                "SELECT id, usuario, nombre, rol FROM usuarios WHERE id = ? AND activo = 1",
                (usuario_id,)).fetchone())
    return g.usuario


def exigir_login():
    usuario = usuario_actual()
    if usuario is None:
        raise ErrorNegocio("Debes iniciar sesión.", status=401, codigo="sin_sesion")
    return usuario


def solo_admin(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if exigir_login()["rol"] != "admin":
            raise ErrorNegocio("Solo un administrador puede hacer esto.", status=403)
        return vista(*args, **kwargs)
    return envoltura


def con_permiso(clave_config):
    """Admin siempre; cajero solo si la opción de configuración está activada."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = exigir_login()
            if usuario["rol"] != "admin" and not config_activa(get_db(), clave_config):
                raise ErrorNegocio("No tienes permiso para hacer esto.", status=403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador
