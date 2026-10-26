"""API JSON de Neji POS. Todas las rutas viven bajo /api."""

from flask import Blueprint, request

from ..auth import exigir_login
from ..validar import ErrorNegocio

bp = Blueprint("api", __name__, url_prefix="/api")

RUTAS_PUBLICAS = {"api.estado", "api.login", "api.setup"}


@bp.before_request
def _proteger():
    if request.endpoint not in RUTAS_PUBLICAS:
        exigir_login()


CAMPOS_COSTO = {"precio_costo", "costo_unitario", "costo_estimado"}
CAMPOS_GANANCIA = {"ganancia"}


def sin_costos(datos):
    """Quita costos (sin permiso de productos, inventario o reportes) y ganancias (sin permiso de reportes)."""
    from ..auth import tiene_permiso, usuario_actual, ve_costos

    usuario = usuario_actual()
    privados = (set() if ve_costos(usuario) else CAMPOS_COSTO) | \
        (set() if tiene_permiso(usuario, "reportes") else CAMPOS_GANANCIA)
    if not privados:
        return datos

    def limpiar(valor):
        if isinstance(valor, dict):
            return {k: limpiar(v) for k, v in valor.items() if k not in privados}
        if isinstance(valor, list):
            return [limpiar(v) for v in valor]
        return valor

    return limpiar(datos)


def datos_json():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        raise ErrorNegocio("Datos inválidos.")
    return datos


def rango_fechas():
    """Lee ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD (por defecto, hoy)."""
    from datetime import date

    from ..validar import fecha

    hoy = date.today().isoformat()
    desde = fecha(request.args.get("desde"), "desde") or hoy
    hasta = fecha(request.args.get("hasta"), "hasta") or desde
    if hasta < desde:
        raise ErrorNegocio("La fecha final no puede ser anterior a la inicial.")
    return desde, hasta, f"{desde} 00:00:00", f"{hasta} 23:59:59"


from . import (caja, clientes, farmacia, inventario, productos, recetario, reportes,  # noqa: E402,F401
               sii, sistema, ventas)
