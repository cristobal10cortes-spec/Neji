"""Vademécum: dosis habitual, importar y exportar en Excel o CSV, y el vademécum base en palabras simples."""

import csv
import io

from test_xlsx import planilla


def subir(api, contenido, nombre="vademecum.csv", modo="completar", crear=True, esperado=200):
    datos = {"archivo": (io.BytesIO(contenido), nombre), "modo": modo, "crear": "1" if crear else "0"}
    r = api.http.post("/api/principios/importar", data=datos, content_type="multipart/form-data")
    assert r.status_code == esperado, r.get_json()
    return r.get_json()


def principio(api, nombre):
    return next(p for p in api.get(f"/api/principios?q={nombre}") if p["nombre"] == nombre)


def csv_texto(*filas):
    salida = io.StringIO()
    csv.writer(salida, delimiter=";").writerows(filas)
    return ("﻿" + salida.getvalue()).encode("utf-8")


def test_la_ficha_tiene_dosis_habitual(api):
    pa = api.post("/api/principios", {"nombre": "Paracetamol", "accion_terapeutica": "Analgésico",
                                      "dosis": "Adultos: 500 mg a 1 g cada 6 a 8 horas."}, esperado=201)
    assert pa["dosis"] == "Adultos: 500 mg a 1 g cada 6 a 8 horas."
    pa = api.put(f"/api/principios/{pa['id']}", {"nombre": "PARACETAMOL", "accion_terapeutica": "Analgésico",
                                                 "dosis": "Máximo 4 g al día."})
    assert pa["dosis"] == "Máximo 4 g al día."


def test_vademecum_base_completa_respetando_lo_escrito_o_reemplaza(api):
    # Lo que ya tiene la farmacia: un principio con su sal (de un producto) y una ficha técnica.
    api.post("/api/productos", {"codigo": "7800010", "descripcion": "LOSARTAN 50MG X 30", "precio_venta": 2990,
                                "principios": "LOSARTAN POTASICO 50 mg"}, esperado=201)
    api.post("/api/principios", {"nombre": "PARACETAMOL", "accion_terapeutica": "Inhibidor de la COX-1 y COX-2"},
             esperado=201)
    r = api.post("/api/principios/base", {"modo": "completar"})
    assert r["creados"] > 150 and r["actualizados"] == 2 and r["errores"] == []
    # La ficha técnica se respeta; lo vacío (la dosis) se completa.
    para = principio(api, "PARACETAMOL")
    assert para["accion_terapeutica"] == "Inhibidor de la COX-1 y COX-2"
    assert "Máximo 4 g al día" in para["dosis"]
    # «LOSARTÁN» del vademécum completa «LOSARTAN POTASICO»: no se crea otro.
    losartan = [p for p in api.get("/api/principios?q=losartan")]
    assert [p["nombre"] for p in losartan] == ["LOSARTAN POTASICO"]
    assert losartan[0]["accion_terapeutica"].startswith("Antihipertensivo")
    assert losartan[0]["productos"] == 1
    # Los alias: «ASPIRINA» no existe aparte del ácido acetilsalicílico.
    assert api.get("/api/principios?q=aspirina") == []
    # Reemplazar: la ficha técnica pasa a la simple. Volver a cargar no cambia nada más.
    r = api.post("/api/principios/base", {"modo": "reemplazar"})
    assert r["creados"] == 0 and r["actualizados"] == 1
    assert principio(api, "PARACETAMOL")["accion_terapeutica"].startswith("Analgésico y antipirético")
    r = api.post("/api/principios/base", {"modo": "reemplazar"})
    assert r["actualizados"] == 0 and r["sin_cambios"] > 150


def test_exportar_corregir_e_importar(api):
    api.post("/api/principios", {"nombre": "IBUPROFENO", "accion_terapeutica": "AINE", "dosis": "400 mg cada 8 h",
                                 "unidad_receta": "mg", "precio_receta": 0.5}, esperado=201)
    r = api.http.get("/api/principios/exportar")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    filas = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert filas[0][:3] == ["Principio activo", "Para qué sirve", "Dosis habitual"]
    assert filas[1][:3] == ["IBUPROFENO", "AINE", "400 mg cada 8 h"] and filas[1][-2:] == ["mg", "0,5"]
    # Se corrige en Excel y se vuelve a subir: reemplazar cambia lo escrito, y la fila nueva se agrega.
    filas[1][1] = "Antiinflamatorio para el dolor y la fiebre."
    filas.append(["Naproxeno", "Antiinflamatorio de 12 horas.", "", "", "", "", "", ""])
    r = subir(api, csv_texto(*filas), modo="reemplazar")
    assert (r["creados"], r["actualizados"]) == (1, 1)
    ibu = principio(api, "IBUPROFENO")
    assert ibu["accion_terapeutica"] == "Antiinflamatorio para el dolor y la fiebre."
    assert (ibu["dosis"], ibu["unidad_receta"], ibu["precio_receta"]) == ("400 mg cada 8 h", "mg", 0.5)
    assert principio(api, "NAPROXENO")["accion_terapeutica"] == "Antiinflamatorio de 12 horas."


def test_importar_otros_titulos_y_excel(api):
    api.post("/api/principios", {"nombre": "OMEPRAZOL"}, esperado=201)
    contenido = planilla({1: ["Fármaco", "Indicaciones", "Posología", "Reacciones adversas"],
                          2: ["Omeprazol", "Protector gástrico.", "20 mg al día en ayunas.", "Cefalea."],
                          3: ["Cetirizina", "Antialérgico.", "10 mg al día.", None]})
    r = subir(api, contenido, "vademecum.xlsx", crear=False)
    assert (r["creados"], r["actualizados"]) == (0, 1)              # sin «agregar», la cetirizina no se crea
    ome = principio(api, "OMEPRAZOL")
    assert (ome["accion_terapeutica"], ome["dosis"], ome["efectos_adversos"]) == (
        "Protector gástrico.", "20 mg al día en ayunas.", "Cefalea.")
    assert api.get("/api/principios?q=cetirizina") == []


def test_planillas_que_no_sirven_y_permisos(api):
    r = subir(api, csv_texto(["Código", "Producto"], ["1", "X"]), esperado=400)
    assert "Principio activo" in r["error"]
    r = subir(api, csv_texto(["Principio activo", "Unidad recetario"], ["ZINC", "kg"]))
    assert r["errores"][0]["fila"] == 2 and "unidad" in r["errores"][0]["error"]
    api.post("/api/usuarios", {"usuario": "caja", "password": "1111", "rol": "cajero"}, esperado=201)
    api.post("/api/logout")
    api.post("/api/login", {"usuario": "caja", "password": "1111"})
    subir(api, csv_texto(["Principio activo"], ["ZINC"]), esperado=403)
    api.post("/api/principios/base", {"modo": "completar"}, esperado=403)
    assert api.http.get("/api/principios/exportar").status_code == 403


def test_el_vademecum_base_esta_completo():
    from pathlib import Path

    from neji.api.farmacia import _filas_vademecum

    archivo = Path(__file__).resolve().parent.parent / "neji" / "static" / "referencia" / "vademecum_base.csv"
    filas = _filas_vademecum(archivo.read_bytes())
    assert len(filas) >= 150
    for _, f in filas:
        assert f["nombre"] and f["accion_terapeutica"] and f["dosis"] and f["efectos_adversos"], f["nombre"]
        assert len(f["accion_terapeutica"]) <= 2000 and len(f["dosis"]) <= 2000
