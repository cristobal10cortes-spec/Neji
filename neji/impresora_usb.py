"""Impresoras de tickets conectadas por USB, leídas directo del USB (sin controlador ni cola de Windows).

Windows carga su controlador genérico «Compatibilidad con impresoras USB» (usbprint.sys) para cualquier
impresora USB, aunque no se haya instalado su controlador. Esa interfaz (GUID_DEVINTERFACE_USBPRINT) se
puede abrir como un archivo y escribirle los bytes ESC/POS: así el ticket sale aunque la impresora no
aparezca en «Impresoras» o su controlador no acepte impresión directa.

El nombre se lee de la propia impresora (identificador IEEE 1284: «MFG:...;MDL:...;CMD:ESC/POS;»).
"""

import re
import sys
import threading
import uuid

GUID_USBPRINT = "{28D78FAD-5A12-11D1-AE5B-0000F803A8C2}"
IOCTL_USBPRINT_GET_1284_ID = 0x220034
SUFIJO = " (USB directo)"
# Lenguajes de impresoras de oficina: a esas no se les manda ESC/POS.
PATRON_OFICINA_1284 = re.compile(r"PCL|PJL|POSTSCRIPT|\bPDF\b|PWG|URF|\bXPS\b", re.IGNORECASE)


class ErrorUSB(Exception):
    """Problema con la impresora USB directa (con un mensaje para la caja)."""


class ErrorAbrirUSB(ErrorUSB):
    """El USB no se pudo abrir (p. ej. lo está usando Windows): se puede probar con la cola de impresión."""


def leer_1284(texto):
    """«MFG:POS;MDL:POS-80;CMD:ESC/POS;» -> {'MFG': 'POS', 'MDL': 'POS-80', 'CMD': 'ESC/POS'} (con sinónimos)."""
    campos = {}
    for parte in (texto or "").split(";"):
        if ":" in parte:
            clave, valor = parte.split(":", 1)
            campos[clave.strip().upper()] = valor.strip()
    sinonimos = {"MANUFACTURER": "MFG", "MODEL": "MDL", "COMMAND SET": "CMD", "DESCRIPTION": "DES"}
    for largo, corto in sinonimos.items():
        if largo in campos and corto not in campos:
            campos[corto] = campos[largo]
    return campos


def nombre_impresora(id_1284, ruta):
    """Nombre para mostrar: fabricante y modelo de la impresora, o su VID/PID del USB."""
    campos = leer_1284(id_1284)
    fabricante, modelo = campos.get("MFG", ""), campos.get("MDL", "") or campos.get("DES", "")
    if modelo and fabricante and not modelo.upper().startswith(fabricante.upper()):
        nombre = f"{fabricante} {modelo}"
    else:
        nombre = modelo or fabricante
    if not nombre:
        m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", ruta or "", re.IGNORECASE)
        nombre = f"Impresora USB {m.group(1).upper()}:{m.group(2).upper()}" if m else "Impresora USB"
    return " ".join(nombre.split())[:60]


def es_de_oficina(id_1284):
    return bool(PATRON_OFICINA_1284.search(leer_1284(id_1284).get("CMD", "")))


# --- Windows -----------------------------------------------------------------------------------------

def _api():
    if sys.platform != "win32":
        raise ErrorUSB("La impresión directa por USB funciona en Windows, con NejiPOS.exe.")
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD),
                    ("Reserved", ctypes.c_size_t)]

    s = ctypes.WinDLL("setupapi", use_last_error=True)
    s.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    s.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    s.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
                                              ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    s.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    s.SetupDiGetDeviceInterfaceDetailW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                   ctypes.c_void_p]
    s.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    s.SetupDiOpenDeviceInterfaceRegKey.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                   wintypes.DWORD, wintypes.DWORD]
    s.SetupDiOpenDeviceInterfaceRegKey.restype = wintypes.HANDLE
    s.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                            ctypes.c_void_p]
    k.WriteFile.restype = wintypes.BOOL
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.DeviceIoControl.restype = wintypes.BOOL
    k.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]

    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.RegQueryValueExW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                   ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    a.RegQueryValueExW.restype = wintypes.LONG
    a.RegCloseKey.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, s, k, a, GUID, SP_DEVICE_INTERFACE_DATA


INVALIDO = -1


def _es_invalido(ctypes, handle):
    return handle is None or handle == 0 or ctypes.c_ssize_t(handle).value == INVALIDO


def _puerto(ctypes, wintypes, s, a, conjunto, interfaz):
    """Nombre del puerto que Windows le dio a esa impresora USB (USB001...), o ''."""
    clave = s.SetupDiOpenDeviceInterfaceRegKey(conjunto, ctypes.byref(interfaz), 0, 0x20019)  # KEY_READ
    if _es_invalido(ctypes, clave):
        return ""
    try:
        numero, tamano, tipo = wintypes.DWORD(0), wintypes.DWORD(4), wintypes.DWORD(0)
        if a.RegQueryValueExW(clave, "Port Number", None, ctypes.byref(tipo), ctypes.byref(numero), ctypes.byref(tamano)):
            return ""
        base = ctypes.create_unicode_buffer(64)
        tamano = wintypes.DWORD(ctypes.sizeof(base))
        if a.RegQueryValueExW(clave, "Base Name", None, ctypes.byref(tipo), base, ctypes.byref(tamano)):
            base.value = "USB"
        return f"{base.value or 'USB'}{numero.value:03d}"
    finally:
        a.RegCloseKey(clave)


def _abrir(ctypes, k, ruta):
    # GENERIC_READ | GENERIC_WRITE, compartida para lectura y escritura, OPEN_EXISTING
    manejador = k.CreateFileW(ruta, 0x80000000 | 0x40000000, 0x1 | 0x2, None, 3, 0x80, None)
    if _es_invalido(ctypes, manejador):
        codigo = ctypes.get_last_error()
        raise ErrorAbrirUSB(f"No se pudo abrir la impresora USB (código {codigo}). Revisa que esté encendida y conectada.")
    return manejador


def _leer_1284_de(ctypes, wintypes, k, ruta):
    try:
        manejador = _abrir(ctypes, k, ruta)
    except ErrorUSB:
        return ""
    try:
        buf = ctypes.create_string_buffer(1024)
        leidos = wintypes.DWORD(0)
        if not k.DeviceIoControl(manejador, IOCTL_USBPRINT_GET_1284_ID, None, 0, buf, len(buf), ctypes.byref(leidos), None):
            return ""
        crudo = buf.raw[:leidos.value]
        largo = int.from_bytes(crudo[:2], "big") if len(crudo) >= 2 else 0
        return crudo[2:max(largo, 2)].decode("latin-1", "replace").strip("\x00 ")
    finally:
        k.CloseHandle(manejador)


def _dispositivos(guid_texto, leer):
    """Recorre los dispositivos presentes con esa interfaz: [leer(api, conjunto, interfaz, ruta), ...]."""
    api = _api()
    ctypes, wintypes, s, k, a, GUID, SP_DEVICE_INTERFACE_DATA = api
    guid = GUID.from_buffer_copy(uuid.UUID(guid_texto).bytes_le)
    conjunto = s.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x2 | 0x10)  # DIGCF_PRESENT | DEVICEINTERFACE
    if _es_invalido(ctypes, conjunto):
        return []
    resultado = []
    try:
        indice = 0
        while True:
            interfaz = SP_DEVICE_INTERFACE_DATA()
            interfaz.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not s.SetupDiEnumDeviceInterfaces(conjunto, None, ctypes.byref(guid), indice, ctypes.byref(interfaz)):
                break   # ERROR_NO_MORE_ITEMS
            indice += 1
            necesario = wintypes.DWORD(0)
            s.SetupDiGetDeviceInterfaceDetailW(conjunto, ctypes.byref(interfaz), None, 0, ctypes.byref(necesario), None)
            if not necesario.value:
                continue
            detalle = ctypes.create_string_buffer(necesario.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 en 64 bits, 6 en 32 bits
            ctypes.c_uint32.from_buffer(detalle).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not s.SetupDiGetDeviceInterfaceDetailW(conjunto, ctypes.byref(interfaz), detalle, necesario, None, None):
                continue
            ruta = ctypes.wstring_at(ctypes.addressof(detalle) + 4)
            resultado.append(leer(api, conjunto, interfaz, ruta))
    finally:
        s.SetupDiDestroyDeviceInfoList(conjunto)
    return resultado


def rutas(guid_texto):
    """[{ruta, puerto}] de los dispositivos con esa interfaz. Lo usa la prueba del programa compilado con los
    discos del equipo, para comprobar en Windows este recorrido sin tener una impresora USB."""
    def leer(api, conjunto, interfaz, ruta):
        ctypes, wintypes, s, _, a, _, _ = api
        return {"ruta": ruta, "puerto": _puerto(ctypes, wintypes, s, a, conjunto, interfaz)}
    return _dispositivos(guid_texto, leer)


def listar():
    """Impresoras USB de este computador: [{nombre, ruta, puerto, id_1284, oficina}] (vacío si no hay)."""
    def leer(api, conjunto, interfaz, ruta):
        ctypes, wintypes, s, k, a, _, _ = api
        id_1284 = _leer_1284_de(ctypes, wintypes, k, ruta)
        return {
            "nombre": nombre_impresora(id_1284, ruta), "ruta": ruta, "id_1284": id_1284,
            "puerto": _puerto(ctypes, wintypes, s, a, conjunto, interfaz), "oficina": es_de_oficina(id_1284),
        }
    impresoras = _dispositivos(GUID_USBPRINT, leer)
    # Dos impresoras iguales: «POS-80», «POS-80 (2)»
    vistos = {}
    for imp in impresoras:
        vistos[imp["nombre"]] = vistos.get(imp["nombre"], 0) + 1
        if vistos[imp["nombre"]] > 1:
            imp["nombre"] = f"{imp['nombre']} ({vistos[imp['nombre']]})"
    return impresoras


def escribir(ruta, datos, espera=15):
    """Manda los bytes a la impresora USB. Si no responde en `espera` segundos (sin papel, tapa abierta,
    apagada) se cancela y avisa, en vez de dejar la caja esperando."""
    ctypes, wintypes, _, k, _, _, _ = _api()
    manejador = _abrir(ctypes, k, ruta)
    resultado = {}

    def mandar():
        escritos = wintypes.DWORD(0)
        datos_b = bytes(datos)
        ok = k.WriteFile(manejador, datos_b, len(datos_b), ctypes.byref(escritos), None)
        resultado["ok"], resultado["escritos"], resultado["error"] = bool(ok), escritos.value, ctypes.get_last_error()

    try:
        hilo = threading.Thread(target=mandar, name="impresora-usb", daemon=True)
        hilo.start()
        hilo.join(espera)
        if hilo.is_alive():
            k.CancelIoEx(manejador, None)
            hilo.join(2)
            raise ErrorUSB("La impresora USB no responde. Revisa que tenga papel, la tapa cerrada y que esté encendida.")
        if not resultado.get("ok") or resultado.get("escritos") != len(bytes(datos)):
            raise ErrorUSB(f"No se pudo enviar el ticket a la impresora USB (código {resultado.get('error')}).")
    finally:
        k.CloseHandle(manejador)
