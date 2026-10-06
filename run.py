"""Inicia Neji POS.

    python run.py            solo este computador (http://localhost:5000)
    python run.py --red      también otras cajas de la red local (multicaja)
"""

import argparse
import threading
import webbrowser

from neji import create_app, equipo


def main():
    parser = argparse.ArgumentParser(description="Neji POS")
    parser.add_argument("--puerto", type=int, default=5000)
    parser.add_argument("--red", action="store_true",
                        help="aceptar conexiones de otras cajas en la red local")
    parser.add_argument("--sin-navegador", action="store_true",
                        help="no abrir el navegador automáticamente")
    args = parser.parse_args()

    app = create_app()
    # También se activa desde Configuración → Cajas («Permitir otras cajas»).
    red = args.red or equipo.modo_red_configurado(app.config["DATABASE"])
    host = "0.0.0.0" if red else "127.0.0.1"
    equipo.anunciar(red, args.puerto)
    url = f"http://localhost:{args.puerto}"
    print(f"\n  Neji POS funcionando en {url}")
    if red:
        print(f"  Otras cajas de la red pueden entrar a http://{equipo.ip_local()}:{args.puerto}")
    print("  Para detenerlo cierra esta ventana o presiona Ctrl+C.\n")

    if not args.sin_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=args.puerto)
    else:
        serve(app, host=host, port=args.puerto, threads=8)


if __name__ == "__main__":
    main()
