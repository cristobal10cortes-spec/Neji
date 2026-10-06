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


CAMPOS_PRIVADOS = {"precio_costo", "costo_unitario", "ganancia", "costo_estimado"}


def sin_costos(datos):
    """Quita costos y ganancias de la respuesta si quien consulta es cajero."""
    from ..auth import usuario_actual

    if usuario_actual()["rol"] == "admin":
        return datos

    def limpiar(valor):
        if isinstance(valor, dict):
            return {k: limpiar(v) for k, v in valor.items() if k not in CAMPOS_PRIVADOS}
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


from . import caja, clientes, inventario, productos, reportes, sistema, ventas  # noqa: E402,F401
