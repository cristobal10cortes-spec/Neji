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


def responde_neji(base, segundos=2.0):
    """True si en esa dirección ya hay un Neji POS funcionando."""
    try:
        with urllib.request.urlopen(f"{base}/api/estado", timeout=segundos) as r:
            return "configurado" in json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
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

def webview2_disponible():
    """En Windows, True si la ventana usará WebView2 (Edge). Sin él pywebview caería a Internet
    Explorer, que no ejecuta la interfaz de Neji."""
    if sys.platform != "win32":
        return True
    try:
        from webview.platforms import winforms
        return winforms.renderer == "edgechromium"
    except Exception:  # noqa: BLE001 - p. ej. falta .NET Framework 4.6.2
        registro.exception("No se pudo iniciar el motor de la ventana")
        return False


def sin_webview2(url):
    import webbrowser
    registro.warning("Sin WebView2: se abre el navegador")
    if mensaje("Este computador no tiene «Microsoft Edge WebView2», que Neji POS necesita para "
               "abrirse en su propia ventana.\n\n¿Abrir la página para instalarlo? (es gratis y "
               "tarda un minuto)\n\nMientras tanto Neji POS se abrirá en el navegador.", pregunta=True):
        webbrowser.open(WEBVIEW2_URL)
    webbrowser.open(url)


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


def crear_ventana(webview, url, confirmar_cierre=True):
    return webview.create_window(
        TITULO, url, width=1366, height=800, min_size=(1024, 640), maximized=True,
        confirm_close=confirmar_cierre, text_select=True, zoomable=True, background_color="#F3F5F7")


def abrir_ventana(url, red=False):
    """Abre la ventana y espera a que la cierren. Devuelve False si no hay WebView2."""
    if not webview2_disponible():
        return False
    webview = configurar_webview()
    crear_ventana(webview, url)
    carpeta_webview().mkdir(parents=True, exist_ok=True)
    # private_mode=False: si no, se borran al cerrar la caja elegida y los tickets en espera.
    # storage_path propio y fuera de datos/ (con modo privado pywebview borraría esa carpeta).
    webview.start(private_mode=False, storage_path=str(carpeta_webview()), localization=textos(red))
    return True


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

        if sys.platform == "win32":
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

    return informar(salida, {"ok": ok, "congelado": congelado(),
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
    resultado = {"ok": False, "webview2": webview2_disponible()}
    if not resultado["webview2"]:
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


def informar(salida, resultado):
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if salida:
        Path(salida).write_text(texto, encoding="utf-8")
    if sys.stdout:  # sin consola sys.stdout es None
        print(texto)
    return 0 if resultado.get("ok") else 1


# --- Inicio -----------------------------------------------------------------------------------------

def conectar(destino):
    """Caja secundaria: abre la ventana apuntando al equipo principal."""
    base = "http://" + destino.removeprefix("http://").rstrip("/")
    if ":" not in base.removeprefix("http://"):
        base += f":{PUERTO}"
    if not esperar(base, segundos=8):
        mensaje(f"No se pudo conectar con Neji POS en {base}.\n\nRevisa que el equipo principal esté "
                "encendido, con Neji POS abierto y con «Permitir otras cajas» activado en "
                "Configuración → Cajas.", error=True)
        return 1
    if not abrir_ventana(base + "/"):
        sin_webview2(base + "/")
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
    args = parser.parse_args(argv)

    if args.prueba:
        return prueba_de_humo(args.salida)
    if args.prueba_ventana:
        return prueba_ventana(args.prueba_ventana, args.salida)

    datos = carpeta_datos()
    datos.mkdir(parents=True, exist_ok=True)
    os.environ["NEJI_DATOS"] = str(datos)
    configurar_registro(datos)
    registro.info("Iniciando %s (datos en %s)", TITULO, datos)

    if args.impresion_directa:
        imprimir_directo()
    if args.conectar:
        return conectar(args.conectar)

    base = f"http://{HOST_VENTANA}:{args.puerto}"
    if responde_neji(base):
        mensaje("Neji POS ya está abierto en este computador.\n\nBúscalo en la barra de tareas.")
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
    try:
        if not esperar(base):
            mensaje(f"El servidor de Neji POS no respondió. Revisa {datos / 'neji.log'}.", error=True)
            return 1
        if not abrir_ventana(base + "/", red):
            sin_webview2(base + "/")
            # En el navegador el programa sigue funcionando hasta que se responda este mensaje.
            mensaje("Neji POS está funcionando en el navegador.\n\nPresiona Aceptar solo cuando "
                    "termines de usarlo: al hacerlo, Neji POS se cerrará.")
    finally:
        detener_servidor(servidor)
        registro.info("Neji POS cerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
