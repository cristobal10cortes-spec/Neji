"""Muestras impresas para la certificación (manual_muestras_impresas.pdf del SII).

Un PDF de una página por documento: los del set de pruebas, uno de cada tipo de la simulación y las boletas del set de
boletas; las facturas llevan además su copia cedible (con el acuse de recibo de la Ley 19.983 y la leyenda CEDIBLE).
Formato hoja carta para facturas y notas; papel continuo de 80 mm para las boletas. Todo sale del XML firmado.
"""

import io
import json
import zipfile
from datetime import date

from . import NOMBRES, NS_SII, ErrorSII
from .pdf import CARTA, Pagina, documento, partir
from .pdf417 import matriz

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
CEDIBLES = (33, 34)
REFERENCIAS = {"SET": "SET DE PRUEBAS", 30: "FACTURA", 32: "FACTURA NO AFECTA O EXENTA", 33: NOMBRES[33],
               34: NOMBRES[34], 39: NOMBRES[39], 41: NOMBRES[41], 56: NOMBRES[56], 61: NOMBRES[61]}
CODIGOS_REFERENCIA = {1: "Anula documento", 2: "Corrige texto", 3: "Corrige montos"}
ACUSE = ("El acuse de recibo que se declara en este acto, de acuerdo a lo dispuesto en la letra b) del Art. 4°, y la "
         "letra c) del Art. 5° de la Ley 19.983, acredita que la entrega de mercaderías o servicio (s) prestado (s) "
         "ha (n) sido recibido (s).")


# --- Lectura del documento firmado -----------------------------------------------------------------------------

def leer_dte(xml):
    """Lo que se imprime, tal como quedó en el documento firmado."""
    from lxml import etree

    ns = {"s": NS_SII}
    raiz = etree.fromstring(bytes(xml))
    doc = raiz.find("s:Documento", ns)
    if doc is None:
        raise ErrorSII("El XML no es un documento tributario electrónico.")

    def t(el, ruta):
        return (el.findtext(ruta, namespaces=ns) or "").strip() if el is not None else ""

    enc = doc.find("s:Encabezado", ns)
    emisor, receptor, totales = (enc.find(f"s:{n}", ns) for n in ("Emisor", "Receptor", "Totales"))
    lineas = []
    for d in doc.findall("s:Detalle", ns):
        lineas.append({"codigo": t(d, "s:CdgItem/s:VlrCodigo"), "nombre": t(d, "s:NmbItem"),
                       "descripcion": t(d, "s:DscItem"), "cantidad": t(d, "s:QtyItem"), "unidad": t(d, "s:UnmdItem"),
                       "precio": t(d, "s:PrcItem"), "descuento_pct": t(d, "s:DescuentoPct"),
                       "descuento": t(d, "s:DescuentoMonto"), "monto": int(t(d, "s:MontoItem") or 0),
                       "exento": t(d, "s:IndExe") == "1"})
    globales = [{"glosa": t(g, "s:GlosaDR"), "tipo": t(g, "s:TpoValor"), "valor": t(g, "s:ValorDR"),
                 "movimiento": t(g, "s:TpoMov")} for g in doc.findall("s:DscRcgGlobal", ns)]
    referencias = []
    for r in doc.findall("s:Referencia", ns):
        tipo = t(r, "s:TpoDocRef")
        referencias.append({"tipo": int(tipo) if tipo.isdigit() else tipo, "folio": t(r, "s:FolioRef"),
                            "fecha": t(r, "s:FchRef"), "codigo": t(r, "s:CodRef"), "razon": t(r, "s:RazonRef")})
    ted = doc.find("s:TED", ns)
    texto_ted = etree.tostring(ted, encoding="unicode").replace(f' xmlns="{NS_SII}"', "")
    texto_ted = texto_ted.replace(' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"', "")
    return {
        "tipo": int(t(enc, "s:IdDoc/s:TipoDTE")), "folio": int(t(enc, "s:IdDoc/s:Folio")),
        "fecha": t(enc, "s:IdDoc/s:FchEmis"), "forma_pago": t(enc, "s:IdDoc/s:FmaPago"),
        "bruto": t(enc, "s:IdDoc/s:MntBruto") == "1",
        "emisor": {"rut": t(emisor, "s:RUTEmisor"), "razon_social": t(emisor, "s:RznSoc") or t(emisor, "s:RznSocEmisor"),
                   "giro": t(emisor, "s:GiroEmis") or t(emisor, "s:GiroEmisor"), "direccion": t(emisor, "s:DirOrigen"),
                   "comuna": t(emisor, "s:CmnaOrigen"), "ciudad": t(emisor, "s:CiudadOrigen"),
                   "telefono": t(emisor, "s:Telefono"), "email": t(emisor, "s:CorreoEmisor")},
        "receptor": {"rut": t(receptor, "s:RUTRecep"), "razon_social": t(receptor, "s:RznSocRecep"),
                     "giro": t(receptor, "s:GiroRecep"), "direccion": t(receptor, "s:DirRecep"),
                     "comuna": t(receptor, "s:CmnaRecep"), "ciudad": t(receptor, "s:CiudadRecep")},
        "totales": {"neto": int(t(totales, "s:MntNeto") or 0), "exento": int(t(totales, "s:MntExe") or 0),
                    "tasa": t(totales, "s:TasaIVA") or "19", "iva": int(t(totales, "s:IVA") or 0),
                    "total": int(t(totales, "s:MntTotal") or 0),
                    "hay_neto": t(totales, "s:MntNeto") != "", "hay_exento": t(totales, "s:MntExe") != ""},
        "lineas": lineas, "globales": globales, "referencias": referencias,
        "ted": texto_ted.encode("iso-8859-1", "replace"),
    }


# --- Formatos ------------------------------------------------------------------------------------------------

def pesos(valor):
    return f"${int(valor):,}".replace(",", ".")


def numero(texto):
    """'1.5' -> '1,5'; '12' -> '12' (como se escribe en Chile)."""
    if texto in (None, ""):
        return ""
    entero, _, decimales = str(texto).partition(".")
    entero = f"{int(entero):,}".replace(",", ".") if entero.lstrip("-").isdigit() else entero
    decimales = decimales.rstrip("0")
    return f"{entero},{decimales}" if decimales else entero


def rut_con_puntos(rut):
    cuerpo, _, dv = str(rut or "").partition("-")
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv}" if cuerpo.isdigit() else str(rut or "")


def fecha_larga(fecha):
    try:
        d = date.fromisoformat(fecha)
    except ValueError:
        return fecha
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(fecha):
    try:
        return date.fromisoformat(fecha).strftime("%d-%m-%Y")
    except ValueError:
        return fecha or ""


def _timbre(pagina, x, y, ted, ancho_mm, cfg):
    """El timbre PDF417 (módulos de 4 px, filas de 3 módulos de alto) y su leyenda. Devuelve la y final."""
    # El SII pide entre 2x5 y 4x9 cm: con el ancho fijo, se buscan las columnas que dejen el alto en ese rango.
    for columnas in range(6, 21):
        filas = matriz(ted, columnas)
        alto_mm = ancho_mm / (17 * (columnas + 4) + 1) * 3 * len(filas)
        if alto_mm <= 36:
            break
    pixeles = []
    for fila in filas:
        ancha = "".join(c * 4 for c in fila)
        pixeles += [ancha] * 12
    pagina.imagen_bits(x, y, ancho_mm, alto_mm, pixeles)
    y += alto_mm + 3.5
    centro = x + ancho_mm / 2
    pagina.texto(centro, y, "Timbre Electrónico SII", 8, True, "centro")
    fecha_res = cfg.get("fecha_resolucion") or ""
    pagina.texto(centro, y + 3.6, f"Res. {cfg.get('numero_resolucion') or 0} de {fecha_res[:4]} - "
                                  "Verifique documento: www.sii.cl", 7, alinear="centro")
    return y + 4


def _referencia_texto(r):
    if r["tipo"] == "SET":
        return f"Set de pruebas: {r['razon']}"
    nombre = REFERENCIAS.get(r["tipo"], f"Documento tipo {r['tipo']}")
    partes = [f"{nombre.capitalize()} N° {r['folio']}"]
    if r["fecha"]:
        partes.append(f"del {fecha_corta(r['fecha'])}")
    codigo = CODIGOS_REFERENCIA.get(int(r["codigo"])) if str(r["codigo"]).isdigit() else None
    motivo = " - ".join(x for x in (codigo, r["razon"]) if x)
    return " ".join(partes) + (f". Motivo: {motivo}" if motivo else "")


# --- Hoja carta (facturas y notas) ---------------------------------------------------------------------------

def hoja(d, cfg, cedible=False):
    """Una página carta con el documento `d` (leer_dte)."""
    p = Pagina(*CARTA)
    izq, der = 12, CARTA[0] - 12
    emisor, receptor, tot = d["emisor"], d["receptor"], d["totales"]

    # Emisor (arriba a la izquierda): la razón social destacada, el giro sin abreviar y la casa matriz.
    y = p.parrafo(izq, 17, emisor["razon_social"], 110, 13, True, 5.6)
    y = p.parrafo(izq, y + 0.5, emisor["giro"], 110, 9, interlineado=4)
    direccion = ", ".join(x for x in (emisor["direccion"], emisor["comuna"], emisor["ciudad"]) if x)
    y = p.parrafo(izq, y + 0.5, f"Casa matriz: {direccion}", 110, 9, interlineado=4)
    contacto = "   ".join(x for x in (f"Teléfono: {emisor['telefono']}" if emisor["telefono"] else "",
                                      f"Correo: {emisor['email']}" if emisor["email"] else "") if x)
    if contacto:
        y = p.parrafo(izq, y, contacto, 110, 9, interlineado=4)

    # Recuadro del documento (arriba a la derecha), y bajo él la unidad del SII.
    rojo = (0.8, 0, 0)
    caja_x, caja_ancho = 132, der - 132
    nombre_doc = partir(NOMBRES.get(d["tipo"], ""), caja_ancho - 6, 11, True)[:2]
    caja_alto = 13 + 5 * len(nombre_doc) + 6
    p.rectangulo(caja_x, 10, caja_ancho, caja_alto, 0.7, rojo)
    centro = caja_x + caja_ancho / 2
    p.texto(centro, 17, f"R.U.T.: {rut_con_puntos(emisor['rut'])}", 11, True, "centro", rojo)
    for n, linea in enumerate(nombre_doc):
        p.texto(centro, 23.5 + 5 * n, linea, 11, True, "centro", rojo)
    p.texto(centro, 23.5 + 5 * len(nombre_doc) + 1, f"N° {d['folio']}", 11, True, "centro", rojo)
    oficina = (cfg.get("oficina_sii") or emisor["comuna"] or "").upper()
    p.texto(centro, 10 + caja_alto + 5, f"S.I.I. - {oficina}", 9, True, "centro")

    # Fecha y receptor.
    y = max(y, 10 + caja_alto + 9) + 3
    p.texto(izq, y, f"Fecha de emisión: {fecha_larga(d['fecha'])}", 9.5, True)
    if d["forma_pago"]:
        p.texto(der, y, f"Forma de pago: {'Crédito' if d['forma_pago'] == '2' else 'Contado'}", 9, alinear="der")
    y += 3
    filas_receptor = [("Señor(es)", receptor["razon_social"]), ("R.U.T.", rut_con_puntos(receptor["rut"])),
                      ("Giro", receptor["giro"]), ("Dirección", receptor["direccion"]),
                      ("Comuna", receptor["comuna"]), ("Ciudad", receptor["ciudad"])]
    filas_receptor = [(k, v) for k, v in filas_receptor if v]
    alto_receptor = 4.6 * len(filas_receptor) + 3
    p.rectangulo(izq, y, der - izq, alto_receptor, 0.3)
    yy = y + 4.8
    for etiqueta, valor in filas_receptor:
        p.texto(izq + 3, yy, f"{etiqueta}:", 9, True)
        p.texto(izq + 25, yy, partir(valor, der - izq - 30, 9)[0], 9)
        yy += 4.6
    y += alto_receptor + 5

    # Referencias (tipo de documento en palabras, folio, fecha y motivo).
    if d["referencias"]:
        p.texto(izq, y, "Referencias:", 9, True)
        y += 4.2
        for r in d["referencias"]:
            y = p.parrafo(izq + 3, y, _referencia_texto(r), der - izq - 3, 8.5, interlineado=3.9)
        y += 2

    # Detalle.
    columnas = [("Código", izq + 1, "izq"), ("Descripción", izq + 23, "izq"), ("Cant.", 124, "der"),
                ("Unid.", 126, "izq"), ("P. unitario", 152, "der"), ("% Desc.", 165, "der"),
                ("Descuento", 183, "der"), ("Valor", der - 1, "der")]
    p.linea(izq, y, der, y, 0.4)
    for titulo, x, alinear in columnas:
        p.texto(x, y + 4, titulo, 8, True, alinear)
    y += 5.5
    p.linea(izq, y, der, y, 0.4)
    y += 4.2
    for l in d["lineas"]:
        nombre = l["nombre"] + (" (exento)" if l["exento"] and d["tipo"] not in (34, 41) else "")
        lineas_nombre = partir(nombre, 76, 8.5)
        p.texto(izq + 1, y, (l["codigo"] or "")[:12], 8.5)
        for n, texto in enumerate(lineas_nombre):
            p.texto(izq + 23, y + 3.8 * n, texto, 8.5)
        p.texto(124, y, numero(l["cantidad"]), 8.5, alinear="der")
        p.texto(126, y, l["unidad"], 8.5)
        p.texto(152, y, numero(l["precio"]), 8.5, alinear="der")
        p.texto(165, y, f"{numero(l['descuento_pct'])}%" if l["descuento_pct"] else "", 8.5, alinear="der")
        p.texto(183, y, pesos(l["descuento"]) if l["descuento"] else "", 8.5, alinear="der")
        p.texto(der - 1, y, pesos(l["monto"]), 8.5, alinear="der")
        y += 3.8 * len(lineas_nombre)
        if l["descripcion"]:
            y = p.parrafo(izq + 23, y, l["descripcion"], 90, 8, interlineado=3.6)
        y += 1.2
    p.linea(izq, y, der, y, 0.4)
    y += 5
    if d["bruto"]:
        p.texto(izq, y, "Precios con IVA incluido.", 7.5)

    # Totales (abajo a la derecha).
    exento_solo = d["tipo"] in (34, 41) or (not tot["hay_neto"] and tot["hay_exento"])
    totales = []
    afecto = sum(l["monto"] for l in d["lineas"] if not l["exento"])
    for g in d["globales"]:
        nombre = "Descuento global" if g["movimiento"] == "D" else "Recargo global"
        if g["tipo"] == "%":         # en porcentaje y en pesos
            monto = round(afecto * float(g["valor"]) / 100)
            totales.append((f"{nombre} {numero(g['valor'])}%", pesos(monto)))
        else:
            totales.append((nombre, pesos(g["valor"])))
    if not exento_solo and (tot["hay_neto"] or tot["neto"]):
        totales.append(("Monto neto", pesos(tot["neto"])))
    if tot["hay_exento"] or exento_solo:
        totales.append(("Monto exento", pesos(tot["exento"])))
    if not exento_solo and (tot["hay_neto"] or tot["iva"]):
        totales.append((f"IVA ({tot['tasa']}%)", pesos(tot["iva"])))
    totales.append(("Monto total", pesos(tot["total"])))
    y_totales = max(y, 185)
    alto_totales = 5.2 * len(totales) + 3
    p.rectangulo(130, y_totales - 4.5, der - 130, alto_totales, 0.3)
    for n, (etiqueta, valor) in enumerate(totales):
        negrita = etiqueta == "Monto total"
        p.texto(133, y_totales + 5.2 * n, etiqueta, 9, negrita)
        p.texto(der - 3, y_totales + 5.2 * n, valor, 9, negrita, "der")

    # Timbre (abajo, a 2 cm del borde izquierdo) y, en la copia cedible, el acuse de recibo y la leyenda.
    y_timbre = max(y_totales - 4.5, 200)
    _timbre(p, 22, y_timbre, d["ted"], 68, cfg)
    if cedible:
        caja_x, caja_y = 112, max(y_totales - 4.5 + alto_totales + 4, 214)
        p.rectangulo(caja_x, caja_y, der - caja_x, 50, 0.3)
        p.texto(caja_x + 3, caja_y + 5, "ACUSE DE RECIBO", 9, True)
        for n, campo in enumerate(("Nombre:", "R.U.T.:", "Fecha:", "Recinto:", "Firma:")):
            yy = caja_y + 11 + 5.5 * n
            p.texto(caja_x + 3, yy, campo, 8.5)
            p.linea(caja_x + 19, yy + 0.6, der - 4, yy + 0.6, 0.2)
        p.parrafo(caja_x + 3, caja_y + 39.5, ACUSE, der - caja_x - 6, 6.5, interlineado=2.8)
        p.texto(der, CARTA[1] - 9, "CEDIBLE", 12, True, "der")
    return p


# --- Papel continuo de 80 mm (boletas) -----------------------------------------------------------------------

def ticket(d, cfg):
    """Una boleta en papel continuo de 80 mm (formato POS): tan larga como lo que lleva."""
    borrador = Pagina(80, 2000)
    largo = _dibujar_ticket(borrador, d, cfg)
    pagina = Pagina(80, largo + 8)
    _dibujar_ticket(pagina, d, cfg)
    return pagina


def _dibujar_ticket(p, d, cfg):
    ancho_papel, margen = p.ancho, 5
    util = ancho_papel - 2 * margen
    centro = ancho_papel / 2
    emisor, tot = d["emisor"], d["totales"]
    nombre_doc = partir(NOMBRES.get(d["tipo"], ""), util - 8, 10, True)
    oficina = (cfg.get("oficina_sii") or emisor["comuna"] or "").upper()
    caja_alto = 12 + 4.6 * len(nombre_doc)
    p.rectangulo(margen + 2, 5, util - 4, caja_alto, 0.6)
    p.texto(centro, 10, f"R.U.T.: {rut_con_puntos(emisor['rut'])}", 10, True, "centro")
    for n, linea in enumerate(nombre_doc):
        p.texto(centro, 14.8 + 4.6 * n, linea, 10, True, "centro")
    p.texto(centro, 14.8 + 4.6 * len(nombre_doc), f"N° {d['folio']}", 10, True, "centro")
    y = 5 + caja_alto + 4.5
    p.texto(centro, y, f"S.I.I. - {oficina}", 8, True, "centro")
    y += 6
    y = p.parrafo(margen, y, emisor["razon_social"], util, 9.5, True, 4.2)
    y = p.parrafo(margen, y, emisor["giro"], util, 7.5, interlineado=3.3)
    direccion = ", ".join(x for x in (emisor["direccion"], emisor["comuna"]) if x)
    y = p.parrafo(margen, y, direccion, util, 7.5, interlineado=3.3)
    y += 1.5
    p.texto(margen, y, f"Fecha de emisión: {fecha_corta(d['fecha'])}", 8)
    y += 3
    p.linea(margen, y, ancho_papel - margen, y, 0.2)
    y += 4
    for l in d["lineas"]:
        y = p.parrafo(margen, y, l["nombre"] + (" (exento)" if l["exento"] and d["tipo"] != 41 else ""), util, 8,
                      interlineado=3.5)
        cantidad = f"{numero(l['cantidad'])}{(' ' + l['unidad']) if l['unidad'] else ''} x {numero(l['precio'])}"
        p.texto(margen + 2, y, cantidad, 8)
        p.texto(ancho_papel - margen, y, pesos(l["monto"]), 8, alinear="der")
        y += 4
    p.linea(margen, y - 1.5, ancho_papel - margen, y - 1.5, 0.2)
    y += 3
    for g in d["globales"]:
        p.texto(margen, y, "Descuento", 8.5)
        p.texto(ancho_papel - margen, y, pesos(g["valor"]) if g["tipo"] != "%" else f"{g['valor']}%", 8.5,
                alinear="der")
        y += 4
    if tot["hay_exento"] or d["tipo"] == 41:
        p.texto(margen, y, "Monto exento", 8.5)
        p.texto(ancho_papel - margen, y, pesos(tot["exento"]), 8.5, alinear="der")
        y += 4
    p.texto(margen, y, "TOTAL", 10, True)
    p.texto(ancho_papel - margen, y, pesos(tot["total"]), 10, True, "der")
    y += 4.5
    if tot["iva"]:
        p.texto(margen, y, f"El IVA de esta boleta es: {pesos(tot['iva'])}", 8)
        y += 4
    y += 2
    # También en papel continuo el timbre va a 2 cm o más del borde izquierdo (y de 5 cm de ancho o más).
    return _timbre(p, 21, y, d["ted"], ancho_papel - 21 - 3, cfg)


# --- El paquete para el SII -------------------------------------------------------------------------------------

def _nombre_archivo(etapa, fila, cedible=False):
    caso = (fila["caso"] or "").replace(" ", "_")
    tipo = {33: "factura", 34: "factura_exenta", 39: "boleta", 41: "boleta_exenta", 56: "nota_debito",
            61: "nota_credito"}.get(fila["tipo"], f"tipo{fila['tipo']}")
    partes = [etapa, f"caso_{caso}" if caso and caso != "SIMULACION" else "", f"{tipo}_{fila['folio']}"]
    return "_".join(x for x in partes if x) + ("_cedible" if cedible else "") + ".pdf"


def pdf_de(fila, cfg, cedible=False):
    d = leer_dte(fila["xml"])
    pagina = ticket(d, cfg) if d["tipo"] in (39, 41) else hoja(d, cfg, cedible)
    titulo = f"{NOMBRES.get(d['tipo'], '')} N° {d['folio']}" + (" (cedible)" if cedible else "")
    return documento([pagina], titulo)


def zip_de_certificacion(con):
    """Las muestras impresas de la certificación (lo último emitido de cada etapa) en un ZIP."""
    from .certificacion import ultimo_envio
    from .servicio import leer

    cfg = leer(con)
    archivos = {}
    for etapa in ("basico", "exenta", "simulacion", "boletas"):
        envio = ultimo_envio(con, etapa, cfg.get("ambiente") or "certificacion")
        if envio is None:
            continue
        filas = con.execute("SELECT * FROM sii_documentos WHERE envio_id = ? ORDER BY id", (envio["id"],)).fetchall()
        if etapa == "simulacion":          # uno de cada tipo
            vistos, elegidas = set(), []
            for f in filas:
                if f["tipo"] not in vistos:
                    vistos.add(f["tipo"])
                    elegidas.append(f)
            filas = elegidas
        for f in filas:
            archivos[_nombre_archivo(etapa, f)] = pdf_de(f, cfg)
            if f["tipo"] in CEDIBLES:
                archivos[_nombre_archivo(etapa, f, True)] = pdf_de(f, cfg, True)
    if not archivos:
        raise ErrorSII("Todavía no hay documentos de la certificación: primero emite el set de pruebas.")
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
        z.writestr("LEEME.txt", (
            "Muestras impresas para la certificacion del SII (generadas por Neji POS).\n\n"
            "Envialas al correo SII_dte_impresos@sii.cl, un documento por archivo, en correos de no mas de 3 MB.\n"
            "En el asunto: el RUT y la razon social de la empresa (por ejemplo: "
            f"RUT {cfg.get('rut', '')}, {cfg.get('razon_social', '')}, envio 1 de N).\n"
            "Si el SII las rechaza y las vuelves a enviar, indica en el asunto que son muestras corregidas.\n"
            "Si tu negocio no usa algun tipo de descuento, dilo en el cuerpo del correo.\n").encode("utf-8"))
        z.writestr("documentos.json", json.dumps(sorted(archivos), ensure_ascii=False, indent=1).encode("utf-8"))
    return salida.getvalue()
