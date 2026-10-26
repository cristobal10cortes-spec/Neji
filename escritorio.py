"""Neji POS como programa de escritorio: su propia ventana, con el servidor adentro.

    NejiPOS.exe                         abre Neji POS en su propia ventana
    NejiPOS.exe --red                   además acepta otras cajas de la red local
                                        (también se activa en Configuración → Cajas)
    NejiPOS.exe --conectar 192.168.1.5  caja secundaria: abre la ventana conectada al equipo
                                        principal, sin servidor propio
    NejiPOS.exe --impresion-directa     imprime sin mostrar el cuadro de impresión (también se
                                        activa en Configuración → Negocio y ticket)
    NejiPOS.exe --prueba                prueba sin ventana: servidor con una base temporal,
                                        pide /, /static/... y /api/..., y sale con 0 o 1
    NejiPOS.exe --listar-impresoras     muestra las impresoras que ve Neji POS en este computador
    NejiPOS.exe --prueba-impresora "POS-80"  imprime un ticket de prueba (con --modo windows: por el
                                        controlador de Windows en vez de ESC/POS)
    NejiPOS.exe --prueba-ventana        prueba con la ventana real (WebView2), para la compilación
    python escritorio.py                lo mismo sin compilar (necesita pywebview)

Los datos (neji.db, respaldos, registro) nunca van dentro del programa: quedan en
%LOCALAPPDATA%\\NejiPOS\\datos, o en una carpeta «datos» junto a NejiPOS.exe si ya existe una
(modo portátil). Así se puede actualizar el programa sin tocar los datos.
"""

import argparse
import json
import logging
import mimetypes
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from neji.version import VERSION, numeros

NOMBRE = "NejiPOS"
TITULO = "Neji POS"
# Puerto y dirección fijos: lo que la ventana guarda (caja de la terminal, tickets en espera)
# depende de host:puerto. Si cambiaran, esos datos "desaparecerían".
PUERTO = 5000
HOST_VENTANA = "127.0.0.1"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

registro = logging.getLogger("neji.escritorio")


# --- Dónde viven los datos ------------------------------------------------------------------------

def congelado():
    """True dentro de NejiPOS.exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def carpeta_local():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NOMBRE


def carpeta_datos():
    """Carpeta de neji.db, respaldos, .clave_secreta y neji.log.

    1. NEJI_DATOS, si está definida (igual que con run.py).
    2. Sin compilar: <proyecto>/datos, la misma que usa run.py.
    3. Compilado: una carpeta «datos» junto a NejiPOS.exe si ya tiene una base (modo portátil);
       si no, %LOCALAPPDATA%\\NejiPOS\\datos, que no cambia al actualizar ni al mover el programa.
    """
    if os.environ.get("NEJI_DATOS"):
        return Path(os.environ["NEJI_DATOS"])
    if not congelado():
        return Path(__file__).resolve().parent / "datos"
    portatil = Path(sys.executable).resolve().parent / "datos"
    if (portatil / "neji.db").exists():
        return portatil
    return carpeta_local() / "datos"


def carpeta_webview():
    """Cookies y almacenamiento de la ventana (no son datos del negocio: fuera de datos/)."""
    return carpeta_local() / "WebView2"


def configurar_registro(datos):
    formato = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if congelado() or not sys.stderr:
        # Sin consola: el registro va a un archivo junto a la base.
        from logging.handlers import RotatingFileHandler
        manejador = RotatingFileHandler(datos / "neji.log", maxBytes=1_000_000, backupCount=3,
                                        encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[manejador], format=formato, force=True)
    else:
        logging.basicConfig(level=logging.INFO, format=formato)

    def sin_atrapar(tipo, valor, tb):
        registro.critical("Error inesperado:\n%s", "".join(traceback.format_exception(tipo, valor, tb)))
        mensaje(f"Neji POS encontró un error y debe cerrarse.\n\n{valor}\n\n"
                f"El detalle quedó en {datos / 'neji.log'}", error=True)

    sys.excepthook = sin_atrapar
    threading.excepthook = lambda a: registro.error(
        "Error en el hilo %s:\n%s", a.thread.name if a.thread else "?",
        "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))


# --- Mensajes nativos -------------------------------------------------------------------------------

def mensaje(texto, error=False, pregunta=False):
    """Cuadro de mensaje de Windows (sin depender de la ventana). Con pregunta=True devuelve Sí/No."""
    if sys.platform == "win32":
        import ctypes
        estilo = (0x10 if error else 0x40) | (0x04 if pregunta else 0) | 0x10000  # MB_SETFOREGROUND
        return ctypes.windll.user32.MessageBoxW(None, texto, TITULO, estilo) == 6  # IDYES
    if sys.stderr:
        print(texto, file=sys.stderr)
    return False


# --- Servidor ---------------------------------------------------------------------------------------

def crear_app(config=None):
    # En Windows mimetypes lee el registro y a veces .js queda como text/plain, lo que impide
    # cargar <script type="module">. Se fijan los tipos correctos antes de crear la app.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    from neji import create_app
    return create_app(config)


def iniciar_servidor(app, host, puerto):
    from waitress import create_server
    servidor = create_server(app, host=host, port=puerto, threads=8)
    threading.Thread(target=servidor.run, name="servidor", daemon=True).start()
    return servidor


def detener_servidor(servidor):
    try:
        servidor.task_dispatcher.shutdown(timeout=5)  # deja terminar la venta en curso
    finally:
        servidor.close()


def estado_neji(base, segundos=2.0):
    """Lo que responde /api/estado del Neji POS que está en esa dirección, o None si no hay uno."""
    try:
        with urllib.request.urlopen(f"{base}/api/estado", timeout=segundos) as r:
            estado = json.loads(r.read().decode("utf-8"))
            return estado if isinstance(estado, dict) and "configurado" in estado else None
    except (OSError, ValueError):
        return None


def responde_neji(base, segundos=2.0):
    """True si en esa dirección ya hay un Neji POS funcionando."""
    return estado_neji(base, segundos) is not None


# --- Otra versión abierta ---------------------------------------------------------------------------
# Si al instalar una versión nueva la anterior sigue abierta (en la barra de tareas o de una carpeta
# portátil), la nueva no puede usar el puerto y se seguiría viendo la anterior: se ofrece cerrarla.

SIN_VENTANA_CONSOLA = 0x08000000   # CREATE_NO_WINDOW


def pid_en_puerto(salida_netstat, puerto):
    """PID del programa que escucha en ese puerto, según «netstat -ano -p TCP» (en cualquier idioma)."""
    for linea in salida_netstat.splitlines():
        partes = linea.split()
        if len(partes) >= 5 and partes[0].upper() == "TCP" and partes[1].rsplit(":", 1)[-1] == str(puerto) \
                and partes[2].rsplit(":", 1)[-1] == "0" and partes[-1].isdigit():
            return int(partes[-1])
    return None


def nombre_de_proceso(salida_tasklist):
    """Nombre del programa en la salida de «tasklist /FO CSV /NH» (primer campo), o ''."""
    primera = salida_tasklist.strip().splitlines()[0] if salida_tasklist.strip() else ""
    return primera.split('","')[0].strip('"') if primera.startswith('"') else ""


def _ejecutar(*comando):
    import subprocess
    try:
        r = subprocess.run(comando, capture_output=True, timeout=15, check=False,
                           creationflags=SIN_VENTANA_CONSOLA if sys.platform == "win32" else 0)
        return r.stdout.decode("mbcs" if sys.platform == "win32" else "utf-8", "replace")
    except (OSError, ValueError, subprocess.SubprocessError):   # p. ej. netstat que tarda demasiado
        return ""


def cerrar_neji_en_puerto(puerto):
    """Cierra el NejiPOS.exe que usa el puerto (solo si es Neji POS). True si lo cerró."""
    if sys.platform != "win32":
        return False
    pid = pid_en_puerto(_ejecutar("netstat", "-ano", "-p", "TCP"), puerto)
    if not pid or pid == os.getpid():
        return False
    nombre = nombre_de_proceso(_ejecutar("tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"))
    if nombre.lower() != "nejipos.exe":
        registro.warning("El puerto %s lo usa %r (PID %s): no se cierra", puerto, nombre, pid)
        return False
    registro.info("Cerrando la otra versión de Neji POS (PID %s)", pid)
    _ejecutar("taskkill", "/PID", str(pid), "/T", "/F")
    return True


def resolver_otra_instancia(base, puerto, esperar_segundos=15):
    """Ya hay un Neji POS en el puerto. Devuelve True si hay que seguir abriendo este (la otra versión
    se cerró) o False si hay que salir (es esta misma versión, o la otra no se pudo cerrar)."""
    otra = estado_neji(base) or {}
    version_otra = otra.get("version")
    if version_otra == VERSION:
        mensaje("Neji POS ya está abierto en este computador.\n\nBúscalo en la barra de tareas.")
        return False
    if numeros(version_otra) and numeros(VERSION) and numeros(version_otra) > numeros(VERSION):
        # La abierta es más nueva: este acceso directo abre una copia vieja. No se cierra la nueva.
        mensaje(f"Ya está abierta la versión {version_otra} de Neji POS, más nueva que esta ({VERSION}).\n\n"
                f"Este acceso directo abre una copia antigua, en:\n{Path(sys.executable).parent}\n\n"
                "Usa el acceso directo «Neji POS» del escritorio o del menú Inicio.")
        return False
    descripcion = f"la versión {version_otra}" if version_otra else "una versión anterior"
    if not mensaje(f"Hay otra ventana de Neji POS abierta en este computador, con {descripcion}.\n\n"
                   f"Para abrir la versión {VERSION} hay que cerrarla. Lo que está guardado no se pierde.\n\n"
                   "¿Cerrarla ahora y abrir la versión nueva?", pregunta=True):
        return False
    if cerrar_neji_en_puerto(puerto):
        limite = time.monotonic() + esperar_segundos
        while time.monotonic() < limite:
            if not responde_neji(base, 0.5) and puerto_libre(HOST_VENTANA, puerto):
                return True
            time.sleep(0.3)
    mensaje("No se pudo cerrar la otra ventana de Neji POS.\n\nCiérrala (o reinicia el computador) y vuelve "
            "a abrir Neji POS.", error=True)
    return False


def esperar(base, segundos=20):
    limite = time.monotonic() + segundos
    while not responde_neji(base):
        if time.monotonic() > limite:
            return False
        time.sleep(0.1)
    return True


def puerto_libre(host, puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, puerto))
            return True
        except OSError:
            return False


# --- Ventana ----------------------------------------------------------------------------------------

CLAVE_WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"  # Microsoft Edge WebView2 Runtime


def desbloquear_archivos(carpeta):
    """Quita la «marca de la web» (Zone.Identifier) a los archivos del programa.

    Windows se la pone a todo lo que se descomprime de un .zip descargado, y .NET Framework se
    niega a cargar esas DLL: la ventana no abre aunque WebView2 esté instalado.
    """
    if os.environ.get("NEJI_SIN_DESBLOQUEO"):  # solo para comprobar el problema en la compilación
        return 0
    quitados = 0
    for raiz, _, archivos in os.walk(carpeta):
        for nombre in archivos:
            try:
                os.remove(os.path.join(raiz, nombre) + ":Zone.Identifier")
                quitados += 1
            except OSError:
                pass
    return quitados


def version_webview2():
    """Versión de WebView2 registrada en Windows ("" si no aparece)."""
    import winreg
    for raiz, ruta in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients")):
        try:
            with winreg.OpenKey(raiz, rf"{ruta}\{CLAVE_WEBVIEW2}") as clave:
                version = str(winreg.QueryValueEx(clave, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return version
    return ""


def carpeta_webview2():
    """Carpeta de la versión más nueva de WebView2 instalada (con msedgewebview2.exe), o None."""
    candidatas = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidatas += [exe.parent for exe in
                           (Path(base) / "Microsoft" / "EdgeWebView" / "Application").glob("*/msedgewebview2.exe")]

    def numero_version(carpeta):
        return tuple(int(n) if n.isdigit() else 0 for n in carpeta.name.split("."))

    return max(candidatas, key=numero_version) if candidatas else None


def version_dotnet():
    """Número «Release» de .NET Framework 4.x (0 si no está). 4.6.2 = 394802."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as clave:
            return int(winreg.QueryValueEx(clave, "Release")[0])
    except (OSError, ValueError):
        return 0


def preparar_motor():
    """Deja lista la ventana WebView2 (Edge). Devuelve (estado, detalle, datos):

    - "ok": se puede abrir la ventana propia;
    - "falta": WebView2 no está instalado (se puede instalar);
    - "error": está, pero no se pudo cargar; el detalle dice por qué.

    Sin WebView2 pywebview caería a Internet Explorer, que no ejecuta la interfaz de Neji.
    """
    if sys.platform != "win32":
        return "ok", "", {}
    datos = {"programa": str(Path(sys.executable).resolve().parent)}
    if congelado():
        datos["archivos_desbloqueados"] = desbloquear_archivos(datos["programa"])
    datos["webview2_registro"] = version_webview2()
    carpeta = carpeta_webview2()
    datos["webview2_carpeta"] = str(carpeta or "")
    datos["dotnet"] = version_dotnet()
    if carpeta and not datos["webview2_registro"]:
        # Instalado pero no registrado donde lo busca pywebview: se le indica la carpeta.
        import webview
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(carpeta)
    registro.info("Motor de la ventana: %s", datos)

    if not datos["webview2_registro"] and not carpeta:
        return "falta", "Microsoft Edge WebView2 no está instalado.", datos
    if datos["dotnet"] < 394802:
        return "error", "Falta .NET Framework 4.6.2 o superior (viene con Windows 10 y 11).", datos
    try:
        import clr  # noqa: F401 - el puente con .NET; se prueba aparte para conocer el error real
    except Exception as e:  # noqa: BLE001
        registro.exception("No se pudo cargar .NET Framework")
        return "error", f"No se pudo cargar .NET: {type(e).__name__}: {e}", datos
    try:
        from webview.platforms import winforms
    except Exception as e:  # noqa: BLE001
        registro.exception("No se pudo cargar el motor de la ventana")
        return "error", f"{type(e).__name__}: {e}", datos
    datos["motor"] = winforms.renderer
    if winforms.renderer != "edgechromium":
        return "error", (f"No se pudo usar WebView2 {datos['webview2_registro'] or carpeta} "
                         f"(motor: {winforms.renderer})."), datos
    return "ok", "", datos


def firmado_por_microsoft(ruta):
    """¿El archivo trae una firma Authenticode válida de Microsoft? (antes de ejecutar algo descargado)."""
    import subprocess
    # Con la ruta completa (no el que aparezca primero en el PATH) y sin el PSModulePath de PowerShell 7, que
    # no le sirve a Windows PowerShell (no podría cargar su módulo de firmas).
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / \
        "powershell.exe"
    entorno = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    entorno["NEJI_ARCHIVO"] = str(ruta)
    comando = [str(powershell), "-NoProfile", "-NonInteractive", "-Command",
               "$f = Get-AuthenticodeSignature -LiteralPath $env:NEJI_ARCHIVO; "
               "Write-Output $f.Status; Write-Output $f.SignerCertificate.Subject"]
    try:
        r = subprocess.run(comando, capture_output=True, timeout=60, check=False, text=True, env=entorno,
                           creationflags=SIN_VENTANA_CONSOLA)
    except (OSError, subprocess.SubprocessError):
        registro.exception("No se pudo revisar la firma del instalador")
        return False
    lineas = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    ok = len(lineas) >= 2 and lineas[0] == "Valid" and "O=Microsoft Corporation" in lineas[1]
    if not ok:
        registro.warning("El instalador descargado no tiene una firma válida de Microsoft: %s %s", lineas,
                         (r.stderr or "").strip()[:500])
    return ok


def instalar_webview2():
    """Descarga y ejecuta el instalador oficial de Microsoft (si su firma es de Microsoft). True si terminó bien."""
    import subprocess
    carpeta = Path(tempfile.mkdtemp(prefix="neji-webview2-"))    # carpeta propia: nadie la cambia entremedio
    destino = carpeta / "MicrosoftEdgeWebview2Setup.exe"
    try:
        urllib.request.urlretrieve(WEBVIEW2_URL, destino)
        if not firmado_por_microsoft(destino):
            return False
        resultado = subprocess.run([str(destino), "/install"], timeout=1200, check=False)
    except (OSError, subprocess.SubprocessError):
        registro.exception("No se pudo instalar WebView2")
        return False
    registro.info("El instalador de WebView2 terminó con el código %s", resultado.returncode)
    return resultado.returncode == 0


def relanzar():
    """Vuelve a abrir Neji POS (después de instalar WebView2)."""
    import subprocess
    programa = [sys.executable] if congelado() else [sys.executable, str(Path(__file__).resolve())]
    subprocess.Popen(programa + sys.argv[1:], close_fds=True)


def sin_ventana(url, estado, detalle, datos):
    """La ventana propia no se pudo abrir: ofrece instalar WebView2 o abre el navegador.
    Devuelve True si hay que volver a abrir Neji POS (se acaba de instalar WebView2)."""
    import webbrowser
    registro.warning("Sin ventana propia (%s): %s", estado, detalle)
    if estado == "falta":
        if mensaje("Falta «Microsoft Edge WebView2», que Neji POS usa para abrirse en su propia "
                   "ventana.\n\n¿Instalarlo ahora? Es gratis, de Microsoft, y tarda un par de "
                   "minutos (necesita internet).", pregunta=True):
            if instalar_webview2():
                return True
            mensaje("No se pudo instalar WebView2. Neji POS se abrirá en el navegador.", error=True)
    else:
        mensaje("No se pudo abrir la ventana propia de Neji POS, así que se abrirá en el navegador."
                f"\n\nDetalle: {detalle}\n\nEl registro completo está en {datos / 'neji.log'}.",
                error=True)
    webbrowser.open(url)
    return False


def textos(red):
    return {
        "global.quitConfirmation": ("¿Cerrar Neji POS?\n\nLas otras cajas conectadas a este equipo "
                                    "dejarán de funcionar hasta que lo vuelvas a abrir.") if red
                                   else "¿Cerrar Neji POS?",
        "global.ok": "Aceptar",
        "global.quit": "Cerrar",
        "global.cancel": "Cancelar",
        "global.saveFile": "Guardar archivo",
        "windows.fileFilter.allFiles": "Todos los archivos",
        "windows.fileFilter.otherFiles": "Otros tipos de archivo",
    }


def imprimir_directo():
    """Imprime los tickets en la impresora predeterminada sin mostrar el cuadro de impresión,
    igual que Chrome con --kiosk-printing (WebView2 agrega estos argumentos a los suyos)."""
    actuales = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if "--kiosk-printing" not in actuales:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"{actuales} --kiosk-printing".strip()


def configurar_webview():
    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True    # Exportar CSV y bajar respaldos
    webview.settings["ALLOW_FILE_URLS"] = False   # la ventana solo muestra Neji
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    return webview


# --- Lectores de códigos por puerto COM USB ---------------------------------------------------------------

_lector = None
_candado_lector = threading.Lock()
ARCHIVO_LECTORES = "lectores.json"   # en la carpeta de datos: qué puertos COM usar como lector


def _archivo_lectores():
    return carpeta_datos() / ARCHIVO_LECTORES


def leer_lectores_elegidos():
    try:
        datos = json.loads(_archivo_lectores().read_text(encoding="utf-8"))
        return {str(k).upper(): bool(v) for k, v in datos.items()} if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_lector_elegido(puerto, usar):
    elegidos = leer_lectores_elegidos()
    elegidos[str(puerto).upper()] = bool(usar)
    _archivo_lectores().parent.mkdir(parents=True, exist_ok=True)
    _archivo_lectores().write_text(json.dumps(elegidos, ensure_ascii=False), encoding="utf-8")


def puertos_de_impresoras():
    """Puertos COM de las impresoras instaladas: no se abren como lector (la impresora dejaría de imprimir)."""
    from neji import impresoras
    try:
        return {p["puerto"].rstrip(":").upper() for p in impresoras._listar_windows() if p["puerto"].upper().startswith("COM")}
    except impresoras.ErrorImpresora:
        return set()


def lector_serie():
    """El que lee los lectores COM (se pone en marcha la primera vez que la ventana lo pide)."""
    global _lector
    with _candado_lector:
        if _lector is None:
            from neji.lector_serie import LectorSerie
            _lector = LectorSerie(excluir=puertos_de_impresoras, elegidos=leer_lectores_elegidos).iniciar()
        return _lector


class ApiEscritorio:
    """Lo que la interfaz le pide a este computador (window.pywebview.api): sus impresoras de tickets.

    Siempre se usan las impresoras del equipo donde está la ventana, aunque el servidor sea otro (--conectar).
    Devuelve {ok, ...} en vez de lanzar errores, para que la caja muestre un mensaje claro.
    """

    def impresoras(self):
        from neji import impresoras
        try:
            return {"ok": True, "impresoras": impresoras.listar()}
        except impresoras.ErrorImpresora as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            registro.exception("No se pudieron leer las impresoras")
            return {"ok": False, "error": f"No se pudieron leer las impresoras: {e}"}

    def imprimir(self, trabajo):
        from neji import impresoras
        try:
            aviso = impresoras.imprimir_trabajo(trabajo)
            if aviso:
                registro.warning("%s", aviso)
                return {"ok": True, "aviso": aviso}
            return {"ok": True}
        except impresoras.ErrorImpresora as e:
            registro.warning("No se pudo imprimir: %s", e)
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            registro.exception("Error al imprimir")
            return {"ok": False, "error": f"Error al imprimir: {e}"}

    def lecturas(self, segundos=20):
        """Códigos leídos por los lectores COM. Espera hasta `segundos` (la ventana vuelve a preguntar)."""
        try:
            espera = max(0.0, min(float(segundos or 0), 25.0))
            return {"ok": True, "codigos": lector_serie().esperar(espera)}
        except Exception as e:  # noqa: BLE001
            registro.exception("Error al leer los lectores")
            return {"ok": False, "codigos": [], "error": str(e)}

    def lectores(self):
        """Puertos COM USB de este computador y cuáles se están leyendo como lector de códigos."""
        try:
            lector = lector_serie()
            if lector.disponible:
                lector.revisar()
            return {"ok": True, "disponible": lector.disponible, "error": lector.error, "puertos": lector.estado()}
        except ImportError:
            return {"ok": True, "disponible": False, "error": "Falta el módulo pyserial.", "puertos": []}
        except Exception as e:  # noqa: BLE001
            registro.exception("Error al revisar los lectores")
            return {"ok": False, "error": str(e), "puertos": []}

    def lector_usar(self, puerto, usar):
        """Usar (o no) ese puerto COM como lector de códigos. Queda guardado en este computador."""
        try:
            guardar_lector_elegido(puerto, usar)
        except OSError as e:
            return {"ok": False, "error": f"No se pudo guardar: {e}", "puertos": []}
        return self.lectores()


def crear_ventana(webview, url, confirmar_cierre=True, titulo=None):
    return webview.create_window(
        titulo or f"{TITULO} {VERSION}", url, width=1366, height=800, min_size=(1024, 640), maximized=True,
        confirm_close=confirmar_cierre, text_select=True, zoomable=True, background_color="#F3F5F7",
        js_api=ApiEscritorio())


def abrir_ventana(url, red=False, titulo=None):
    """Abre la ventana y espera a que la cierren. Si no se puede, devuelve (estado, detalle)."""
    estado, detalle, _ = preparar_motor()
    if estado != "ok":
        return estado, detalle
    webview = configurar_webview()
    crear_ventana(webview, url, titulo=titulo)
    carpeta_webview().mkdir(parents=True, exist_ok=True)
    # private_mode=False: si no, se borran al cerrar la caja elegida y los tickets en espera.
    # storage_path propio y fuera de datos/ (con modo privado pywebview borraría esa carpeta).
    webview.start(private_mode=False, storage_path=str(carpeta_webview()), localization=textos(red))
    return None


# --- Pruebas para la compilación ------------------------------------------------------------------

def prueba_de_humo(salida=None):
    """Sin ventana. Devuelve 0 si todo responde, 1 si algo falla."""
    resultados, ok = [], True
    datos = Path(tempfile.mkdtemp(prefix="neji-prueba-"))  # nunca toca los datos reales
    servidor = app = None
    try:
        app = crear_app({"DATOS": str(datos), "DATABASE": str(datos / "neji.db"),
                         "RESPALDOS": str(datos / "respaldos"), "RESPALDO_AUTOMATICO": False})
        servidor = iniciar_servidor(app, "127.0.0.1", 0)  # cualquier puerto libre
        base = f"http://127.0.0.1:{servidor.effective_port}"
        navegador = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

        def pedir(ruta, esperado, tipo, contiene=None, cuerpo=None):
            nonlocal ok
            datos_json = json.dumps(cuerpo).encode() if cuerpo is not None else None
            req = urllib.request.Request(base + ruta, data=datos_json,
                                         headers={"Content-Type": "application/json"} if cuerpo else {})
            try:
                with navegador.open(req, timeout=10) as r:
                    estado, ctipo, texto = r.status, r.headers.get("Content-Type", ""), r.read()
            except urllib.error.HTTPError as e:
                estado, ctipo, texto = e.code, e.headers.get("Content-Type", ""), e.read()
            bien = estado == esperado and tipo in ctipo and (contiene is None or contiene in texto)
            ok &= bien
            resultados.append({"ruta": ruta, "estado": estado, "tipo": ctipo, "ok": bien})

        pedir("/", 200, "text/html", b'type="module"')
        pedir("/static/js/app.js", 200, "javascript")
        pedir("/static/js/vistas/recetario.js", 200, "javascript")
        pedir("/static/css/app.css", 200, "text/css")
        pedir("/api/estado", 200, "application/json", b'"configurado":false')
        pedir("/api/setup", 200, "application/json", cuerpo={
            "negocio_nombre": "Prueba", "usuario": "admin", "nombre": "Prueba", "password": "1234",
            "modulo_farmacia": True})
        pedir("/api/productos", 200, "application/json")      # con la sesión recién creada
        pedir("/api/recetario/formas", 200, "application/json", b"psula")
        pedir("/api/equipo", 200, "application/json", b"carpeta_datos")
        pedir("/api/sii", 200, "application/json", b'"falta_modulo":""')

        # Boleta electrónica: firma (cryptography), XML firmado y verificado (lxml) y timbre PDF417 empaquetados.
        try:
            from neji.sii.autoprueba import probar
            resultados.append({"sii": probar(), "ok": True})
        except Exception as e:  # noqa: BLE001
            ok = False
            resultados.append({"sii": f"{type(e).__name__}: {e}", "ok": False})

        if sys.platform == "win32":
            # Impresoras USB directas (SetupAPI) y lectores COM (pyserial) empaquetados y funcionando.
            try:
                import serial.tools.list_ports
                from neji import impresora_usb
                usb = impresora_usb.listar()
                puertos = list(serial.tools.list_ports.comports())
                # Sin impresoras USB en el equipo de prueba, el mismo recorrido se prueba con los discos.
                discos = impresora_usb.rutas("{53F56307-B6BF-11D0-94F2-00A0C91EFB8B}")   # GUID_DEVINTERFACE_DISK
                if not discos or not all(d["ruta"].startswith("\\\\?\\") for d in discos):
                    raise RuntimeError(f"recorrido de dispositivos USB mal leído: {discos!r}")
                resultados.append({"usb": f"{len(usb)} impresoras USB", "serie": f"{len(puertos)} puertos COM",
                                   "discos": [d["ruta"][:60] for d in discos], "ok": True})
            except Exception as e:  # noqa: BLE001
                ok = False
                resultados.append({"usb_serie": f"{type(e).__name__}: {e}", "ok": False})
            # Carga pythonnet y las DLL de WebView2 empaquetadas, sin abrir la ventana.
            try:
                import webview.platforms.edgechromium  # noqa: F401
                resultados.append({"webview": "edgechromium cargado", "ok": True})
            except Exception as e:  # noqa: BLE001
                ok = False
                resultados.append({"webview": f"{type(e).__name__}: {e}", "ok": False})
    except Exception as e:  # noqa: BLE001
        ok = False
        resultados.append({"error": f"{type(e).__name__}: {e}", "ok": False})
    finally:
        if servidor is not None:
            detener_servidor(servidor)
        shutil.rmtree(datos, ignore_errors=True)

    return informar(salida, {"ok": ok, "version": VERSION, "congelado": congelado(),
                             "static_folder": app.static_folder if app else None,
                             "resultados": resultados})


VERIFICAR_VENTANA = """
(() => {
  const listo = Boolean(document.querySelector('#app form, #app nav'));
  const anterior = localStorage.getItem('neji.prueba');
  localStorage.setItem('neji.prueba', 'guardado');
  return JSON.stringify({ listo, anterior, titulo: document.title, modulos: Boolean(window.fetch) });
})()
"""


def prueba_ventana(carpeta, salida=None):
    """Abre la ventana real con una base temporal, revisa que la interfaz cargue y que el
    almacenamiento se conserve entre aperturas (correrla dos veces con la misma carpeta)."""
    carpeta = Path(carpeta)
    datos = carpeta / "datos"
    datos.mkdir(parents=True, exist_ok=True)
    os.environ["NEJI_DATOS"] = str(datos)
    estado, detalle, motor = preparar_motor()
    resultado = {"ok": False, "motor": estado, "detalle": detalle, **motor}
    if estado != "ok":
        return informar(salida, resultado)
    servidor = iniciar_servidor(crear_app(), HOST_VENTANA, PUERTO)
    base = f"http://{HOST_VENTANA}:{PUERTO}"
    try:
        if not esperar(base):
            resultado["error"] = "el servidor no respondió"
            return informar(salida, resultado)
        webview = configurar_webview()
        ventana = crear_ventana(webview, base + "/", confirmar_cierre=False)

        def revisar():
            try:
                if not ventana.events.loaded.wait(60):
                    resultado["error"] = "la ventana no terminó de cargar"
                    return
                limite = time.monotonic() + 30
                while True:
                    datos_js = json.loads(ventana.evaluate_js(VERIFICAR_VENTANA))
                    if datos_js["listo"] or time.monotonic() > limite:
                        break
                    time.sleep(0.5)
                resultado.update(datos_js)
                resultado["ok"] = datos_js["listo"]
            except Exception as e:  # noqa: BLE001
                resultado["error"] = f"{type(e).__name__}: {e}"
            finally:
                ventana.destroy()

        webview.start(revisar, private_mode=False, storage_path=str(carpeta / "WebView2"),
                      localization=textos(False))
    finally:
        detener_servidor(servidor)
    return informar(salida, resultado)


# Ticket de prueba (el mismo formato que arma la interfaz con impresion.js → bloquesTicket).
TICKET_PRUEBA = [
    {"tipo": "texto", "texto": "Neji POS", "alinear": "centro", "negrita": True, "grande": True},
    {"tipo": "texto", "texto": "Prueba de impresión", "alinear": "centro"},
    {"tipo": "linea"},
    {"tipo": "texto", "texto": "Tildes y eñes: áéíóú ÁÉÍÓÚ ñ Ñ ü ¿? ¡! °"},
    {"tipo": "par", "izq": "Izquierda", "der": "Derecha"},
    {"tipo": "par", "izq": "TOTAL", "der": "$12.345", "negrita": True, "grande": True},
    {"tipo": "linea"},
    {"tipo": "texto", "texto": "Si ves esto bien, la impresora está lista.", "alinear": "centro"},
]


def listar_impresoras(salida=None):
    resultado = ApiEscritorio().impresoras()

    def resumen(r):
        if not r.get("ok"):
            return r.get("error", "No se pudieron leer las impresoras.")
        if not r["impresoras"]:
            return "No hay impresoras instaladas en este computador."
        return "Impresoras de este computador:\n\n" + "\n".join(
            f"• {i['nombre']} ({i['conexion']}){' · de tickets' if i['termica'] else ''}"
            f"{' · predeterminada' if i['predeterminada'] else ''}{' · sin conexión' if i['sin_conexion'] else ''}"
            f"{' · directo por USB' if i.get('usb_directo') else ''}"
            for i in r["impresoras"])
    return informar(salida, resultado, resumen)


def probar_impresora(nombre, modo="escpos", salida=None):
    resultado = ApiEscritorio().imprimir({"impresora": nombre, "modo": modo, "papel": "80", "bloques": TICKET_PRUEBA})

    def resumen(r):
        if not r.get("ok"):
            return r.get("error", "No se pudo imprimir.")
        return f"Se mandó el ticket de prueba a «{nombre}».{chr(10) * 2 + r['aviso'] if r.get('aviso') else ''}"
    return informar(salida, {**resultado, "impresora": nombre, "modo": modo}, resumen)


def informar(salida, resultado, resumen=None):
    """Deja el resultado en --salida (JSON) y lo muestra: en la consola o, en NejiPOS.exe, en un cuadro."""
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if salida:
        Path(salida).write_text(texto, encoding="utf-8")
    if sys.stdout:  # sin consola sys.stdout es None
        print(texto)
    elif resumen and not salida:   # NejiPOS.exe no tiene consola: se ve en un cuadro de mensaje
        mensaje(resumen(resultado), error=not resultado.get("ok"))
    return 0 if resultado.get("ok") else 1


# --- Inicio -----------------------------------------------------------------------------------------

def conectar(destino, datos):
    """Caja secundaria: abre la ventana apuntando al equipo principal."""
    base = "http://" + destino.removeprefix("http://").rstrip("/")
    if ":" not in base.removeprefix("http://"):
        base += f":{PUERTO}"
    if not esperar(base, segundos=8):
        mensaje(f"No se pudo conectar con Neji POS en {base}.\n\nRevisa que el equipo principal esté "
                "encendido, con Neji POS abierto y con «Permitir otras cajas» activado en "
                "Configuración → Cajas.", error=True)
        return 1
    # La interfaz (pantallas, tickets) la da el equipo principal: su versión es la que se ve.
    version_principal = (estado_neji(base) or {}).get("version")
    equipo = base.removeprefix("http://")
    mas_antigua = not version_principal or (numeros(version_principal) and numeros(VERSION)
                                            and numeros(version_principal) < numeros(VERSION))
    if mas_antigua:
        # Se actualizó esta caja y no el principal: los cambios no se verían y nadie sabría por qué.
        mensaje(f"Esta caja tiene Neji POS {VERSION}, pero las pantallas las da el equipo principal "
                f"({equipo}), que tiene {f'la versión {version_principal}' if version_principal else 'una versión anterior'}."
                "\n\nPara ver los cambios de la versión nueva, instálala también en el equipo principal.")
    titulo = f"{TITULO} {version_principal or ''} (conectado a {equipo})".replace("  ", " ")
    fallo = abrir_ventana(base + "/", titulo=titulo)
    if fallo and sin_ventana(base + "/", *fallo, datos):
        relanzar()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog=NOMBRE, description=TITULO)
    parser.add_argument("--puerto", type=int, default=PUERTO)
    parser.add_argument("--red", action="store_true", help="aceptar otras cajas de la red local")
    parser.add_argument("--conectar", metavar="EQUIPO",
                        help="caja secundaria: conectarse al Neji POS de otro equipo (IP o IP:puerto)")
    parser.add_argument("--impresion-directa", action="store_true",
                        help="imprimir sin mostrar el cuadro de impresión")
    parser.add_argument("--prueba", action="store_true", help="prueba sin ventana")
    parser.add_argument("--prueba-ventana", metavar="CARPETA", help="prueba con la ventana real")
    parser.add_argument("--salida", help="con --prueba: escribir el informe JSON en este archivo")
    parser.add_argument("--listar-impresoras", action="store_true", help="mostrar las impresoras de este computador")
    parser.add_argument("--prueba-impresora", metavar="IMPRESORA", help="imprimir un ticket de prueba")
    parser.add_argument("--modo", choices=["escpos", "windows"], default="escpos",
                        help="con --prueba-impresora: ESC/POS directo o controlador de Windows")
    args = parser.parse_args(argv)

    if args.prueba:
        return prueba_de_humo(args.salida)
    if args.listar_impresoras:
        return listar_impresoras(args.salida)
    if args.prueba_impresora:
        return probar_impresora(args.prueba_impresora, args.modo, args.salida)
    if args.prueba_ventana:
        return prueba_ventana(args.prueba_ventana, args.salida)

    datos = carpeta_datos()
    datos.mkdir(parents=True, exist_ok=True)
    os.environ["NEJI_DATOS"] = str(datos)
    configurar_registro(datos)
    registro.info("Iniciando %s %s (datos en %s)", TITULO, VERSION, datos)

    if args.impresion_directa:
        imprimir_directo()
    if args.conectar:
        return conectar(args.conectar, datos)

    base = f"http://{HOST_VENTANA}:{args.puerto}"
    if responde_neji(base) and not resolver_otra_instancia(base, args.puerto):
        return 0
    app = crear_app()
    from neji import equipo
    red = args.red or equipo.modo_red_configurado(app.config["DATABASE"])
    if equipo.opcion_activada(app.config["DATABASE"], "impresion_directa"):
        imprimir_directo()
    host = "0.0.0.0" if red else HOST_VENTANA
    if not puerto_libre(host, args.puerto):
        mensaje(f"No se pudo iniciar Neji POS: otro programa está usando el puerto {args.puerto}.",
                error=True)
        return 1
    equipo.anunciar(red, args.puerto, escritorio=True)
    servidor = iniciar_servidor(app, host, args.puerto)
    volver_a_abrir = False
    try:
        if not esperar(base):
            mensaje(f"El servidor de Neji POS no respondió. Revisa {datos / 'neji.log'}.", error=True)
            return 1
        fallo = abrir_ventana(base + "/", red)
        if fallo:
            volver_a_abrir = sin_ventana(base + "/", *fallo, datos)
            if not volver_a_abrir:
                # En el navegador el programa sigue funcionando hasta que se responda este mensaje.
                mensaje("Neji POS está funcionando en el navegador.\n\nPresiona Aceptar solo cuando "
                        "termines de usarlo: al hacerlo, Neji POS se cerrará.")
    finally:
        detener_servidor(servidor)
        registro.info("Neji POS cerrado")
    if volver_a_abrir:
        relanzar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
