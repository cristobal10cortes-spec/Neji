"""Lectores de códigos de barras conectados como puerto serie USB (COM), leídos directo por NejiPOS.exe.

La mayoría de los lectores funcionan como un teclado (eso lo maneja la página: lector.js). Algunos vienen o
se configuran en modo «USB COM» / «USB serie»: no escriben nada, mandan el código por un puerto COM. Aquí se
leen esos puertos y los códigos quedan en una cola que la ventana va pidiendo (ApiEscritorio.lecturas).

Solo se abren solos los puertos que parecen lectores (fabricante o descripción conocidos). Los demás puertos
USB se muestran en Configuración → Esta terminal para activarlos a mano: abrir un puerto lo deja ocupado y
podría ser, por ejemplo, el de una máquina de pagos.
"""

import logging
import queue
import re
import threading
import time

registro = logging.getLogger("neji.lector")

# Fabricantes de lectores (VID del USB): Honeywell/Metrologic, Hand Held Products, Zebra/Symbol, Datalogic,
# Datalogic ADC, Newland, Opticon.
VENDEDORES_LECTOR = {0x0C2E, 0x0536, 0x05E0, 0x05F9, 0x080C, 0x1EAB, 0x065A}
PATRON_LECTOR = re.compile(
    r"scanner|barcode|bar ?code|lector|esc[aá]ner|honeywell|metrologic|zebra|symbol|datalogic|newland|zebex|"
    r"opticon|hand ?held|motorola", re.IGNORECASE)


def parece_lector(vid, texto):
    return (vid in VENDEDORES_LECTOR) or bool(PATRON_LECTOR.search(texto or ""))


def limpiar(datos):
    """Bytes leídos -> código (sin espacios ni caracteres de control)."""
    texto = bytes(datos).decode("latin-1", "replace")
    return "".join(c for c in texto if c.isprintable()).strip()


class Acumulador:
    """Junta lo que llega por el puerto y separa los códigos: por Enter (CR o LF) o, si el lector no manda
    terminador, cuando deja de llegar algo por un momento."""

    def __init__(self, pausa=0.25):
        self.pausa = pausa
        self.buffer = bytearray()
        self.ultimo = 0.0

    def agregar(self, datos, ahora):
        codigos = []
        for b in datos:
            if b in (10, 13):
                codigos.append(limpiar(self.buffer))
                self.buffer.clear()
            else:
                self.buffer.append(b)
        if datos:
            self.ultimo = ahora
        return [c for c in codigos if c]

    def vencidos(self, ahora):
        if self.buffer and ahora - self.ultimo >= self.pausa:
            codigo = limpiar(self.buffer)
            self.buffer.clear()
            return [codigo] if codigo else []
        return []


class LectorSerie:
    """Vigila los puertos COM USB, lee los elegidos y deja los códigos en una cola."""

    def __init__(self, excluir=lambda: set(), elegidos=lambda: {}, revisar_cada=3.0):
        self.excluir, self.elegidos, self.revisar_cada = excluir, elegidos, revisar_cada
        self.cola = queue.Queue()
        self.puertos = {}
        self._hilos = {}
        self._parar = threading.Event()
        self._candado = threading.Lock()
        self.disponible = True
        self.error = ""

    def iniciar(self):
        threading.Thread(target=self._vigilar, name="lector-serie", daemon=True).start()
        return self

    def detener(self):
        self._parar.set()

    def _vigilar(self):
        while not self._parar.is_set():
            try:
                self.revisar()
            except ImportError:
                self.disponible, self.error = False, "Falta el módulo pyserial: los lectores por puerto COM no se pueden leer."
                return
            except Exception:  # noqa: BLE001
                registro.exception("No se pudieron revisar los puertos COM")
            self._parar.wait(self.revisar_cada)

    def revisar(self, comports=None):
        """Mira qué puertos USB hay y abre los que corresponde (los que parecen lectores o se eligieron)."""
        if comports is None:
            from serial.tools import list_ports
            comports = list_ports.comports
        excluidos = {p.upper() for p in self.excluir()}
        elegidos = {k.upper(): v for k, v in self.elegidos().items()}
        vistos = set()
        for p in comports():
            if getattr(p, "vid", None) is None:
                continue   # solo los del USB
            nombre = p.device.upper()
            vistos.add(nombre)
            texto = " ".join(str(x or "") for x in (p.description, getattr(p, "manufacturer", ""), getattr(p, "product", "")))
            with self._candado:
                info = self.puertos.setdefault(nombre, {"puerto": nombre, "estado": "sin usar", "ultima": ""})
                info["descripcion"] = (p.description or nombre).strip()
                info["automatico"] = parece_lector(p.vid, texto)
                info["impresora"] = nombre in excluidos
                info["usar"] = elegidos.get(nombre, info["automatico"]) and not info["impresora"]
                info["conectado"] = True
            hilo = self._hilos.get(nombre)
            if info["usar"] and not (hilo and hilo.is_alive()):
                self._hilos[nombre] = threading.Thread(target=self._leer, args=(nombre,), name=f"lector-{nombre}", daemon=True)
                self._hilos[nombre].start()
        with self._candado:
            for nombre, info in self.puertos.items():
                if nombre not in vistos:
                    info["conectado"] = False
                    info["estado"] = "desconectado"

    def _leer(self, nombre):
        import serial
        try:
            with serial.Serial(nombre, 9600, timeout=0.2) as puerto:
                self._estado(nombre, "leyendo")
                acumulador = Acumulador()
                while not self._parar.is_set() and self.puertos.get(nombre, {}).get("usar"):
                    datos = puerto.read(64)
                    ahora = time.monotonic()
                    for codigo in acumulador.agregar(datos, ahora) + acumulador.vencidos(ahora):
                        self.recibir(nombre, codigo)
            self._estado(nombre, "sin usar")
        except (serial.SerialException, OSError, ValueError) as e:
            registro.warning("Lector en %s: %s", nombre, e)
            self._estado(nombre, f"no se pudo abrir: {e}")

    def _estado(self, nombre, estado):
        with self._candado:
            if nombre in self.puertos:
                self.puertos[nombre]["estado"] = estado

    def recibir(self, nombre, codigo):
        with self._candado:
            if nombre in self.puertos:
                self.puertos[nombre]["ultima"] = codigo
        self.cola.put(codigo)

    def esperar(self, segundos):
        """Los códigos leídos; si no hay, espera hasta `segundos` a que llegue alguno."""
        codigos = []
        try:
            codigos.append(self.cola.get(timeout=max(0.0, segundos)))
            while True:
                codigos.append(self.cola.get_nowait())
        except queue.Empty:
            pass
        return codigos

    def estado(self):
        with self._candado:
            return [dict(info) for info in sorted(self.puertos.values(), key=lambda x: x["puerto"])]
