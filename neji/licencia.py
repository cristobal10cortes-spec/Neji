"""Licencias de Neji POS: 15 días de prueba y licencias de pago único, por caja o por local (multicaja).

- Una licencia es un texto firmado (Ed25519) con la llave privada del vendedor, que solo está en su computador
  (herramientas/licencias.py la crea y firma). Neji trae las llaves públicas (LLAVES_PUBLICAS) y con ellas
  revisa que la licencia sea auténtica: sin la llave privada nadie puede hacer una.
- La licencia dice a quién se vendió, el tipo (caja: una caja; local: varias o todas las cajas del local) y en
  qué computador vale: el «código de equipo» del que tiene la base de Neji (las otras cajas del local se
  conectan a él), o cualquiera («*»).
- Sin licencia, Neji funciona completo 15 días desde que se instaló. Después se puede ver, respaldar y
  configurar todo, pero no vender.
- Sin llaves públicas (en desarrollo, o en una compilación sin ellas) no hay control de licencias.
"""

import base64
import hashlib
import json
import sys
import uuid
from datetime import date, timedelta

from .validar import ErrorNegocio

# Llaves públicas del vendedor (la que imprime `python herramientas/licencias.py llave`), en base64. Van en el
# código y no en un archivo aparte, para que no se puedan cambiar por otras junto al programa.
LLAVES_PUBLICAS = [
    "00QZU6AS9Jl2rVW5OqkS+05S1s5ridkzoVDZfFg6V6w=",     # Cristóbal (NejiLicencias, creada el 31-10-2026)
]

DIAS_PRUEBA = 15
PREFIJO = "NEJI-"
TIPOS = {"caja": "Caja", "local": "Local (multicaja)"}
CUALQUIER_EQUIPO = "*"


# --- Formato -------------------------------------------------------------------------------------------

def _b64(datos):
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _de_b64(texto):
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def armar(datos, llave_privada):
    """Licencia firmada con la llave privada (Ed25519PrivateKey). La usa el generador del vendedor."""
    contenido = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return f"{PREFIJO}{_b64(contenido)}.{_b64(llave_privada.sign(contenido))}"


def leer(texto, llaves=None):
    """Texto de una licencia -> sus datos, si la firmó una de las llaves. Lanza ErrorNegocio si no."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    texto = "".join(str(texto or "").split())
    if not texto.startswith(PREFIJO) or texto.count(".") != 1:
        raise ErrorNegocio("Eso no es una licencia de Neji POS: cópiala completa, desde «NEJI-» hasta el final.")
    cuerpo, firma = texto[len(PREFIJO):].split(".")
    try:
        contenido, firma = _de_b64(cuerpo), _de_b64(firma)
        datos = json.loads(contenido)
    except (ValueError, TypeError):
        raise ErrorNegocio("La licencia está incompleta o dañada: vuelve a copiarla completa.") from None
    for llave in (LLAVES_PUBLICAS if llaves is None else llaves):
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(llave)).verify(firma, contenido)
        except (InvalidSignature, ValueError):
            continue
        if not isinstance(datos, dict) or datos.get("tipo") not in TIPOS or not datos.get("cliente"):
            raise ErrorNegocio("La licencia no trae el cliente o el tipo: pide otra a quien te vendió Neji POS.")
        return datos
    raise ErrorNegocio("La licencia no es válida: no la emitió quien vende Neji POS o se modificó.")


# --- Este computador -----------------------------------------------------------------------------------

def _identificador():
    """Lo que identifica al computador: el MachineGuid de Windows (o el machine-id de Linux)."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as llave:
                return str(winreg.QueryValueEx(llave, "MachineGuid")[0])
        except OSError:
            pass
    for ruta in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(ruta, encoding="ascii") as archivo:
                valor = archivo.read().strip()
            if valor:
                return valor
        except OSError:
            pass
    return f"{uuid.getnode():012x}"


def codigo_equipo():
    """El código que el cliente le manda al vendedor para su licencia: XXXX-XXXX-XXXX-XXXX."""
    resumen = base64.b32encode(hashlib.sha256(f"neji-equipo:{_identificador()}".encode()).digest()[:10]).decode()
    return "-".join(resumen[i:i + 4] for i in range(0, 16, 4))


def normalizar_equipo(texto):
    texto = "".join(str(texto or "").split()).upper()
    if texto == CUALQUIER_EQUIPO:
        return texto
    limpio = texto.replace("-", "")
    return "-".join(limpio[i:i + 4] for i in range(0, len(limpio), 4))


# --- Lo guardado ---------------------------------------------------------------------------------------

def _valor(con, clave):
    fila = con.execute("SELECT valor FROM licencia WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else None


def _poner(con, clave, valor):
    con.execute("INSERT INTO licencia (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = ?",
                (clave, valor, valor))


def _marca_windows(fecha=None):
    """En NejiPOS.exe, la fecha de instalación también queda en el registro del usuario de Windows: así borrar la
    base no reinicia la prueba. Devuelve la guardada (o None)."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\NejiPOS") as llave:
            if fecha:
                winreg.SetValueEx(llave, "Inicio", 0, winreg.REG_SZ, fecha)
                return fecha
            return str(winreg.QueryValueEx(llave, "Inicio")[0])
    except OSError:
        return None


def _hoy(con):
    """La fecha de hoy, pero nunca antes de la última vista (atrasar el reloj no alarga la prueba)."""
    hoy = date.today().isoformat()
    ultima = max(filter(None, [_valor(con, "ultima_fecha"),
                               (con.execute("SELECT MAX(fecha) FROM ventas").fetchone()[0] or "")[:10]]),
                 default="")
    if hoy > ultima:
        _poner(con, "ultima_fecha", hoy)
        return hoy
    return ultima


def _inicio_prueba(con, hoy):
    guardado, windows = _valor(con, "prueba_inicio"), _marca_windows()
    inicio = min(filter(None, [guardado, windows]), default=hoy)
    if guardado != inicio:
        _poner(con, "prueba_inicio", inicio)
    if windows is None or windows > inicio:
        _marca_windows(inicio)
    return inicio


def _licencia_guardada(con):
    """(datos, error) de la licencia activada en este equipo; (None, None) si no hay."""
    texto = _valor(con, "texto")
    if not texto:
        return None, None
    try:
        datos = leer(texto)
    except ErrorNegocio as e:
        return None, str(e)
    if datos.get("equipo") not in (CUALQUIER_EQUIPO, codigo_equipo()):
        return None, (f"La licencia guardada es de otro computador (código {datos.get('equipo')}). "
                      "Pide una para este equipo.")
    return datos, None


# --- Estado y reglas -----------------------------------------------------------------------------------

def control_activo():
    return bool(LLAVES_PUBLICAS)


def estado(con):
    """{estado: libre | activa | prueba | vencida, puede_vender, cajas (0 = sin límite), ...}."""
    if not control_activo():
        return {"estado": "libre", "puede_vender": True, "cajas": 0}
    datos, error = _licencia_guardada(con)
    if datos:
        return {"estado": "activa", "puede_vender": True, "cajas": int(datos.get("cajas") or 0),
                "cliente": datos["cliente"], "rut": datos.get("rut") or "", "tipo": datos["tipo"],
                "tipo_texto": TIPOS[datos["tipo"]], "numero": datos.get("numero") or "",
                "emitida": datos.get("emitida") or "", "equipo": datos.get("equipo")}
    hoy = _hoy(con)
    inicio = _inicio_prueba(con, hoy)
    restantes = DIAS_PRUEBA - (date.fromisoformat(hoy) - date.fromisoformat(inicio)).days
    vence = (date.fromisoformat(inicio) + timedelta(days=DIAS_PRUEBA)).isoformat()
    resultado = {"estado": "prueba" if restantes > 0 else "vencida", "puede_vender": restantes > 0, "cajas": 0,
                 "dias": max(0, restantes), "inicio": inicio, "vence": vence}
    if error:
        resultado["error"] = error
    return resultado


def activar(con, texto):
    datos = leer(texto)
    equipo = codigo_equipo()
    if datos.get("equipo") not in (CUALQUIER_EQUIPO, equipo):
        raise ErrorNegocio(f"Esta licencia es para otro computador (código {datos.get('equipo')}). El código de "
                           f"este es {equipo}: pide la licencia con ese código.")
    _poner(con, "texto", "".join(str(texto).split()))
    return datos


def cajas_habilitadas(con, limite):
    """Las cajas que pueden vender con una licencia de `limite` cajas: la principal y las primeras activas."""
    return [f["id"] for f in con.execute(
        "SELECT id FROM cajas WHERE activa = 1 ORDER BY principal DESC, id LIMIT ?", (limite,))]


def exigir_venta(con, caja_id):
    """Antes de registrar una venta (dentro de su transacción)."""
    e = estado(con)
    if not e["puede_vender"]:
        raise ErrorNegocio("Terminaron los 15 días de prueba de Neji POS: para seguir vendiendo, activa la "
                           "licencia en Configuración → Licencia.", status=403)
    if e["cajas"] and caja_id not in cajas_habilitadas(con, e["cajas"]):
        raise ErrorNegocio(f"La licencia es para {_cajas(e['cajas'])}: esta caja no está incluida. Vende desde la "
                           "caja principal, o pide una licencia para más cajas.", status=403)


def exigir_cupo_caja(con):
    """Antes de crear o reactivar una caja."""
    e = estado(con)
    activas = con.execute("SELECT COUNT(*) FROM cajas WHERE activa = 1").fetchone()[0]
    if e["cajas"] and activas >= e["cajas"]:
        raise ErrorNegocio(f"La licencia es para {_cajas(e['cajas'])}. Para más cajas, pide una licencia de local "
                           "(multicaja).", status=403)


def _cajas(n):
    return "una caja" if n == 1 else f"{n} cajas"


def resumen(con):
    """Lo que ven todas las cajas (en /api/config): para avisar de la prueba o de que terminó."""
    e = estado(con)
    return {k: e[k] for k in ("estado", "dias") if k in e}
