import pytest

from neji import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATOS": str(tmp_path),
        "DATABASE": str(tmp_path / "neji.db"),
        "RESPALDOS": str(tmp_path / "respaldos"),
        "RESPALDO_AUTOMATICO": False,
        "SECRET_KEY": "pruebas",
    })


class Cliente:
    """Atajos para llamar la API y fallar con el mensaje del servidor."""

    def __init__(self, http):
        self.http = http

    def _ok(self, resp, esperado):
        assert resp.status_code == esperado, resp.get_json()
        return resp.get_json()

    def get(self, url, esperado=200, **kw):
        return self._ok(self.http.get(url, **kw), esperado)

    def post(self, url, datos=None, esperado=200, **kw):
        return self._ok(self.http.post(url, json=datos or {}, **kw), esperado)

    def put(self, url, datos=None, esperado=200):
        return self._ok(self.http.put(url, json=datos or {}), esperado)

    def delete(self, url, esperado=200):
        return self._ok(self.http.delete(url), esperado)


@pytest.fixture
def api(app):
    c = Cliente(app.test_client())
    c.post("/api/setup", {"negocio_nombre": "Almacén Prueba", "negocio_rut": "76.086.428-5",
                          "usuario": "admin", "nombre": "Dueño", "password": "1234"})
    return c


@pytest.fixture
def turno(api):
    return api.post("/api/caja/1/abrir", {"fondo_inicial": 10000}, esperado=201)["turno"]


@pytest.fixture
def productos(api):
    def crear(**datos):
        return api.post("/api/productos", datos, esperado=201)

    return {
        "bebida": crear(codigo="7801610001196", descripcion="Bebida cola 1.5L", precio_costo=900,
                        precio_venta=1590, precio_mayoreo=1390, cantidad_mayoreo=6, existencia=24,
                        minimo=6, departamento="Bebidas"),
        "pan": crear(codigo="PAN", descripcion="Pan batido", tipo_venta="granel", precio_costo=1200,
                     precio_venta=2290, existencia=10, minimo=2, departamento="Panadería"),
        "huevos": crear(codigo="HUEVO", descripcion="Huevo blanco", precio_costo=150, precio_venta=250,
                        existencia=3, exento=False),
        "recarga": crear(codigo="REC", descripcion="Recarga", precio_venta=1000, usa_inventario=False),
    }
