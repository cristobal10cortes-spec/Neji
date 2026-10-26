"""Protecciones: cabeceras, origen de los pedidos, dirección (DNS rebinding), sesiones, clave secreta y CSV."""

import sys

import pytest

from neji import proteccion


def test_cabeceras_de_seguridad(api):
    r = api.http.get("/")
    politica = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in politica and "frame-ancestors 'none'" in politica
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert api.http.get("/api/estado").headers["Cache-Control"] == "no-store"


def test_pedido_desde_otra_pagina_se_rechaza(api):
    r = api.http.post("/api/clientes", json={"nombre": "X"}, headers={"Origin": "https://malo.example"})
    assert r.status_code == 403 and "no viene de la página" in r.get_json()["error"]
    r = api.http.post("/api/clientes", json={"nombre": "X"}, headers={"Referer": "https://malo.example/a"})
    assert r.status_code == 403
    r = api.http.post("/api/clientes", json={"nombre": "X"}, headers={"Origin": "null"})
    assert r.status_code == 403
    r = api.http.post("/api/clientes", json={"nombre": "Bien"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 201
    # Los GET (leer) no cambian nada: no se revisan.
    assert api.http.get("/api/clientes", headers={"Origin": "https://malo.example"}).status_code == 200


@pytest.mark.parametrize("host,permitido", [
    ("localhost:5000", True), ("127.0.0.1:5000", True), ("192.168.1.20:5000", True), ("[::1]:5000", True),
    ("CAJA-PRINCIPAL:5000", True), ("farmacia.local:5000", True),
    ("ataque.example.com:5000", False), ("127.0.0.1.nip.io:5000", False)])
def test_dns_rebinding(api, host, permitido):
    r = api.http.get("/api/estado", headers={"Host": host})
    assert (r.status_code == 200) == permitido, r.get_json()


def test_pedido_json_demasiado_grande(api):
    r = api.http.post("/api/login", data=b"{" + b" " * (3 * 1024 * 1024) + b"}",
                      headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_cambiar_contrasena_cierra_las_otras_sesiones(app, api):
    cajero = api.post("/api/usuarios", {"usuario": "ana", "password": "clave1", "rol": "cajero"}, esperado=201)
    otra = app.test_client()
    assert otra.post("/api/login", json={"usuario": "ana", "password": "clave1"}).status_code == 200
    assert otra.get("/api/clientes").status_code == 200
    api.put(f"/api/usuarios/{cajero['id']}", {"password": "clave2"})
    r = otra.get("/api/clientes")
    assert r.status_code == 401 and r.get_json()["codigo"] == "sin_sesion"
    # El administrador que cambia su propia contraseña sigue dentro.
    yo = api.get("/api/estado")["usuario"]
    api.put(f"/api/usuarios/{yo['id']}", {"password": "nueva123"})
    assert api.get("/api/estado")["usuario"]["id"] == yo["id"]


def test_clave_secreta(tmp_path):
    clave = proteccion.clave_secreta(tmp_path)
    assert len(clave) == 64 and proteccion.clave_secreta(tmp_path) == clave
    guardado = (tmp_path / ".clave_secreta").read_bytes()
    if sys.platform == "win32":
        assert guardado.startswith(proteccion.PREFIJO) and clave.encode() not in guardado
    else:
        assert (tmp_path / ".clave_secreta").stat().st_mode & 0o777 == 0o600


def test_clave_secreta_antigua_se_conserva(tmp_path):
    (tmp_path / ".clave_secreta").write_text("a" * 64)
    assert proteccion.clave_secreta(tmp_path) == "a" * 64
    if sys.platform == "win32":                     # queda protegida con DPAPI
        assert (tmp_path / ".clave_secreta").read_bytes().startswith(proteccion.PREFIJO)
        assert proteccion.clave_secreta(tmp_path) == "a" * 64


def test_clave_de_otro_computador(tmp_path):
    (tmp_path / ".clave_secreta").write_bytes(proteccion.PREFIJO + b"no-es-de-este-equipo")
    nueva = proteccion.clave_secreta(tmp_path)
    assert len(nueva) == 64 and (tmp_path / ".clave_secreta.ilegible").exists()
