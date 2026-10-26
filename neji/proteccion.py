"""La clave secreta de Neji guardada con la protección de Windows (DPAPI).

Con esa clave se firman las sesiones y se cifran la contraseña de la firma electrónica y la del correo. En
Windows queda cifrada para ESTE computador (CryptProtectData con alcance de equipo): si alguien copia la carpeta de
datos (o un respaldo) a otro computador, no puede leerla. En Linux y macOS queda en un archivo que solo puede leer
el usuario dueño (permisos 600).
"""

import base64
import os
import secrets
import sys
from pathlib import Path

PREFIJO = b"DPAPI1:"
DESCRIPCION = "Neji POS"
CRYPTPROTECT_LOCAL_MACHINE = 0x4
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(datos, proteger):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(datos, len(datos))
    entrada = Blob(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = Blob()
    banderas = CRYPTPROTECT_UI_FORBIDDEN | (CRYPTPROTECT_LOCAL_MACHINE if proteger else 0)
    if proteger:
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), DESCRIPCION, None, None, None, banderas,
                                      ctypes.byref(salida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, banderas,
                                        ctypes.byref(salida))
    if not ok:
        raise OSError(f"DPAPI: error {ctypes.GetLastError()}")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(salida.pbData)


def proteger(texto):
    """Texto -> bytes para guardar (cifrados con DPAPI en Windows)."""
    if sys.platform == "win32":
        return PREFIJO + base64.b64encode(_dpapi(texto.encode("utf-8"), True))
    return texto.encode("utf-8")


def leer(contenido):
    """Bytes guardados -> texto. Lanza OSError si no se puede descifrar (por ejemplo, en otro computador)."""
    contenido = contenido.strip()
    if contenido.startswith(PREFIJO):
        if sys.platform != "win32":
            raise OSError("La clave está protegida por Windows y este no es ese computador.")
        return _dpapi(base64.b64decode(contenido[len(PREFIJO):]), False).decode("utf-8")
    return contenido.decode("utf-8")


def _guardar(ruta, contenido):
    temporal = ruta.with_name(ruta.name + ".nueva")
    temporal.write_bytes(contenido)
    if sys.platform != "win32":
        os.chmod(temporal, 0o600)
    os.replace(temporal, ruta)


def clave_secreta(carpeta, registro=None):
    """La clave de esta instalación (la crea la primera vez). Una clave antigua sin proteger se protege."""
    ruta = Path(carpeta) / ".clave_secreta"
    if ruta.exists():
        contenido = ruta.read_bytes()
        try:
            clave = leer(contenido)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            # Datos copiados de otro computador: la clave de allá no se puede leer aquí. Se crea otra (hay
            # que volver a iniciar sesión y a subir la firma electrónica, como avisa Configuración).
            if registro is not None:
                registro.warning("No se pudo leer la clave secreta (%s): se crea una nueva.", e)
            respaldo = ruta.with_name(".clave_secreta.ilegible")
            try:
                os.replace(ruta, respaldo)
            except OSError:
                pass
        else:
            if clave and sys.platform == "win32" and not contenido.strip().startswith(PREFIJO):
                try:
                    _guardar(ruta, proteger(clave))
                except OSError as e:
                    if registro is not None:
                        registro.warning("No se pudo proteger la clave secreta: %s", e)
            elif clave and sys.platform != "win32":
                try:
                    os.chmod(ruta, 0o600)
                except OSError:
                    pass
            if clave:
                return clave
    clave = secrets.token_hex(32)
    try:
        contenido = proteger(clave)
    except OSError as e:
        if registro is not None:
            registro.warning("No se pudo proteger la clave secreta con Windows: %s", e)
        contenido = clave.encode("utf-8")
    _guardar(ruta, contenido)
    return clave
