"""La certificación del SII hecha desde Neji, en el ambiente de certificación.

Etapas (sii.cl → Factura electrónica → Sistema de certificación → «Revisar avance»):

1. Set de pruebas: el SII entrega un texto con los casos (set básico de facturas, notas de crédito y débito; set
   de factura exenta si se postula a ella; y los sets de los libros). Neji emite cada caso y los envía al SII en un
   sobre por set; después se envían los libros de ventas y de compras.
2. Simulación: un envío con documentos como los de la operación real (aquí, con productos del inventario y los
   mismos cálculos que usa Neji al vender: precios con IVA).
3. Intercambio: el SII manda un EnvioDTE al correo de intercambio; Neji arma las tres respuestas (intercambio.py).
4. Muestras impresas: un PDF por documento, con el timbre (muestras.py).
5. Boleta electrónica: su propio set de pruebas («CASO-1»...), enviado con su reporte de consumo de folios.

Los documentos quedan en sii_documentos (con su caso) y los sobres en sii_envios (con su etapa); el hilo de envío
de siempre los sube al SII y consulta su estado, también con la boleta electrónica desactivada.
"""

import copy
import json
from collections import Counter
from datetime import date
from decimal import Decimal

from ..chile import redondear
from ..db import ahora, sin_acentos, transaccion
from . import BOLETAS, NOMBRES, NOTAS, RUT_SII, ErrorSII
from .set_pruebas import codigo_referencia, leer_set, leer_set_boletas

ETAPAS = {
    "basico": "Set básico", "exenta": "Set factura exenta", "simulacion": "Simulación",
    "libro_ventas": "Libro de ventas", "libro_compras": "Libro de compras",
    "libro_compras_exentos": "Libro de compras (exentos)", "boletas": "Set de boletas",
    "rcof": "Consumo de folios (boletas)",
}
SETS_DE_DOCUMENTOS = ("basico", "exenta")
PRIORIDAD = {33: 0, 34: 0, 61: 1, 56: 2}
MOTIVOS = {1: "ANULA DOCUMENTO", 2: "CORRIGE TEXTO", 3: "CORRIGE MONTOS"}
RECEPTOR_SII = {"rut": RUT_SII, "razon_social": "SERVICIO DE IMPUESTOS INTERNOS", "giro": "ADMINISTRACION PUBLICA",
                "direccion": "TEATINOS 120", "comuna": "SANTIAGO", "ciudad": "SANTIAGO"}
# Para la simulación, si el inventario está vacío.
PRODUCTOS_EJEMPLO = [("PARACETAMOL 500 MG X 16 COMPRIMIDOS", 1290), ("IBUPROFENO 400 MG X 20 COMPRIMIDOS", 2490),
                     ("LORATADINA 10 MG X 30 COMPRIMIDOS", 3990), ("OMEPRAZOL 20 MG X 30 CAPSULAS", 2990),
                     ("ALCOHOL GEL 500 ML", 2590), ("VITAMINA C 1 G X 10 EFERVESCENTES", 3490),
                     ("SUERO FISIOLOGICO 20 X 5 ML", 2190), ("MASCARILLAS DESECHABLES X 50", 4990)]


# --- Preparación -------------------------------------------------------------------------------------------

def preparar(con, secreto):
    """La configuración y la firma, revisando que esté lo necesario para certificar."""
    from .servicio import actecos, cargar_firma, leer

    cfg = leer(con)
    if cfg.get("ambiente") != "certificacion":
        raise ErrorSII("La certificación se hace en el ambiente de certificación: cámbialo arriba, en el estado de la "
                       "boleta electrónica.")
    faltan = [nombre for clave, nombre in (("rut", "el RUT de la empresa"), ("razon_social", "la razón social"),
                                           ("giro", "el giro"), ("direccion", "la dirección"), ("comuna", "la comuna"),
                                           ("fecha_resolucion", "la fecha de resolución")) if not cfg.get(clave)]
    if not actecos(cfg):
        faltan.append("la actividad económica (Acteco)")
    if not cfg.get("firma_pfx"):
        faltan.append("la firma electrónica")
    if faltan:
        raise ErrorSII("Para certificar falta: " + "; ".join(faltan) + ".")
    firma = cargar_firma(cfg, secreto)
    firma.exigir_vigente()
    return cfg, firma


def receptor(cfg):
    """El receptor de los documentos del set y la simulación (por omisión, el SII)."""
    try:
        guardado = json.loads(cfg.get("cert_receptor") or "null")
    except ValueError:
        guardado = None
    return guardado if isinstance(guardado, dict) and guardado.get("rut") else dict(RECEPTOR_SII)


def guardar_receptor(con, datos):
    from ..chile import limpiar_rut, validar_rut
    from .servicio import _poner
    from .textos import texto_sii

    rut = limpiar_rut(datos.get("rut"))
    if not rut or not validar_rut(rut):
        raise ErrorSII("El RUT del receptor no es válido.")
    nuevo = {"rut": rut}
    for campo, largo, nombre in (("razon_social", 100, "la razón social"), ("giro", 40, "el giro"),
                                 ("direccion", 70, "la dirección"), ("comuna", 20, "la comuna"),
                                 ("ciudad", 20, None)):
        nuevo[campo] = texto_sii(datos.get(campo), largo)
        if nombre and not nuevo[campo]:
            raise ErrorSII(f"Falta {nombre} del receptor.")
    _poner(con, "cert_receptor", json.dumps(nuevo, ensure_ascii=False))
    return nuevo


# --- Documentos del set ------------------------------------------------------------------------------------

def _clave(nombre):
    return " ".join(sin_acentos(nombre or "").upper().split())


def _linea(nombre, cantidad, precio, exento, descuento_pct=None, unidad=None):
    """Línea con precio neto (como los da el set): monto = cantidad × precio - descuento, al peso."""
    cantidad, precio = Decimal(str(cantidad)), Decimal(str(precio or 0))
    bruto = redondear(cantidad * precio)
    pct = Decimal(str(descuento_pct)) if descuento_pct else None
    descuento = redondear(Decimal(bruto) * pct / 100) if pct else 0
    return {"nombre": nombre, "cantidad": cantidad, "precio": precio, "unidad": unidad, "exento": bool(exento),
            "descuento_pct": pct, "descuento": descuento, "monto": bruto - descuento}


def _texto(razon, exento, datos_receptor=None):
    """La línea de una nota que corrige un texto (giro, dirección): sin cantidad ni precio y monto cero. El manual de
    muestras impresas del SII pide que el detalle diga «donde dice... debe decir...»."""
    datos_receptor = datos_receptor or {}
    clave = _clave(razon)
    for palabra, campo, nombre in (("GIRO", "giro", "GIRO"), ("DIRECCION", "direccion", "DIRECCION"),
                                   ("RAZON", "razon_social", "RAZON SOCIAL"), ("COMUNA", "comuna", "COMUNA")):
        if palabra in clave and datos_receptor.get(campo):
            correccion = f"DONDE DICE: {nombre} ERRONEO(A) DEBE DECIR: {datos_receptor[campo]}"
            break
    else:
        correccion = "DONDE DICE: TEXTO ERRONEO DEBE DECIR: TEXTO CORREGIDO"
    return {"nombre": razon, "descripcion": correccion, "solo_texto": True, "cantidad": 0, "precio": 0, "monto": 0,
            "exento": exento}


def _lineas_factura(caso, exenta):
    if not caso["items"]:
        raise ErrorSII(f"El caso {caso['id']} no trae ítems.")
    return [_linea(i["nombre"], i["cantidad"] if i["cantidad"] is not None else 1, i["precio"],
                   exenta or "EXENT" in _clave(i["nombre"]), i["descuento_pct"], i["unidad"]) for i in caso["items"]]


def _lineas_nota(caso, base, codigo, exenta, datos_receptor=None):
    """Las líneas de una nota de crédito o débito según lo que hace (CodRef) y el documento que corrige.

    1 anula: las mismas líneas (y el mismo descuento global). 2 corrige un texto: una línea con el motivo y monto
    cero. 3 corrige montos: en una devolución, las cantidades del caso con los precios y descuentos del documento;
    si modifica el monto, el precio del caso con las cantidades del documento.
    """
    razon = caso["razon"] or MOTIVOS[codigo]
    todo_exento = exenta or all(l["exento"] for l in base["lineas"])
    solo_texto = all(l.get("solo_texto") for l in base["lineas"])
    if codigo == 2:
        return [_texto(razon, todo_exento, datos_receptor)], 0
    if codigo == 1 and solo_texto:
        return [{"nombre": razon, "solo_texto": True, "cantidad": 0, "precio": 0, "monto": 0,
                 "exento": todo_exento}], 0
    if codigo == 1 or not caso["items"]:
        return copy.deepcopy(base["lineas"]), base.get("descuento_pct") or 0
    originales = {_clave(l["nombre"]): l for l in base["lineas"] if not l.get("solo_texto")}
    modifica_monto = "MONTO" in _clave(razon) and "DEVOLU" not in _clave(razon)
    lineas = []
    for item in caso["items"]:
        original = originales.get(_clave(item["nombre"]))
        exento = original["exento"] if original else (exenta or "EXENT" in _clave(item["nombre"]))
        unidad = item["unidad"] or (original or {}).get("unidad")
        if modifica_monto:
            cantidad = item["cantidad"] if item["cantidad"] is not None else (original or {}).get("cantidad") or 1
            precio = item["precio"] if item["precio"] is not None else (original or {}).get("precio") or 0
            lineas.append(_linea(item["nombre"], cantidad, precio, exento, unidad=unidad))
        else:
            cantidad = item["cantidad"] if item["cantidad"] is not None else (original or {}).get("cantidad") or 1
            precio = item["precio"] if item["precio"] is not None else (original or {}).get("precio") or 0
            pct = (original or {}).get("descuento_pct") if original else item["descuento_pct"]
            lineas.append(_linea(item["nombre"], cantidad, precio, exento, pct, unidad))
    return lineas, (0 if modifica_monto else base.get("descuento_pct") or 0)


def _orden(casos):
    """Los casos en el orden en que se emiten: facturas, notas de crédito, notas de débito (y por número)."""
    return sorted(casos, key=lambda c: (PRIORIDAD.get(c["tipo_dte"], 9), c["numero"]))


def _revisar_folios(con, cfg, necesarios):
    """Antes de emitir nada: que alcancen los folios de cada tipo (así no queda un set enviado y otro no)."""
    from .servicio import folios

    disponibles = Counter()
    for f in folios(con, cfg["ambiente"]):
        disponibles[f["tipo"]] += f["disponibles"]
    faltan = [f"{NOMBRES.get(t, t).lower()} ({t}): se necesitan {n} y quedan {disponibles[t]}"
              for t, n in sorted(necesarios.items(), key=lambda x: str(x[0])) if t is not None and disponibles[t] < n]
    if faltan:
        raise ErrorSII("Faltan folios de certificación: " + "; ".join(faltan) + ". Pídelos en sii.cl (ambiente de "
                       "certificación) y cárgalos en la pestaña «Boleta electrónica».")


def emitir_set(con, cfg, firma, set_, datos_receptor, fecha=None):
    """Emite los documentos de un set (básico o exenta) y deja listo su sobre. Devuelve el id del envío."""
    from . import dte
    from .servicio import _guardar_documento, emisor, tomar_folio

    if set_["tipo"] not in SETS_DE_DOCUMENTOS:
        raise ErrorSII(f"Neji no emite los documentos del set «{set_['nombre']}».")
    sin_soporte = [f"{c['id']} ({c['documento'] or 'sin documento'})" for c in set_["casos"] if c["tipo_dte"] is None]
    if sin_soporte:
        raise ErrorSII(f"Neji no emite los documentos de estos casos del set «{set_['nombre']}»: "
                       + ", ".join(sin_soporte) + ".")
    if not set_["casos"]:
        raise ErrorSII(f"El set «{set_['nombre']}» no trae casos.")
    fecha = fecha or date.today().isoformat()
    exenta = set_["tipo"] == "exenta"
    ids_casos = {c["id"] for c in set_["casos"]}
    hechos, documentos = {}, []
    pendientes = _orden(set_["casos"])
    with transaccion(con):
        while pendientes:
            avance = False
            for caso in list(pendientes):
                base = None
                if caso["tipo_dte"] in NOTAS:
                    ref = caso["referencia_caso"]
                    if not ref or ref not in ids_casos:
                        raise ErrorSII(f"El caso {caso['id']} no dice a qué caso del set corresponde.")
                    if ref not in hechos:
                        continue
                    base = hechos[ref]
                if base is None:
                    lineas, pct, codigo, razon = _lineas_factura(caso, exenta), caso["descuento_pct"] or 0, None, None
                else:
                    codigo = codigo_referencia(caso["razon"])
                    razon = caso["razon"] or MOTIVOS[codigo]
                    lineas, pct = _lineas_nota(caso, base, codigo, exenta, datos_receptor)
                folio, caf = tomar_folio(con, cfg["ambiente"], caso["tipo_dte"])
                referencias = [{"tipo": "SET", "folio": folio, "fecha": fecha, "razon": f"CASO {caso['id']}"}]
                if base is not None:
                    referencias.append({"tipo": base["tipo"], "folio": base["folio"], "fecha": base["fecha"],
                                        "codigo": codigo, "razon": razon})
                doc = {"tipo": caso["tipo_dte"], "folio": folio, "fecha": fecha, "emisor": emisor(cfg),
                       "receptor": dict(datos_receptor), "lineas": lineas, "netos": True, "descuento_pct": pct,
                       "glosa_descuento": "DESCUENTO GLOBAL ITEMES AFECTOS" if pct else None,
                       "referencias": referencias}
                resultado = dte.construir(doc, caf, firma)
                doc_id = _guardar_documento(con, cfg, doc, resultado)
                con.execute("UPDATE sii_documentos SET caso = ?, correo_receptor = NULL, correo_estado = NULL, "
                            "correo_glosa = NULL WHERE id = ?", (caso["id"], doc_id))
                hechos[caso["id"]] = doc
                documentos.append(doc_id)
                pendientes.remove(caso)
                avance = True
            if not avance:
                raise ErrorSII("Los casos del set se referencian en círculo: no se pueden emitir.")
        return _crear_envio(con, cfg, firma, documentos, set_["tipo"],
                            {"set": set_["nombre"], "numero_atencion": set_["numero_atencion"]})


def _crear_envio(con, cfg, firma, documentos, etapa, detalle):
    """El sobre (EnvioDTE o EnvioBOLETA) con esos documentos, listo para que el hilo lo suba."""
    from . import envio

    marcas = ",".join("?" * len(documentos))
    filas = con.execute(f"SELECT id, tipo, xml FROM sii_documentos WHERE id IN ({marcas}) ORDER BY id",
                        documentos).fetchall()
    xml = envio.construir([f["xml"] for f in filas], [f["tipo"] for f in filas], cfg["rut"], firma,
                          cfg["fecha_resolucion"], cfg.get("numero_resolucion") or 0)
    envio_id = con.execute(
        "INSERT INTO sii_envios (ambiente, boletas, creado, xml, clase, etapa, detalle) "
        "VALUES (?, ?, ?, ?, 'documentos', ?, ?)",
        (cfg["ambiente"], int(filas[0]["tipo"] in BOLETAS), ahora(), xml, etapa,
         json.dumps(detalle, ensure_ascii=False))).lastrowid
    con.execute(f"UPDATE sii_documentos SET envio_id = ? WHERE id IN ({marcas})", [envio_id] + list(documentos))
    return envio_id


def emitir_sets(con, secreto, texto, datos_receptor=None, fecha=None):
    """Lee el texto del set de pruebas, emite los sets de documentos y guarda el texto (para los libros).

    Devuelve [{etapa, nombre, envio_id, documentos}]."""
    from .servicio import _poner

    cfg, firma = preparar(con, secreto)
    sets = leer_set(texto)
    de_documentos = [s for s in sets if s["tipo"] in SETS_DE_DOCUMENTOS]
    otros = [s["nombre"] for s in sets if s["tipo"] not in SETS_DE_DOCUMENTOS and not s["tipo"].startswith("libro")]
    if otros:
        raise ErrorSII("El texto trae sets de documentos que Neji no emite (" + ", ".join(otros) + "). Postula solo "
                       "a factura, factura exenta, nota de crédito y nota de débito electrónicas.")
    if not de_documentos:
        raise ErrorSII("El texto no trae el SET BASICO (ni el de factura exenta).")
    _revisar_folios(con, cfg, Counter(c["tipo_dte"] for s in de_documentos for c in s["casos"]))
    with transaccion(con):
        _poner(con, "cert_set", texto)
    resultado = []
    for set_ in de_documentos:
        envio_id = emitir_set(con, cfg, firma, set_, datos_receptor or receptor(cfg), fecha)
        resultado.append({"etapa": set_["tipo"], "nombre": set_["nombre"], "envio_id": envio_id,
                          "documentos": len(set_["casos"])})
    return resultado


# --- Libros ------------------------------------------------------------------------------------------------

def ultimo_envio(con, etapa, ambiente="certificacion"):
    return con.execute("SELECT * FROM sii_envios WHERE ambiente = ? AND etapa = ? ORDER BY id DESC LIMIT 1",
                       (ambiente, etapa)).fetchone()


def periodo_sugerido(con):
    """El mes de los documentos del último set básico (el SII espera el período de esos documentos)."""
    envio = ultimo_envio(con, "basico")
    if envio is not None:
        fila = con.execute("SELECT MIN(fecha) FROM sii_documentos WHERE envio_id = ?", (envio["id"],)).fetchone()
        if fila[0]:
            return fila[0][:7]
    return date.today().isoformat()[:7]


def emitir_libros(con, secreto, periodo=None, tipo_envio="TOTAL", tipo_libro="MENSUAL", folio_notificacion=None,
                  cuales=("ventas", "compras"), texto=None):
    """Arma y deja listos para enviar los libros del set: ventas (con el último set básico) y compras (con el
    texto del set). Devuelve [{etapa, envio_id, documentos}]."""
    import re

    from . import libros
    from .servicio import _poner

    cfg, firma = preparar(con, secreto)
    periodo = periodo or periodo_sugerido(con)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", periodo or ""):
        raise ErrorSII("El período del libro es año y mes (AAAA-MM).")
    if texto:
        with transaccion(con):
            _poner(con, "cert_set", texto)
    texto = texto or cfg.get("cert_set")
    comunes = {"rut_emisor": cfg["rut"], "firma": firma, "periodo": periodo,
               "fecha_resolucion": cfg["fecha_resolucion"], "numero_resolucion": cfg.get("numero_resolucion") or 0,
               "tipo_envio": tipo_envio, "tipo_libro": tipo_libro, "folio_notificacion": folio_notificacion}
    preparados = []
    if "ventas" in cuales:
        envio = ultimo_envio(con, "basico")
        if envio is None:
            raise ErrorSII("Primero emite el set básico: el libro de ventas lleva sus documentos.")
        envios = [envio["id"]]
        # Si las instrucciones del set del libro de ventas mencionan la factura exenta, va también ese set.
        instrucciones = " ".join(" ".join(s["instrucciones"]) for s in (leer_set(texto) if texto else [])
                                 if s["tipo"] == "libro_ventas").upper()
        exenta = ultimo_envio(con, "exenta")
        if exenta is not None and "EXENT" in instrucciones:
            envios.append(exenta["id"])
        documentos = con.execute(f"SELECT * FROM sii_documentos WHERE envio_id IN ({','.join('?' * len(envios))}) "
                                 "ORDER BY tipo, folio", envios).fetchall()
        detalle = libros.detalle_ventas(documentos, periodo)
        xml = libros.construir("VENTA", detalle, **comunes)
        preparados.append(("libro_ventas", xml, len(detalle), None))
    if "compras" in cuales:
        if not texto:
            raise ErrorSII("Falta el texto del set de pruebas (trae el set del libro de compras).")
        sets = [s for s in leer_set(texto) if s["tipo"] in ("libro_compras", "libro_compras_exentos")]
        if not sets:
            raise ErrorSII("El texto del set de pruebas no trae el «SET LIBRO DE COMPRAS».")
        for set_ in sets:
            if not set_["libro"]:
                raise ErrorSII(f"No se encontraron los documentos del «SET {set_['nombre']}».")
            exentos = set_["tipo"] == "libro_compras_exentos"
            fecha = f"{periodo}-15" if periodo != date.today().isoformat()[:7] else date.today().isoformat()
            detalle = libros.detalle_compras(set_["libro"], periodo, fecha, exentos=exentos)
            xml = libros.construir("COMPRA", detalle, factor=set_["factor"], **comunes)
            preparados.append((set_["tipo"], xml, len(detalle), set_["numero_atencion"]))
    resultado = []
    with transaccion(con):
        for etapa, xml, cantidad, numero in preparados:
            detalle = {"periodo": periodo, "tipo_envio": tipo_envio, "tipo_libro": tipo_libro,
                       "documentos": cantidad, "numero_atencion": numero}
            envio_id = con.execute(
                "INSERT INTO sii_envios (ambiente, boletas, creado, xml, clase, etapa, detalle) "
                "VALUES (?, 0, ?, ?, 'libro', ?, ?)",
                (cfg["ambiente"], ahora(), xml, etapa, json.dumps(detalle, ensure_ascii=False))).lastrowid
            resultado.append({"etapa": etapa, "envio_id": envio_id, "documentos": cantidad})
    return resultado


# --- Simulación ----------------------------------------------------------------------------------------------

def _productos(con, cuantos=12):
    filas = con.execute("SELECT descripcion, precio_venta, exento FROM productos WHERE activo = 1 AND precio_venta > 0 "
                        "ORDER BY id LIMIT ?", (cuantos,)).fetchall()
    productos = [(f["descripcion"], int(f["precio_venta"]), bool(f["exento"])) for f in filas if not f["exento"]]
    if len(productos) < 4:
        productos += [(n, p, False) for n, p in PRODUCTOS_EJEMPLO][: 8 - len(productos)]
    return productos


def _con_iva(nombre, cantidad, precio, exento=False):
    """Línea como las de una venta de Neji: precio con IVA, monto = cantidad × precio."""
    return {"nombre": nombre, "cantidad": Decimal(cantidad), "precio": Decimal(precio), "exento": exento,
            "monto": redondear(Decimal(cantidad) * Decimal(precio))}


def emitir_simulacion(con, secreto, datos_receptor=None, fecha=None):
    """Diez documentos como los de la operación real (seis facturas, tres notas de crédito y una de débito; y una
    factura exenta si hay folios de ella), en un solo envío. Devuelve {envio_id, documentos}."""
    from . import dte
    from .servicio import _guardar_documento, emisor, tomar_folio

    cfg, firma = preparar(con, secreto)
    fecha = fecha or date.today().isoformat()
    destinatario = dict(datos_receptor or receptor(cfg))
    p = _productos(con)
    m = len(p)
    facturas = [
        [(p[0], 2), (p[1 % m], 1), (p[2 % m], 3)],
        [(p[3 % m], 1), (p[4 % m], 2)],
        [(p[5 % m], 5)],
        [(p[6 % m], 1), (p[7 % m], 2), (p[0], 1), (p[2 % m], 1)],
        [(p[1 % m], 4), (p[3 % m], 1)],
        [(p[4 % m], 1), (p[5 % m], 1), (p[6 % m], 2)],
    ]
    plan = [{"tipo": 33, "lineas": [_con_iva(prod[0], cant, prod[1]) for prod, cant in items]} for items in facturas]
    plan[3]["descuento_pct"] = 10            # una con descuento global (en pesos, como en el punto de venta)
    plan += [
        {"tipo": 61, "base": 0, "codigo": 3, "razon": "DEVOLUCION DE MERCADERIA"},
        {"tipo": 61, "base": 1, "codigo": 1, "razon": "ANULA FACTURA"},
        {"tipo": 61, "base": 2, "codigo": 2, "razon": "CORRIGE DIRECCION DEL RECEPTOR"},
        {"tipo": 56, "base": 7, "codigo": 1, "razon": "ANULA NOTA DE CREDITO"},
    ]
    if con.execute("SELECT 1 FROM sii_caf WHERE ambiente = ? AND tipo = 34", (cfg["ambiente"],)).fetchone():
        plan.append({"tipo": 34, "lineas": [_con_iva("SERVICIO DE TOMA DE PRESION ARTERIAL", 1, 2000, True),
                                            _con_iva("SERVICIO DE INYECCION", 2, 1500, True)]})
    _revisar_folios(con, cfg, Counter(p["tipo"] for p in plan))
    emitidos, ids = [], []
    with transaccion(con):
        for paso in plan:
            folio, caf = tomar_folio(con, cfg["ambiente"], paso["tipo"])
            doc = {"tipo": paso["tipo"], "folio": folio, "fecha": fecha, "emisor": emisor(cfg),
                   "receptor": dict(destinatario), "credito": False}
            if "base" in paso:
                base = emitidos[paso["base"]]
                if paso["codigo"] == 2:
                    doc["lineas"] = [_texto(paso["razon"], False, destinatario)]
                elif paso["codigo"] == 1:
                    doc["lineas"] = copy.deepcopy(base["lineas"])
                    doc["descuento_afecto"] = base.get("descuento_afecto", 0)
                else:
                    primera = base["lineas"][0]
                    doc["lineas"] = [_con_iva(primera["nombre"], 1, primera["precio"], primera["exento"])]
                doc["referencias"] = [{"tipo": base["tipo"], "folio": base["folio"], "fecha": base["fecha"],
                                       "codigo": paso["codigo"], "razon": paso["razon"]}]
            else:
                doc["lineas"] = paso["lineas"]
                if paso.get("descuento_pct"):
                    afecto = sum(l["monto"] for l in doc["lineas"] if not l["exento"])
                    doc["descuento_afecto"] = redondear(Decimal(afecto) * paso["descuento_pct"] / 100)
                    doc["glosa_descuento"] = f"DESCUENTO {paso['descuento_pct']}%"
            resultado = dte.construir(doc, caf, firma)
            doc_id = _guardar_documento(con, cfg, doc, resultado)
            con.execute("UPDATE sii_documentos SET caso = 'SIMULACION', correo_receptor = NULL, correo_estado = NULL, "
                        "correo_glosa = NULL WHERE id = ?", (doc_id,))
            emitidos.append(doc)
            ids.append(doc_id)
        envio_id = _crear_envio(con, cfg, firma, ids, "simulacion", {"documentos": len(ids)})
    return {"envio_id": envio_id, "documentos": len(ids)}


# --- Boletas -------------------------------------------------------------------------------------------------

def emitir_boletas(con, secreto, texto, fecha=None):
    """Emite las boletas del set de pruebas de boletas y deja listos su envío y el reporte de consumo de folios.

    Las referencias van como pide el SII en la certificación: código «SET» y razón «CASO-n». Los precios del set
    son con IVA (precio al público). Devuelve {envio_id, rcof_id, documentos}."""
    from . import dte, rcof
    from .servicio import _guardar_documento, _poner, emisor, tomar_folio

    cfg, firma = preparar(con, secreto)
    casos = leer_set_boletas(texto)
    fecha = fecha or date.today().isoformat()
    _revisar_folios(con, cfg, Counter(41 if c["items"] and all(i["exento"] for i in c["items"]) else 39
                                      for c in casos))
    ids = []
    with transaccion(con):
        _poner(con, "cert_set_boletas", texto)
        for caso in casos:
            if not caso["items"]:
                raise ErrorSII(f"El CASO-{caso['numero']} no trae ítems.")
            lineas = [dict(_con_iva(i["nombre"], i["cantidad"], i["precio"], i["exento"]), unidad=i["unidad"])
                      for i in caso["items"]]
            tipo = 41 if all(l["exento"] for l in lineas) else 39
            folio, caf = tomar_folio(con, cfg["ambiente"], tipo)
            doc = {"tipo": tipo, "folio": folio, "fecha": fecha, "emisor": emisor(cfg), "receptor": None,
                   "lineas": lineas, "referencias": [{"codigo": "SET", "razon": f"CASO-{caso['numero']}"}]}
            resultado = dte.construir(doc, caf, firma)
            doc_id = _guardar_documento(con, cfg, doc, resultado)
            con.execute("UPDATE sii_documentos SET caso = ? WHERE id = ?", (f"CASO-{caso['numero']}", doc_id))
            ids.append(doc_id)
        envio_id = _crear_envio(con, cfg, firma, ids, "boletas", {"casos": len(ids)})
        marcas = ",".join("?" * len(ids))
        boletas = con.execute(f"SELECT tipo, folio, fecha, neto, iva, exento, total FROM sii_documentos "
                              f"WHERE id IN ({marcas})", ids).fetchall()
        secuencia = con.execute("SELECT COUNT(*) FROM sii_envios WHERE etapa = 'rcof' AND creado LIKE ?",
                                (f"{fecha}%",)).fetchone()[0] + 1
        xml = rcof.construir([dict(b) for b in boletas], cfg["rut"], firma, cfg["fecha_resolucion"],
                             cfg.get("numero_resolucion") or 0, secuencia)
        rcof_id = con.execute(
            "INSERT INTO sii_envios (ambiente, boletas, creado, xml, clase, etapa, detalle) "
            "VALUES (?, 0, ?, ?, 'rcof', 'rcof', ?)",
            (cfg["ambiente"], ahora(), xml, json.dumps({"secuencia": secuencia, "boletas": len(ids)}))).lastrowid
    return {"envio_id": envio_id, "rcof_id": rcof_id, "documentos": len(ids)}


# --- Intercambio ----------------------------------------------------------------------------------------------

def responder_intercambio(con, secreto, xml, nombre_archivo):
    """Las tres respuestas firmadas al envío del SII, en un ZIP (bytes) y lo leído del envío."""
    import io
    import zipfile

    from . import intercambio

    cfg, firma = preparar(con, secreto)
    contacto = {"nombre": firma.nombre, "correo": cfg.get("correo_remitente") or cfg.get("email")}
    recinto = ", ".join(x for x in (cfg.get("direccion"), cfg.get("comuna")) if x)
    r = intercambio.respuestas(xml, nombre_archivo, cfg["rut"], firma, contacto, recinto)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("1_RespuestaRecepcionEnvio.xml", r["recepcion"])
        if r["recibos"]:
            z.writestr("2_EnvioRecibos.xml", r["recibos"])
        z.writestr("3_RespuestaResultadoDTE.xml", r["resultado"])
    return salida.getvalue(), r["envio"]


# --- Estado ---------------------------------------------------------------------------------------------------

def estado(con):
    """Lo que muestra la pantalla de certificación: el último envío de cada etapa y sus documentos."""
    from .servicio import ESTADOS, leer

    cfg = leer(con)
    etapas = []
    for clave, nombre in ETAPAS.items():
        envio = ultimo_envio(con, clave)
        if envio is None:
            etapas.append({"etapa": clave, "nombre": nombre, "envio": None, "documentos": []})
            continue
        documentos = [{"id": d["id"], "caso": d["caso"], "tipo": d["tipo"], "nombre": NOMBRES.get(d["tipo"], ""),
                       "folio": d["folio"], "total": d["total"], "estado": d["estado"],
                       "estado_texto": ESTADOS.get(d["estado"], d["estado"]), "glosa": d["glosa"]}
                      for d in con.execute("SELECT * FROM sii_documentos WHERE envio_id = ? ORDER BY id",
                                           (envio["id"],))]
        etapas.append({"etapa": clave, "nombre": nombre, "documentos": documentos, "envio": {
            "id": envio["id"], "creado": envio["creado"], "trackid": envio["trackid"], "estado": envio["estado"],
            "glosa": envio["glosa"], "detalle": json.loads(envio["detalle"] or "{}")}})
    return {"ambiente": cfg.get("ambiente"), "receptor": receptor(cfg), "periodo": periodo_sugerido(con),
            "tiene_set": bool(cfg.get("cert_set")), "etapas": etapas}
