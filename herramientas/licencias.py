"""Generador de licencias de Neji POS (solo para quien vende Neji POS).

Se usa en TU computador, nunca en el de un cliente:

    python herramientas/licencias.py              menú
    python herramientas/licencias.py llave        crea tu llave (la primera vez)
    python herramientas/licencias.py crear        crea una licencia (pregunta los datos)
    python herramientas/licencias.py ver NEJI-…   muestra qué dice una licencia
    python herramientas/licencias.py publica      muestra tu llave pública

En Windows basta con abrir «Generar licencias.bat».

La llave privada queda en la carpeta NejiLicencias de tu usuario (o en NEJI_LICENCIAS_CARPETA), protegida con
una contraseña. Con ella se firman las licencias: respáldala (por ejemplo, en un pendrive) y no la compartas.
Si se pierde, las licencias ya entregadas siguen valiendo, pero no puedes hacer otras hasta poner una llave
nueva en Neji. La llave pública es la que va dentro de Neji (neji/licencia.py, LLAVES_PUBLICAS).

Cada licencia queda guardada en licencias/ y anotada en registro.csv (tu lista de ventas).
"""

import argparse
import base64
import csv
import getpass
import os
import re
import sys
import types
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# De Neji solo se usan licencia.py, chile.py y validar.py, que no necesitan nada más: se cargan sin pasar por
# neji/__init__.py (el servidor, con Flask), así basta con instalar cryptography.
if "neji" not in sys.modules:
    paquete = types.ModuleType("neji")
    paquete.__path__ = [str(RAIZ / "neji")]
    sys.modules["neji"] = paquete

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    sys.exit("Falta el módulo cryptography: instálalo con «pip install cryptography» y vuelve a intentarlo.")

from neji import licencia  # noqa: E402
from neji.chile import formatear_rut, validar_rut  # noqa: E402
from neji.validar import ErrorNegocio  # noqa: E402

ARCHIVO_LLAVE = "llave_privada.pem"
ARCHIVO_PUBLICA = "llave_publica.txt"
REGISTRO = "registro.csv"
COLUMNAS = ["numero", "emitida", "cliente", "rut", "tipo", "cajas", "equipo", "nota", "archivo"]
FORMATO_EQUIPO = re.compile(r"^[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}$")


class Error(Exception):
    pass


def carpeta():
    return Path(os.environ.get("NEJI_LICENCIAS_CARPETA") or Path.home() / "NejiLicencias")


def publica_de(llave):
    crudo = llave.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(crudo).decode()


def crear_llave(clave, donde=None):
    """Crea la llave privada (protegida con la contraseña) y devuelve la pública."""
    donde = Path(donde or carpeta())
    ruta = donde / ARCHIVO_LLAVE
    if ruta.exists():
        raise Error(f"Ya tienes una llave en {ruta}. No se crea otra: las licencias se firman siempre con la misma.")
    if len(clave) < 6:
        raise Error("La contraseña de la llave debe tener al menos 6 caracteres.")
    donde.mkdir(parents=True, exist_ok=True)
    llave = Ed25519PrivateKey.generate()
    ruta.write_bytes(llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.BestAvailableEncryption(clave.encode())))
    publica = publica_de(llave)
    (donde / ARCHIVO_PUBLICA).write_text(publica + "\n", encoding="utf-8")
    return publica


def cargar_llave(clave, donde=None):
    ruta = Path(donde or carpeta()) / ARCHIVO_LLAVE
    if not ruta.exists():
        raise Error(f"No hay llave en {ruta}: créala primero (opción «llave»).")
    try:
        return serialization.load_pem_private_key(ruta.read_bytes(), password=clave.encode())
    except (ValueError, TypeError):
        raise Error("La contraseña de la llave no es correcta.") from None


def _registro(donde):
    ruta = Path(donde) / REGISTRO
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _nombre_archivo(numero, cliente):
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", cliente).strip("_")[:40] or "cliente"
    return f"{numero}_{limpio}.txt"


def crear_licencia(llave, cliente, tipo, cajas=None, equipo=licencia.CUALQUIER_EQUIPO, rut="", nota="", donde=None):
    """Firma una licencia, la guarda en licencias/ y la anota en registro.csv. Devuelve (texto, datos)."""
    donde = Path(donde or carpeta())
    cliente = " ".join(str(cliente or "").split())
    if not cliente:
        raise Error("Falta el nombre del cliente.")
    if tipo not in licencia.TIPOS:
        raise Error("El tipo es «caja» o «local».")
    cajas = 1 if tipo == "caja" else int(cajas or 0)
    if cajas < 0:
        raise Error("El número de cajas no puede ser negativo.")
    equipo = licencia.normalizar_equipo(equipo or licencia.CUALQUIER_EQUIPO)
    if equipo != licencia.CUALQUIER_EQUIPO and not FORMATO_EQUIPO.match(equipo):
        raise Error("El código de equipo tiene la forma XXXX-XXXX-XXXX-XXXX (está en Configuración → Licencia del "
                    "cliente).")
    rut = str(rut or "").strip()
    if rut:
        if not validar_rut(rut):
            raise Error("El RUT no es válido.")
        rut = formatear_rut(rut)
    anteriores = _registro(donde)
    numero = f"{len(anteriores) + 1:04d}"
    datos = {"numero": numero, "emitida": date.today().isoformat(), "cliente": cliente, "rut": rut, "tipo": tipo,
             "cajas": cajas, "equipo": equipo}
    texto = licencia.armar(datos, llave)
    licencia.leer(texto, [publica_de(llave)])          # se revisa como la revisará Neji
    archivo = _nombre_archivo(numero, cliente)
    (donde / "licencias").mkdir(parents=True, exist_ok=True)
    (donde / "licencias" / archivo).write_text(
        f"Licencia de Neji POS N° {numero}\nCliente: {cliente}{' (RUT ' + rut + ')' if rut else ''}\n"
        f"Tipo: {describir(datos)}\nEquipo: {_equipo_texto(equipo)}\n\n"
        "Para activarla: en Neji POS, Configuración → Licencia, pega el texto que sigue y pulsa\n"
        "«Activar licencia».\n\n"
        f"{texto}\n", encoding="utf-8")
    nuevo = not (donde / REGISTRO).exists()
    with (donde / REGISTRO).open("a", encoding="utf-8-sig", newline="") as salida:
        escritor = csv.DictWriter(salida, COLUMNAS, delimiter=";")
        if nuevo:
            escritor.writeheader()
        escritor.writerow({"numero": numero, "emitida": datos["emitida"], "cliente": cliente, "rut": rut, "tipo": tipo,
                           "cajas": cajas or "sin límite", "equipo": equipo, "nota": nota, "archivo": archivo})
    return texto, datos


def describir(datos):
    if datos["tipo"] == "caja":
        return "Caja (una caja)"
    return f"Local (multicaja), {'cajas sin límite' if not datos.get('cajas') else str(datos['cajas']) + ' cajas'}"


def _equipo_texto(equipo):
    return "cualquier computador" if equipo == licencia.CUALQUIER_EQUIPO else equipo


# --- Por consola ---------------------------------------------------------------------------------------

def _preguntar(texto, defecto=""):
    respuesta = input(f"{texto}{f' [{defecto}]' if defecto else ''}: ").strip()
    return respuesta or defecto


def _leer_clave(texto):
    """Pide la contraseña sin mostrarla. En la ventana de Windows cada letra se ve como un asterisco (sin nada en
    pantalla parece que el teclado no funcionara)."""
    if sys.platform != "win32" or not sys.stdin or not sys.stdin.isatty():
        return getpass.getpass(texto)
    import msvcrt

    print(texto, end="", flush=True)
    letras = []
    while True:
        letra = msvcrt.getwch()
        if letra in ("\r", "\n"):
            print()
            return "".join(letras)
        if letra == "\x03":                       # Ctrl+C
            raise KeyboardInterrupt
        if letra in ("\x00", "\xe0"):             # flechas y teclas de función: se ignoran
            msvcrt.getwch()
        elif letra == "\b":
            if letras:
                letras.pop()
                print("\b \b", end="", flush=True)
        else:
            letras.append(letra)
            print("*", end="", flush=True)


def _clave(confirmar=False):
    clave = os.environ.get("NEJI_LICENCIAS_CLAVE")
    if clave:
        return clave
    clave = _leer_clave("Contraseña de tu llave: ")
    if confirmar and _leer_clave("Repite la contraseña: ") != clave:
        raise Error("Las contraseñas no coinciden.")
    return clave


def accion_llave():
    print("Se va a crear tu llave para firmar licencias. Elige una contraseña (mínimo 6 letras) y no la olvides:")
    print("sin ella no se pueden hacer licencias. Escríbela y presiona Enter.\n")
    publica = crear_llave(_clave(confirmar=True))
    print(f"\nLlave creada en {carpeta() / ARCHIVO_LLAVE}")
    print("Respalda esa carpeta (por ejemplo, en un pendrive) y no la compartas con nadie.\n")
    print("Tu llave PÚBLICA (esta sí se puede compartir: es la que va dentro de Neji POS):\n")
    print(f"    {publica}\n")
    print("Para que Neji POS acepte tus licencias, esa llave pública tiene que quedar en neji/licencia.py")
    print("(LLAVES_PUBLICAS) y compilarse una versión nueva.")


def accion_crear(argumentos=None):
    a = argumentos
    if a and a.cliente:
        cliente, tipo, cajas, equipo, rut, nota = a.cliente, a.tipo, a.cajas, a.equipo, a.rut, a.nota
    else:
        cliente = _preguntar("Cliente (nombre del negocio)")
        rut = _preguntar("RUT del cliente (opcional)")
        opcion = _preguntar("Tipo: 1 = Caja (una caja), 2 = Local (multicaja)", "1")
        tipo = "local" if opcion.strip() == "2" else "caja"
        cajas = None
        if tipo == "local":
            cajas = _preguntar("¿Cuántas cajas? (Enter = sin límite)", "0")
        equipo = _preguntar("Código del equipo del cliente (está en su Configuración → Licencia; "
                            "Enter = cualquier computador)")
        if not equipo:
            if _preguntar("¿Sirve en cualquier computador? Solo para clientes de confianza (s/n)", "n").lower() != "s":
                raise Error("Pídele al cliente el código de su equipo.")
            equipo = licencia.CUALQUIER_EQUIPO
        nota = _preguntar("Nota para tu registro (opcional, p. ej. precio o forma de pago)")
    texto, datos = crear_licencia(cargar_llave(_clave()), cliente, tipo, cajas, equipo, rut, nota)
    print(f"\nLicencia N° {datos['numero']} · {datos['cliente']} · {describir(datos)} · "
          f"{_equipo_texto(datos['equipo'])}\n")
    print(texto)
    print(f"\nQuedó guardada en {carpeta() / 'licencias'} y anotada en {carpeta() / REGISTRO}.")
    print("Mándale al cliente el texto (o el archivo): lo pega en Configuración → Licencia.")


def accion_ver(texto=None):
    texto = texto or _preguntar("Pega la licencia")
    publica = (carpeta() / ARCHIVO_PUBLICA)
    llaves = [publica.read_text(encoding="utf-8").strip()] if publica.exists() else []
    llaves += licencia.LLAVES_PUBLICAS
    datos = licencia.leer(texto, llaves)
    print(f"\nLicencia N° {datos.get('numero')} del {datos.get('emitida')}")
    print(f"Cliente: {datos['cliente']}{' (RUT ' + datos['rut'] + ')' if datos.get('rut') else ''}")
    print(f"Tipo: {describir(datos)}")
    print(f"Equipo: {_equipo_texto(datos.get('equipo'))}")


def accion_publica():
    ruta = carpeta() / ARCHIVO_PUBLICA
    if not ruta.exists():
        raise Error("Todavía no tienes llave: créala primero.")
    print(ruta.read_text(encoding="utf-8").strip())


def menu():
    print("Neji POS · Licencias")
    print(f"Carpeta: {carpeta()}\n")
    if not (carpeta() / ARCHIVO_LLAVE).exists():
        print("Todavía no tienes una llave para firmar licencias.\n")
        accion_llave()
        return
    opcion = _preguntar("1 = Crear una licencia, 2 = Ver qué dice una licencia, 3 = Ver mi llave pública", "1")
    {"1": accion_crear, "2": accion_ver, "3": accion_publica}.get(opcion, accion_crear)()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Licencias de Neji POS")
    sub = parser.add_subparsers(dest="accion")
    sub.add_parser("llave")
    sub.add_parser("publica")
    ver = sub.add_parser("ver")
    ver.add_argument("texto", nargs="?")
    crear = sub.add_parser("crear")
    crear.add_argument("--cliente")
    crear.add_argument("--tipo", choices=list(licencia.TIPOS), default="caja")
    crear.add_argument("--cajas", type=int, default=0, help="solo local: 0 = sin límite")
    crear.add_argument("--equipo", default=licencia.CUALQUIER_EQUIPO)
    crear.add_argument("--rut", default="")
    crear.add_argument("--nota", default="")
    a = parser.parse_args(argv)
    try:
        if a.accion == "llave":
            accion_llave()
        elif a.accion == "crear":
            accion_crear(a)
        elif a.accion == "ver":
            accion_ver(a.texto)
        elif a.accion == "publica":
            accion_publica()
        else:
            menu()
    except (Error, ErrorNegocio) as e:
        print(f"\nNo se pudo: {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
