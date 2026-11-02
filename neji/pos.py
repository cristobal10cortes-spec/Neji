"""Máquinas POS integradas (pago con tarjeta): Neji le manda el monto a la máquina y espera el resultado.

Es opcional y se configura por caja (Configuración → Máquina POS). Cada proveedor es un «conector» con la misma
forma: iniciar el cobro, consultar cómo va, cancelarlo mientras espera o anularlo si ya se aprobó. Hoy está el
simulador, para probar todo sin máquina; Klap, TUU (Haulmer), Mercado Pago, Transbank y Getnet aparecen como
pendientes hasta tener su documentación de integración. Para agregar un proveedor basta con un conector nuevo en
CONECTORES.

Si la máquina además entrega la boleta (Configuración → Boleta electrónica → «La máquina POS»), Neji no emite
boleta para no emitir dos.

El cobro se guarda (pos_cobros) y una venta lo usa una sola vez: el servidor revisa que esté aprobado, que sea de
la misma caja, del mismo monto y método, y que ninguna otra venta lo haya usado. Si la venta no se pudo registrar
después de aprobado el pago, se vuelve a intentar con el mismo cobro: no se cobra dos veces.
"""

import base64
import hashlib
import json
import secrets
import time

from .db import ahora, transaccion
from .validar import ErrorNegocio

METODOS = {"debito": "Débito", "credito": "Crédito"}
ESTADOS = {"esperando": "Esperando la tarjeta", "aprobado": "Aprobado", "rechazado": "Rechazado",
           "cancelado": "Cancelado", "anulado": "Anulado", "error": "Error"}


class ErrorPOS(Exception):
    """Problema al hablar con la máquina (sin conexión, credenciales malas...): el cobro queda en «error»."""


class Conector:
    """Lo que tiene que hacer cada proveedor. Los métodos reciben el cobro (dict, con «datos» propios del conector)
    y la configuración de la caja, y devuelven {estado, autorizacion?, tarjeta?, mensaje?, externo?, datos?}."""

    clave = ""
    nombre = ""
    disponible = True
    nota = ""
    # Campos de configuración: {clave, etiqueta, tipo (texto | numero | opciones | secreto), ...}. Los «secreto»
    # (llaves de API) se guardan cifrados y nunca vuelven a la pantalla.
    campos = ()

    def validar(self, datos):
        return {}

    def iniciar(self, cobro, config):
        raise ErrorPOS(f"{self.nombre} todavía no está disponible.")

    def consultar(self, cobro, config):
        return {"estado": cobro["estado"]}

    def cancelar(self, cobro, config):
        return {"estado": "cancelado"}

    def anular(self, cobro, config):
        raise ErrorPOS(f"{self.nombre} no permite anular desde Neji: anúlalo en la máquina.")


class Simulador(Conector):
    clave = "simulador"
    nombre = "Simulador de pruebas"
    nota = "No cobra de verdad: sirve para probar el cobro con máquina sin tener una."
    campos = (
        {"clave": "resultado", "etiqueta": "Qué responde", "tipo": "opciones",
         "opciones": {"aprobar": "Aprueba los pagos", "rechazar": "Rechaza los pagos"}},
        {"clave": "segundos", "etiqueta": "Segundos que tarda", "tipo": "numero", "minimo": 0, "maximo": 60,
         "ayuda": "Lo que demoraría el cliente en pasar la tarjeta."},
    )

    def validar(self, datos):
        resultado = datos.get("resultado") or "aprobar"
        if resultado not in ("aprobar", "rechazar"):
            raise ErrorNegocio("El simulador aprueba o rechaza.")
        try:
            segundos = int(datos.get("segundos", 3))
        except (TypeError, ValueError):
            raise ErrorNegocio("Los segundos del simulador son un número.") from None
        if not 0 <= segundos <= 60:
            raise ErrorNegocio("Los segundos del simulador van de 0 a 60.")
        return {"resultado": resultado, "segundos": segundos}

    def iniciar(self, cobro, config):
        if config["segundos"] <= 0:
            return self._respuesta(config)
        return {"estado": "esperando", "datos": {"listo": time.time() + config["segundos"]}}

    def consultar(self, cobro, config):
        if time.time() < cobro["datos"].get("listo", 0):
            return {"estado": "esperando"}
        return self._respuesta(config)

    def anular(self, cobro, config):
        return {"estado": "anulado", "mensaje": "Pago anulado (simulador)."}

    @staticmethod
    def _respuesta(config):
        if config["resultado"] == "rechazar":
            return {"estado": "rechazado", "mensaje": "Tarjeta rechazada (simulador)."}
        return {"estado": "aprobado", "autorizacion": f"{secrets.randbelow(10 ** 6):06d}", "tarjeta": "4242",
                "mensaje": "Aprobado (simulador)."}


class Pendiente(Conector):
    """Un proveedor que se va a integrar cuando entregue su documentación."""

    disponible = False

    def __init__(self, clave, nombre, nota):
        self.clave, self.nombre, self.nota = clave, nombre, nota


CONECTORES = {c.clave: c for c in (
    Simulador(),
    Pendiente("klap", "Klap",
              "Pendiente: falta la documentación de integración de Klap (programa «POS Integrados»)."),
    Pendiente("tuu", "TUU (Haulmer)", "Pendiente: falta la documentación de «Pago remoto» de TUU."),
    Pendiente("mercadopago", "Mercado Pago (Point)",
              "Pendiente: falta integrar Mercado Pago Point (la orden de cobro llega a la máquina por internet)."),
    Pendiente("transbank", "Transbank (POS Integrado)",
              "Pendiente: falta integrar el «POS Integrado» de Transbank (la máquina va conectada a la caja por "
              "USB)."),
    Pendiente("getnet", "Getnet", "Pendiente: falta la documentación de integración de Getnet."),
)}


# --- Configuración de cada caja ---------------------------------------------------------------------------

def _cifrador(secreto):
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"neji-pos:{secreto}".encode()).digest()))


def _fila_config(con, caja_id):
    return con.execute("SELECT * FROM pos_config WHERE caja_id = ?", (caja_id,)).fetchone()


def _config(con, caja_id, secreto=None):
    """(conector, datos) de la caja si tiene el cobro con máquina activo; None si no."""
    fila = _fila_config(con, caja_id)
    if fila is None or not fila["activo"] or fila["proveedor"] not in CONECTORES:
        return None
    conector = CONECTORES[fila["proveedor"]]
    datos = json.loads(fila["datos"] or "{}")
    for campo in conector.campos:
        if campo["tipo"] == "secreto" and datos.get(campo["clave"]) and secreto:
            datos[campo["clave"]] = _cifrador(secreto).decrypt(datos[campo["clave"]].encode()).decode()
    return conector, datos


def proveedores():
    return [{"clave": c.clave, "nombre": c.nombre, "disponible": c.disponible, "nota": c.nota,
             "campos": list(c.campos)} for c in CONECTORES.values()]


def configuracion(con):
    """Cada caja con su máquina (sin los secretos: solo si están guardados)."""
    resultado = []
    for caja in con.execute("SELECT id, nombre, activa FROM cajas ORDER BY id"):
        fila = _fila_config(con, caja["id"])
        datos = json.loads(fila["datos"] or "{}") if fila else {}
        conector = CONECTORES.get(fila["proveedor"]) if fila else None
        for campo in conector.campos if conector else ():
            if campo["tipo"] == "secreto":
                datos[campo["clave"] + "_guardada"] = bool(datos.pop(campo["clave"], None))
        resultado.append({"caja_id": caja["id"], "nombre": caja["nombre"], "caja_activa": bool(caja["activa"]),
                          "proveedor": fila["proveedor"] if fila else "", "activo": bool(fila and fila["activo"]),
                          "datos": datos})
    return resultado


def guardar(con, caja_id, entrada, secreto):
    if not con.execute("SELECT 1 FROM cajas WHERE id = ?", (caja_id,)).fetchone():
        raise ErrorNegocio("Caja no encontrada.", status=404)
    proveedor = str(entrada.get("proveedor") or "")
    activo = entrada.get("activo") in (True, 1, "1")
    if not proveedor:
        con.execute("DELETE FROM pos_config WHERE caja_id = ?", (caja_id,))
        return
    conector = CONECTORES.get(proveedor)
    if conector is None:
        raise ErrorNegocio("Ese proveedor de máquinas no existe.")
    if not conector.disponible:
        raise ErrorNegocio(f"{conector.nombre} todavía no se puede usar: {conector.nota}")
    datos_entrada = entrada.get("datos") or {}
    if not isinstance(datos_entrada, dict):
        raise ErrorNegocio("Formato de configuración inválido.")
    datos = conector.validar(datos_entrada)
    anterior = _fila_config(con, caja_id)
    previos = json.loads(anterior["datos"] or "{}") if anterior and anterior["proveedor"] == proveedor else {}
    for campo in conector.campos:
        if campo["tipo"] == "secreto":
            valor = str(datos_entrada.get(campo["clave"]) or "")
            datos[campo["clave"]] = (_cifrador(secreto).encrypt(valor.encode()).decode() if valor
                                     else previos.get(campo["clave"], ""))
    con.execute("INSERT INTO pos_config (caja_id, proveedor, activo, datos) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(caja_id) DO UPDATE SET proveedor = excluded.proveedor, activo = excluded.activo, "
                "datos = excluded.datos", (caja_id, proveedor, int(activo), json.dumps(datos)))


def resumen(con):
    """Lo que necesita la caja (en /api/config): qué cajas cobran con máquina y con cuál."""
    resultado = {}
    for fila in con.execute("SELECT caja_id, proveedor FROM pos_config WHERE activo = 1"):
        conector = CONECTORES.get(fila["proveedor"])
        if conector is not None and conector.disponible:
            resultado[str(fila["caja_id"])] = {"proveedor": conector.clave, "nombre": conector.nombre}
    return resultado


# --- Cobros -----------------------------------------------------------------------------------------------

def _cobro(con, cobro_id):
    fila = con.execute("SELECT * FROM pos_cobros WHERE id = ?", (cobro_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio("Cobro no encontrado.", status=404)
    cobro = dict(fila)
    cobro["datos"] = json.loads(cobro["datos"] or "{}")
    return cobro


def publico(cobro):
    return {k: cobro[k] for k in ("id", "caja_id", "proveedor", "metodo", "monto", "estado", "autorizacion",
                                  "tarjeta", "mensaje", "venta_id")} | {"estado_texto": ESTADOS[cobro["estado"]]}


def _aplicar(con, cobro, respuesta):
    estado = respuesta.get("estado")
    if estado not in ESTADOS:
        estado, respuesta = "error", {"mensaje": f"La máquina respondió algo inesperado ({estado!r})."}
    datos = cobro["datos"] | (respuesta.get("datos") or {})
    with transaccion(con):
        con.execute("UPDATE pos_cobros SET estado = ?, autorizacion = COALESCE(?, autorizacion), "
                    "tarjeta = COALESCE(?, tarjeta), mensaje = ?, externo = COALESCE(?, externo), datos = ?, "
                    "actualizado = ? WHERE id = ?",
                    (estado, respuesta.get("autorizacion"), respuesta.get("tarjeta"), respuesta.get("mensaje"),
                     respuesta.get("externo"), json.dumps(datos), ahora(), cobro["id"]))
    return _cobro(con, cobro["id"])


def _llamar(con, cobro, funcion, config):
    try:
        respuesta = funcion(cobro, config)
    except ErrorPOS as e:
        respuesta = {"estado": "error", "mensaje": str(e)}
    return _aplicar(con, cobro, respuesta)


def iniciar(con, caja_id, monto, metodo, usuario, secreto):
    """Manda el monto a la máquina de la caja. Devuelve el cobro (normalmente «esperando»)."""
    if metodo not in METODOS:
        raise ErrorNegocio("La máquina cobra con débito o crédito.")
    if not isinstance(monto, int) or monto <= 0:
        raise ErrorNegocio("El monto a cobrar debe ser mayor que cero.")
    configurada = _config(con, caja_id, secreto)
    if configurada is None or not configurada[0].disponible:
        raise ErrorNegocio("Esta caja no tiene una máquina POS configurada (Configuración → Máquina POS).")
    conector, config = configurada
    with transaccion(con):
        cobro_id = con.execute(
            "INSERT INTO pos_cobros (caja_id, usuario_id, proveedor, metodo, monto, estado, creado, actualizado) "
            "VALUES (?, ?, ?, ?, ?, 'esperando', ?, ?)",
            (caja_id, usuario["id"], conector.clave, metodo, monto, ahora(), ahora())).lastrowid
    # La máquina se llama fuera de la transacción: mientras espera, las otras cajas siguen vendiendo.
    return publico(_llamar(con, _cobro(con, cobro_id), conector.iniciar, config))


def consultar(con, cobro_id, secreto):
    cobro = _cobro(con, cobro_id)
    if cobro["estado"] == "esperando":
        configurada = _config(con, cobro["caja_id"], secreto)
        if configurada is None:
            cobro = _aplicar(con, cobro, {"estado": "error", "mensaje": "Se desactivó la máquina de esta caja."})
        else:
            cobro = _llamar(con, cobro, configurada[0].consultar, configurada[1])
    return publico(cobro)


def cancelar(con, cobro_id, secreto):
    """Cancela un cobro que espera la tarjeta, o anula uno aprobado que ninguna venta usó."""
    cobro = _cobro(con, cobro_id)
    if cobro["venta_id"]:
        raise ErrorNegocio("Este pago ya es parte de una venta: para devolverlo, haz la devolución de la venta.")
    if cobro["estado"] not in ("esperando", "aprobado"):
        return publico(cobro)
    configurada = _config(con, cobro["caja_id"], secreto) or (CONECTORES.get(cobro["proveedor"], Conector()), {})
    conector, config = configurada
    accion = conector.cancelar if cobro["estado"] == "esperando" else conector.anular
    return publico(_llamar(con, cobro, accion, config))


def usar_en_venta(con, cobro_id, caja_id, pagos):
    """Dentro de la transacción de la venta: el cobro tiene que estar aprobado, ser de esta caja y cuadrar con lo
    que la venta paga con ese método. Devuelve el cobro; se marca usado con marcar_usado."""
    cobro = _cobro(con, cobro_id)
    if cobro["estado"] != "aprobado":
        raise ErrorNegocio(f"El pago en la máquina no está aprobado ({ESTADOS[cobro['estado']].lower()}).")
    if cobro["venta_id"]:
        raise ErrorNegocio("Ese pago de la máquina ya se usó en otra venta.")
    if cobro["caja_id"] != caja_id:
        raise ErrorNegocio("Ese pago se hizo en la máquina de otra caja.")
    if pagos.get(cobro["metodo"]) != cobro["monto"]:
        raise ErrorNegocio(f"El pago aprobado en la máquina ({METODOS[cobro['metodo']].lower()}, "
                           f"${cobro['monto']:,}".replace(",", ".") + ") no coincide con el de la venta.")
    return cobro


def marcar_usado(con, cobro_id, venta_id):
    if con.execute("UPDATE pos_cobros SET venta_id = ?, actualizado = ? WHERE id = ? AND venta_id IS NULL",
                   (venta_id, ahora(), cobro_id)).rowcount != 1:
        raise ErrorNegocio("Ese pago de la máquina ya se usó en otra venta.")
