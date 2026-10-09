"""Configuración inicial, sesión, usuarios, cajas, departamentos, configuración y respaldos."""

import json
import os

from flask import current_app, jsonify, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from .. import equipo, respaldos
from ..auth import PERMISOS, con_permiso, leer_permisos, permisos_de, solo_admin, usuario_actual
from ..chile import formatear_rut, validar_rut
from ..db import CONFIG_POR_DEFECTO, ahora, filas, get_db, leer_config, transaccion
from ..validar import ErrorNegocio, booleano, entero, texto
from . import bp, datos_json

OPCIONES_SI_NO = {
    "imprimir_automatico", "redondeo_efectivo", "permitir_stock_negativo",
    "cajero_puede_devolver", "cajero_puede_cambiar_precio", "modulo_farmacia", "modo_red",
    "impresion_directa",
}
CONFIG_EDITABLE = set(CONFIG_POR_DEFECTO) - {"ultimo_respaldo", "recetario_semilla"}


def _iniciar_sesion(usuario_id):
    session.clear()
    session.permanent = True
    session["usuario_id"] = usuario_id


@bp.get("/estado")
def estado():
    con = get_db()
    configurado = con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None
    nombre = con.execute("SELECT valor FROM config WHERE clave = 'negocio_nombre'").fetchone()
    return jsonify(configurado=configurado, usuario=usuario_actual(),
                   negocio=nombre["valor"] if nombre else "")


@bp.post("/setup")
def setup():
    """Primera ejecución: datos del negocio y usuario administrador."""
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
            raise ErrorNegocio("El sistema ya está configurado.", status=409)
        usuario = texto(datos, "usuario", requerido=True, nombre="el usuario", max_largo=40)
        password = datos.get("password") or ""
        if len(password) < 4:
            raise ErrorNegocio("La contraseña debe tener al menos 4 caracteres.")
        rut = texto(datos, "negocio_rut")
        if rut:
            if not validar_rut(rut):
                raise ErrorNegocio("El RUT del negocio no es válido.")
            rut = formatear_rut(rut)
        nombre_negocio = texto(datos, "negocio_nombre", requerido=True, nombre="el nombre del negocio")
        con.execute("UPDATE config SET valor = ? WHERE clave = 'negocio_nombre'", (nombre_negocio,))
        con.execute("UPDATE config SET valor = ? WHERE clave = 'negocio_rut'", (rut or "",))
        con.execute("UPDATE config SET valor = ? WHERE clave = 'modulo_farmacia'",
                    ("1" if booleano(datos.get("modulo_farmacia", False)) else "0",))
        usuario_id = con.execute(
            "INSERT INTO usuarios (usuario, nombre, password_hash, rol, creado) "
            "VALUES (?, ?, ?, 'admin', ?)",
            (usuario, texto(datos, "nombre") or usuario, generate_password_hash(password), ahora()),
        ).lastrowid
    _iniciar_sesion(usuario_id)
    return jsonify(ok=True)


@bp.post("/login")
def login():
    datos = datos_json()
    row = get_db().execute(
        "SELECT id, password_hash FROM usuarios WHERE usuario = ? AND activo = 1",
        (str(datos.get("usuario") or "").strip(),),
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], str(datos.get("password") or "")):
        raise ErrorNegocio("Usuario o contraseña incorrectos.", status=401)
    _iniciar_sesion(row["id"])
    return jsonify(usuario=usuario_actual())


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# --- Configuración -----------------------------------------------------------

@bp.get("/config")
def ver_config():
    return jsonify(leer_config(get_db()))


@bp.put("/config")
@solo_admin
def guardar_config():
    datos = datos_json()
    cambios = {}
    for clave, valor in datos.items():
        if clave not in CONFIG_EDITABLE:
            continue
        if clave in OPCIONES_SI_NO:
            valor = "1" if booleano(valor) else "0"
        elif clave == "iva_porcentaje":
            valor = str(entero(valor, "porcentaje de IVA", minimo=0))
        elif clave == "respaldos_mantener":
            valor = str(min(entero(valor, "cantidad de respaldos", minimo=1), 100))
        elif clave == "ticket_ancho":
            valor = "58" if str(valor) == "58" else "80"
        elif clave == "receta_redondeo":
            valor = str(valor).strip()
            if valor not in ("1", "10", "50", "100"):
                raise ErrorNegocio("El redondeo de recetas debe ser 1, 10, 50 o 100 pesos.")
        elif clave == "negocio_rut":
            valor = str(valor or "").strip()
            if valor:
                if not validar_rut(valor):
                    raise ErrorNegocio("El RUT del negocio no es válido.")
                valor = formatear_rut(valor)
        else:
            valor = str(valor or "").strip()[:500]
        cambios[clave] = valor
    if "negocio_nombre" in cambios and not cambios["negocio_nombre"]:
        raise ErrorNegocio("El nombre del negocio no puede quedar vacío.")
    con = get_db()
    with transaccion(con):
        for clave, valor in cambios.items():
            con.execute("UPDATE config SET valor = ? WHERE clave = ?", (valor, clave))
    return jsonify(leer_config(con))


# --- Usuarios ----------------------------------------------------------------

def _usuario_publico(u):
    u = dict(u)
    u["permisos"] = permisos_de(u)
    # Lo que tendría como cajero (para el formulario: pasar un administrador a cajero restringe, no da todo).
    u["permisos_cajero"] = permisos_de({**u, "rol": "cajero"})
    u.pop("password_hash", None)
    return u


@bp.get("/permisos")
def catalogo_permisos():
    """Los permisos que se pueden dar a un cajero, en orden y con su explicación."""
    return jsonify([{"clave": clave, "etiqueta": etiqueta, "por_defecto": defecto, "farmacia": farmacia}
                    for clave, etiqueta, defecto, farmacia in PERMISOS])


@bp.get("/usuarios")
@solo_admin
def listar_usuarios():
    return jsonify([_usuario_publico(u) for u in get_db().execute(
        "SELECT id, usuario, nombre, nombre_ticket, rol, activo, creado, permisos FROM usuarios "
        "ORDER BY nombre")])


def _leer_rol(datos):
    rol = datos.get("rol") or "cajero"
    if rol not in ("admin", "cajero"):
        raise ErrorNegocio("El rol debe ser admin o cajero.")
    return rol


@bp.post("/usuarios")
@solo_admin
def crear_usuario():
    datos = datos_json()
    usuario = texto(datos, "usuario", requerido=True, nombre="el usuario", max_largo=40)
    password = str(datos.get("password") or "")
    if len(password) < 4:
        raise ErrorNegocio("La contraseña debe tener al menos 4 caracteres.")
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
            raise ErrorNegocio("Ya existe un usuario con ese nombre.")
        nuevo = con.execute(
            "INSERT INTO usuarios (usuario, nombre, nombre_ticket, password_hash, rol, permisos, creado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (usuario, texto(datos, "nombre", max_largo=80) or usuario,
             texto(datos, "nombre_ticket", max_largo=60) or None, generate_password_hash(password),
             _leer_rol(datos), json.dumps(leer_permisos(datos.get("permisos"))), ahora()),
        ).lastrowid
    return jsonify(_usuario_publico(con.execute("SELECT * FROM usuarios WHERE id = ?", (nuevo,)).fetchone())), 201


@bp.put("/usuarios/<int:usuario_id>")
@solo_admin
def editar_usuario(usuario_id):
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        actual = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if actual is None:
            raise ErrorNegocio("Usuario no encontrado.", status=404)
        rol = _leer_rol({"rol": datos.get("rol", actual["rol"])})
        activo = 1 if booleano(datos.get("activo", actual["activo"])) else 0
        if usuario_id == usuario_actual()["id"] and (rol != "admin" or not activo):
            raise ErrorNegocio("No puedes quitarte el rol de administrador ni desactivarte.")
        if actual["rol"] == "admin" and (rol != "admin" or not activo):
            otros = con.execute(
                "SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> ?",
                (usuario_id,)).fetchone()[0]
            if not otros:
                raise ErrorNegocio("Debe quedar al menos un administrador activo.")
        nombre_ticket = (texto(datos, "nombre_ticket", max_largo=60) or None) if "nombre_ticket" in datos \
            else actual["nombre_ticket"]
        permisos = leer_permisos(datos.get("permisos"), permisos_de({**dict(actual), "rol": "cajero"}))
        con.execute("UPDATE usuarios SET nombre = ?, nombre_ticket = ?, rol = ?, activo = ?, permisos = ? "
                    "WHERE id = ?",
                    (texto(datos, "nombre", max_largo=80) or actual["nombre"], nombre_ticket, rol, activo,
                     json.dumps(permisos), usuario_id))
        password = str(datos.get("password") or "")
        if password:
            if len(password) < 4:
                raise ErrorNegocio("La contraseña debe tener al menos 4 caracteres.")
            con.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?",
                        (generate_password_hash(password), usuario_id))
    return jsonify(_usuario_publico(con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()))


# --- Cajas y departamentos ---------------------------------------------------

@bp.get("/cajas")
def listar_cajas():
    return jsonify(filas(get_db().execute("SELECT * FROM cajas ORDER BY id")))


@bp.post("/cajas")
@solo_admin
def crear_caja():
    nombre = texto(datos_json(), "nombre", requerido=True, nombre="el nombre", max_largo=40)
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM cajas WHERE nombre = ?", (nombre,)).fetchone():
            raise ErrorNegocio("Ya existe una caja con ese nombre.")
        nuevo = con.execute("INSERT INTO cajas (nombre) VALUES (?)", (nombre,)).lastrowid
    return jsonify(id=nuevo), 201


@bp.put("/cajas/<int:caja_id>")
@solo_admin
def editar_caja(caja_id):
    datos = datos_json()
    con = get_db()
    with transaccion(con):
        caja = con.execute("SELECT * FROM cajas WHERE id = ?", (caja_id,)).fetchone()
        if caja is None:
            raise ErrorNegocio("Caja no encontrada.", status=404)
        nombre = texto(datos, "nombre", max_largo=40) or caja["nombre"]
        if con.execute("SELECT 1 FROM cajas WHERE nombre = ? AND id <> ?", (nombre, caja_id)).fetchone():
            raise ErrorNegocio("Ya existe una caja con ese nombre.")
        activa = 1 if booleano(datos.get("activa", caja["activa"])) else 0
        if not activa and con.execute(
                "SELECT 1 FROM turnos WHERE caja_id = ? AND estado = 'abierto'", (caja_id,)).fetchone():
            raise ErrorNegocio("Cierra el turno de la caja antes de desactivarla.")
        principal = booleano(datos.get("principal", caja["principal"]))
        if caja["principal"] and not principal:
            raise ErrorNegocio("Para cambiar la caja principal, marca como principal la otra caja.")
        if principal and not activa:
            raise ErrorNegocio("La caja principal no se puede desactivar.")
        if principal and not caja["principal"]:
            con.execute("UPDATE cajas SET principal = 0")   # solo una caja es la principal
        con.execute("UPDATE cajas SET nombre = ?, activa = ?, principal = ? WHERE id = ?",
                    (nombre, activa, 1 if principal else 0, caja_id))
    return jsonify(ok=True)


@bp.get("/departamentos")
def listar_departamentos():
    return jsonify(filas(get_db().execute(
        """SELECT d.*, (SELECT COUNT(*) FROM productos p
                        WHERE p.departamento_id = d.id AND p.activo = 1) AS productos
           FROM departamentos d ORDER BY d.nombre""")))


@bp.post("/departamentos")
@con_permiso("productos")
def crear_departamento():
    nombre = texto(datos_json(), "nombre", requerido=True, nombre="el nombre", max_largo=60)
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM departamentos WHERE nombre = ?", (nombre,)).fetchone():
            raise ErrorNegocio("Ya existe un departamento con ese nombre.")
        nuevo = con.execute("INSERT INTO departamentos (nombre) VALUES (?)", (nombre,)).lastrowid
    return jsonify(id=nuevo), 201


@bp.put("/departamentos/<int:dep_id>")
@con_permiso("productos")
def editar_departamento(dep_id):
    nombre = texto(datos_json(), "nombre", requerido=True, nombre="el nombre", max_largo=60)
    con = get_db()
    with transaccion(con):
        if con.execute("SELECT 1 FROM departamentos WHERE nombre = ? AND id <> ?",
                       (nombre, dep_id)).fetchone():
            raise ErrorNegocio("Ya existe un departamento con ese nombre.")
        if con.execute("UPDATE departamentos SET nombre = ? WHERE id = ?",
                       (nombre, dep_id)).rowcount == 0:
            raise ErrorNegocio("Departamento no encontrado.", status=404)
    return jsonify(ok=True)


@bp.delete("/departamentos/<int:dep_id>")
@con_permiso("productos")
def borrar_departamento(dep_id):
    con = get_db()
    with transaccion(con):
        con.execute("UPDATE productos SET departamento_id = NULL WHERE departamento_id = ?", (dep_id,))
        con.execute("DELETE FROM departamentos WHERE id = ?", (dep_id,))
    return jsonify(ok=True)


# --- Equipo ------------------------------------------------------------------

@bp.get("/equipo")
@solo_admin
def datos_equipo():
    """Dónde están los datos y la dirección que usan las otras cajas para conectarse."""
    return jsonify(equipo.describir(current_app.config["DATOS"]))


# --- Respaldos ---------------------------------------------------------------

@bp.get("/respaldos")
@solo_admin
def listar_respaldos():
    return jsonify(respaldos.listar(current_app.config["RESPALDOS"]))


@bp.post("/respaldos")
@solo_admin
def respaldar_ahora():
    con = get_db()
    mantener = int(leer_config(con).get("respaldos_mantener") or 10)
    nombre = respaldos.crear_respaldo(current_app.config["DATABASE"],
                                      current_app.config["RESPALDOS"], mantener)
    con.execute("UPDATE config SET valor = ? WHERE clave = 'ultimo_respaldo'", (ahora(),))
    return jsonify(nombre=nombre), 201


@bp.get("/respaldos/<nombre>")
@solo_admin
def descargar_respaldo(nombre):
    if nombre not in {r["nombre"] for r in respaldos.listar(current_app.config["RESPALDOS"])}:
        raise ErrorNegocio("Respaldo no encontrado.", status=404)
    return send_from_directory(os.path.abspath(current_app.config["RESPALDOS"]), nombre,
                               as_attachment=True)
