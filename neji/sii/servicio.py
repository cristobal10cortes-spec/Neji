"""La boleta y factura electrónica dentro de Neji: configuración, firma, folios, emisión y envío al SII.

- Al cobrar (servicios/ventas.registrar_venta) se emite la boleta o factura en la misma transacción de la
  venta: el folio queda tomado solo si la venta se guarda. Si la boleta no se puede emitir (sin folios, firma
  vencida...), la venta igual se registra con su comprobante interno y se avisa; una factura pedida, en
  cambio, no se vende sin ella.
- Al devolver se emite la nota de crédito que corrige el documento de la venta.
- El envío al SII lo hace un hilo en segundo plano (Enviador): arma los sobres, los sube y consulta su
  estado. Nada de red ocurre dentro de una venta.
- Intercambio: cuando el SII acepta una factura (o la nota de crédito de una factura), el mismo hilo le
  manda el XML por correo al cliente, si se configuró la cuenta de correo.
"""

import base64
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta

from ..chile import limpiar_rut, validar_rut
from ..db import ahora, conectar, transaccion
from . import BOLETAS, FACTURAS, NOMBRES, NS_SII, RUT_CONSUMIDOR_FINAL, ErrorSII, falta_modulo

registro = logging.getLogger("neji.sii")

AMBIENTES = {"certificacion": "Certificación (pruebas del SII)", "produccion": "Producción"}
CAMPOS_TEXTO = {"rut": 12, "razon_social": 100, "giro": 80, "direccion": 70, "comuna": 20, "ciudad": 20,
                "telefono": 20, "email": 80, "oficina_sii": 40, "fecha_resolucion": 10,
                "correo_servidor": 120, "correo_usuario": 120, "correo_remitente": 120}
BOLETAS_POR_SOBRE = 50
ESPERA_CONSULTA = 30            # segundos entre subir un sobre y preguntar por él
REINTENTOS = (60, 120, 300, 600, 1800, 3600)


# --- Configuración ------------------------------------------------------------------------------------

def leer(con):
    cfg = {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM sii_config")}
    cfg.setdefault("activo", "0")
    cfg.setdefault("ambiente", "certificacion")
    cfg.setdefault("numero_resolucion", "0")
    return cfg


def _poner(con, clave, valor):
    con.execute("INSERT INTO sii_config (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = ?",
                (clave, valor, valor))


def activo(con):
    return leer(con).get("activo") == "1" and not falta_modulo()


def actecos(cfg):
    return [int(x) for x in str(cfg.get("actecos") or "").replace(";", ",").split(",") if x.strip().isdigit()]


def guardar(con, datos, secreto=None):
    """Guarda los datos del emisor, el ambiente, la resolución y el correo. Para activar tiene que estar todo listo.

    La contraseña del correo (correo_clave) se guarda cifrada; vacía, queda la que estaba.
    """
    from .textos import correo_valido, texto_sii

    cambios = {}
    for clave, largo in CAMPOS_TEXTO.items():
        if clave in datos:
            cambios[clave] = texto_sii(datos[clave], largo) if not clave.startswith("correo_") else \
                str(datos[clave] or "").strip()[:largo]
    if cambios.get("correo_remitente") and not correo_valido(cambios["correo_remitente"]):
        raise ErrorSII("El correo del remitente no es válido.")
    if "correo_puerto" in datos:
        puerto = str(datos["correo_puerto"] or "").strip() or "587"
        if not puerto.isdigit() or not 0 < int(puerto) < 65536:
            raise ErrorSII("El puerto del correo es un número (587, o 465 con SSL).")
        cambios["correo_puerto"] = puerto
    if datos.get("correo_clave"):
        if not secreto:
            raise ErrorSII("No se puede guardar la contraseña del correo.")
        cambios["correo_clave"] = _cifrador(secreto).encrypt(str(datos["correo_clave"]).encode()).decode()
    if "rut" in cambios and cambios["rut"]:
        rut = limpiar_rut(cambios["rut"])
        if not validar_rut(rut):
            raise ErrorSII("El RUT de la empresa no es válido.")
        cambios["rut"] = rut
    if "actecos" in datos:
        codigos = [x.strip() for x in str(datos["actecos"] or "").replace(";", ",").split(",") if x.strip()]
        if any(not c.isdigit() or len(c) > 6 for c in codigos) or len(codigos) > 4:
            raise ErrorSII("La actividad económica son hasta 4 códigos de 6 dígitos (p. ej. 477310), separados "
                           "por coma.")
        cambios["actecos"] = ",".join(codigos)
    if "sucursal_sii" in datos:
        codigo = str(datos["sucursal_sii"] or "").strip()
        if codigo and (not codigo.isdigit() or len(codigo) > 9):
            raise ErrorSII("El código de sucursal del SII son solo números (hasta 9).")
        cambios["sucursal_sii"] = codigo
    if "numero_resolucion" in datos:
        numero = str(datos["numero_resolucion"] or "0").strip()
        if not numero.isdigit():
            raise ErrorSII("El número de resolución son solo números (en certificación es 0).")
        cambios["numero_resolucion"] = str(int(numero))
    if cambios.get("fecha_resolucion"):
        try:
            datetime.strptime(cambios["fecha_resolucion"], "%Y-%m-%d")
        except ValueError:
            raise ErrorSII("La fecha de resolución debe ser una fecha (AAAA-MM-DD).") from None
    if "ambiente" in datos:
        if datos["ambiente"] not in AMBIENTES:
            raise ErrorSII("El ambiente debe ser certificación o producción.")
        cambios["ambiente"] = datos["ambiente"]
    for clave, valor in cambios.items():
        _poner(con, clave, valor)
    if "activo" in datos:
        quiere = datos["activo"] in (True, 1, "1", "si", "true")
        if quiere:
            faltan = pendientes_para_activar(con)
            if faltan:
                raise ErrorSII("Para activar la boleta electrónica falta: " + "; ".join(faltan) + ".")
        _poner(con, "activo", "1" if quiere else "0")
    return leer(con)


def pendientes_para_activar(con):
    cfg = leer(con)
    faltan = []
    if falta_modulo():
        faltan.append(falta_modulo())
    for clave, nombre in (("rut", "el RUT de la empresa"), ("razon_social", "la razón social"),
                          ("giro", "el giro"), ("direccion", "la dirección"), ("comuna", "la comuna"),
                          ("fecha_resolucion", "la fecha de resolución")):
        if not cfg.get(clave):
            faltan.append(nombre)
    if not actecos(cfg):
        faltan.append("la actividad económica (Acteco)")
    if not cfg.get("firma_pfx"):
        faltan.append("la firma electrónica")
    if not con.execute("SELECT 1 FROM sii_caf WHERE ambiente = ? AND tipo IN (39, 41)",
                       (cfg["ambiente"],)).fetchone():
        faltan.append("los folios (CAF) de boleta electrónica")
    return faltan


# --- Firma electrónica ----------------------------------------------------------------------------------

def _cifrador(secreto):
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"neji-sii:{secreto}".encode()).digest()))


def guardar_firma(con, pfx, clave, secreto):
    from .firma import Firma

    firma = Firma(pfx, clave)
    if not firma.rut:
        raise ErrorSII("La firma no trae el RUT de su titular: no sirve para el SII.")
    firma.exigir_vigente()
    _poner(con, "firma_pfx", base64.b64encode(bytes(pfx)).decode())
    _poner(con, "firma_clave", _cifrador(secreto).encrypt((clave or "").encode()).decode())
    return firma.resumen()


def borrar_firma(con):
    con.execute("DELETE FROM sii_config WHERE clave IN ('firma_pfx', 'firma_clave')")


_firmas = {}


def cargar_firma(cfg, secreto):
    """La firma guardada (se carga una vez por proceso)."""
    from .firma import Firma

    if not cfg.get("firma_pfx"):
        raise ErrorSII("Falta la firma electrónica en Configuración → Boleta electrónica.")
    huella = hashlib.sha256((cfg["firma_pfx"] + cfg.get("firma_clave", "")).encode()).hexdigest()
    if huella not in _firmas:
        try:
            clave = _cifrador(secreto).decrypt(cfg.get("firma_clave", "").encode()).decode()
        except Exception:  # noqa: BLE001 (otra clave de Neji: p. ej. se restauró en otro computador)
            raise ErrorSII("No se puede leer la contraseña guardada de la firma (¿se restauró un respaldo en otro "
                           "computador?). Vuelve a subir la firma en Configuración → Boleta electrónica.") from None
        _firmas.clear()
        _firmas[huella] = Firma(base64.b64decode(cfg["firma_pfx"]), clave)
    return _firmas[huella]


def resumen_firma(cfg, secreto):
    if not cfg.get("firma_pfx"):
        return None
    try:
        return cargar_firma(cfg, secreto).resumen()
    except ErrorSII as e:
        return {"error": str(e)}


# --- Folios (CAF) -------------------------------------------------------------------------------------

def cargar_caf(con, xml):
    from .caf import Caf

    caf = Caf(xml)
    cfg = leer(con)
    if cfg.get("rut") and caf.rut != cfg["rut"]:
        raise ErrorSII(f"Estos folios son del RUT {caf.rut} y la empresa configurada es {cfg['rut']}.")
    ambiente = cfg["ambiente"]
    if con.execute("SELECT 1 FROM sii_caf WHERE ambiente = ? AND tipo = ? AND desde <= ? AND hasta >= ?",
                   (ambiente, caf.tipo, caf.hasta, caf.desde)).fetchone():
        raise ErrorSII(f"Ya están cargados folios de {caf.nombre.lower()} que se cruzan con el {caf.desde} "
                       f"al {caf.hasta}.")
    con.execute("INSERT INTO sii_caf (ambiente, tipo, desde, hasta, usar_desde, fecha, xml, cargado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ambiente, caf.tipo, caf.desde, caf.hasta, caf.desde, caf.fecha, caf.xml_original, ahora()))
    if not cfg.get("rut"):
        _poner(con, "rut", caf.rut)
    if not cfg.get("razon_social"):
        _poner(con, "razon_social", caf.razon_social[:100])
    return caf.resumen()


def folios(con, ambiente):
    resultado = []
    for c in con.execute("SELECT * FROM sii_caf WHERE ambiente = ? ORDER BY tipo, desde", (ambiente,)):
        usados = con.execute("SELECT COUNT(*), MAX(folio) FROM sii_documentos WHERE ambiente = ? AND tipo = ? "
                             "AND folio BETWEEN ? AND ?", (ambiente, c["tipo"], c["desde"], c["hasta"])).fetchone()
        siguiente = max(c["usar_desde"], (usados[1] or 0) + 1)
        resultado.append({"id": c["id"], "tipo": c["tipo"], "nombre": NOMBRES.get(c["tipo"], str(c["tipo"])),
                          "desde": c["desde"], "hasta": c["hasta"], "usar_desde": c["usar_desde"],
                          "fecha": c["fecha"], "usados": usados[0],
                          "disponibles": max(0, c["hasta"] - siguiente + 1)})
    return resultado


def cambiar_inicio(con, caf_id, usar_desde):
    c = con.execute("SELECT * FROM sii_caf WHERE id = ?", (caf_id,)).fetchone()
    if c is None:
        raise ErrorSII("No existen esos folios.")
    if not c["desde"] <= usar_desde <= c["hasta"]:
        raise ErrorSII(f"El folio debe estar entre {c['desde']} y {c['hasta']}.")
    con.execute("UPDATE sii_caf SET usar_desde = ? WHERE id = ?", (usar_desde, caf_id))


def borrar_caf(con, caf_id):
    c = con.execute("SELECT * FROM sii_caf WHERE id = ?", (caf_id,)).fetchone()
    if c is None:
        return
    if con.execute("SELECT 1 FROM sii_documentos WHERE ambiente = ? AND tipo = ? AND folio BETWEEN ? AND ?",
                   (c["ambiente"], c["tipo"], c["desde"], c["hasta"])).fetchone():
        raise ErrorSII("Ya se emitieron documentos con estos folios: no se pueden quitar.")
    con.execute("DELETE FROM sii_caf WHERE id = ?", (caf_id,))


def tomar_folio(con, ambiente, tipo):
    """El siguiente folio libre de ese tipo y su CAF. Debe llamarse dentro de la transacción del documento."""
    from .caf import Caf

    ultimo = con.execute("SELECT MAX(folio) FROM sii_documentos WHERE ambiente = ? AND tipo = ?",
                         (ambiente, tipo)).fetchone()[0] or 0
    for c in con.execute("SELECT * FROM sii_caf WHERE ambiente = ? AND tipo = ? ORDER BY desde",
                         (ambiente, tipo)):
        folio = max(c["usar_desde"], ultimo + 1)
        if folio <= c["hasta"]:
            return folio, Caf(c["xml"])
    raise ErrorSII(f"No quedan folios de {NOMBRES[tipo].lower()}: pide más al SII y cárgalos en "
                   "Configuración → Boleta electrónica.")


# --- Emisión ------------------------------------------------------------------------------------------

def emisor(cfg):
    return {"rut": cfg.get("rut"), "razon_social": cfg.get("razon_social"), "giro": cfg.get("giro"),
            "actecos": actecos(cfg), "direccion": cfg.get("direccion"), "comuna": cfg.get("comuna"),
            "ciudad": cfg.get("ciudad"), "sucursal_sii": cfg.get("sucursal_sii"), "telefono": cfg.get("telefono"),
            "email": cfg.get("email")}


def _receptor_cliente(cliente):
    if cliente is None:
        return None
    return {"rut": cliente["rut"], "razon_social": cliente["nombre"], "giro": cliente["giro"],
            "direccion": cliente["direccion"], "comuna": cliente["comuna"], "ciudad": cliente["ciudad"],
            "email": cliente["email"]}


def _intercambio(doc):
    """(correo, estado, glosa) del envío del XML al cliente: solo facturas y notas de crédito de facturas."""
    from .textos import correo_valido

    de_factura = doc["tipo"] in FACTURAS or (
        doc["tipo"] == 61 and any(r.get("tipo") in FACTURAS for r in doc.get("referencias") or []))
    if not de_factura:
        return None, None, None
    correo = str((doc.get("receptor") or {}).get("email") or "").strip()
    if not correo:
        return None, "sin_correo", "El cliente no tiene correo: descarga el XML y envíaselo."
    if not correo_valido(correo):
        return correo, "sin_correo", f"El correo del cliente ({correo}) no es válido: corrígelo en Clientes."
    return correo, "pendiente", None


def _guardar_documento(con, cfg, doc, resultado, venta_id=None, devolucion_id=None):
    receptor = doc.get("receptor") or {}
    t = resultado["totales"]
    correo, correo_estado, correo_glosa = _intercambio(doc)
    return con.execute(
        """INSERT INTO sii_documentos (ambiente, tipo, folio, fecha, emitido, venta_id, devolucion_id,
               rut_receptor, razon_receptor, neto, iva, exento, total, xml, ted, correo_receptor, correo_estado,
               correo_glosa)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cfg["ambiente"], doc["tipo"], doc["folio"], doc["fecha"], ahora(), venta_id, devolucion_id,
         limpiar_rut(receptor.get("rut")) or RUT_CONSUMIDOR_FINAL, receptor.get("razon_social") or "Consumidor Final",
         t["neto"], t["iva"], t["exento"], t["total"], resultado["xml"], resultado["ted"].decode("iso-8859-1"),
         correo, correo_estado, correo_glosa),
    ).lastrowid


def emitir_venta(con, venta_id, documento, secreto, tasa_iva=19):
    """Emite la boleta (o factura) de una venta ya guardada. Llamar dentro de una transacción."""
    from . import dte

    cfg = leer(con)
    venta = con.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    items = con.execute("SELECT * FROM venta_items WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    cliente = (con.execute("SELECT * FROM clientes WHERE id = ?", (venta["cliente_id"],)).fetchone()
               if venta["cliente_id"] else None)
    todos_exentos = all(i["exento"] for i in items)
    if documento == "factura":
        if cliente is None:
            raise ErrorSII("Para la factura elige el cliente (con RUT, giro, dirección y comuna).")
        tipo, receptor = (34 if todos_exentos else 33), _receptor_cliente(cliente)
    else:
        tipo = 41 if todos_exentos else 39
        receptor = None
        if cliente is not None and cliente["rut"] and validar_rut(cliente["rut"]):
            receptor = {"rut": cliente["rut"], "razon_social": cliente["nombre"]}
    exento_bruto = sum(i["importe"] for i in items if i["exento"])
    descuento_exento = exento_bruto - venta["exento"] if venta["descuento"] else 0
    folio, caf = tomar_folio(con, cfg["ambiente"], tipo)
    fiado = con.execute("SELECT 1 FROM venta_pagos WHERE venta_id = ? AND metodo = 'fiado'", (venta_id,)).fetchone()
    doc = {"tipo": tipo, "folio": folio, "fecha": venta["fecha"][:10], "emisor": emisor(cfg), "receptor": receptor,
           "lineas": [{"nombre": i["descripcion"], "codigo": i["codigo"], "cantidad": i["cantidad"],
                       "precio": i["precio_unitario"], "monto": i["importe"], "exento": bool(i["exento"])}
                      for i in items],
           "descuento_afecto": venta["descuento"] - descuento_exento, "descuento_exento": descuento_exento,
           "tasa_iva": tasa_iva, "credito": bool(fiado)}
    resultado = dte.construir(doc, caf, cargar_firma(cfg, secreto))
    if resultado["totales"]["total"] != venta["total"]:     # no debería pasar: mismos cálculos que la venta
        raise ErrorSII(f"El total del documento ({resultado['totales']['total']}) no cuadra con la venta "
                       f"({venta['total']}).")
    return _guardar_documento(con, cfg, doc, resultado, venta_id=venta_id)


def documento_de_venta(con, venta_id):
    """La boleta o factura vigente de la venta (no las rechazadas), o None."""
    return con.execute(
        f"SELECT * FROM sii_documentos WHERE venta_id = ? AND tipo IN ({','.join(map(str, BOLETAS + FACTURAS))}) "
        "AND estado != 'rechazado' ORDER BY id DESC LIMIT 1", (venta_id,)).fetchone()


def emitir_nota_credito(con, devolucion_id, secreto, tasa_iva=19):
    """Nota de crédito por una devolución, si la venta tiene boleta o factura electrónica. Dentro de la
    transacción de la devolución. Devuelve el id del documento o None (venta sin documento electrónico)."""
    from . import dte

    devolucion = con.execute("SELECT * FROM devoluciones WHERE id = ?", (devolucion_id,)).fetchone()
    original = documento_de_venta(con, devolucion["venta_id"])
    if original is None:
        return None
    cfg = leer(con)
    if original["ambiente"] != cfg["ambiente"]:
        return None
    venta = con.execute("SELECT * FROM ventas WHERE id = ?", (devolucion["venta_id"],)).fetchone()
    lineas = []
    for d in con.execute("""SELECT d.cantidad, d.monto, i.descripcion, i.codigo, i.exento FROM devolucion_items d
                            JOIN venta_items i ON i.id = d.venta_item_id WHERE d.devolucion_id = ? ORDER BY d.id""",
                         (devolucion_id,)):
        lineas.append({"nombre": d["descripcion"], "codigo": d["codigo"], "cantidad": d["cantidad"],
                       "precio": d["monto"] / d["cantidad"] if d["cantidad"] else 0, "monto": d["monto"],
                       "exento": bool(d["exento"]) or original["tipo"] in (34, 41)})
    anula = venta["estado"] == "devuelta" and devolucion["monto"] == venta["total"]
    receptor = None
    if original["tipo"] in FACTURAS and venta["cliente_id"]:
        receptor = _receptor_cliente(con.execute("SELECT * FROM clientes WHERE id = ?",
                                                 (venta["cliente_id"],)).fetchone())
    elif original["rut_receptor"] and original["rut_receptor"] != RUT_CONSUMIDOR_FINAL:
        receptor = {"rut": original["rut_receptor"], "razon_social": original["razon_receptor"]}
    folio, caf = tomar_folio(con, cfg["ambiente"], 61)
    doc = {"tipo": 61, "folio": folio, "fecha": devolucion["fecha"][:10], "emisor": emisor(cfg), "receptor": receptor,
           "lineas": lineas, "tasa_iva": tasa_iva,
           "referencias": [{"tipo": original["tipo"], "folio": original["folio"], "fecha": original["fecha"],
                            "codigo": 1 if anula else 3,
                            "razon": devolucion["motivo"] or "Devolución de mercadería"}]}
    resultado = dte.construir(doc, caf, cargar_firma(cfg, secreto))
    return _guardar_documento(con, cfg, doc, resultado, venta_id=devolucion["venta_id"], devolucion_id=devolucion_id)


ESTADOS_CORREO = {"pendiente": "XML por enviar al cliente", "enviado": "XML enviado al cliente",
                  "sin_correo": "Cliente sin correo"}
ESTADOS = {"pendiente": "Por enviar al SII", "enviado": "Enviado, esperando respuesta", "aceptado": "Aceptado por el SII",
           "reparo": "Aceptado con reparos", "rechazado": "Rechazado por el SII"}


def _entero_o_texto(valor):
    """Las referencias del set de pruebas traen «SET» donde va el tipo (o el código, en la boleta)."""
    return int(valor) if valor.isdigit() else (valor or 0)


def _impreso(xml):
    """Del documento firmado, lo que va impreso: receptor, líneas y referencias (lo mismo que recibe el SII)."""
    try:
        from lxml import etree
    except ImportError:
        return {}
    ns = {"s": NS_SII}
    doc = etree.fromstring(bytes(xml)).find("s:Documento", ns)
    if doc is None:
        return {}
    texto = lambda el, ruta: (el.findtext(ruta, namespaces=ns) or "").strip()   # noqa: E731
    numero = lambda el, ruta: float(texto(el, ruta) or 0)                       # noqa: E731
    emisor = doc.find("s:Encabezado/s:Emisor", ns)
    receptor = doc.find("s:Encabezado/s:Receptor", ns)
    return {
        "emisor": {"rut": texto(emisor, "s:RUTEmisor"),
                   "razon_social": texto(emisor, "s:RznSoc") or texto(emisor, "s:RznSocEmisor"),
                   "giro": texto(emisor, "s:GiroEmis") or texto(emisor, "s:GiroEmisor"),
                   "direccion": texto(emisor, "s:DirOrigen"), "comuna": texto(emisor, "s:CmnaOrigen"),
                   "ciudad": texto(emisor, "s:CiudadOrigen")} if emisor is not None else {},
        "receptor": {"rut": texto(receptor, "s:RUTRecep"), "razon_social": texto(receptor, "s:RznSocRecep"),
                     "giro": texto(receptor, "s:GiroRecep"), "direccion": texto(receptor, "s:DirRecep"),
                     "comuna": texto(receptor, "s:CmnaRecep"), "ciudad": texto(receptor, "s:CiudadRecep")}
        if receptor is not None else None,
        "lineas": [{"nombre": texto(d, "s:NmbItem"), "cantidad": numero(d, "s:QtyItem"),
                    "precio": numero(d, "s:PrcItem"), "monto": int(numero(d, "s:MontoItem")),
                    "exento": texto(d, "s:IndExe") == "1"} for d in doc.findall("s:Detalle", ns)],
        "descuento": sum(int(numero(d, "s:ValorDR")) for d in doc.findall("s:DscRcgGlobal", ns)
                         if texto(d, "s:TpoMov") == "D"),
        "referencias": [{"tipo": _entero_o_texto(texto(r, "s:TpoDocRef")), "folio": texto(r, "s:FolioRef"),
                         "fecha": texto(r, "s:FchRef"), "codigo": _entero_o_texto(texto(r, "s:CodRef")),
                         "razon": texto(r, "s:RazonRef")} for r in doc.findall("s:Referencia", ns)],
    }


def para_ticket(con, fila, cfg=None):
    """Lo que necesita la pantalla y el ticket de un documento: datos, estado y el timbre (PDF417)."""
    from .pdf417 import matriz

    cfg = cfg or leer(con)
    fecha_res = cfg.get("fecha_resolucion") or ""
    impreso = _impreso(fila["xml"])
    # Los datos del emisor, los del documento firmado (si después se cambia la configuración, se reimprime igual).
    emisor = {"rut": cfg.get("rut"), "razon_social": cfg.get("razon_social"), "giro": cfg.get("giro"),
              "direccion": cfg.get("direccion"), "comuna": cfg.get("comuna"), "ciudad": cfg.get("ciudad")}
    emisor |= {k: v for k, v in impreso.pop("emisor", {}).items() if v}
    return {"id": fila["id"], "tipo": fila["tipo"], "nombre": NOMBRES.get(fila["tipo"], ""), "folio": fila["folio"],
            "fecha": fila["fecha"], "ambiente": fila["ambiente"], "estado": fila["estado"],
            "estado_texto": ESTADOS.get(fila["estado"], fila["estado"]), "glosa": fila["glosa"],
            "neto": fila["neto"], "iva": fila["iva"], "exento": fila["exento"], "total": fila["total"],
            "rut_receptor": fila["rut_receptor"], "razon_receptor": fila["razon_receptor"],
            "devolucion_id": fila["devolucion_id"], "ted": fila["ted"],
            "correo": {"estado": fila["correo_estado"], "texto": ESTADOS_CORREO.get(fila["correo_estado"]),
                       "glosa": fila["correo_glosa"], "a": fila["correo_receptor"]} if fila["correo_estado"] else None,
            # El timbre para la pantalla y la impresión con el navegador: derecho en 80 mm; en 58 mm, girado y más
            # angosto (más columnas), para que sus módulos midan 0,25 mm (2 puntos de la impresora).
            "pdf417": matriz(fila["ted"].encode("iso-8859-1", "replace"), 12),
            "pdf417_58": matriz(fila["ted"].encode("iso-8859-1", "replace"), 14),
            "resolucion": {"numero": cfg.get("numero_resolucion") or "0", "anio": fecha_res[:4]},
            "emisor": emisor | {"oficina_sii": cfg.get("oficina_sii")}, **impreso}


def documentos_de_venta(con, venta_id):
    filas = con.execute("SELECT * FROM sii_documentos WHERE venta_id = ? ORDER BY id", (venta_id,)).fetchall()
    if not filas:
        return []
    cfg = leer(con)
    return [para_ticket(con, f, cfg) for f in filas]


# --- Envío al SII ----------------------------------------------------------------------------------------

def _mas(segundos):
    return (datetime.now() + timedelta(seconds=segundos)).strftime("%Y-%m-%d %H:%M:%S")


def armar_sobres(con, cfg, firma):
    """Junta los documentos pendientes en sobres firmados (boletas de a 50; facturas y notas, de a una)."""
    from . import envio

    creados = 0
    pendientes = con.execute("SELECT id, tipo, xml FROM sii_documentos WHERE ambiente = ? AND estado = 'pendiente' "
                             "AND envio_id IS NULL ORDER BY id", (cfg["ambiente"],)).fetchall()
    boletas = [d for d in pendientes if d["tipo"] in BOLETAS]
    grupos = [boletas[i:i + BOLETAS_POR_SOBRE] for i in range(0, len(boletas), BOLETAS_POR_SOBRE)]
    grupos += [[d] for d in pendientes if d["tipo"] not in BOLETAS]
    for grupo in grupos:
        xml = envio.construir([d["xml"] for d in grupo], [d["tipo"] for d in grupo], cfg["rut"], firma,
                              cfg["fecha_resolucion"], cfg.get("numero_resolucion") or 0)
        with transaccion(con):
            envio_id = con.execute("INSERT INTO sii_envios (ambiente, boletas, creado, xml) VALUES (?, ?, ?, ?)",
                                   (cfg["ambiente"], int(grupo[0]["tipo"] in BOLETAS), ahora(), xml)).lastrowid
            con.execute(f"UPDATE sii_documentos SET envio_id = ? WHERE id IN ({','.join('?' * len(grupo))}) "
                        "AND envio_id IS NULL", [envio_id] + [d["id"] for d in grupo])
        creados += 1
    return creados


def _aplicar_estado(con, envio, r):
    """Pasa a cada documento del sobre lo que respondió el SII."""
    from .conexion import RECHAZADO

    docs = con.execute("SELECT id, tipo, folio FROM sii_documentos WHERE envio_id = ?", (envio["id"],)).fetchall()
    with transaccion(con):
        if r["estado"] in RECHAZADO:
            glosa = f"El SII {RECHAZADO[r['estado']]} ({r['estado']}){': ' + r['glosa'] if r.get('glosa') else ''}"
            con.execute("UPDATE sii_envios SET estado = 'rechazado', glosa = ?, revisado = ? WHERE id = ?",
                        (glosa, ahora(), envio["id"]))
            con.execute("UPDATE sii_documentos SET estado = 'rechazado', glosa = ? WHERE envio_id = ?",
                        (glosa, envio["id"]))
            return
        detalle = {(d["tipo"], d["folio"]): d for d in r.get("detalle") or []}
        informados, rechazados, reparos = r.get("informados", 0), r.get("rechazados", 0), r.get("reparos", 0)
        for d in docs:
            propio = detalle.get((d["tipo"], d["folio"]))
            if propio:
                estado = "rechazado" if propio["estado"] in ("RCH", "RFR", "RSC") else "reparo"
                glosa = propio.get("glosa") or propio["estado"]
            elif rechazados and not detalle and rechazados >= informados:
                estado, glosa = "rechazado", r.get("glosa") or "Rechazado por el SII"
            elif (rechazados or reparos) and not detalle and len(docs) > 1:
                estado, glosa = "reparo", (f"El SII rechazó {rechazados} y objetó {reparos} de {informados} "
                                           "documentos de este envío: revísalo en sii.cl")
            elif reparos and not detalle:
                estado, glosa = "reparo", r.get("glosa") or "Aceptado con reparos"
            else:
                estado, glosa = "aceptado", None
            con.execute("UPDATE sii_documentos SET estado = ?, glosa = ? WHERE id = ?", (estado, glosa, d["id"]))
        con.execute("UPDATE sii_envios SET estado = 'procesado', glosa = ?, revisado = ? WHERE id = ?",
                    (f"{r['estado']}: {informados} informados, {r.get('aceptados', 0)} aceptados, {rechazados} "
                     f"rechazados, {reparos} con reparos", ahora(), envio["id"]))


def _aplicar_estado_libro(con, envio, r):
    """Lo que respondió el SII de un libro o de un consumo de folios (no tienen documentos propios)."""
    from .conexion import ACEPTADO, RECHAZADO

    estado = r["estado"]
    if estado in RECHAZADO:
        nuevo, glosa = "rechazado", f"El SII {RECHAZADO[estado]} ({estado})"
    else:
        nuevo, glosa = "procesado", f"{ACEPTADO.get(estado, estado).capitalize()} ({estado})"
    if r.get("glosa"):
        glosa += f": {r['glosa']}"
    with transaccion(con):
        con.execute("UPDATE sii_envios SET estado = ?, glosa = ?, revisado = ? WHERE id = ?",
                    (nuevo, glosa, ahora(), envio["id"]))


_candado_ciclo = threading.Lock()


def ciclo(ruta_db, secreto, conexion=None, correo=None):
    """Una vuelta del envío: arma sobres, sube los que faltan y consulta los ya subidos. Devuelve un resumen.

    Una vuelta a la vez (el hilo y el botón «Enviar ahora»): así un documento nunca queda en dos sobres.
    """
    with _candado_ciclo:
        return _ciclo(ruta_db, secreto, conexion, correo)


def _ciclo(ruta_db, secreto, conexion, correo):
    from .conexion import ConexionSII

    resumen = {"sobres": 0, "subidos": 0, "consultados": 0, "correos": 0, "errores": []}
    con = conectar(ruta_db)
    try:
        cfg = leer(con)
        if falta_modulo():
            return resumen
        # Con la boleta electrónica desactivada solo se mueven los envíos de la certificación.
        activo = cfg.get("activo") == "1"
        if not activo and not con.execute("SELECT 1 FROM sii_envios WHERE ambiente = ? AND etapa IS NOT NULL AND "
                                          "estado IN ('por_enviar', 'enviado')", (cfg["ambiente"],)).fetchone():
            return resumen
        firma = cargar_firma(cfg, secreto)
        if activo:
            resumen["sobres"] = armar_sobres(con, cfg, firma)
        sii = conexion or ConexionSII(cfg["ambiente"], firma, cfg["rut"])
        momento = ahora()
        for envio in con.execute("SELECT * FROM sii_envios WHERE ambiente = ? AND estado = 'por_enviar' AND "
                                 "(proximo IS NULL OR proximo <= ?) AND (? OR etapa IS NOT NULL) ORDER BY id",
                                 (cfg["ambiente"], momento, activo)).fetchall():
            try:
                trackid = sii.enviar(envio["xml"], bool(envio["boletas"]), envio["clase"])
            except ErrorSII as e:
                definitivo = getattr(e, "definitivo", False)
                espera = REINTENTOS[min(envio["intentos"], len(REINTENTOS) - 1)]
                with transaccion(con):
                    con.execute("UPDATE sii_envios SET estado = ?, glosa = ?, intentos = intentos + 1, proximo = ? "
                                "WHERE id = ?", ("rechazado" if definitivo else "por_enviar", str(e), _mas(espera),
                                                 envio["id"]))
                    if definitivo:
                        con.execute("UPDATE sii_documentos SET estado = 'rechazado', glosa = ? WHERE envio_id = ?",
                                    (str(e), envio["id"]))
                resumen["errores"].append(str(e))
                if not definitivo:
                    break           # sin conexión o el SII caído: se reintenta en la próxima vuelta
                continue
            with transaccion(con):
                con.execute("UPDATE sii_envios SET estado = 'enviado', trackid = ?, glosa = NULL, intentos = 0, "
                            "proximo = ? WHERE id = ?", (trackid, _mas(ESPERA_CONSULTA), envio["id"]))
                con.execute("UPDATE sii_documentos SET estado = 'enviado', glosa = NULL WHERE envio_id = ?",
                            (envio["id"],))
            resumen["subidos"] += 1
        for envio in con.execute("SELECT * FROM sii_envios WHERE ambiente = ? AND estado = 'enviado' AND "
                                 "(proximo IS NULL OR proximo <= ?) AND (? OR etapa IS NOT NULL) ORDER BY id",
                                 (cfg["ambiente"], momento, activo)).fetchall():
            try:
                r = sii.estado(envio["trackid"], bool(envio["boletas"]), envio["clase"])
            except ErrorSII as e:
                resumen["errores"].append(str(e))
                break
            resumen["consultados"] += 1
            if r.get("final") and envio["clase"] != "documentos":
                _aplicar_estado_libro(con, envio, r)
            elif r.get("final"):
                _aplicar_estado(con, envio, r)
            else:
                espera = REINTENTOS[min(envio["intentos"], len(REINTENTOS) - 1)]
                with transaccion(con):
                    con.execute("UPDATE sii_envios SET intentos = intentos + 1, proximo = ?, glosa = ? WHERE id = ?",
                                (_mas(espera), f"En proceso en el SII ({r['estado']})", envio["id"]))
        if activo and correo_configurado(cfg):
            try:
                resumen["correos"] = enviar_correos(con, cfg, firma, secreto, correo)
            except ErrorSII as e:
                resumen["errores"].append(str(e))
    finally:
        con.close()
    return resumen


# --- Intercambio: el XML de la factura al cliente, por correo -----------------------------------------------

ESPERA_CORREO = 600          # tras un error del servidor de correo, se vuelve a intentar 10 minutos después
_correo_espera_hasta = [0.0]


def correo_configurado(cfg):
    return bool(cfg.get("correo_servidor") and (cfg.get("correo_remitente") or cfg.get("correo_usuario")))


def _clave_correo(cfg, secreto):
    if not cfg.get("correo_clave"):
        return ""
    try:
        return _cifrador(secreto).decrypt(cfg["correo_clave"].encode()).decode()
    except Exception:  # noqa: BLE001 (otra clave de Neji, como con la firma)
        raise ErrorSII("No se puede leer la contraseña guardada del correo: vuelve a escribirla en Configuración "
                       "→ Boleta electrónica.") from None


def transporte_correo(cfg, secreto):
    """Función que manda un correo (EmailMessage) con la cuenta configurada (SMTP con STARTTLS, o SSL en 465)."""
    import smtplib
    import ssl

    servidor, puerto = cfg["correo_servidor"], int(cfg.get("correo_puerto") or 587)
    usuario, clave = cfg.get("correo_usuario") or "", _clave_correo(cfg, secreto)

    def enviar(mensaje):
        contexto = ssl.create_default_context()
        try:
            if puerto == 465:
                cliente = smtplib.SMTP_SSL(servidor, puerto, timeout=30, context=contexto)
            else:
                cliente = smtplib.SMTP(servidor, puerto, timeout=30)
            with cliente:
                if puerto != 465:
                    cliente.ehlo()
                    if cliente.has_extn("starttls"):
                        cliente.starttls(context=contexto)
                        cliente.ehlo()
                if usuario:
                    cliente.login(usuario, clave)
                cliente.send_message(mensaje)
        except smtplib.SMTPAuthenticationError:
            raise ErrorSII("El servidor de correo no aceptó el usuario o la contraseña (en Gmail se usa una "
                           "«contraseña de aplicación»).") from None
        except (smtplib.SMTPException, OSError) as e:
            raise ErrorSII(f"No se pudo mandar el correo ({type(e).__name__}: {e}).") from None
    return enviar


def _mensaje(cfg, de, para, asunto, cuerpo, adjunto=None, nombre_adjunto=None):
    from email.message import EmailMessage
    from email.utils import formataddr, make_msgid

    mensaje = EmailMessage()
    mensaje["From"] = formataddr((cfg.get("razon_social") or "", de))
    mensaje["To"] = para
    mensaje["Subject"] = asunto
    mensaje["Message-ID"] = make_msgid(domain=de.split("@")[-1])
    mensaje.set_content(cuerpo)
    if adjunto is not None:
        mensaje.add_attachment(adjunto, maintype="application", subtype="xml", filename=nombre_adjunto)
    return mensaje


def enviar_correos(con, cfg, firma, secreto, transporte=None):
    """Manda a cada cliente el XML de sus facturas (y notas de crédito) ya aceptadas por el SII. Devuelve cuántas."""
    from . import envio

    if time.time() < _correo_espera_hasta[0] and transporte is None:
        return 0
    pendientes = con.execute(
        "SELECT * FROM sii_documentos WHERE ambiente = ? AND correo_estado = 'pendiente' "
        "AND estado IN ('aceptado', 'reparo') ORDER BY id", (cfg["ambiente"],)).fetchall()
    if not pendientes:
        return 0
    enviar = transporte or transporte_correo(cfg, secreto)
    de = cfg.get("correo_remitente") or cfg.get("correo_usuario")
    enviados = 0
    for d in pendientes:
        nombre = NOMBRES.get(d["tipo"], "Documento").capitalize()
        sobre = envio.construir([d["xml"]], [d["tipo"]], cfg["rut"], firma, cfg["fecha_resolucion"],
                                cfg.get("numero_resolucion") or 0, rut_receptor=d["rut_receptor"])
        total = f"{d['total']:,}".replace(",", ".")
        cuerpo = (f"Estimado cliente:\n\nAdjuntamos el documento tributario electrónico {nombre} N° {d['folio']}, "
                  f"emitido por {cfg.get('razon_social')} (RUT {cfg['rut']}) el {d['fecha']}, por un total de "
                  f"${total}.\n\nEste correo se envía automáticamente.\n")
        mensaje = _mensaje(cfg, de, d["correo_receptor"], f"DTE {cfg['rut']} - {nombre} N° {d['folio']}", cuerpo,
                           sobre, f"DTE_{cfg['rut']}_T{d['tipo']}_F{d['folio']}.xml")
        try:
            enviar(mensaje)
        except ErrorSII as e:
            _correo_espera_hasta[0] = time.time() + ESPERA_CORREO
            with transaccion(con):
                con.execute("UPDATE sii_documentos SET correo_glosa = ? WHERE id = ?", (str(e), d["id"]))
            raise
        with transaccion(con):
            con.execute("UPDATE sii_documentos SET correo_estado = 'enviado', correo_glosa = NULL, "
                        "correo_enviado = ? WHERE id = ?", (ahora(), d["id"]))
        enviados += 1
    return enviados


def probar_correo(cfg, secreto, para=None, transporte=None):
    """Manda un correo de prueba (a la misma cuenta, si no se dice otra) con la configuración guardada."""
    if not correo_configurado(cfg):
        raise ErrorSII("Falta el servidor y la cuenta de correo.")
    de = cfg.get("correo_remitente") or cfg.get("correo_usuario")
    para = para or de
    (transporte or transporte_correo(cfg, secreto))(_mensaje(
        cfg, de, para, "Prueba de correo de Neji POS",
        "Este es un correo de prueba de Neji POS: la cuenta sirve para mandar las facturas electrónicas a tus "
        "clientes.\n"))
    _correo_espera_hasta[0] = 0.0
    return para


def resumen_envios(con, ambiente):
    contar = dict(con.execute("SELECT estado, COUNT(*) FROM sii_documentos WHERE ambiente = ? GROUP BY estado",
                              (ambiente,)).fetchall())
    ultimo_error = con.execute("SELECT glosa, revisado, creado FROM sii_envios WHERE ambiente = ? AND glosa IS NOT NULL "
                               "AND estado = 'por_enviar' ORDER BY id DESC LIMIT 1", (ambiente,)).fetchone()
    correos = con.execute("SELECT COUNT(*), MAX(correo_glosa) FROM sii_documentos WHERE ambiente = ? "
                          "AND correo_estado = 'pendiente'", (ambiente,)).fetchone()
    return {"documentos": contar, "error": ultimo_error["glosa"] if ultimo_error else None,
            "correos_pendientes": correos[0], "error_correo": correos[1]}


def reenviar_correo(con, documento_id, correo=None):
    """Vuelve a dejar por enviar el XML de una factura a su cliente (a otro correo, si se indica)."""
    from .textos import correo_valido

    d = con.execute("SELECT * FROM sii_documentos WHERE id = ?", (documento_id,)).fetchone()
    if d is None:
        raise ErrorSII("Documento no encontrado.")
    if d["tipo"] in BOLETAS or d["rut_receptor"] == RUT_CONSUMIDOR_FINAL:
        raise ErrorSII("Solo las facturas (y sus notas de crédito) se mandan al cliente por correo.")
    correo = (correo or d["correo_receptor"] or "").strip()
    if not correo_valido(correo):
        raise ErrorSII("Escribe un correo válido.")
    con.execute("UPDATE sii_documentos SET correo_receptor = ?, correo_estado = 'pendiente', correo_glosa = NULL "
                "WHERE id = ?", (correo, documento_id))


class Enviador:
    """Hilo que manda al SII lo emitido, cada minuto (o al tiro, si se le avisa)."""

    def __init__(self, ruta_db, secreto, cada=60):
        self.ruta_db, self.secreto, self.cada = ruta_db, secreto, cada
        self._despertar = threading.Event()
        self._hilo = None
        self.ultimo = None

    def iniciar(self):
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._vigilar, name="sii-envio", daemon=True)
            self._hilo.start()
        return self

    def avisar(self):
        self._despertar.set()

    def _vigilar(self):
        time.sleep(5)
        while True:
            try:
                self.ultimo = ciclo(self.ruta_db, self.secreto)
            except ErrorSII as e:
                self.ultimo = {"errores": [str(e)]}
            except Exception:  # noqa: BLE001 (que el hilo no muera)
                registro.exception("Error en el envío al SII")
            self._despertar.wait(self.cada)
            self._despertar.clear()
