"""Importa a Neji POS los datos de CORAND.ERP / Easy Pharma.

    python importar_corand.py ruta/a/corand_erp_pro.db
    python importar_corand.py ruta/a/corand_erp_pro.db --sin-existencias

Cierra CORAND.ERP antes de importar. El archivo original no se modifica y Neji
hace un respaldo de su propia base antes de empezar. También se puede hacer desde
Configuración → Importar en la pantalla de Neji.
"""

import argparse
import sys

from neji import create_app, respaldos
from neji.db import get_db, leer_config
from neji.servicios import importar_corand
from neji.validar import ErrorNegocio


def main():
    parser = argparse.ArgumentParser(description="Importar datos de CORAND.ERP a Neji POS")
    parser.add_argument("archivo", help="ruta a corand_erp_pro.db")
    parser.add_argument("--sin-existencias", action="store_true",
                        help="no cambiar las existencias de productos que ya están en Neji")
    for opcion in ("productos", "vademecum", "recetario", "negocio"):
        parser.add_argument(f"--sin-{opcion}", action="store_true", help=f"no importar {opcion}")
    args = parser.parse_args()

    app = create_app({"RESPALDO_AUTOMATICO": False})
    with app.app_context():
        con = get_db()
        admin = con.execute("SELECT id FROM usuarios WHERE rol = 'admin' AND activo = 1 "
                            "ORDER BY id LIMIT 1").fetchone()
        if admin is None:
            sys.exit("Primero abre Neji POS y crea el usuario administrador.")
        nombre = respaldos.crear_respaldo(app.config["DATABASE"], app.config["RESPALDOS"],
                                          int(leer_config(con).get("respaldos_mantener") or 10))
        print(f"Respaldo creado: {nombre}")
        opciones = {"existencias": not args.sin_existencias}
        opciones.update({k: not getattr(args, f"sin_{k}") for k in ("productos", "vademecum", "recetario", "negocio")})
        try:
            r = importar_corand.importar(con, args.archivo, admin["id"], opciones)
        except ErrorNegocio as e:
            sys.exit(f"No se pudo importar: {e.mensaje}")

    print(f"Productos nuevos: {r['productos_creados']}  actualizados: {r['productos_actualizados']}  "
          f"con principio activo: {r['productos_con_principio']}")
    print(f"Fichas de vademécum: {r['fichas_vademecum']}  precios de recetario: {r['precios_recetario']}  "
          f"formas magistrales: {r['formas']}  datos del negocio: {r['datos_negocio']}")
    for aviso in r["advertencias"]:
        print(f"  ! {aviso}")


if __name__ == "__main__":
    main()
