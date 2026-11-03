"""Buscar en la red del local el computador principal de Neji POS (para una caja que se conecta a él).

El principal acepta cajas cuando en Configuración → Cajas se marca «Permitir que otras cajas de la red se
conecten»: escucha en el puerto 5000 de la red local. Una caja nueva prueba ese puerto en todas las direcciones
de su red (192.168.1.1 a 192.168.1.254, por ejemplo) y le pregunta a cada una que responda si es Neji POS
(/api/estado, que dice el nombre del negocio y la versión). Tarda unos segundos.
"""

import ipaddress
import json
import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PUERTO = 5000
MAX_REDES = 4                # adaptadores de red que se revisan (el del local, y quizás uno virtual)

# Sin proxy: las direcciones del local nunca pasan por el proxy de Windows o de la empresa.
_navegador = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ips_de_este_equipo():
    """Las direcciones IPv4 de este computador."""
    from .equipo import ip_local

    ips = {ip_local()}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ips)


def redes(ips):
    """Las redes locales (/24) donde buscar: solo direcciones privadas, sin 127.x ni 169.254.x."""
    vistas = []
    for ip in ips:
        try:
            direccion = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if not direccion.is_private or direccion.is_loopback or direccion.is_link_local:
            continue
        red = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        if red not in vistas:
            vistas.append(red)
    return vistas[:MAX_REDES]


def candidatos(ips):
    """Todas las direcciones de esas redes, menos las de este mismo computador."""
    propias = set(ips)
    return [str(h) for red in redes(ips) for h in red.hosts() if str(h) not in propias]


def estado(direccion, segundos=1.5):
    """Lo que responde /api/estado del Neji POS en «ip:puerto», o None si ahí no hay uno."""
    try:
        with _navegador.open(f"http://{direccion}/api/estado", timeout=segundos) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) and "configurado" in datos else None


def _abierto(ip, puerto, segundos):
    try:
        with socket.create_connection((ip, puerto), timeout=segundos):
            return True
    except OSError:
        return False


def buscar(puerto=PUERTO, hosts=None, segundos=0.4, hilos=64):
    """Los Neji POS de la red que aceptan cajas: [{direccion, ip, negocio, version}], ordenados por IP."""
    hosts = candidatos(ips_de_este_equipo()) if hosts is None else list(hosts)

    def revisar(ip):
        if not _abierto(ip, puerto, segundos):
            return None
        datos = estado(f"{ip}:{puerto}")
        if datos is None:
            return None
        return {"direccion": f"{ip}:{puerto}", "ip": ip, "negocio": str(datos.get("negocio") or ""),
                "version": str(datos.get("version") or "")}

    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(hilos, len(hosts))) as hilos_:
        encontrados = [r for r in hilos_.map(revisar, hosts) if r]

    def orden(r):
        try:
            return (0, int(ipaddress.IPv4Address(r["ip"])), r["ip"])
        except ValueError:
            return (1, 0, r["ip"])

    return sorted(encontrados, key=orden)


def normalizar(destino, puerto=PUERTO):
    """«192.168.1.20», «http://192.168.1.20:5000/» → «192.168.1.20:5000». ValueError con el motivo, si no."""
    texto = str(destino or "").strip()
    for prefijo in ("http://", "https://"):
        texto = texto.removeprefix(prefijo)
    texto = texto.split("/", 1)[0]
    if not texto:
        raise ValueError("Escribe la dirección del computador principal (por ejemplo 192.168.1.20).")
    equipo, _, numero = texto.partition(":")
    if numero:
        if not numero.isdigit() or not 0 < int(numero) < 65536:
            raise ValueError(f"«{texto}» no es una dirección válida: el puerto va de 1 a 65535.")
        puerto = int(numero)
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", equipo):
        raise ValueError(f"«{texto}» no es una dirección válida (por ejemplo 192.168.1.20).")
    return f"{equipo}:{puerto}"
