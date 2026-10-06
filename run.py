"""Inicia Neji POS.

    python run.py            solo este computador (http://localhost:5000)
    python run.py --red      también otras cajas de la red local (multicaja)
"""

import argparse
import socket
import threading
import webbrowser

from neji import create_app


def ip_local():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Neji POS")
    parser.add_argument("--puerto", type=int, default=5000)
    parser.add_argument("--red", action="store_true",
                        help="aceptar conexiones de otras cajas en la red local")
    parser.add_argument("--sin-navegador", action="store_true",
                        help="no abrir el navegador automáticamente")
    args = parser.parse_args()

    host = "0.0.0.0" if args.red else "127.0.0.1"
    app = create_app()
    url = f"http://localhost:{args.puerto}"
    print(f"\n  Neji POS funcionando en {url}")
    if args.red:
        print(f"  Otras cajas de la red pueden entrar a http://{ip_local()}:{args.puerto}")
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
