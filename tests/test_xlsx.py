"""Importar el inventario directo desde una planilla Excel (.xlsx), como la que exporta eleventa."""

import io
import zipfile
from xml.sax.saxutils import escape

from neji.xlsx import leer_xlsx

TIPOS = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/hoja.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
M = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def planilla(filas, fecha_1904=False):
    """Un .xlsx mínimo, como lo guarda Excel: textos compartidos, números, fechas con estilo y filas salteadas.

    `filas`: {número de fila: [celdas]}; una celda es texto (compartido), int/float (número), ("fecha", serial),
    ("inline", texto), ("numero", "texto tal como lo guarda Excel") o None (vacía, no se escribe).
    """
    compartidos, xml_filas = [], []
    for n, celdas in sorted(filas.items()):
        xml_celdas = []
        for i, c in enumerate(celdas):
            ref = f"{chr(65 + i)}{n}"
            if c is None:
                continue
            if isinstance(c, str):
                compartidos.append(c)
                xml_celdas.append(f'<c r="{ref}" t="s"><v>{len(compartidos) - 1}</v></c>')
            elif isinstance(c, tuple) and c[0] == "fecha":
                xml_celdas.append(f'<c r="{ref}" s="1"><v>{c[1]}</v></c>')
            elif isinstance(c, tuple) and c[0] == "numero":
                xml_celdas.append(f'<c r="{ref}"><v>{c[1]}</v></c>')
            elif isinstance(c, tuple) and c[0] == "inline":
                xml_celdas.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(c[1])}</t></is></c>')
            else:
                xml_celdas.append(f'<c r="{ref}"><v>{c}</v></c>')
        xml_filas.append(f'<row r="{n}">{"".join(xml_celdas)}</row>')
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", TIPOS)
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sistema = ' date1904="1"' if fecha_1904 else ""
        z.writestr("xl/workbook.xml", f'<workbook {M} {R}><workbookPr{sistema}/>'
                   '<sheets><sheet name="Inventario" sheetId="1" r:id="rIdHoja"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rIdHoja" Type="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships/worksheet" Target="worksheets/hoja.xml"/></Relationships>')
        z.writestr("xl/styles.xml", f'<styleSheet {M}><numFmts count="1"><numFmt numFmtId="164" '
                   'formatCode="dd/mm/yyyy"/></numFmts><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/>'
                   '</cellXfs></styleSheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst {M}>' + "".join(
            f"<si><t>{escape(t)}</t></si>" for t in compartidos) + "</sst>")
        z.writestr("xl/worksheets/hoja.xml", f'<worksheet {M}><sheetData>{"".join(xml_filas)}</sheetData></worksheet>')
    return salida.getvalue()


def importar(api, contenido, nombre="inventario.xlsx", existencias="reemplazar"):
    r = api.http.post("/api/productos/importar", data={"archivo": (io.BytesIO(contenido), nombre),
                                                        "existencias": existencias},
                      content_type="multipart/form-data")
    return r.status_code, r.get_json()


def test_lee_textos_numeros_fechas_y_filas_salteadas():
    filas = leer_xlsx(planilla({
        1: ["Inventario al 4-9-26"],
        3: ["Código", "Producto", None, "Existencia", "Vence"],
        4: [7800060005723, ("inline", "Ñandú & «Peña»"), 4990, 2.5, ("fecha", 46203)],
        5: ["0012", "Con cero adelante", 1234.5, 0.125, None],
        7: [None, None],
    }))
    assert filas == [
        ["Inventario al 4-9-26"], [],
        ["Código", "Producto", "", "Existencia", "Vence"],
        ["7800060005723", "Ñandú & «Peña»", "4990", "2,5", "2026-06-30"],
        ["0012", "Con cero adelante", "1234,5", "0,125"],
    ]
    # En el sistema de fechas de 1904 (Excel antiguo de Mac) el mismo número es otra fecha.
    assert leer_xlsx(planilla({1: [("fecha", 365)]}, fecha_1904=True)) == [["1904-12-31"]]


def test_numeros_grandes_sin_notacion_cientifica():
    # Excel puede guardar un código de barras numérico como 7.800060005723E12.
    assert leer_xlsx(planilla({1: [("numero", "7.800060005723E12"), ("numero", "1.5E-2")]})) == [
        ["7800060005723", "0,015"]]


def test_importa_el_excel_de_eleventa_tal_cual(api):
    """Las columnas, los «$2,830» y los «2.00» de eleventa; los departamentos repetidos quedan como uno."""
    contenido = planilla({
        1: ["Código", "Producto", "P. Costo", "P. Venta", "P. Mayoreo", "Existencia", "Inv. Mínimo",
            "Inv. Máximo", "Departamento"],
        2: ["7804640561364", "AZITROMICINA SUSP.200MG/5ML X 30ML", "$2,390", "$7,990", "$0", "3.00", "2", "10",
            "INYECTABLES"],
        3: ["7800001", "AMPOLLA VITAMINA B12", "$1,000", "$2,490", "$0", "1.00", "0", "0", "inyectable"],
        4: ["COBAN 2", "Venda Coban 5cm x 4,5mt", 3105, 4990, 0, 2, 0, 0, "Insumos Médicos"],
        5: ["7800002", "x" * 150, "$100", "$200", "$0", "1.00", "0", "0", "Insumos medicos"],
    })
    estado, r = importar(api, contenido)
    assert estado == 200, r
    assert (r["creados"], r["actualizados"]) == (4, 0)
    assert r["errores"] == [{"fila": 4, "error": "El código «COBAN 2» quedó como «COBAN2» (los códigos no llevan "
                                                "espacios)."}]
    azitro = api.get("/api/productos/codigo/7804640561364")
    assert (azitro["precio_costo"], azitro["precio_venta"], azitro["existencia"], azitro["minimo"], azitro["maximo"]) \
        == (2390, 7990, 3, 2, 10)
    assert api.get("/api/productos/codigo/COBAN2")["precio_venta"] == 4990
    assert len(api.get("/api/productos/codigo/7800002")["descripcion"]) == 150
    departamentos = sorted(d["nombre"] for d in api.get("/api/departamentos"))
    assert "INYECTABLES" in departamentos and "inyectable" not in departamentos
    assert "Insumos Médicos" in departamentos and "Insumos medicos" not in departamentos
    assert api.get("/api/productos/codigo/7800001")["departamento"] == "INYECTABLES"
    # Subirlo otra vez actualiza (no duplica) y «Se suma al stock» suma las existencias.
    estado, r = importar(api, contenido, existencias="sumar")
    assert (r["creados"], r["actualizados"]) == (0, 4)
    assert api.get("/api/productos/codigo/7804640561364")["existencia"] == 6


def test_planillas_que_no_sirven(api):
    estado, r = importar(api, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "viejo.xls")
    assert estado == 400 and ".xlsx" in r["error"]
    estado, r = importar(api, planilla({1: ["Nombre", "Precio"], 2: ["Algo", 100]}))
    assert estado == 400 and "código" in r["error"]
    estado, r = importar(api, b"PK\x03\x04 esto no es un zip")
    assert estado == 400 and "Excel" in r["error"]
    estado, r = importar(api, planilla({}))
    assert estado == 400 and "vacío" in r["error"]
