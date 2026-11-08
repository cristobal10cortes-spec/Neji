"""Vademécum: los productos quedan unidos solos a sus principios activos (por la descripción, la sal o una marca)."""

import io

import pytest

from conftest import Cliente
from neji.db import conectar
from neji.servicios.farmacia import Reconocedor


@pytest.fixture
def farmacia(app):
    """Un Neji nuevo configurado como farmacia: parte con el vademécum base."""
    c = Cliente(app.test_client())
    c.post("/api/setup", {"negocio_nombre": "Farmacia Prueba", "usuario": "admin", "nombre": "Dueño",
                          "password": "1234", "modulo_farmacia": True})
    return c


def producto(api, codigo, descripcion, **extra):
    return api.post("/api/productos", {"codigo": codigo, "descripcion": descripcion, "precio_venta": 1990, **extra},
                    esperado=201)


def nombres(api, q):
    return [p["nombre"] for p in api.get(f"/api/principios?q={q}")]


def test_una_farmacia_nueva_parte_con_el_vademecum_base(farmacia):
    principios = farmacia.get("/api/principios")
    assert len(principios) > 150
    assert farmacia.get("/api/config")["vademecum_base"] == "1"
    para = next(p for p in principios if p["nombre"] == "PARACETAMOL")
    assert "Máximo 4 g al día" in para["dosis"] and "ACETAMINOFENO" in para["otros_nombres"]


def test_al_activar_farmacia_se_carga_una_sola_vez(api):
    assert api.get("/api/principios") == []
    api.put("/api/config", {"modulo_farmacia": True})
    assert len(api.get("/api/principios")) > 150
    # Si la farmacia borra uno y vuelve a activar la opción, no reaparece.
    pa = next(p for p in api.get("/api/principios") if p["nombre"] == "ZOLPIDEM")
    api.delete(f"/api/principios/{pa['id']}")
    api.put("/api/config", {"modulo_farmacia": False})
    api.put("/api/config", {"modulo_farmacia": True})
    assert "ZOLPIDEM" not in nombres(api, "zolpidem")


@pytest.mark.parametrize("descripcion, esperado", [
    ("KITADOL 500 MG PARACETAMOL X 24 COMP", "PARACETAMOL 500 mg"),
    ("VALACICLOVIR 1G X 10", "VALACICLOVIR 1 g"),
    ("ACIDO FUSIDICO CREMA 2% 15G", "ÁCIDO FUSÍDICO 2%"),
    ("ACIDO FOLICO 1MG X 30", "ÁCIDO FÓLICO 1 mg"),
    ("Ácido fólico 0,4 mg x 30", "ÁCIDO FÓLICO 0,4 mg"),
    ("PARACETAMOL 500MG + CAFEINA 65MG X 20", "PARACETAMOL 500 mg + CAFEÍNA 65 mg"),
    ("TAPSIN DIA 500 MG PARACETAMOL 10 MG FENILEFRINA", "PARACETAMOL 500 mg + FENILEFRINA 10 mg"),
    ("PARACETAMOL JARABE 160MG/5ML 120ML", "PARACETAMOL 160 mg/5 ml"),
    ("LOSARTAN POTASICO 50MG X 30 COMP", "LOSARTÁN 50 mg"),
    ("ASPIRINA 100 MG X 30", "ÁCIDO ACETILSALICÍLICO 100 mg"),
    ("AMOXICILINA 500 MG + ACIDO CLAVULANICO 125 MG X 21", "AMOXICILINA 500 mg + ÁCIDO CLAVULÁNICO 125 mg"),
    ("SHAMPOO ANTICASPA 400 ML", ""),
    ("TOALLITAS HUMEDAS X 80", ""),
])
def test_reconoce_el_principio_activo_en_la_descripcion(app, farmacia, descripcion, esperado):
    con = conectar(app.config["DATABASE"])
    try:
        detectados = Reconocedor(con).detectar(descripcion)
    finally:
        con.close()
    assert " + ".join(d["nombre"] + (f" {d['concentracion']}" if d["concentracion"] else "")
                      for d in detectados) == esperado


def test_producto_nuevo_queda_unido_al_vademecum(farmacia):
    p = producto(farmacia, "7800001", "KITADOL 500 MG PARACETAMOL X 24 COMP")
    assert p["principios"] == "PARACETAMOL 500 mg" and p["principios_detectados"] == "PARACETAMOL 500 mg"
    assert p["principios_detalle"][0]["dosis"].startswith("Adultos")
    # Lo que se escribe a mano manda; con la sal, se une al mismo principio activo (no se crea otro).
    p = producto(farmacia, "7800002", "COZAAR 50MG X 30", principios="LOSARTAN POTASICO 50 mg")
    assert p["principios"] == "LOSARTÁN 50 mg"
    assert nombres(farmacia, "losartan") == ["LOSARTÁN"]
    # Una marca sin el principio activo en la descripción no se reconoce... hasta agregarla en «Otros nombres».
    assert producto(farmacia, "7800003", "ZOLOFT 50MG X 30")["principios"] is None
    sertralina = next(pa for pa in farmacia.get("/api/principios?q=sertralina") if pa["nombre"] == "SERTRALINA")
    farmacia.put(f"/api/principios/{sertralina['id']}", {**sertralina, "otros_nombres": "ZOLOFT | Altruline"})
    assert producto(farmacia, "7800004", "ALTRULINE 50MG X 30")["principios"] == "SERTRALINA 50 mg"


def test_sin_farmacia_no_se_busca(api):
    api.post("/api/principios", {"nombre": "PARACETAMOL"}, esperado=201)
    assert producto(api, "7800001", "PARACETAMOL 500MG X 16")["principios"] is None


def test_inventario_importado_queda_unido(farmacia):
    planilla = ("Código;Producto;P. Venta\n7801;KITADOL 500 MG PARACETAMOL X 24 COMP;2990\n"
                "7802;VALACICLOVIR 1G X 10;9990\n7803;CEPILLO DENTAL SUAVE;1490\n").encode("utf-8")
    r = farmacia.http.post("/api/productos/importar", data={"archivo": (io.BytesIO(planilla), "inventario.csv")},
                           content_type="multipart/form-data")
    datos = r.get_json()
    assert r.status_code == 200 and (datos["creados"], datos["vinculados"]) == (3, 2), datos
    assert farmacia.get("/api/productos/codigo/7802")["principios"] == "VALACICLOVIR 1 g"
    assert farmacia.get("/api/productos/codigo/7803")["principios"] is None


def test_vincular_el_inventario_que_ya_estaba(app, api):
    # Productos cargados antes de activar Farmacia: quedan sin principio activo.
    for codigo, desc in (("1", "KITADOL 500 MG PARACETAMOL X 24"), ("2", "IBUPROFENO 400MG X 20"),
                         ("3", "ALCOHOL GEL 500 ML")):
        producto(api, codigo, desc)
    api.put("/api/config", {"modulo_farmacia": True})
    r = api.get("/api/principios/vincular")
    assert [(s["codigo"], s["principios"]) for s in r["sugerencias"]] == [
        ("2", "IBUPROFENO 400 mg"), ("1", "PARACETAMOL 500 mg")]
    assert [p["codigo"] for p in r["sin_reconocer"]] == ["3"] and r["total_sin_reconocer"] == 1
    # Se vincula solo lo aprobado.
    ids = {s["codigo"]: s["id"] for s in r["sugerencias"]}
    assert api.post("/api/principios/vincular", {"ids": [ids["1"]]}) == {"vinculados": 1}
    assert api.get("/api/productos/codigo/1")["principios"] == "PARACETAMOL 500 mg"
    assert api.get("/api/productos/codigo/2")["principios"] is None
    assert [s["codigo"] for s in api.get("/api/principios/vincular")["sugerencias"]] == ["2"]
    assert "Elige" in api.post("/api/principios/vincular", {"ids": []}, esperado=400)["error"]
