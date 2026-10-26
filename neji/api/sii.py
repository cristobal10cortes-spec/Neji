"""Boleta y factura electrónica (SII): configuración, firma, folios, documentos y envío."""

from flask import Response, current_app, jsonify, request

from ..auth import con_permiso, solo_admin
from ..db import get_db, transaccion
from ..sii import NOMBRES, ErrorSII, falta_modulo
from ..sii import servicio as sii
from ..validar import ErrorNegocio, entero
from . import bp, datos_json, rango_fechas

OCULTOS = {"firma_pfx", "firma_clave", "correo_clave", "cert_set", "cert_set_boletas", "cert_intercambio",
           "cert_receptor"}


def _error(e):
    return ErrorNegocio(str(e))


@bp.get("/sii")
@solo_admin
def estado_sii():
    con = get_db()
    cfg = sii.leer(con)
    return jsonify({
        "config": {k: v for k, v in cfg.items() if k not in OCULTOS},
        "falta_modulo": falta_modulo(),
        "ambientes": sii.AMBIENTES,
        "firma": sii.resumen_firma(cfg, current_app.secret_key) if not falta_modulo() else None,
        "folios": sii.folios(con, cfg["ambiente"]),
        "pendientes": sii.pendientes_para_activar(con),
        "envios": sii.resumen_envios(con, cfg["ambiente"]),
        "correo": {"configurado": sii.correo_configurado(cfg), "clave_guardada": bool(cfg.get("correo_clave"))},
        "tipos": NOMBRES,
    })


@bp.put("/sii")
@solo_admin
def guardar_sii():
    con = get_db()
    try:
        with transaccion(con):
            sii.guardar(con, datos_json(), current_app.secret_key)
    except ErrorSII as e:
        raise _error(e) from None
    return estado_sii()


@bp.post("/sii/firma")
@solo_admin
def subir_firma():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        raise ErrorNegocio("Elige el archivo de la firma electrónica (.pfx o .p12).")
    if falta_modulo():
        raise ErrorNegocio(falta_modulo())
    con = get_db()
    try:
        with transaccion(con):
            sii.guardar_firma(con, archivo.read(), request.form.get("clave") or "", current_app.secret_key)
    except ErrorSII as e:
        raise _error(e) from None
    return estado_sii()


@bp.delete("/sii/firma")
@solo_admin
def quitar_firma():
    con = get_db()
    with transaccion(con):
        sii.borrar_firma(con)
        con.execute("UPDATE sii_config SET valor = '0' WHERE clave = 'activo'")
    return estado_sii()


@bp.post("/sii/caf")
@solo_admin
def subir_caf():
    archivos = request.files.getlist("archivo")
    if not archivos or not archivos[0].filename:
        raise ErrorNegocio("Elige el archivo de folios (CAF) que descargaste del SII.")
    if falta_modulo():
        raise ErrorNegocio(falta_modulo())
    con = get_db()
    try:
        with transaccion(con):
            for archivo in archivos:
                sii.cargar_caf(con, archivo.read())
    except ErrorSII as e:
        raise _error(e) from None
    return estado_sii()


@bp.put("/sii/caf/<int:caf_id>")
@solo_admin
def cambiar_caf(caf_id):
    con = get_db()
    try:
        with transaccion(con):
            sii.cambiar_inicio(con, caf_id, entero(datos_json().get("usar_desde"), "folio", minimo=1))
    except ErrorSII as e:
        raise _error(e) from None
    return estado_sii()


@bp.delete("/sii/caf/<int:caf_id>")
@solo_admin
def quitar_caf(caf_id):
    con = get_db()
    try:
        with transaccion(con):
            sii.borrar_caf(con, caf_id)
    except ErrorSII as e:
        raise _error(e) from None
    return estado_sii()


@bp.post("/sii/probar")
@solo_admin
def probar_conexion():
    """Se conecta al SII con la firma (pide un token): así se sabe que la firma y la red funcionan."""
    from ..sii.conexion import ConexionSII

    con = get_db()
    cfg = sii.leer(con)
    try:
        firma = sii.cargar_firma(cfg, current_app.secret_key)
        conexion = ConexionSII(cfg["ambiente"], firma, cfg.get("rut") or firma.rut)
        conexion.token(rest=False)
        if cfg["ambiente"] == "produccion":
            conexion.token(rest=True)
    except ErrorSII as e:
        raise _error(e) from None
    return jsonify(ok=True, mensaje=f"Conectado con el SII ({sii.AMBIENTES[cfg['ambiente']].lower()}) con la "
                                    f"firma de {firma.nombre}.")


@bp.post("/sii/enviar")
@solo_admin
def enviar_ahora():
    try:
        resumen = sii.ciclo(current_app.config["DATABASE"], current_app.secret_key)
    except ErrorSII as e:
        raise _error(e) from None
    return jsonify(resumen=resumen, **estado_sii().get_json())


@bp.post("/sii/correo/probar")
@solo_admin
def probar_correo():
    """Manda un correo de prueba con la cuenta guardada (a ella misma o a la dirección indicada)."""
    cfg = sii.leer(get_db())
    try:
        para = sii.probar_correo(cfg, current_app.secret_key, (request.get_json(silent=True) or {}).get("para"))
    except ErrorSII as e:
        raise _error(e) from None
    _avisar_enviador()
    return jsonify(ok=True, mensaje=f"Correo de prueba enviado a {para}.")


@bp.post("/sii/documentos/<int:documento_id>/correo")
@con_permiso("reportes")
def reenviar_correo(documento_id):
    """Deja por enviar (otra vez, o a otro correo) el XML de una factura a su cliente."""
    con = get_db()
    try:
        with transaccion(con):
            sii.reenviar_correo(con, documento_id, (request.get_json(silent=True) or {}).get("correo"))
    except ErrorSII as e:
        raise _error(e) from None
    _avisar_enviador()
    return jsonify(ok=True)


def _avisar_enviador():
    enviador = current_app.extensions.get("sii_enviador")
    if enviador is not None:
        enviador.avisar()


@bp.get("/sii/documentos")
@con_permiso("reportes")
def listar_documentos():
    con = get_db()
    cfg = sii.leer(con)
    _, _, inicio, fin = rango_fechas()
    condiciones, parametros = ["d.ambiente = ?", "d.emitido BETWEEN ? AND ?"], [cfg["ambiente"], inicio, fin]
    if request.args.get("estado"):
        condiciones.append("d.estado = ?")
        parametros.append(request.args["estado"])
    filas = con.execute(
        f"""SELECT d.id, d.tipo, d.folio, d.fecha, d.emitido, d.total, d.estado, d.glosa, d.rut_receptor,
                   d.razon_receptor, d.venta_id, d.devolucion_id, v.folio AS venta_folio, e.trackid,
                   d.correo_receptor, d.correo_estado, d.correo_glosa, d.correo_enviado
            FROM sii_documentos d LEFT JOIN ventas v ON v.id = d.venta_id
            LEFT JOIN sii_envios e ON e.id = d.envio_id
            WHERE {' AND '.join(condiciones)} ORDER BY d.id DESC LIMIT 2000""", parametros).fetchall()
    return jsonify([dict(f) | {"nombre": NOMBRES.get(f["tipo"], ""),
                               "estado_texto": sii.ESTADOS.get(f["estado"], f["estado"]),
                               "correo_texto": sii.ESTADOS_CORREO.get(f["correo_estado"])} for f in filas])


@bp.get("/sii/documentos/<int:documento_id>/xml")
@con_permiso("reportes")
def descargar_xml(documento_id):
    fila = get_db().execute("SELECT tipo, folio, xml FROM sii_documentos WHERE id = ?", (documento_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio("Documento no encontrado.", status=404)
    return Response(fila["xml"], mimetype="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=DTE_T{fila['tipo']}_F{fila['folio']}.xml"})


@bp.post("/sii/ventas/<int:venta_id>/emitir")
@con_permiso("devoluciones")
def emitir_pendiente(venta_id):
    """Emite la boleta (o factura) de una venta que quedó sin documento o cuyo documento rechazó el SII."""
    from ..servicios import ventas as svc_ventas
    from ..db import leer_config

    con = get_db()
    documento = (request.get_json(silent=True) or {}).get("documento") or "boleta"
    if not sii.activo(con):
        raise ErrorNegocio("La boleta electrónica no está activada.")
    try:
        with transaccion(con):
            venta = con.execute("SELECT estado FROM ventas WHERE id = ?", (venta_id,)).fetchone()
            if venta is None:
                raise ErrorNegocio("Venta no encontrada.", status=404)
            if venta["estado"] != "completada":
                raise ErrorNegocio("La venta tiene devoluciones: ya no se le puede emitir el documento.")
            if sii.documento_de_venta(con, venta_id) is not None:
                raise ErrorNegocio("Esta venta ya tiene su documento electrónico.")
            sii.emitir_venta(con, venta_id, documento if documento in ("boleta", "factura") else "boleta",
                             current_app.secret_key, int(leer_config(con)["iva_porcentaje"]))
    except ErrorSII as e:
        raise _error(e) from None
    _avisar_enviador()
    return jsonify(svc_ventas.obtener_venta(con, venta_id)), 201


# --- Certificación ---------------------------------------------------------------------------------------------

def _texto_del_set(datos):
    texto = str(datos.get("texto") or "").strip()
    if not texto:
        raise ErrorNegocio("Pega el texto del set de pruebas que descargaste del SII.")
    if len(texto) > 500_000:
        raise ErrorNegocio("El texto es demasiado largo para ser un set de pruebas.")
    return texto


def _certificar(funcion, *args, **kwargs):
    from ..sii import falta_modulo as falta

    if falta():
        raise ErrorNegocio(falta())
    try:
        resultado = funcion(get_db(), current_app.secret_key, *args, **kwargs)
    except ErrorSII as e:
        raise _error(e) from None
    _avisar_enviador()
    return resultado


@bp.get("/sii/certificacion")
@solo_admin
def estado_certificacion():
    from ..sii import certificacion

    return jsonify(certificacion.estado(get_db()))


@bp.put("/sii/certificacion/receptor")
@solo_admin
def receptor_certificacion():
    from ..sii import certificacion

    con = get_db()
    try:
        with transaccion(con):
            certificacion.guardar_receptor(con, datos_json())
    except ErrorSII as e:
        raise _error(e) from None
    return estado_certificacion()


@bp.post("/sii/certificacion/set")
@solo_admin
def certificar_set():
    """Emite los documentos del set de pruebas (básico y exenta) y los deja enviándose al SII."""
    from ..sii import certificacion

    resultado = _certificar(certificacion.emitir_sets, _texto_del_set(datos_json()))
    return jsonify(resultado=resultado, **certificacion.estado(get_db()))


@bp.post("/sii/certificacion/libros")
@solo_admin
def certificar_libros():
    from ..sii import certificacion

    datos = datos_json()
    cuales = [c for c in (datos.get("cuales") or ["ventas", "compras"]) if c in ("ventas", "compras")]
    if not cuales:
        raise ErrorNegocio("Elige qué libros enviar.")
    resultado = _certificar(
        certificacion.emitir_libros, periodo=str(datos.get("periodo") or "").strip() or None,
        tipo_envio=str(datos.get("tipo_envio") or "TOTAL").upper(),
        tipo_libro=str(datos.get("tipo_libro") or "MENSUAL").upper(),
        folio_notificacion=str(datos.get("folio_notificacion") or "").strip() or None, cuales=cuales,
        texto=str(datos.get("texto") or "").strip()[:500_000] or None)
    return jsonify(resultado=resultado, **certificacion.estado(get_db()))


@bp.post("/sii/certificacion/simulacion")
@solo_admin
def certificar_simulacion():
    from ..sii import certificacion

    resultado = _certificar(certificacion.emitir_simulacion)
    return jsonify(resultado=resultado, **certificacion.estado(get_db()))


@bp.post("/sii/certificacion/boletas")
@solo_admin
def certificar_boletas():
    from ..sii import certificacion

    resultado = _certificar(certificacion.emitir_boletas, _texto_del_set(datos_json()))
    return jsonify(resultado=resultado, **certificacion.estado(get_db()))


@bp.post("/sii/certificacion/intercambio")
@solo_admin
def certificar_intercambio():
    """Arma las tres respuestas firmadas al EnvioDTE que el SII mandó al correo de intercambio. Quedan guardadas
    en un ZIP para descargarlo (GET): así la descarga funciona igual en el navegador y en la ventana de Neji."""
    import base64

    from ..sii import certificacion
    from ..sii.servicio import _poner

    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        raise ErrorNegocio("Elige el archivo XML que te llegó del SII.")
    contenido = archivo.read(20 * 1024 * 1024 + 1)
    if len(contenido) > 20 * 1024 * 1024:
        raise ErrorNegocio("El archivo es demasiado grande para ser un envío de documentos.")
    zip_, leido = _certificar(certificacion.responder_intercambio, contenido, archivo.filename)
    con = get_db()
    with transaccion(con):
        _poner(con, "cert_intercambio", base64.b64encode(zip_).decode())
    return jsonify(documentos=leido["documentos"], firma_valida=leido["firma_valida"],
                   emisor=leido["rut_emisor"], receptor=leido["rut_receptor"])


@bp.get("/sii/certificacion/intercambio")
@solo_admin
def descargar_intercambio():
    import base64

    guardado = sii.leer(get_db()).get("cert_intercambio")
    if not guardado:
        raise ErrorNegocio("Primero sube el archivo que te mandó el SII.", status=404)
    return Response(base64.b64decode(guardado), mimetype="application/zip",
                    headers={"Content-Disposition": "attachment; filename=respuestas_intercambio.zip"})


@bp.get("/sii/certificacion/muestras")
@solo_admin
def certificar_muestras():
    """Las muestras impresas (un PDF por documento, con la copia cedible de las facturas), en un ZIP."""
    from ..sii import muestras

    con = get_db()
    try:
        contenido = muestras.zip_de_certificacion(con)
    except ErrorSII as e:
        raise _error(e) from None
    return Response(contenido, mimetype="application/zip",
                    headers={"Content-Disposition": "attachment; filename=muestras_impresas.zip"})


@bp.get("/sii/envios/<int:envio_id>/xml")
@solo_admin
def descargar_envio(envio_id):
    fila = get_db().execute("SELECT id, etapa, clase, trackid, xml FROM sii_envios WHERE id = ?",
                            (envio_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio("Envío no encontrado.", status=404)
    nombre = f"{fila['etapa'] or fila['clase']}_{fila['trackid'] or fila['id']}.xml"
    return Response(fila["xml"], mimetype="application/xml",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})
