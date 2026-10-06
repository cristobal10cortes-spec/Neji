import sys
import os
import sqlite3
import re
from datetime import datetime, timedelta, date

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QFrame, QAbstractItemView,
    QStackedWidget, QFormLayout, QSpinBox, QDoubleSpinBox, QTextEdit,
    QComboBox, QCheckBox, QDialog, QListWidget, QListWidgetItem,
    QTabWidget, QDateEdit, QSplitter, QInputDialog, QLayout, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QDate, QSizeF, QEvent
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QTextDocument, QPageSize

try:
    from PyQt6.QtPrintSupport import QPrinter
    HAS_PRINTER_SUPPORT = True
except ImportError:
    HAS_PRINTER_SUPPORT = False

import pyqtgraph as pg

RUTA_BASE_DATOS = 'corand_erp_pro.db'

# ==========================================
# ESTILOS Y CLASES AUXILIARES
# ==========================================
class EstilosGlobales:
    @staticmethod
    def obtener_paleta(es_claro):
        if es_claro:
            return {"bg": "#f0f2f5", "panel": "#ffffff", "text": "#333333", "input_bg": "#ffffff", "border": "#d1d5db", "accent": "#0078D7", "success": "#107c41", "danger": "#d13438", "warning": "#ffb900", "header": "#f3f4f6", "text_inv": "#ffffff", "alt_row": "#fafafa", "hover": "#e5f1fb"}
        else:
            return {"bg": "#1e1e1e", "panel": "#252526", "text": "#d4d4d4", "input_bg": "#3c3c3c", "border": "#454545", "accent": "#0078D7", "success": "#6A9955", "danger": "#f48771", "warning": "#cca700", "header": "#2d2d30", "text_inv": "#ffffff", "alt_row": "#2a2a2b", "hover": "#2a2d2e"}

    @staticmethod
    def generar_hoja_estilos(es_claro):
        c = EstilosGlobales.obtener_paleta(es_claro)
        return f"""
            QWidget {{ background-color: {c['bg']}; color: {c['text']}; font-family: 'Segoe UI', Arial, sans-serif; }}
            QFrame#panel, QFrame#panelDerecho, QFrame#loginPanel {{ background-color: {c['panel']}; border-radius: 8px; border: 1px solid {c['border']}; }}
            QLabel {{ background-color: transparent; border: none; }}

            QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QComboBox, QDateEdit {{
                background-color: {c['input_bg']}; color: {c['text']}; border: 1px solid {c['border']};
                padding: 6px; border-radius: 4px; font-size: 13px;
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 1px solid {c['accent']}; }}

            QPushButton {{ font-weight: bold; border-radius: 4px; color: {c['text_inv']}; border: none; padding: 6px 12px; }}
            QPushButton#btnMenu {{ background-color: transparent; text-align: left; padding-left: 15px; font-size: 14px; color: {c['text']}; border-radius: 6px; font-weight: normal; }}
            QPushButton#btnMenu:hover {{ background-color: {c['hover']}; color: {c['accent']}; }}
            QPushButton#btnAccion {{ background-color: {c['accent']}; color: #ffffff; }}
            QPushButton#btnAccion:hover {{ background-color: #005a9e; }}

            QTableWidget {{ background-color: {c['panel']}; color: {c['text']}; gridline-color: {c['border']}; border: 1px solid {c['border']}; font-size: 13px; selection-background-color: {c['accent']}; selection-color: white; alternate-background-color: {c['alt_row']}; }}
            QHeaderView::section {{ background-color: {c['header']}; color: {c['text']}; padding: 6px; font-weight: bold; border: none; border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['border']}; }}

            QTabBar::tab {{ background: {c['bg']}; color: {c['text']}; padding: 8px 15px; border-top-left-radius: 4px; border-top-right-radius: 4px; border: 1px solid {c['border']}; border-bottom: none; margin-right: 2px; }}
            QTabBar::tab:selected {{ background: {c['panel']}; font-weight: bold; border-top: 3px solid {c['accent']}; }}

            QListWidget {{ background-color: {c['panel']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 2px; font-size: 13px; color: {c['text']}; }}

            QLabel#lblExito {{ color: {c['success']}; font-weight: bold; }}
            QLabel#lblAlerta {{ color: {c['danger']}; font-weight: bold; }}
            QLabel#lblTotal {{ color: {c['success']}; font-size: 36px; font-weight: bold; }}
            QLabel#lblTitulo {{ color: {c['text']}; font-weight: bold; font-size: 18px; }}

            QFrame#ticketPreview {{ background-color: #ffffff; color: #000000; border: 1px dashed #999999; padding: 10px; }}
            QLineEdit#ticketInput {{ background-color: transparent; border: 1px dashed #dddddd; padding: 0px; color: #000000; font-family: monospace; font-size: 12px; }}
            QLineEdit#ticketInput:focus {{ border: 1px solid {c['accent']}; background-color: #f0f8ff; }}
        """

class LineEditEnter(QLineEdit):
    def __init__(self, accion=None, *args, **kwargs): super().__init__(*args, **kwargs); self.accion = accion
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.accion: self.accion()
            else: self.focusNextChild()
        else: super().keyPressEvent(event)

class ComboBoxEnter(QComboBox):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter): self.focusNextChild()
        else: super().keyPressEvent(event)

class MonedaEdit(QLineEdit):
    def __init__(self, accion=None, *args, **kwargs):
        super().__init__(*args, **kwargs); self.accion = accion; self.textEdited.connect(self.formatear)
    def formatear(self, text):
        val = text.replace('.', '').replace(',', '').replace('$', '').strip()
        val = val if val.isdigit() else '0'
        self.setText(f"{int(val):,}".replace(',', '.'))
    def valor(self):
        val = self.text().replace('.', '').replace(',', '').replace('$', '').strip()
        return float(val) if val.isdigit() else 0.0
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.accion: self.accion()
            else: self.focusNextChild()
        else: super().keyPressEvent(event)

class SpinBoxEnter(QSpinBox):
    def __init__(self, accion=None, *args, **kwargs): super().__init__(*args, **kwargs); self.accion = accion
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.accion: self.accion()
            else: self.focusNextChild()
        else: super().keyPressEvent(event)

class DSpinBoxEnter(QDoubleSpinBox):
    def __init__(self, accion=None, *args, **kwargs): super().__init__(*args, **kwargs); self.accion = accion
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.accion: self.accion()
            else: self.focusNextChild()
        else: super().keyPressEvent(event)

class EjeMoneda(pg.AxisItem):
    def tickStrings(self, values, scale, spacing): return [f"${int(value):,}".replace(',', '.') for value in values]

# ==========================================
# BASE DE DATOS
# ==========================================
class BaseDatos:
    def __init__(self, nombre_db=RUTA_BASE_DATOS):
        self.nombre_db = nombre_db if ('\\' in nombre_db or '/' in nombre_db) else os.path.join(os.path.abspath(os.path.dirname(__file__)), nombre_db)
        self.crear_tablas()
        self.sembrar_datos_iniciales()

    def conectar(self):
        con = sqlite3.connect(self.nombre_db, timeout=20.0)
        con.execute('PRAGMA journal_mode = WAL;')
        con.execute('PRAGMA synchronous = NORMAL;')
        return con

    def ejecutar_query(self, query, parametros=(), fetch=False):
        with self.conectar() as con:
            cursor = con.cursor(); cursor.execute(query, parametros)
            if fetch: return cursor.fetchall()
            con.commit()

    def ejecutar_muchos(self, query, lista_parametros):
        with self.conectar() as con:
            cur = con.cursor(); cur.execute('BEGIN TRANSACTION;'); cur.executemany(query, lista_parametros); con.commit()

    def crear_tablas(self):
        q = [
            '''CREATE TABLE IF NOT EXISTS usuarios (usuario TEXT PRIMARY KEY, password TEXT NOT NULL, rol TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS departamentos (nombre TEXT PRIMARY KEY)''',
            '''CREATE TABLE IF NOT EXISTS inventario (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL, costo REAL NOT NULL, precio_venta REAL NOT NULL, stock INTEGER NOT NULL, distribuidor TEXT DEFAULT '', departamento TEXT DEFAULT 'General', vencimiento TEXT DEFAULT '', principio_activo TEXT DEFAULT '')''',
            '''CREATE TABLE IF NOT EXISTS vademecum (principio_activo TEXT PRIMARY KEY, efecto_terapeutico TEXT, efectos_adversos TEXT, imagen TEXT DEFAULT '')''',
            '''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, total REAL NOT NULL, articulos INTEGER NOT NULL, caja TEXT NOT NULL DEFAULT 'Caja 1', metodo_pago TEXT NOT NULL DEFAULT 'Efectivo', tipo_operacion TEXT NOT NULL DEFAULT 'VENTA', usuario TEXT NOT NULL DEFAULT 'Admin', ticket_diario INTEGER DEFAULT 1)''',
            '''CREATE TABLE IF NOT EXISTS kardex (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, codigo TEXT NOT NULL, tipo_movimiento TEXT NOT NULL, motivo TEXT DEFAULT '', cantidad INTEGER NOT NULL, stock_resultante INTEGER NOT NULL, usuario TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS facturas_ingreso (numero TEXT, distribuidor TEXT, fecha TEXT, usuario TEXT, total REAL DEFAULT 0, PRIMARY KEY(numero, distribuidor))''',
            '''CREATE TABLE IF NOT EXISTS recetario_insumos (nombre TEXT PRIMARY KEY, unidad TEXT, precio REAL)''',
            '''CREATE TABLE IF NOT EXISTS recetario_formulas (nombre TEXT PRIMARY KEY, precio_base REAL, unidad TEXT, precio_unidad REAL)'''
        ]
        for query in q: self.ejecutar_query(query)

        for col in ['distribuidor', 'departamento', 'vencimiento', 'principio_activo']:
            try: self.ejecutar_query(f"ALTER TABLE inventario ADD COLUMN {col} TEXT DEFAULT ''")
            except: pass
        try: self.ejecutar_query("ALTER TABLE vademecum ADD COLUMN imagen TEXT DEFAULT ''")
        except: pass

    def sembrar_datos_iniciales(self):
        self.ejecutar_query("INSERT OR IGNORE INTO usuarios (usuario, password, rol) VALUES ('admin', 'admin', 'Administrador')")
        for d in ["General", "BIOEQUIVALENTES", "Naturales", "Marca", "Perfumeria", "Farmacia", "Insumos Medicos", "ANTICON Y HORMONAS", "Antibiotico", "Dermatologicos", "Inyectables"]:
            self.ejecutar_query('INSERT OR IGNORE INTO departamentos (nombre) VALUES (?)', (d,))

        configs = [
            ('nombre_caja', 'Caja 1'), ('tema_sistema', 'Claro'), ('foco_escaner', '1'), ('impresion_auto', '1'),
            ('ticket_empresa', 'FARMACIA EASYPHARMA LA SERENA'), ('ticket_rut', ''), ('ticket_direccion', 'Direccion Balmaceda 4521, local 4'),
            ('ticket_telefono', '+56971503275'), ('ticket_correo', 'easyfarmalaserena@gmail.com'), ('ticket_pie', 'Gracias por su compra'),
            ('ticket_largo', '120'), ('ticket_fuente', 'monospace'),
            ('ticket_lineas_top', '0'), ('ticket_lineas_bot', '2'), ('ticket_precio_unit', '1'), ('ticket_desc_comp', '0'), ('ticket_datos_cli', '0')
        ]
        for clave, valor in configs: self.ejecutar_query('INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)', (clave, valor))

        res_pa = self.ejecutar_query("SELECT count(*) FROM recetario_insumos", fetch=True)
        if res_pa and res_pa[0][0] == 0:
            defs = [
                ('Paracetamol', 'mg', 0.1), ('Biotina', 'mcg', 1.0),
                ('Vitamina C', 'gr', 38.87), ('Aloe Vera', 'mg', 0.3), ('Cafeina', 'mg', 0.2)
            ]
            self.ejecutar_muchos('INSERT INTO recetario_insumos (nombre, unidad, precio) VALUES (?, ?, ?)', defs)

        res_f = self.ejecutar_query("SELECT count(*) FROM recetario_formulas", fetch=True)
        if res_f and res_f[0][0] == 0:
            defs_f = [
                ('Cápsulas', 4000.0, 'Cápsulas', 40.0),
                ('Cremas', 4500.0, 'Gramos', 2.5),
                ('Lociones', 4000.0, 'Mililitros', 1.0)
            ]
            self.ejecutar_muchos('INSERT INTO recetario_formulas (nombre, precio_base, unidad, precio_unidad) VALUES (?, ?, ?, ?)', defs_f)

    def validar_login(self, usuario, password):
        if usuario.lower() == "master" and password == "corand2026": return "Administrador"
        res = self.ejecutar_query('SELECT rol FROM usuarios WHERE lower(usuario) = ? AND password = ?', (usuario.lower(), password), fetch=True)
        return res[0][0] if res else None

    def obtener_config(self, clave):
        res = self.ejecutar_query('SELECT valor FROM configuracion WHERE clave = ?', (clave,), fetch=True)
        return res[0][0] if res else ""

    def guardar_config(self, clave, valor):
        self.ejecutar_query('INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)', (clave, valor))

    def buscar_producto(self, codigo):
        res = self.ejecutar_query('SELECT nombre, costo, precio_venta, stock, distribuidor, departamento, vencimiento, principio_activo FROM inventario WHERE codigo = ?', (codigo,), fetch=True)
        return res[0] if res else None

    def ingresar_producto_manual(self, codigo, nombre, costo, precio, stock, distribuidor, departamento, principio, factura, usuario_actual, vencimiento=""):
        try:
            res = self.ejecutar_query('SELECT stock FROM inventario WHERE codigo = ?', (codigo,), fetch=True)
            s_ant = res[0][0] if res else 0; n_stock = s_ant + stock
            self.ejecutar_query('''INSERT INTO inventario (codigo, nombre, costo, precio_venta, stock, distribuidor, departamento, principio_activo, vencimiento) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(codigo) DO UPDATE SET nombre = excluded.nombre, costo = excluded.costo, precio_venta = excluded.precio_venta, stock = inventario.stock + excluded.stock, distribuidor = excluded.distribuidor, departamento = excluded.departamento, principio_activo = excluded.principio_activo, vencimiento = excluded.vencimiento''', (codigo, nombre, costo, precio, stock, distribuidor, departamento, principio, vencimiento))
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tipo = "INGRESO MANUAL" if not res else "ACTUALIZACIÓN STOCK"; motivo_kardex = f"Factura: {factura}" if factura else ""
            self.ejecutar_query('''INSERT INTO kardex (fecha, codigo, tipo_movimiento, motivo, cantidad, stock_resultante, usuario) VALUES (?, ?, ?, ?, ?, ?, ?)''', (fecha, codigo, tipo, motivo_kardex, stock, n_stock, usuario_actual))
            if factura and distribuidor: self.ejecutar_query('''INSERT INTO facturas_ingreso (numero, distribuidor, fecha, usuario, total) VALUES (?, ?, ?, ?, ?) ON CONFLICT(numero, distribuidor) DO UPDATE SET total = facturas_ingreso.total + excluded.total''', (factura, distribuidor, fecha, usuario_actual, costo * stock))
            return True, "Producto ingresado correctamente."
        except Exception as e: return False, str(e)

    def modificar_producto_existente(self, codigo, nombre, costo, precio, distribuidor, departamento, principio):
        try:
            self.ejecutar_query('UPDATE inventario SET nombre = ?, costo = ?, precio_venta = ?, distribuidor = ?, departamento = ?, principio_activo = ? WHERE codigo = ?', (nombre, costo, precio, distribuidor, departamento, principio, codigo))
            return True, "Producto modificado."
        except Exception as e: return False, str(e)

    def dar_baja_producto(self, codigo, cantidad, motivo, usuario_actual):
        try:
            res = self.ejecutar_query('SELECT stock FROM inventario WHERE codigo = ?', (codigo,), fetch=True)
            if not res: return False, "El producto no existe."
            s_act = res[0][0]
            if cantidad > s_act: return False, "No hay suficiente stock."
            n_stock = s_act - cantidad
            self.ejecutar_query('UPDATE inventario SET stock = ? WHERE codigo = ?', (n_stock, codigo))
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.ejecutar_query('''INSERT INTO kardex (fecha, codigo, tipo_movimiento, motivo, cantidad, stock_resultante, usuario) VALUES (?, ?, ?, ?, ?, ?, ?)''', (fecha, codigo, "BAJA / MERMA", motivo, cantidad, n_stock, usuario_actual))
            return True, f"Baja registrada. Stock restante: {n_stock}"
        except Exception as e: return False, str(e)

    def registrar_venta(self, total, arts, detalles, metodo_pago, tipo_operacion, usuario):
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S"); caja = self.obtener_config('nombre_caja')
        with self.conectar() as con:
            cur = con.cursor(); cur.execute("BEGIN TRANSACTION;")
            res = cur.execute("SELECT MAX(ticket_diario) FROM ventas WHERE substr(fecha, 1, 10) = ? AND caja = ?", (fecha[:10], caja)).fetchone()
            tkt = (int(res[0]) if res[0] else 0) + 1
            cur.execute('INSERT INTO ventas (fecha, total, articulos, caja, metodo_pago, tipo_operacion, usuario, ticket_diario) VALUES (?,?,?,?,?,?,?,?)', (fecha, total, arts, caja, metodo_pago, tipo_operacion, usuario, tkt))
            for cod, cant in detalles:
                if cod == "RM-001" or cod == "ENV-001": continue
                stock_res = cur.execute('SELECT stock FROM inventario WHERE codigo = ?', (cod,)).fetchone()
                if stock_res:
                    n_stock = stock_res[0] - cant if tipo_operacion == "VENTA" else stock_res[0] + cant
                    cur.execute('UPDATE inventario SET stock = ? WHERE codigo = ?', (n_stock, cod))
                    cur.execute('''INSERT INTO kardex (fecha, codigo, tipo_movimiento, motivo, cantidad, stock_resultante, usuario) VALUES (?, ?, ?, '', ?, ?, ?)''', (fecha, cod, f"{tipo_operacion} ({caja})", cant, n_stock, usuario))
            con.commit()
            return tkt

# ==========================================
# DIÁLOGOS
# ==========================================
class DialogoEnvio(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Costo de Envío"); self.setFixedSize(300, 150); lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Ingrese el monto del envío ($):")); self.txt_monto = MonedaEdit(self.accept); self.txt_monto.setStyleSheet("font-size: 20px; padding: 5px;"); lay.addWidget(self.txt_monto)
        btn = QPushButton("Agregar al POS (Enter)"); btn.setObjectName("btnAccion"); btn.clicked.connect(self.accept); lay.addWidget(btn); self.txt_monto.setFocus()
    def obtener_monto(self): return self.txt_monto.valor()

class DialogoCodigoCantidad(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Ingreso Manual (Ctrl+V)"); self.setFixedSize(300, 200); lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Código del producto:")); self.txt_cod = LineEditEnter(self.foco_cant); self.txt_cod.setStyleSheet("font-size: 16px; padding: 5px;"); lay.addWidget(self.txt_cod)
        lay.addWidget(QLabel("Cantidad a ingresar:")); self.sp_cant = SpinBoxEnter(self.accept); self.sp_cant.setRange(1, 9999); self.sp_cant.setValue(1); self.sp_cant.setStyleSheet("font-size: 20px; padding: 5px;"); lay.addWidget(self.sp_cant)
        btn = QPushButton("Aceptar (Enter)"); btn.setObjectName("btnAccion"); btn.clicked.connect(self.accept); lay.addWidget(btn)
    def foco_cant(self): self.sp_cant.setFocus(); self.sp_cant.selectAll()

class DialogoModificarPrecio(QDialog):
    def __init__(self, nombre, precio_actual, es_claro, parent=None):
        super().__init__(parent); self.setWindowTitle("Modificar Precio"); self.setFixedSize(300, 150); self.setStyleSheet(EstilosGlobales.generar_hoja_estilos(es_claro)); lay = QVBoxLayout(self); lay.addWidget(QLabel(f"Nuevo precio para:\n{nombre}")); self.sp_precio = QDoubleSpinBox(); self.sp_precio.setRange(0, 9999999); self.sp_precio.setDecimals(0); self.sp_precio.setValue(precio_actual); self.sp_precio.setStyleSheet("font-size: 20px; padding: 5px;"); lay.addWidget(self.sp_precio); btn_ok = QPushButton("Guardar (Enter)"); btn_ok.setObjectName("btnAccion"); btn_ok.clicked.connect(self.accept); lay.addWidget(btn_ok); self.sp_precio.setFocus(); self.sp_precio.selectAll()
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter): self.accept()
        else: super().keyPressEvent(event)

class DialogoBuscadorProductos(QDialog):
    def __init__(self, db, es_claro, parent=None):
        super().__init__(parent)
        self.db = db
        self.es_claro = es_claro
        self.codigo_seleccionado = None
        self.setWindowTitle("🔍 Buscador de Productos Clínico")
        self.resize(1100, 500)
        lay_izq = QVBoxLayout(self)

        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Escriba nombre/código, o inicie con '%' para buscar por Componente (ej. %paracetamol)...")
        self.txt_buscar.textChanged.connect(self.buscar)
        self.txt_buscar.installEventFilter(self)
        lay_izq.addWidget(self.txt_buscar)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["CÓDIGO", "PRODUCTO", "STOCK", "PRECIO", "INFO. CLÍNICA / P.A."])
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.itemDoubleClicked.connect(self.seleccionar)
        lay_izq.addWidget(self.tabla)

        self.txt_buscar.setFocus()

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.KeyPress and source is self.txt_buscar and event.key() == Qt.Key.Key_Down and self.tabla.rowCount() > 0:
            self.tabla.setFocus()
            self.tabla.selectRow(0)
            return True
        return super().eventFilter(source, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.tabla.hasFocus(): self.seleccionar()
            else: self.buscar()
        elif event.key() == Qt.Key.Key_Escape: self.reject()
        else: super().keyPressEvent(event)

    def buscar(self):
        txt = self.txt_buscar.text().strip()

        if len(txt) < 2 and not txt.startswith('%'):
            return self.tabla.setRowCount(0)

        if txt.startswith('%'):
            termino = txt[1:].strip()
            if not termino: return self.tabla.setRowCount(0)

            query = """
                SELECT i.codigo, i.nombre, i.stock, i.precio_venta, i.principio_activo, v.efecto_terapeutico
                FROM inventario i
                LEFT JOIN vademecum v ON i.principio_activo = v.principio_activo
                WHERE i.nombre LIKE ? OR i.principio_activo LIKE ?
                LIMIT 50
            """
            params = (f"%{termino}%", f"%{termino}%")
        else:
            query = """
                SELECT i.codigo, i.nombre, i.stock, i.precio_venta, i.principio_activo, v.efecto_terapeutico
                FROM inventario i
                LEFT JOIN vademecum v ON i.principio_activo = v.principio_activo
                WHERE i.nombre LIKE ? OR i.codigo LIKE ?
                LIMIT 50
            """
            params = (f"%{txt}%", f"%{txt}%")

        datos = self.db.ejecutar_query(query, params, fetch=True)
        self.tabla.setRowCount(0)
        c = EstilosGlobales.obtener_paleta(self.es_claro)

        for r, d in enumerate(datos):
            self.tabla.insertRow(r)
            self.tabla.setItem(r, 0, QTableWidgetItem(str(d[0])))
            self.tabla.setItem(r, 1, QTableWidgetItem(str(d[1])))

            it_stock = QTableWidgetItem(str(d[2]))
            it_stock.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if int(d[2]) <= 0: it_stock.setForeground(QColor(c['danger']))
            self.tabla.setItem(r, 2, it_stock)

            it_precio = QTableWidgetItem(f"${d[3]:,.0f}".replace(',', '.'))
            it_precio.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabla.setItem(r, 3, it_precio)

            pa = d[4] if d[4] else ""
            efecto = d[5] if d[5] else ""

            if pa and efecto: info = f"{pa} - {efecto}"
            elif pa: info = pa
            else: info = "-"

            it_info = QTableWidgetItem(info)
            it_info.setForeground(QColor("#0078D7") if self.es_claro else QColor("#4da6ff"))
            self.tabla.setItem(r, 4, it_info)

    def seleccionar(self):
        if self.tabla.currentRow() >= 0:
            self.codigo_seleccionado = self.tabla.item(self.tabla.currentRow(), 0).text()
            self.accept()

class DialogoCobro(QDialog):
    def __init__(self, total, es_claro, parent=None):
        super().__init__(parent)

        # --- SOLUCION AL BLOQUEO DE CLICS ---
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.total = total; self.c = EstilosGlobales.obtener_paleta(es_claro)
        self.metodos = ["Efectivo", "Tarjeta de Crédito", "Transferencia", "Mixto"]
        self.setWindowTitle("Procesar Pago"); self.resize(550, 420); lay = QVBoxLayout(self)

        lbl_tit = QLabel(f"TOTAL A COBRAR:\n${self.total:,.0f}".replace(',', '.')); lbl_tit.setObjectName("lblTotal"); lbl_tit.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(lbl_tit)

        main_h = QHBoxLayout()
        self.lista_pagos = QListWidget()
        self.lista_pagos.addItems(self.metodos)
        self.lista_pagos.setFixedWidth(200)
        self.lista_pagos.setStyleSheet(f"QListWidget {{ font-size: 15px; background-color: {self.c['input_bg']}; }} QListWidget::item {{ padding: 15px; border-bottom: 1px solid {self.c['border']}; }} QListWidget::item:selected {{ background-color: {self.c['accent']}; color: white; font-weight: bold; }}")
        self.lista_pagos.currentRowChanged.connect(self.cambiar_metodo)
        main_h.addWidget(self.lista_pagos)

        self.panel_dinamico = QStackedWidget(); main_h.addWidget(self.panel_dinamico); lay.addLayout(main_h)

        self.w_ef = QWidget(); lay_ef = QFormLayout(self.w_ef)
        self.txt_recibido = MonedaEdit(self.validar_y_aceptar); self.txt_recibido.setText(f"{int(self.total):,}".replace(',', '.')); self.txt_recibido.textChanged.connect(self.calcular_vuelto); self.lbl_vuelto = QLabel("$0"); self.lbl_vuelto.setObjectName("lblExito")
        lay_ef.addRow("Monto Recibido ($):", self.txt_recibido); lay_ef.addRow("Vuelto a entregar:", self.lbl_vuelto); self.panel_dinamico.addWidget(self.w_ef)

        self.w_ot = QWidget(); lay_ot = QVBoxLayout(self.w_ot); self.lbl_aviso = QLabel("⚠️ Verifique pago en POS/Terminal."); self.lbl_aviso.setObjectName("lblAlerta"); self.lbl_aviso.setAlignment(Qt.AlignmentFlag.AlignCenter); lay_ot.addWidget(self.lbl_aviso); self.panel_dinamico.addWidget(self.w_ot)

        self.w_mix = QWidget(); lay_mix = QFormLayout(self.w_mix)
        self.txt_mix_ef = MonedaEdit(self.validar_y_aceptar); self.txt_mix_ef.setText("0"); self.txt_mix_ef.textChanged.connect(self.calc_mixto)
        self.txt_mix_tj = MonedaEdit(self.validar_y_aceptar); self.txt_mix_tj.setText("0"); self.txt_mix_tj.textChanged.connect(self.calc_mixto)
        self.lbl_mix_rest = QLabel(f"${self.total:,.0f}".replace(',','.')); self.lbl_mix_rest.setStyleSheet("color: red; font-weight: bold; font-size: 16px;")
        lay_mix.addRow("Parte en Efectivo ($):", self.txt_mix_ef); lay_mix.addRow("Parte en Tarjeta ($):", self.txt_mix_tj); lay_mix.addRow("Resta por pagar:", self.lbl_mix_rest); self.panel_dinamico.addWidget(self.w_mix)

        btn_box = QHBoxLayout(); btn_cancel = QPushButton("Cancelar (Esc)"); btn_cancel.setStyleSheet(f"background-color: {self.c['danger']}; padding: 15px; font-size: 15px; color: white;"); btn_cancel.clicked.connect(self.reject); self.btn_ok = QPushButton("CONFIRMAR PAGO (Enter)"); self.btn_ok.setStyleSheet(f"background-color: {self.c['success']}; padding: 15px; font-size: 15px; color: white;"); self.btn_ok.setDefault(True); self.btn_ok.clicked.connect(self.validar_y_aceptar); btn_box.addWidget(btn_cancel); btn_box.addWidget(self.btn_ok); lay.addLayout(btn_box)

        self.lista_pagos.setCurrentRow(0); self.lista_pagos.setFocus()

    def cambiar_metodo(self, idx):
        if idx < 0: return
        nom = self.metodos[idx]
        if nom == "Efectivo": self.panel_dinamico.setCurrentWidget(self.w_ef)
        elif nom == "Mixto": self.panel_dinamico.setCurrentWidget(self.w_mix)
        else: self.panel_dinamico.setCurrentWidget(self.w_ot)

    def calc_mixto(self):
        suma = self.txt_mix_ef.valor() + self.txt_mix_tj.valor(); rest = self.total - suma
        if rest > 0: self.lbl_mix_rest.setText(f"Faltan: ${rest:,.0f}".replace(',','.')); self.lbl_mix_rest.setStyleSheet("color: red; font-weight: bold; font-size: 16px;")
        else: self.lbl_mix_rest.setText(f"Vuelto: ${abs(rest):,.0f}".replace(',','.')); self.lbl_mix_rest.setStyleSheet("color: green; font-weight: bold; font-size: 16px;")

    def calcular_vuelto(self):
        v = self.txt_recibido.valor() - self.total
        if v < 0: self.lbl_vuelto.setText("Insuficiente"); self.lbl_vuelto.setStyleSheet(f"color: {self.c['danger']}; font-weight:bold; font-size: 20px;")
        else: self.lbl_vuelto.setText(f"${int(v):,}".replace(',', '.')); self.lbl_vuelto.setStyleSheet(f"color: {self.c['success']}; font-weight:bold; font-size: 20px;")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.lista_pagos.hasFocus():
                if self.panel_dinamico.currentWidget() == self.w_ef:
                    self.txt_recibido.setFocus(); self.txt_recibido.selectAll()
                elif self.panel_dinamico.currentWidget() == self.w_mix:
                    self.txt_mix_ef.setFocus(); self.txt_mix_ef.selectAll()
                else:
                    self.validar_y_aceptar()
            else:
                self.validar_y_aceptar()
        elif event.key() == Qt.Key.Key_Escape: self.reject()
        else: super().keyPressEvent(event)

    def validar_y_aceptar(self):
        if not self.lista_pagos.currentItem(): return
        m = self.lista_pagos.currentItem().text()
        if m == "Efectivo" and self.txt_recibido.valor() < self.total: return QMessageBox.warning(self, "Error", "Monto insuficiente en Efectivo.")
        if m == "Mixto" and (self.txt_mix_ef.valor() + self.txt_mix_tj.valor() < self.total): return QMessageBox.warning(self, "Error", "La suma del pago mixto no cubre el total.")
        self.metodo_seleccionado = m; self.accept()

# ==========================================
# CAJA (PUNTO DE VENTA)
# ==========================================
class PantallaCaja(QWidget):
    def __init__(self, db, mw):
        super().__init__()
        self.db = db; self.mw = mw; self.caja_abierta = True; self.cantidad_temporal = 1
        self.crear_ui()
        self.actualizar_estado()

        self.atajo_ctrl_v = QShortcut(QKeySequence("Ctrl+V"), self)
        self.atajo_ctrl_v.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.atajo_ctrl_v.activated.connect(self.abrir_multiplicador)

        self.atajo_ctrl_e = QShortcut(QKeySequence("Ctrl+E"), self)
        self.atajo_ctrl_e.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.atajo_ctrl_e.activated.connect(self.abrir_ventana_envio)

        self.timer_foco = QTimer(self)
        self.timer_foco.timeout.connect(self.mantener_foco_escaner)
        self.timer_foco.start(500)

    def mantener_foco_escaner(self):
        if self.caja_abierta and self.isVisible() and not QApplication.activeModalWidget():
            foco = QApplication.focusWidget()
            if not isinstance(foco, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QAbstractItemView, QComboBox)):
                self.txt_codigo.setFocus()

    def al_mostrar(self): self.forzar_foco(); self.cargar_ultimas_ventas()

    def forzar_foco(self):
        if self.caja_abierta: self.txt_codigo.setFocus()

    def abrir_buscador(self):
        if not self.caja_abierta: return
        dlg = DialogoBuscadorProductos(self.db, self.mw.es_claro, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.codigo_seleccionado: self.txt_codigo.setText(dlg.codigo_seleccionado); self.procesar_codigo()
        self.forzar_foco()

    def abrir_multiplicador(self):
        if not self.caja_abierta: return
        dlg = DialogoCodigoCantidad(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cod = dlg.txt_cod.text().strip()
            cant = dlg.sp_cant.value()
            if cod:
                self.txt_codigo.setText(cod)
                self.cantidad_temporal = cant
                self.procesar_codigo()
        self.forzar_foco()

    def abrir_ventana_envio(self):
        if not self.caja_abierta: return
        dlg = DialogoEnvio(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            monto = dlg.obtener_monto()
            if monto > 0:
                self.agregar_item_especial("ENV-001", "COSTO DE ENVÍO", monto, 1)
        self.forzar_foco()

    def eliminar_fila(self):
        if self.caja_abierta and self.tabla.currentRow() >= 0:
            self.tabla.removeRow(self.tabla.currentRow())
            self.calcular_totales()
            self.forzar_foco()

    def aumentar_cantidad(self):
        if not self.caja_abierta: return
        r = self.tabla.currentRow()
        if r >= 0:
            cod = self.tabla.item(r, 0).text()
            cant = int(self.tabla.item(r, 2).text())

            if cod not in ["RM-001", "ENV-001"] and not self.check_dev.isChecked():
                prod = self.db.buscar_producto(cod)
                if prod and (cant + 1) > int(prod[3]):
                    QMessageBox.warning(self, "Stock Insuficiente", f"No hay más stock disponible para '{prod[0]}'.")
                    return

            nueva_cant = cant + 1
            self.tabla.item(r, 2).setText(str(nueva_cant))
            precio_unit = float(self.tabla.item(r, 3).text().replace('$', '').replace('.', '').strip())
            self.tabla.item(r, 4).setText(f"${int(nueva_cant * precio_unit):,}".replace(',', '.'))
            self.calcular_totales()
            self.forzar_foco()

    def disminuir_cantidad(self):
        if not self.caja_abierta: return
        r = self.tabla.currentRow()
        if r >= 0:
            cant = int(self.tabla.item(r, 2).text())
            if cant > 1:
                nueva_cant = cant - 1
                self.tabla.item(r, 2).setText(str(nueva_cant))
                precio_unit = float(self.tabla.item(r, 3).text().replace('$', '').replace('.', '').strip())
                self.tabla.item(r, 4).setText(f"${int(nueva_cant * precio_unit):,}".replace(',', '.'))
                self.calcular_totales()
                self.forzar_foco()
            else:
                self.eliminar_fila()

    def modificar_precio_item(self, item):
        if not self.caja_abierta: return
        r = item.row(); nombre = self.tabla.item(r, 1).text(); precio_actual = float(self.tabla.item(r, 3).text().replace('$', '').replace('.', '').strip()); dlg = DialogoModificarPrecio(nombre, precio_actual, self.mw.es_claro, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            nuevo_precio = dlg.sp_precio.value(); cant = int(self.tabla.item(r, 2).text())
            it_p = QTableWidgetItem(f"${int(nuevo_precio):,}".replace(',', '.')); it_p.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tabla.setItem(r, 3, it_p)
            it_s = QTableWidgetItem(f"${int(nuevo_precio * cant):,}".replace(',', '.')); it_s.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tabla.setItem(r, 4, it_s)
            self.calcular_totales()
        self.forzar_foco()

    def crear_ui(self):
        lay = QHBoxLayout(self); panel_izq = QVBoxLayout(); marco_busq = QFrame(); marco_busq.setObjectName("panel"); lay_busq = QHBoxLayout(marco_busq); lay_busq.addWidget(QLabel("🔍 ESCANEAR:"))
        self.txt_codigo = QLineEdit(self); self.txt_codigo.returnPressed.connect(self.procesar_codigo);
        btn_buscar = QPushButton(" Buscar (F10)")
        btn_buscar.setObjectName("btnAccion"); btn_buscar.clicked.connect(self.abrir_buscador);

        btn_mul = QPushButton(" Ingreso Manual (Ctrl+V)")
        btn_mul.setStyleSheet("background-color: #ffb900; color: black;")
        btn_mul.clicked.connect(self.abrir_multiplicador)

        btn_envio = QPushButton(" 🚚 Envío (Ctrl+E)")
        btn_envio.setStyleSheet("background-color: #008080; color: white;")
        btn_envio.clicked.connect(self.abrir_ventana_envio)

        self.check_dev = QCheckBox(" Devolución"); self.check_dev.setObjectName("lblAlerta"); self.check_dev.toggled.connect(self.calcular_totales); lay_busq.addWidget(self.txt_codigo); lay_busq.addWidget(btn_buscar); lay_busq.addWidget(btn_mul); lay_busq.addWidget(btn_envio); lay_busq.addWidget(self.check_dev); panel_izq.addWidget(marco_busq)

        self.lbl_vademecum = QLabel(""); self.lbl_vademecum.setStyleSheet("background-color: #fff3cd; color: #856404; padding: 5px; border-radius: 4px; font-weight: bold; border: 1px solid #ffeeba;")
        self.lbl_vademecum.hide(); panel_izq.addWidget(self.lbl_vademecum)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["CÓDIGO", "PRODUCTO", "CANT.", "P. UNIT", "SUBTOTAL"])
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.itemDoubleClicked.connect(self.modificar_precio_item)

        atajo_del = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tabla)
        atajo_del.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        atajo_del.activated.connect(self.eliminar_fila)

        atajo_mas = QShortcut(QKeySequence("+"), self.tabla)
        atajo_mas.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        atajo_mas.activated.connect(self.aumentar_cantidad)

        atajo_menos = QShortcut(QKeySequence("-"), self.tabla)
        atajo_menos.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        atajo_menos.activated.connect(self.disminuir_cantidad)

        panel_izq.addWidget(self.tabla); lay.addLayout(panel_izq, stretch=7)
        panel_der = QFrame(); panel_der.setObjectName("panelDerecho"); panel_der.setFixedWidth(320); lay_d = QVBoxLayout(panel_der); lay_ult = QHBoxLayout(); lay_ult.addWidget(QLabel("🕒 ÚLTIMAS VENTAS")); btn_re = QPushButton("🖨️ Reimprimir"); btn_re.clicked.connect(self.reimprimir_ultimo); lay_ult.addWidget(btn_re); lay_d.addLayout(lay_ult); self.lista_ultimas = QListWidget(); self.lista_ultimas.setFixedHeight(90); self.lista_ultimas.itemDoubleClicked.connect(self.reimprimir_seleccionado); lay_d.addWidget(self.lista_ultimas); lay_d.addWidget(QLabel("🛒 TICKET ACTUAL")); self.lista_ticket = QListWidget(); self.lista_ticket.setFixedHeight(90); lay_d.addWidget(self.lista_ticket); self.lbl_items = QLabel("Artículos físicos: 0"); lay_d.addWidget(self.lbl_items); lay_d.addStretch(); self.lbl_total = QLabel("$0"); self.lbl_total.setObjectName("lblTotal"); self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignCenter); lay_d.addWidget(self.lbl_total); lay_d.addStretch(); self.btn_estado = QPushButton(); self.btn_estado.setFixedHeight(40); self.btn_estado.clicked.connect(self.alternar_estado); lay_d.addWidget(self.btn_estado)

        self.btn_cobrar = QPushButton("F12 - COBRAR")
        self.btn_cobrar.setFixedHeight(60)
        self.btn_cobrar.setStyleSheet("background-color: #107c41; color: white; font-size: 16px; font-weight: bold;")
        self.btn_cobrar.clicked.connect(self.cobrar)
        lay_d.addWidget(self.btn_cobrar); lay.addWidget(panel_der)

    def agregar_item_especial(self, codigo, nombre, precio_total, cantidad=1):
        if not self.caja_abierta: return
        self.tabla.insertRow(self.tabla.rowCount())
        r = self.tabla.rowCount() - 1
        self.tabla.setItem(r, 0, QTableWidgetItem(str(codigo)))
        self.tabla.setItem(r, 1, QTableWidgetItem(str(nombre)))

        it_cant = QTableWidgetItem(str(cantidad))
        it_cant.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tabla.setItem(r, 2, it_cant)

        it_p = QTableWidgetItem(f"${int(precio_total):,}".replace(',', '.'))
        it_p.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tabla.setItem(r, 3, it_p)

        it_s = QTableWidgetItem(f"${int(precio_total):,}".replace(',', '.'))
        it_s.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tabla.setItem(r, 4, it_s)

        self.calcular_totales()
        self.forzar_foco()

    def reimprimir_seleccionado(self, item):
        f_ex = item.data(Qt.ItemDataRole.UserRole)
        if f_ex and QMessageBox.question(self, "Reimprimir", "¿Desea reimprimir este comprobante?") == QMessageBox.StandardButton.Yes: self.reimprimir_ticket_por_fecha(f_ex)
    def reimprimir_ultimo(self):
        if self.lista_ultimas.count() > 0: self.reimprimir_ticket_por_fecha(self.lista_ultimas.item(0).data(Qt.ItemDataRole.UserRole))
    def reimprimir_ticket_por_fecha(self, f_ex):
        venta = self.db.ejecutar_query("SELECT ticket_diario, tipo_operacion, metodo_pago, total, articulos FROM ventas WHERE fecha = ? AND caja = ?", (f_ex, self.db.obtener_config('nombre_caja')), fetch=True)
        if not venta: return
        tkt, tipo, metodo, tot, arts = venta[0]; datos_k = self.db.ejecutar_query('''SELECT k.codigo, i.nombre, k.cantidad, (k.cantidad * i.precio_venta) FROM kardex k LEFT JOIN inventario i ON k.codigo = i.codigo WHERE k.fecha = ? AND k.tipo_movimiento LIKE ?''', (f_ex, f"{tipo}%"), fetch=True); det_imp = []; suma = 0.0
        for d in datos_k: subt = float(d[3] or 0); suma += subt; det_imp.append({'codigo': d[0], 'producto': str(d[1] or d[0]), 'cant': int(d[2]), 'subtotal': subt})
        if suma < float(tot): det_imp.append({'codigo': 'RM/OTROS', 'producto': 'ART. ESPECIAL', 'cant': 1, 'subtotal': float(tot) - suma})
        self.imprimir_ticket_generico(det_imp, float(tot), tkt, tipo, metodo, int(arts), es_reimpresion=True)
    def cargar_ultimas_ventas(self):
        self.lista_ultimas.clear(); hoy = datetime.now().strftime("%Y-%m-%d")
        for tkt, tot, hora, tipo, f_ex in self.db.ejecutar_query('''SELECT ticket_diario, total, substr(fecha,12,5), tipo_operacion, fecha FROM ventas WHERE fecha LIKE ? AND caja = ? ORDER BY id DESC LIMIT 8''', (f"{hoy}%", self.db.obtener_config('nombre_caja')), fetch=True):
            simbolo = "-" if tipo == "DEVOLUCION" else ""
            item = QListWidgetItem(f"🎫 TKT #{tkt} | {hora} | {simbolo}${tot:,.0f}".replace(',', '.'))
            item.setData(Qt.ItemDataRole.UserRole, f_ex); self.lista_ultimas.addItem(item)

    def procesar_codigo(self):
        if not self.caja_abierta: return
        cod = self.txt_codigo.text().strip(); self.lbl_vademecum.hide()
        if not cod: return
        prod = self.db.buscar_producto(cod)
        if prod:
            if len(prod) > 7 and prod[7]:
                vad = self.db.ejecutar_query("SELECT efecto_terapeutico FROM vademecum WHERE principio_activo = ?", (prod[7],), fetch=True)
                if vad: self.lbl_vademecum.setText(f"ℹ️ {prod[7]}: {vad[0][0]}"); self.lbl_vademecum.show()

            cant_en_carrito = 0; fila_existente = -1
            for r in range(self.tabla.rowCount()):
                if self.tabla.item(r, 0).text() == cod: cant_en_carrito = int(self.tabla.item(r, 2).text()); fila_existente = r; break
            if not self.check_dev.isChecked() and (int(prod[3]) - cant_en_carrito) < self.cantidad_temporal:
                QMessageBox.warning(self, "Stock Insuficiente", f"El producto '{prod[0]}' no se puede agregar.\nTienes {prod[3]} en inventario."); self.txt_codigo.clear(); self.cantidad_temporal = 1; self.forzar_foco(); return
            if fila_existente >= 0:
                nueva_cant = cant_en_carrito + self.cantidad_temporal; self.tabla.item(fila_existente, 2).setText(str(nueva_cant)); precio_unit = float(self.tabla.item(fila_existente, 3).text().replace('$', '').replace('.', '').strip()); self.tabla.item(fila_existente, 4).setText(f"${int(nueva_cant * precio_unit):,}".replace(',', '.')); self.tabla.selectRow(fila_existente)
            else:
                self.tabla.insertRow(self.tabla.rowCount())
                for col, val in enumerate([cod, prod[0], self.cantidad_temporal, f"${int(prod[2]):,}".replace(',', '.'), f"${int(prod[2] * self.cantidad_temporal):,}".replace(',', '.')]):
                    it = QTableWidgetItem(str(val))
                    if col > 1: it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.tabla.setItem(self.tabla.rowCount()-1, col, it)
                self.tabla.selectRow(self.tabla.rowCount()-1)
            self.calcular_totales()
        else: QMessageBox.warning(self, "Error", f"Producto {cod} no registrado.")
        self.txt_codigo.clear(); self.cantidad_temporal = 1; self.forzar_foco()

    def calcular_totales(self):
        self.lista_ticket.clear(); tot = 0.0; arts = 0
        for r in range(self.tabla.rowCount()):
            tot += float(self.tabla.item(r, 4).text().replace('$', '').replace('.', '').strip()); ct = int(self.tabla.item(r, 2).text()); arts += ct
            self.lista_ticket.addItem(QListWidgetItem(f"{ct}x {self.tabla.item(r, 1).text()}"))
        texto_tot = f"${tot:,.0f}".replace(',', '.')

        if self.check_dev.isChecked():
            self.lbl_total.setText(f"- {texto_tot}");
            self.lbl_total.setStyleSheet("color: #d13438; font-size: 36px; font-weight: bold;")
            self.btn_cobrar.setText("F12 - PROCESAR DEVOLUCIÓN")
            self.btn_cobrar.setStyleSheet("background-color: #d13438; color: white; font-size: 14px; font-weight: bold;")
        else:
            self.lbl_total.setText(texto_tot)
            self.lbl_total.setStyleSheet(f"color: #107c41; font-size: 36px; font-weight: bold;")
            self.btn_cobrar.setText("F12 - COBRAR")
            self.btn_cobrar.setStyleSheet("background-color: #107c41; color: white; font-size: 16px; font-weight: bold;")

        self.lbl_items.setText(f"Artículos físicos: {arts}")

    def alternar_estado(self): self.caja_abierta = not self.caja_abierta; self.actualizar_estado(); self.forzar_foco()
    def actualizar_estado(self):
        if self.caja_abierta: self.btn_estado.setText(" CAJA ABIERTA (Cerrar)"); self.btn_estado.setStyleSheet("background-color: #d13438; color: white;"); self.txt_codigo.setEnabled(True); self.btn_cobrar.setEnabled(True); self.check_dev.setEnabled(True)
        else: self.btn_estado.setText(" CAJA CERRADA (Abrir)"); self.btn_estado.setStyleSheet("background-color: #666666; color: white;"); self.txt_codigo.setEnabled(False); self.btn_cobrar.setEnabled(False); self.check_dev.setEnabled(False)

    def imprimir_ticket_generico(self, detalles_venta, total_venta, num_ticket, tipo_operacion, metodo_pago, cant_articulos, es_reimpresion=False):
        if not HAS_PRINTER_SUPPORT: return QMessageBox.warning(self, "Librería Faltante", "No se detectó el soporte de impresión.")
        caja = self.db.obtener_config('nombre_caja'); nombre_impresora = self.db.obtener_config(f'{caja}_impresora')
        if not nombre_impresora or nombre_impresora == "Ninguna Configurada": return
        top_lines = int(self.db.obtener_config('ticket_lineas_top') or 0); bot_lines = int(self.db.obtener_config('ticket_lineas_bot') or 2)
        html = f"<div style='font-family: monospace; font-size: 9pt; color: black; margin: 0; padding: 0;'>" + ("<br>" * top_lines)
        html += f"<center><span style='font-size: 10pt;'>{self.db.obtener_config('ticket_empresa')}</span><br>{self.db.obtener_config('ticket_direccion')}<br>{self.db.obtener_config('ticket_telefono')}<br>{self.db.obtener_config('ticket_correo')}<br><br></center>"
        html += f"{datetime.now().strftime('%d/%m/%Y %I:%M %p')}<br>CAJERO: {self.mw.usuario_actual.upper()}<br>TURNO #: 1<br>FOLIO: {num_ticket}<br><br>"
        html += "<table width='100%' style='font-family: monospace; font-size: 9pt; border-collapse: collapse;'>"
        html += "<tr><th align='left' width='15%'>CANT.</th><th align='left' width='55%'>DESCRIPCION</th><th align='right' width='30%'>IMPORTE</th></tr><tr><td colspan='3'>==========================================</td></tr>"
        for d in detalles_venta:
            importe = f"{int(d['subtotal']):,}".replace(',', '.')
            html += f"<tr><td align='left' valign='top'>{d['cant']}</td><td align='left' valign='top'>{d['producto'][:24]}</td><td align='right' valign='top'>${importe}</td></tr>"
        html += "</table><br>"
        html += f"NO. DE ARTICULOS: {cant_articulos}<br><div style='text-align: right; font-weight: bold;'>TOTAL: ${f'{int(total_venta):,}'.replace(',', '.')}</div><br>"
        txt_copia = "REIMPRESION DE TICKET" if es_reimpresion else ("COPIA DE TICKET" if tipo_operacion == "VENTA" else "COMPROBANTE DE DEVOLUCION")
        html += f"<center>* PAGO CON {metodo_pago.upper()} *<br>REFERENCIA:<br><br>*** {txt_copia} ***<br><br>{self.db.obtener_config('ticket_pie').replace(chr(10), '<br>')}</center>"
        html += ("<br>" * bot_lines) + "<br>.</div>"
        doc = QTextDocument(); doc.setHtml(html); doc.setTextWidth(280); altura_final = int(max((doc.size().height() * 0.352778) + 40, 120 + (len(detalles_venta) * 12) + ((top_lines + bot_lines) * 5)))
        try: printer = QPrinter(QPrinter.PrinterMode.ScreenResolution); printer.setPrinterName(nombre_impresora); printer.setPageSize(QPageSize(QSizeF(80, altura_final), QPageSize.Unit.Millimeter)); printer.setFullPage(True); doc.print(printer)
        except Exception as e: QMessageBox.critical(self, "Error de Impresora", f"No se pudo completar la impresión.\nVerifique la conexión.\nDetalle: {str(e)}")

    def cobrar(self):
        if not self.caja_abierta or self.tabla.rowCount() == 0: return
        tipo = "DEVOLUCION" if self.check_dev.isChecked() else "VENTA"
        tot = float(self.lbl_total.text().replace('$','').replace('.','').replace('-','').strip())
        metodo = "Efectivo"

        if tipo == "VENTA":
            # --- SOLUCION AL ROBO DE CLICS ---
            self.timer_foco.stop() # Apagamos el lector de código de barras

            dlg = DialogoCobro(tot, self.mw.es_claro, self.mw) # Anclamos al programa principal
            res = dlg.exec()

            self.timer_foco.start(500) # Volvemos a prender el lector

            if res == QDialog.DialogCode.Accepted:
                metodo = dlg.metodo_seleccionado
            else:
                self.forzar_foco()
                return

        det_imp = []; det_db = []
        for r in range(self.tabla.rowCount()):
            cod = self.tabla.item(r, 0).text()
            prod = self.tabla.item(r, 1).text()
            cant = int(self.tabla.item(r, 2).text())
            subt = float(self.tabla.item(r, 4).text().replace('$', '').replace('.', '').strip())
            det_imp.append({'codigo': cod, 'producto': prod, 'cant': cant, 'subtotal': subt})
            det_db.append((cod, cant))

        cant_articulos = int(self.lbl_items.text().split()[-1])
        tkt_num = self.db.registrar_venta(tot, cant_articulos, det_db, metodo, tipo, self.mw.usuario_actual)

        if self.db.obtener_config("impresion_auto") == "1":
            self.imprimir_ticket_generico(det_imp, tot, tkt_num, tipo, metodo, cant_articulos)

        self.tabla.setRowCount(0)
        self.check_dev.setChecked(False)
        self.calcular_totales()
        self.cargar_ultimas_ventas()
        self.mw.actualizar_resumen()
        self.forzar_foco()

# ==========================================
# INVENTARIO Y RECETARIO NATIVO (100% DINÁMICO)
# ==========================================
class PantallaInventario(QWidget):
    def __init__(self, db, mw):
        super().__init__()
        self.db = db
        self.mw = mw
        self.crear_ui()

    def al_mostrar(self):
        self.cargar_departamentos()
        self.txt_cod_ingreso.setFocus()
        self.refrescar_combos_rm()
        self.actualizar_tabla_formulas_rm()
        self.actualizar_tabla_config_rm()

    def cargar_pas_bd(self):
        return self.db.ejecutar_query("SELECT nombre, unidad, precio FROM recetario_insumos ORDER BY nombre", fetch=True)

    def cargar_formulas_bd(self):
        return self.db.ejecutar_query("SELECT nombre, precio_base, unidad, precio_unidad FROM recetario_formulas ORDER BY nombre", fetch=True)

    def cargar_departamentos(self):
        deps = [d[0] for d in self.db.ejecutar_query('SELECT nombre FROM departamentos ORDER BY nombre', fetch=True)]
        self.combo_dep_ingreso.clear(); self.combo_dep_ingreso.addItems(deps)
        self.combo_dep_mod.clear(); self.combo_dep_mod.addItems(deps)

    def crear_nuevo_depto(self):
        nom, ok = QInputDialog.getText(self, "Nuevo Departamento", "Nombre del departamento:")
        if ok and nom.strip():
            self.db.ejecutar_query("INSERT OR IGNORE INTO departamentos (nombre) VALUES (?)", (nom.strip().upper(),))
            self.cargar_departamentos()
            self.combo_dep_ingreso.setCurrentText(nom.strip().upper())
            self.combo_dep_mod.setCurrentText(nom.strip().upper())

    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 10, 20, 10)
        lay.addWidget(QLabel("📦 GESTIÓN DE INVENTARIO Y RECETARIO", styleSheet="font-size: 18px; font-weight: bold;"))
        self.tabs = QTabWidget()

        # --- TAB: INGRESO ---
        tab_ingreso = QWidget(); lay_ing = QVBoxLayout(tab_ingreso)
        p_ing = QFrame(); p_ing.setObjectName("panel"); f_ing = QFormLayout(p_ing)

        self.txt_cod_ingreso = LineEditEnter(self.buscar_ingreso)
        self.txt_nom_ingreso = LineEditEnter()
        self.txt_prin_ingreso = LineEditEnter()

        lay_dep_ing = QHBoxLayout()
        self.combo_dep_ingreso = ComboBoxEnter(); self.combo_dep_ingreso.setEditable(True)
        lay_dep_ing.addWidget(self.combo_dep_ingreso)
        btn_mas_dep = QPushButton("+"); btn_mas_dep.setFixedWidth(30); btn_mas_dep.clicked.connect(self.crear_nuevo_depto)
        lay_dep_ing.addWidget(btn_mas_dep)

        self.txt_dist_ing = LineEditEnter()
        self.date_venc_ing = QDateEdit(); self.date_venc_ing.setCalendarPopup(True); self.date_venc_ing.setDate(QDate.currentDate())
        self.txt_factura_ing = SpinBoxEnter(); self.txt_factura_ing.setRange(0, 9999999)
        self.sp_costo_ing = DSpinBoxEnter(); self.sp_costo_ing.setRange(0, 9999999); self.sp_costo_ing.valueChanged.connect(self.calc_precio_ing)
        self.sp_margen_ing = DSpinBoxEnter(); self.sp_margen_ing.setRange(0, 5000); self.sp_margen_ing.valueChanged.connect(self.calc_precio_ing)
        self.sp_precio_ing = DSpinBoxEnter(); self.sp_precio_ing.setRange(0, 9999999); self.sp_precio_ing.valueChanged.connect(self.calc_margen_ing)
        self.sp_cant_ing = SpinBoxEnter(self.guardar_ingreso); self.sp_cant_ing.setRange(0, 100000)
        self.lbl_info_ing = QLabel(""); self.lbl_info_ing.setObjectName("lblAlerta")

        for t, w in [("Código:", self.txt_cod_ingreso), ("Nombre:", self.txt_nom_ingreso), ("P. Activo:", self.txt_prin_ingreso), ("Depto:", lay_dep_ing), ("Distribuidor:", self.txt_dist_ing), ("Vencimiento:", self.date_venc_ing), ("Factura Nro:", self.txt_factura_ing), ("Costo ($):", self.sp_costo_ing), ("Margen (%):", self.sp_margen_ing), ("Precio Venta ($):", self.sp_precio_ing), ("", self.lbl_info_ing), ("Cant a Sumar:", self.sp_cant_ing)]:
            if isinstance(w, QLayout): f_ing.addRow(t, w)
            else: f_ing.addRow(t, w)

        lay_ing.addWidget(p_ing)
        btn_ing = QPushButton("💾 GRABAR INGRESO (Enter)"); btn_ing.setObjectName("btnAccion")
        btn_ing.clicked.connect(self.guardar_ingreso)
        btn_importar = QPushButton("📥 IMPORTAR EXCEL"); btn_importar.setStyleSheet("background-color: #107c41; color: white; padding: 6px 12px; font-weight: bold;")
        btn_importar.clicked.connect(self.importar_excel)

        hb = QHBoxLayout(); hb.addStretch(); hb.addWidget(btn_importar); hb.addWidget(btn_ing)
        lay_ing.addLayout(hb); lay_ing.addStretch()
        self.tabs.addTab(tab_ingreso, "Ingresar / Sumar")

        # --- TAB: MODIFICAR ---
        tab_mod = QWidget(); lay_mod = QVBoxLayout(tab_mod)
        p_mod = QFrame(); p_mod.setObjectName("panel"); f_mod = QFormLayout(p_mod)

        self.txt_cod_mod = LineEditEnter(self.buscar_modificar)
        self.txt_nom_mod = LineEditEnter()
        self.txt_prin_mod = LineEditEnter()

        lay_dep_mod = QHBoxLayout()
        self.combo_dep_mod = ComboBoxEnter(); self.combo_dep_mod.setEditable(True)
        lay_dep_mod.addWidget(self.combo_dep_mod)
        btn_mas_dep_mod = QPushButton("+"); btn_mas_dep_mod.setFixedWidth(30); btn_mas_dep_mod.clicked.connect(self.crear_nuevo_depto)
        lay_dep_mod.addWidget(btn_mas_dep_mod)

        self.txt_dist_mod = LineEditEnter()
        self.sp_costo_mod = DSpinBoxEnter(); self.sp_costo_mod.setRange(0, 9999999); self.sp_costo_mod.valueChanged.connect(self.calc_precio_mod)
        self.sp_margen_mod = DSpinBoxEnter(); self.sp_margen_mod.setRange(0, 5000); self.sp_margen_mod.valueChanged.connect(self.calc_precio_mod)
        self.sp_precio_mod = DSpinBoxEnter(self.guardar_modificacion); self.sp_precio_mod.setRange(0, 9999999); self.sp_precio_mod.valueChanged.connect(self.calc_margen_mod)
        self.lbl_info_mod = QLabel("Info"); self.lbl_info_mod.setObjectName("lblAlerta")

        for t, w in [("Buscar Cod:", self.txt_cod_mod), ("Nombre:", self.txt_nom_mod), ("P. Activo:", self.txt_prin_mod), ("Depto:", lay_dep_mod), ("Distribuidor:", self.txt_dist_mod), ("Costo ($):", self.sp_costo_mod), ("Margen (%):", self.sp_margen_mod), ("Precio ($):", self.sp_precio_mod), ("", self.lbl_info_mod)]:
            if isinstance(w, QLayout): f_mod.addRow(t, w)
            else: f_mod.addRow(t, w)

        for w in [self.txt_nom_mod, self.txt_prin_mod, self.sp_costo_mod, self.sp_precio_mod, self.sp_margen_mod, self.combo_dep_mod, self.txt_dist_mod]: w.setEnabled(False)

        lay_mod.addWidget(p_mod)
        self.btn_mod = QPushButton("✏ GUARDAR CAMBIOS"); self.btn_mod.setObjectName("btnAccion")
        self.btn_mod.clicked.connect(self.guardar_modificacion); self.btn_mod.setEnabled(False)
        lay_mod.addWidget(self.btn_mod, alignment=Qt.AlignmentFlag.AlignRight); lay_mod.addStretch()
        self.tabs.addTab(tab_mod, "Modificar Producto")

        # --- TAB: CALCULADORA MAGISTRAL ---
        tab_rm = QWidget(); lay_rm = QVBoxLayout(tab_rm)
        h_glob = QHBoxLayout()

        h_glob.addWidget(QLabel("<b>Fórmula Magistral:</b>"))
        self.combo_tipo_form = QComboBox()
        self.combo_tipo_form.currentIndexChanged.connect(self.rm_tipo_form_changed)
        h_glob.addWidget(self.combo_tipo_form)

        h_glob.addSpacing(20)

        self.lbl_uni_form = QLabel("<b>Cantidad/Volumen:</b>")
        h_glob.addWidget(self.lbl_uni_form)
        self.sp_cant_form = SpinBoxEnter()
        self.sp_cant_form.setRange(1, 10000); self.sp_cant_form.setValue(30)
        self.sp_cant_form.valueChanged.connect(self.calcular_totales_rm)
        h_glob.addWidget(self.sp_cant_form)
        h_glob.addStretch()

        btn_reload = QPushButton("🔄 Refrescar Listas")
        btn_reload.clicked.connect(self.refrescar_combos_rm)
        h_glob.addWidget(btn_reload)
        lay_rm.addLayout(h_glob)

        self.tabla_rm = QTableWidget(0, 5)
        self.tabla_rm.setHorizontalHeaderLabels(["Principio Activo", "Dosis Requerida", "Unidad", "Precio Base ($)", "Subtotal P.A. ($)"])
        self.tabla_rm.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla_rm.setAlternatingRowColors(True)
        lay_rm.addWidget(self.tabla_rm)

        for _ in range(5): self.agregar_fila_rm()

        self.btn_add_rm = QPushButton("+ Agregar Casilla P.A.")
        self.btn_add_rm.clicked.connect(self.agregar_fila_rm)
        lay_rm.addWidget(self.btn_add_rm)

        p_res = QFrame(); p_res.setObjectName("panel")
        lay_res = QHBoxLayout(p_res)

        f_izq = QFormLayout()
        self.lbl_rm_pas = QLabel("$0"); f_izq.addRow("Suma Principios Activos:", self.lbl_rm_pas)

        self.lbl_rm_insumo_lbl = QLabel("Costo Insumo/Medida:")
        self.lbl_rm_insumo = QLabel("$0"); f_izq.addRow(self.lbl_rm_insumo_lbl, self.lbl_rm_insumo)

        self.lbl_rm_form = QLabel("$0"); f_izq.addRow("Valor Base Fórmula:", self.lbl_rm_form)
        lay_res.addLayout(f_izq)

        f_der = QFormLayout()
        self.lbl_rm_neto = QLabel("$0"); f_der.addRow("Total Neto:", self.lbl_rm_neto)
        self.lbl_rm_iva = QLabel("$0"); f_der.addRow("IVA (19%):", self.lbl_rm_iva)
        self.lbl_rm_total = QLabel("$0"); self.lbl_rm_total.setStyleSheet("font-size: 22px; font-weight: bold; color: #107c41;")
        f_der.addRow("TOTAL A COBRAR:", self.lbl_rm_total)
        lay_res.addLayout(f_der)

        lay_rm.addWidget(p_res)

        self.btn_enviar_rm = QPushButton("🛒 ENVIAR AL PUNTO DE VENTA (Enter)")
        self.btn_enviar_rm.setObjectName("btnAccion"); self.btn_enviar_rm.setFixedHeight(45)
        self.btn_enviar_rm.clicked.connect(self.enviar_rm_a_caja)
        lay_rm.addWidget(self.btn_enviar_rm)

        self.tabs.addTab(tab_rm, "Calculadora Magistral")

        # --- TAB: CONFIGURAR RECETARIO ---
        tab_cfg = QWidget(); lay_cfg = QVBoxLayout(tab_cfg)

        # 1. Gestor de Tipos de Fórmulas
        g_formulas = QGroupBox("1. Gestor de Tipos de Fórmulas Magistrales")
        g_formulas.setStyleSheet("font-weight: bold;")
        lay_formulas = QVBoxLayout()

        h_f = QHBoxLayout()
        self.txt_cfg_f_nom = QLineEdit(); self.txt_cfg_f_nom.setPlaceholderText("Ej. Cápsulas, Cremas...")
        h_f.addWidget(QLabel("Fórmula:", styleSheet="font-weight: normal;")); h_f.addWidget(self.txt_cfg_f_nom)

        self.sp_cfg_f_base = DSpinBoxEnter(); self.sp_cfg_f_base.setRange(0, 1000000)
        h_f.addWidget(QLabel("Precio Base ($):", styleSheet="font-weight: normal;")); h_f.addWidget(self.sp_cfg_f_base)

        self.txt_cfg_f_uni = QLineEdit(); self.txt_cfg_f_uni.setPlaceholderText("Ej. Cápsula, Gramos, ML...")
        h_f.addWidget(QLabel("Medida:", styleSheet="font-weight: normal;")); h_f.addWidget(self.txt_cfg_f_uni)

        self.sp_cfg_f_pre_uni = DSpinBoxEnter(); self.sp_cfg_f_pre_uni.setRange(0, 100000); self.sp_cfg_f_pre_uni.setDecimals(4)
        h_f.addWidget(QLabel("Precio x Medida ($):", styleSheet="font-weight: normal;")); h_f.addWidget(self.sp_cfg_f_pre_uni)

        btn_guardar_form = QPushButton("➕ Guardar / Actualizar Fórmula")
        btn_guardar_form.clicked.connect(self.guardar_formula_rm)
        h_f.addWidget(btn_guardar_form)
        lay_formulas.addLayout(h_f)

        self.tabla_formulas_cfg = QTableWidget(0, 4)
        self.tabla_formulas_cfg.setHorizontalHeaderLabels(["Fórmula", "Precio Base ($)", "Medida (Unidad)", "Precio x Medida ($)"])
        self.tabla_formulas_cfg.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla_formulas_cfg.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_formulas_cfg.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay_formulas.addWidget(self.tabla_formulas_cfg)

        g_formulas.setLayout(lay_formulas)
        lay_cfg.addWidget(g_formulas)

        # 2. Gestor de Principios Activos
        g_pa = QGroupBox("2. Gestor de Principios Activos")
        g_pa.setStyleSheet("font-weight: bold;")
        lay_pa = QVBoxLayout()

        f_pa = QHBoxLayout()
        self.txt_pa_nom = QLineEdit(); self.txt_pa_nom.setPlaceholderText("Nombre del P.A.")
        f_pa.addWidget(self.txt_pa_nom)

        self.cmb_pa_uni = QComboBox(); self.cmb_pa_uni.addItems(["mg", "mcg", "gr", "ml"])
        f_pa.addWidget(QLabel("Unidad:", styleSheet="font-weight: normal;")); f_pa.addWidget(self.cmb_pa_uni)

        self.sp_pa_pre = DSpinBoxEnter(); self.sp_pa_pre.setRange(0, 99999); self.sp_pa_pre.setDecimals(4)
        f_pa.addWidget(QLabel("Precio x Unidad ($):", styleSheet="font-weight: normal;")); f_pa.addWidget(self.sp_pa_pre)

        btn_guardar_pa = QPushButton("➕ Guardar / Actualizar P.A.")
        btn_guardar_pa.clicked.connect(self.guardar_pa_rm)
        f_pa.addWidget(btn_guardar_pa)
        lay_pa.addLayout(f_pa)

        self.tabla_pas_cfg = QTableWidget(0, 3)
        self.tabla_pas_cfg.setHorizontalHeaderLabels(["Principio Activo", "Unidad", "Precio por Unidad ($)"])
        self.tabla_pas_cfg.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla_pas_cfg.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_pas_cfg.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay_pa.addWidget(self.tabla_pas_cfg)

        g_pa.setLayout(lay_pa)
        lay_cfg.addWidget(g_pa)

        self.tabs.addTab(tab_cfg, "Configurar Recetario")
        lay.addWidget(self.tabs)

    def agregar_fila_rm(self):
        if self.tabla_rm.rowCount() >= 20: return QMessageBox.warning(self, "Límite", "Máximo 20 casillas.")
        r = self.tabla_rm.rowCount()
        self.tabla_rm.insertRow(r)

        combo = QComboBox()
        combo.addItem("- Ninguno -", {"unidad": "", "precio": 0.0})
        for p in self.cargar_pas_bd():
            combo.addItem(p[0], {"unidad": p[1], "precio": p[2]})

        dosis = QDoubleSpinBox(); dosis.setRange(0, 999999); dosis.setDecimals(2)
        lbl_uni = QLabel("-"); lbl_uni.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_pre = QLabel("$0.00"); lbl_pre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub = QLabel("$0"); lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter); lbl_sub.setStyleSheet("font-weight: bold;")

        combo.currentIndexChanged.connect(lambda idx, row=r: self.rm_combo_changed(row))
        dosis.valueChanged.connect(self.calcular_totales_rm)

        self.tabla_rm.setCellWidget(r, 0, combo)
        self.tabla_rm.setCellWidget(r, 1, dosis)
        self.tabla_rm.setCellWidget(r, 2, lbl_uni)
        self.tabla_rm.setCellWidget(r, 3, lbl_pre)
        self.tabla_rm.setCellWidget(r, 4, lbl_sub)

    def rm_combo_changed(self, row):
        combo = self.tabla_rm.cellWidget(row, 0)
        lbl_uni = self.tabla_rm.cellWidget(row, 2)
        lbl_pre = self.tabla_rm.cellWidget(row, 3)
        data = combo.currentData()

        if data and combo.currentIndex() > 0:
            lbl_uni.setText(data["unidad"])
            lbl_pre.setText(f"${data['precio']}")
        else:
            lbl_uni.setText("-")
            lbl_pre.setText("$0.00")

        self.calcular_totales_rm()

    def rm_tipo_form_changed(self):
        data = self.combo_tipo_form.currentData()
        if data:
            self.lbl_uni_form.setText(f"<b>Cantidad de {data['unidad']}:</b>")
            self.lbl_rm_insumo_lbl.setText(f"Costo por {data['unidad']}:")
        self.calcular_totales_rm()

    def calcular_totales_rm(self, val=None):
        cant_f = self.sp_cant_form.value()
        tipo_data = self.combo_tipo_form.currentData()
        if not tipo_data: return

        subtotal_pas = 0.0
        for r in range(self.tabla_rm.rowCount()):
            combo = self.tabla_rm.cellWidget(r, 0)
            dosis = self.tabla_rm.cellWidget(r, 1)
            lbl_subt = self.tabla_rm.cellWidget(r, 4)
            data = combo.currentData()

            if data and combo.currentIndex() > 0:
                precio_u = float(data["precio"])
                d = dosis.value()
                subt_row = precio_u * d * cant_f
                lbl_subt.setText(f"${subt_row:,.1f}")
                subtotal_pas += subt_row
            else:
                lbl_subt.setText("$0")

        costo_insumo = cant_f * float(tipo_data['precio_u'])
        costo_formula = float(tipo_data['base'])

        neto = subtotal_pas + costo_insumo + costo_formula
        iva = neto * 0.19
        total_final = neto + iva

        self.lbl_rm_pas.setText(f"${subtotal_pas:,.0f}")
        self.lbl_rm_insumo.setText(f"${costo_insumo:,.0f}")
        self.lbl_rm_form.setText(f"${costo_formula:,.0f}")

        self.lbl_rm_neto.setText(f"${neto:,.0f}".replace(',', '.'))
        self.lbl_rm_iva.setText(f"${iva:,.0f}".replace(',', '.'))
        self.lbl_rm_total.setText(f"${total_final:,.0f}".replace(',', '.'))
        self.rm_total_calculado = total_final

    def refrescar_combos_rm(self):
        forms = self.cargar_formulas_bd()
        curr_f = self.combo_tipo_form.currentText()
        self.combo_tipo_form.blockSignals(True)
        self.combo_tipo_form.clear()
        idx_f = 0
        for i, f in enumerate(forms):
            self.combo_tipo_form.addItem(f[0], {"base": f[1], "unidad": f[2], "precio_u": f[3]})
            if f[0] == curr_f: idx_f = i
        self.combo_tipo_form.setCurrentIndex(idx_f)
        self.combo_tipo_form.blockSignals(False)
        self.rm_tipo_form_changed()

        pas = self.cargar_pas_bd()
        for r in range(self.tabla_rm.rowCount()):
            combo = self.tabla_rm.cellWidget(r, 0)
            txt_actual = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("- Ninguno -", {"unidad": "", "precio": 0.0})
            idx_seleccionar = 0
            for i, p in enumerate(pas):
                combo.addItem(p[0], {"unidad": p[1], "precio": p[2]})
                if p[0] == txt_actual: idx_seleccionar = i + 1
            combo.setCurrentIndex(idx_seleccionar)
            combo.blockSignals(False)
            self.rm_combo_changed(r)

    def enviar_rm_a_caja(self):
        if hasattr(self, 'rm_total_calculado') and self.rm_total_calculado > 0:
            pantalla_caja = self.mw.pantallas.widget(0)
            pantalla_caja.agregar_item_especial("RM-001", "RECETA MAGISTRAL", self.rm_total_calculado, 1)
            self.sp_cant_form.setValue(30)
            for r in range(self.tabla_rm.rowCount()):
                combo = self.tabla_rm.cellWidget(r, 0); combo.setCurrentIndex(0)
                dosis = self.tabla_rm.cellWidget(r, 1); dosis.setValue(0.0)
            self.calcular_totales_rm()
            self.mw.cambiar_pantalla(0)
        else:
            QMessageBox.warning(self, "Aviso", "No hay un total válido calculado para enviar.")

    def keyPressEvent(self, event):
        if self.tabs.currentIndex() == 2 and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enviar_rm_a_caja()
        else:
            super().keyPressEvent(event)

    def guardar_formula_rm(self):
        nom = self.txt_cfg_f_nom.text().strip().upper()
        base = self.sp_cfg_f_base.value()
        uni = self.txt_cfg_f_uni.text().strip()
        pre_u = self.sp_cfg_f_pre_uni.value()
        if not nom or not uni: return QMessageBox.warning(self, "Error", "Falta el nombre de la fórmula o su unidad de medida.")

        self.db.ejecutar_query("INSERT OR REPLACE INTO recetario_formulas (nombre, precio_base, unidad, precio_unidad) VALUES (?, ?, ?, ?)", (nom, base, uni, pre_u))
        self.txt_cfg_f_nom.clear(); self.txt_cfg_f_uni.clear(); self.sp_cfg_f_base.setValue(0); self.sp_cfg_f_pre_uni.setValue(0)
        self.actualizar_tabla_formulas_rm()
        self.refrescar_combos_rm()
        QMessageBox.information(self, "Guardado", f"La fórmula '{nom}' se actualizó correctamente.")

    def actualizar_tabla_formulas_rm(self):
        datos = self.cargar_formulas_bd()
        self.tabla_formulas_cfg.setRowCount(0)
        for r, d in enumerate(datos):
            self.tabla_formulas_cfg.insertRow(r)
            self.tabla_formulas_cfg.setItem(r, 0, QTableWidgetItem(d[0]))
            self.tabla_formulas_cfg.setItem(r, 1, QTableWidgetItem(f"${d[1]:,.0f}".replace(',','.')))
            self.tabla_formulas_cfg.setItem(r, 2, QTableWidgetItem(d[2]))
            self.tabla_formulas_cfg.setItem(r, 3, QTableWidgetItem(f"${d[3]:,.4f}".replace(',','.')))

    def guardar_pa_rm(self):
        nom = self.txt_pa_nom.text().strip().upper()
        uni = self.cmb_pa_uni.currentText()
        pre = self.sp_pa_pre.value()
        if not nom: return QMessageBox.warning(self, "Error", "Falta el nombre del Principio Activo.")

        self.db.ejecutar_query("INSERT OR REPLACE INTO recetario_insumos (nombre, unidad, precio) VALUES (?, ?, ?)", (nom, uni, pre))
        self.txt_pa_nom.clear(); self.sp_pa_pre.setValue(0.0)
        self.actualizar_tabla_config_rm()
        self.refrescar_combos_rm()
        QMessageBox.information(self, "Guardado", f"El principio activo '{nom}' se ha registrado exitosamente.")

    def actualizar_tabla_config_rm(self):
        datos = self.cargar_pas_bd()
        self.tabla_pas_cfg.setRowCount(0)
        for r, d in enumerate(datos):
            self.tabla_pas_cfg.insertRow(r)
            self.tabla_pas_cfg.setItem(r, 0, QTableWidgetItem(d[0]))
            self.tabla_pas_cfg.setItem(r, 1, QTableWidgetItem(d[1]))
            self.tabla_pas_cfg.setItem(r, 2, QTableWidgetItem(str(d[2])))

    def buscar_ingreso(self):
        prod = self.db.buscar_producto(self.txt_cod_ingreso.text().strip())
        if prod:
            self.txt_nom_ingreso.setText(prod[0])
            self.sp_costo_ing.setValue(prod[1])
            self.sp_precio_ing.setValue(prod[2])
            self.txt_dist_ing.setText(prod[4] if prod[4] else "")
            self.combo_dep_ingreso.setCurrentText(prod[5] if prod[5] else "General")
            self.txt_prin_ingreso.setText(prod[7] if len(prod)>7 and prod[7] else "")
            self.lbl_info_ing.setText(f"ℹ️ Existe. Stock: {prod[3]} | Precio: ${prod[2]:,.0f}")
            self.sp_cant_ing.setFocus()
            self.sp_cant_ing.selectAll()
        else:
            self.lbl_info_ing.setText("✨ Código nuevo.")
            self.txt_nom_ingreso.setFocus()
            self.txt_dist_ing.clear()
            self.txt_prin_ingreso.clear()
            self.combo_dep_ingreso.setCurrentText("General")

    def calc_precio_ing(self):
        self.sp_precio_ing.blockSignals(True)
        self.sp_precio_ing.setValue(self.sp_costo_ing.value() * (1 + (self.sp_margen_ing.value() / 100.0)))
        self.sp_precio_ing.blockSignals(False)

    def calc_margen_ing(self):
        if self.sp_costo_ing.value() > 0:
            self.sp_margen_ing.blockSignals(True)
            self.sp_margen_ing.setValue(((self.sp_precio_ing.value() - self.sp_costo_ing.value()) / self.sp_costo_ing.value()) * 100)
            self.sp_margen_ing.blockSignals(False)

    def guardar_ingreso(self):
        if not self.txt_cod_ingreso.text() or not self.txt_nom_ingreso.text():
            return QMessageBox.warning(self, "Error", "Faltan datos obligatorios.")
        ok, msg = self.db.ingresar_producto_manual(
            self.txt_cod_ingreso.text(), self.txt_nom_ingreso.text(), self.sp_costo_ing.value(),
            self.sp_precio_ing.value(), self.sp_cant_ing.value(), self.txt_dist_ing.text(),
            self.combo_dep_ingreso.currentText(), self.txt_prin_ingreso.text().strip().upper(),
            str(self.txt_factura_ing.value()) if self.txt_factura_ing.value() > 0 else "",
            self.mw.usuario_actual, self.date_venc_ing.date().toString("yyyy-MM-dd")
        )
        QMessageBox.information(self, "Resultado", msg)
        self.txt_cod_ingreso.clear(); self.txt_nom_ingreso.clear(); self.txt_prin_ingreso.clear()
        self.txt_dist_ing.clear(); self.txt_factura_ing.setValue(0); self.sp_costo_ing.setValue(0)
        self.sp_precio_ing.setValue(0); self.sp_cant_ing.setValue(0); self.lbl_info_ing.setText("")
        self.txt_cod_ingreso.setFocus()

    def buscar_modificar(self):
        prod = self.db.buscar_producto(self.txt_cod_mod.text().strip())
        if prod:
            self.txt_nom_mod.setText(prod[0])
            self.sp_costo_mod.setValue(prod[1])
            self.sp_precio_mod.setValue(prod[2])
            self.txt_dist_mod.setText(prod[4] if prod[4] else "")
            self.combo_dep_mod.setCurrentText(prod[5] if prod[5] else "General")
            self.txt_prin_mod.setText(prod[7] if len(prod)>7 and prod[7] else "")
            for w in [self.txt_nom_mod, self.txt_prin_mod, self.sp_costo_mod, self.sp_precio_mod, self.sp_margen_mod, self.combo_dep_mod, self.txt_dist_mod, self.btn_mod]: w.setEnabled(True)
            self.lbl_info_mod.setText(f"ℹ️ Editando. Stock actual: {prod[3]}")
            self.txt_nom_mod.setFocus()
        else:
            QMessageBox.warning(self, "Error", "Producto no encontrado.")
            self.txt_nom_mod.clear()
            for w in [self.txt_nom_mod, self.txt_prin_mod, self.sp_costo_mod, self.sp_precio_mod, self.sp_margen_mod, self.combo_dep_mod, self.txt_dist_mod, self.btn_mod]: w.setEnabled(False)

    def calc_precio_mod(self):
        self.sp_precio_mod.blockSignals(True)
        self.sp_precio_mod.setValue(self.sp_costo_mod.value() * (1 + (self.sp_margen_mod.value() / 100.0)))
        self.sp_precio_mod.blockSignals(False)

    def calc_margen_mod(self):
        if self.sp_costo_mod.value() > 0:
            self.sp_margen_mod.blockSignals(True)
            self.sp_margen_mod.setValue(((self.sp_precio_mod.value() - self.sp_costo_mod.value()) / self.sp_costo_mod.value()) * 100)
            self.sp_margen_mod.blockSignals(False)

    def guardar_modificacion(self):
        ok, msg = self.db.modificar_producto_existente(
            self.txt_cod_mod.text(), self.txt_nom_mod.text(), self.sp_costo_mod.value(),
            self.sp_precio_mod.value(), self.txt_dist_mod.text(), self.combo_dep_mod.currentText(),
            self.txt_prin_mod.text().strip().upper()
        )
        QMessageBox.information(self, "Resultado", msg)
        self.txt_cod_mod.clear(); self.txt_nom_mod.clear(); self.txt_dist_mod.clear(); self.txt_cod_mod.setFocus()

    def importar_excel(self):
        if not HAS_PANDAS:
            return QMessageBox.warning(self, "Librería Faltante", "Instalar pandas y openpyxl.")
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar Excel", "", "Excel (*.xlsx *.xls)")
        if not ruta: return
        try:
            df = pd.read_excel(ruta).fillna("")
            datos = []
            for _, r in df.iterrows():
                cod = str(r.get('Código', r.get('Codigo', ''))).strip()
                if cod:
                    nom = str(r.get('Producto', r.get('Nombre', ''))).strip()
                    cst_str = str(r.get('P. Costo', r.get('Costo', 0))).replace('$', '').replace(',', '').strip()
                    cst = float(cst_str) if cst_str else 0.0
                    prc_str = str(r.get('P. Venta', r.get('Precio', 0))).replace('$', '').replace(',', '').strip()
                    prc = float(prc_str) if prc_str else 0.0
                    stk_str = str(r.get('Existencia', r.get('Stock', 0))).replace(',', '').strip()
                    stk = int(float(stk_str)) if stk_str else 0
                    dist = str(r.get('Distribuidor', ''))
                    dep = str(r.get('Departamento', 'General'))
                    prin = str(r.get('Principio_Activo', '')).upper()
                    datos.append((cod, nom, cst, prc, stk, dist, dep, prin))
            if datos:
                self.db.ejecutar_muchos('''INSERT INTO inventario (codigo, nombre, costo, precio_venta, stock, distribuidor, departamento, principio_activo) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(codigo) DO UPDATE SET nombre=excluded.nombre, costo=excluded.costo, precio_venta=excluded.precio_venta, stock=inventario.stock + excluded.stock, distribuidor=excluded.distribuidor, departamento=excluded.departamento, principio_activo=excluded.principio_activo''', datos)
                QMessageBox.information(self, "Éxito", f"¡Se importaron {len(datos)} productos!")
        except Exception as e:
            QMessageBox.critical(self, "Error al Importar", f"Hubo un fallo. Detalle técnico: {str(e)}")

# ==========================================
# RESTO DE PANTALLAS
# ==========================================
class PantallaVencimientos(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.cargar()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 20, 20, 20); lay.addWidget(QLabel("📅 CONTROL DE VENCIMIENTOS", styleSheet="font-size: 18px; font-weight: bold;"))
        self.tabla = QTableWidget(0, 5); self.tabla.setHorizontalHeaderLabels(["CÓDIGO", "PRODUCTO", "STOCK", "VENCIMIENTO", "DÍAS RESTANTES"])
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setShowGrid(True)
        lay.addWidget(self.tabla)
    def cargar(self):
        datos = self.db.ejecutar_query("SELECT codigo, nombre, stock, vencimiento FROM inventario WHERE vencimiento != '' ORDER BY vencimiento ASC", fetch=True); self.tabla.setRowCount(0); hoy = datetime.now()
        for r, d in enumerate(datos):
            self.tabla.insertRow(r); self.tabla.setItem(r, 0, QTableWidgetItem(str(d[0]))); self.tabla.setItem(r, 1, QTableWidgetItem(str(d[1]))); self.tabla.setItem(r, 2, QTableWidgetItem(str(d[2])))
            self.tabla.setItem(r, 3, QTableWidgetItem(str(d[3])))
            try:
                v = datetime.strptime(d[3], "%Y-%m-%d"); diff = (v - hoy).days
                it_diff = QTableWidgetItem(f"{diff} días"); it_diff.setForeground(QColor("red" if diff < 30 else "green"))
                self.tabla.setItem(r, 4, it_diff)
            except: self.tabla.setItem(r, 4, QTableWidgetItem("Error"))

class PantallaVademecum(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.cargar()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.addWidget(QLabel("📖 VADEMÉCUM CLÍNICO", styleSheet="font-size: 18px; font-weight: bold;")); split = QSplitter(Qt.Orientation.Horizontal)
        w_izq = QWidget(); l_izq = QVBoxLayout(w_izq); l_izq.setContentsMargins(0,0,10,0); self.tabla = QTableWidget(0, 2); self.tabla.setHorizontalHeaderLabels(["PRINCIPIO ACTIVO", "USO TERAPÉUTICO"]); self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); l_izq.addWidget(self.tabla); split.addWidget(w_izq)
        w_der = QFrame(); w_der.setObjectName("panel"); l_der = QFormLayout(w_der); self.txt_prin = QLineEdit(); self.txt_uso = QTextEdit(); self.txt_uso.setFixedHeight(80); self.txt_adv = QTextEdit(); self.txt_adv.setFixedHeight(80)
        l_der.addRow("Principio Activo:", self.txt_prin); l_der.addRow("Uso Terapéutico:", self.txt_uso); l_der.addRow("Ef. Adversos:", self.txt_adv)
        btn_g = QPushButton("💾 Guardar"); btn_g.setObjectName("btnAccion"); btn_g.clicked.connect(self.guardar); l_der.addRow("", btn_g); split.addWidget(w_der); lay.addWidget(split)
    def cargar(self):
        d = self.db.ejecutar_query("SELECT principio_activo, efecto_terapeutico FROM vademecum", fetch=True); self.tabla.setRowCount(0)
        for r, row in enumerate(d): self.tabla.insertRow(r); self.tabla.setItem(r, 0, QTableWidgetItem(str(row[0]))); self.tabla.setItem(r, 1, QTableWidgetItem(str(row[1])))
    def guardar(self):
        p = self.txt_prin.text().strip().upper(); u = self.txt_uso.toPlainText().strip(); a = self.txt_adv.toPlainText().strip()
        if p and u: self.db.ejecutar_query("INSERT OR REPLACE INTO vademecum (principio_activo, efecto_terapeutico, efectos_adversos) VALUES (?,?,?)", (p,u,a)); self.txt_prin.clear(); self.txt_uso.clear(); self.txt_adv.clear(); self.cargar()

class PantallaFacturas(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.cargar()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.addWidget(QLabel("🧾 FACTURAS DE INGRESO (Selecciona varias para sumar)", styleSheet="font-size: 18px; font-weight: bold;"))
        self.tabla = QTableWidget(0, 4); self.tabla.setHorizontalHeaderLabels(["NÚMERO", "PROVEEDOR", "FECHA", "MONTO ($)"]); self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection); self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.tabla.itemSelectionChanged.connect(self.sumar); lay.addWidget(self.tabla)
        self.lbl_suma = QLabel("Suma Seleccionada: $0"); self.lbl_suma.setStyleSheet("font-size: 20px; font-weight: bold; color: #0078D7;"); lay.addWidget(self.lbl_suma, alignment=Qt.AlignmentFlag.AlignRight)
    def cargar(self):
        d = self.db.ejecutar_query("SELECT numero, distribuidor, fecha, total FROM facturas_ingreso ORDER BY fecha DESC", fetch=True); self.tabla.setRowCount(0)
        for r, row in enumerate(d):
            self.tabla.insertRow(r); self.tabla.setItem(r, 0, QTableWidgetItem(str(row[0]))); self.tabla.setItem(r, 1, QTableWidgetItem(str(row[1]))); self.tabla.setItem(r, 2, QTableWidgetItem(str(row[2])[:10]))
            it_m = QTableWidgetItem(str(row[3])); self.tabla.setItem(r, 3, it_m)
    def sumar(self):
        t = 0.0
        for item in self.tabla.selectedItems():
            if item.column() == 3: t += float(item.text() or 0)
        self.lbl_suma.setText(f"Suma Seleccionada: ${t:,.0f}".replace(',','.'))

class PantallaBajas(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.addWidget(QLabel("🔻 BAJA DE PRODUCTOS / MERMAS", styleSheet="font-size: 18px; font-weight: bold;"))
        p = QFrame(); p.setObjectName("panel"); f = QFormLayout(p); self.txt_cod = LineEditEnter(self.buscar); self.lbl_nom = QLabel("-"); self.lbl_stk = QLabel("-"); self.sp_cant = QSpinBox(); self.sp_cant.setRange(1, 9999); self.txt_motivo = QLineEdit()
        f.addRow("Código (Enter):", self.txt_cod); f.addRow("Producto:", self.lbl_nom); f.addRow("Stock Actual:", self.lbl_stk); f.addRow("Cant. a bajar:", self.sp_cant); f.addRow("Motivo:", self.txt_motivo)
        btn = QPushButton("Ejecutar Baja"); btn.setObjectName("btnAccion"); btn.clicked.connect(self.ejecutar); f.addRow("", btn); lay.addWidget(p); lay.addStretch()
    def buscar(self):
        p = self.db.buscar_producto(self.txt_cod.text().strip())
        if p: self.lbl_nom.setText(p[0]); self.lbl_stk.setText(str(p[3]))
        else: QMessageBox.warning(self, "Error", "No encontrado")
    def ejecutar(self):
        ok, m = self.db.dar_baja_producto(self.txt_cod.text(), self.sp_cant.value(), self.txt_motivo.text(), self.mw.usuario_actual)
        if ok: QMessageBox.information(self, "Éxito", m); self.txt_cod.clear(); self.lbl_nom.setText("-"); self.lbl_stk.setText("-"); self.txt_motivo.clear()
        else: QMessageBox.warning(self, "Error", m)

class PantallaUsuarios(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.cargar()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.addWidget(QLabel("👥 GESTIÓN DE USUARIOS", styleSheet="font-size: 18px; font-weight: bold;")); s = QSplitter(Qt.Orientation.Horizontal)
        w_i = QWidget(); l_i = QVBoxLayout(w_i); l_i.setContentsMargins(0,0,10,0); self.tabla = QTableWidget(0,2); self.tabla.setHorizontalHeaderLabels(["USUARIO", "ROL"]); self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); l_i.addWidget(self.tabla); s.addWidget(w_i)
        w_d = QFrame(); w_d.setObjectName("panel"); f = QFormLayout(w_d); self.t_usr = QLineEdit(); self.t_pwd = QLineEdit(); self.t_pwd.setEchoMode(QLineEdit.EchoMode.Password); self.c_rol = QComboBox(); self.c_rol.addItems(["Cajero", "Administrador"])
        f.addRow("Usuario:", self.t_usr); f.addRow("Contraseña:", self.t_pwd); f.addRow("Rol:", self.c_rol); btn = QPushButton("Crear Usuario"); btn.setObjectName("btnAccion"); btn.clicked.connect(self.guardar); f.addRow("", btn); s.addWidget(w_d); lay.addWidget(s)
    def cargar(self):
        d = self.db.ejecutar_query("SELECT usuario, rol FROM usuarios", fetch=True); self.tabla.setRowCount(0)
        for r, row in enumerate(d): self.tabla.insertRow(r); self.tabla.setItem(r, 0, QTableWidgetItem(str(row[0]))); self.tabla.setItem(r, 1, QTableWidgetItem(str(row[1])))
    def guardar(self):
        u = self.t_usr.text().strip(); p = self.t_pwd.text().strip(); r = self.c_rol.currentText()
        if u and p: self.db.ejecutar_query("INSERT OR REPLACE INTO usuarios (usuario, password, rol) VALUES (?,?,?)", (u.lower(), p, r)); self.t_usr.clear(); self.t_pwd.clear(); self.cargar()

class PantallaTickets(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.date_p.setDate(QDate.currentDate()); self.cargar_lista()
    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.addWidget(QLabel("🎫 HISTORIAL DE TICKETS", styleSheet="font-size: 18px; font-weight: bold;"))
        lh = QHBoxLayout(); lh.addWidget(QLabel("Ver tickets del día:")); self.date_p = QDateEdit(); self.date_p.setCalendarPopup(True); self.date_p.dateChanged.connect(self.cargar_lista); lh.addWidget(self.date_p); lh.addStretch(); lay.addLayout(lh)
        s = QSplitter(Qt.Orientation.Horizontal)
        self.lista = QListWidget(); self.lista.itemSelectionChanged.connect(self.cargar_det); s.addWidget(self.lista)
        self.tabla = QTableWidget(0,3); self.tabla.setHorizontalHeaderLabels(["CÓDIGO", "CANT.", "PRODUCTO"]); self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch); self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); s.addWidget(self.tabla); lay.addWidget(s)
    def cargar_lista(self):
        d = self.db.ejecutar_query("SELECT fecha, ticket_diario, total, tipo_operacion FROM ventas WHERE fecha LIKE ?", (f"{self.date_p.date().toString('yyyy-MM-dd')}%",), fetch=True); self.lista.clear()
        for row in d:
            i = QListWidgetItem(f"TKT #{row[1]} | {row[0][11:16]} | {row[3]} | ${row[2]:,.0f}".replace(',','.'))
            i.setData(Qt.ItemDataRole.UserRole, row[0]); self.lista.addItem(i)
    def cargar_det(self):
        if not self.lista.selectedItems(): return
        f = self.lista.selectedItems()[0].data(Qt.ItemDataRole.UserRole)
        d = self.db.ejecutar_query("SELECT k.codigo, k.cantidad, i.nombre FROM kardex k LEFT JOIN inventario i ON k.codigo = i.codigo WHERE k.fecha = ? AND (k.tipo_movimiento LIKE 'VENTA%' OR k.tipo_movimiento LIKE 'DEVOLUCION%')", (f,), fetch=True); self.tabla.setRowCount(0)
        for r, row in enumerate(d): self.tabla.insertRow(r); self.tabla.setItem(r, 0, QTableWidgetItem(str(row[0]))); self.tabla.setItem(r, 1, QTableWidgetItem(str(row[1]))); self.tabla.setItem(r, 2, QTableWidgetItem(str(row[2])))

class PantallaReportes(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.set_periodo('semana')

    def set_periodo(self, tipo):
        hoy = date.today()
        if tipo == 'semana': inicio = hoy - timedelta(days=hoy.weekday()); fin = inicio + timedelta(days=6)
        elif tipo == 'mes_actual': inicio = hoy.replace(day=1); next_month = (inicio.replace(day=28) + timedelta(days=4)); fin = next_month - timedelta(days=next_month.day)
        elif tipo == 'mes_anterior': fin = hoy.replace(day=1) - timedelta(days=1); inicio = fin.replace(day=1)
        elif tipo == 'anio': inicio = hoy.replace(month=1, day=1); fin = hoy.replace(month=12, day=31)
        self.date_ini.setDate(inicio); self.date_fin.setDate(fin); self.cargar_datos()

    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 20, 20, 20); lay.setSpacing(15)
        lay_top = QHBoxLayout()
        lay_top.addWidget(QLabel("Resumen de Ventas de la Semana Actual", styleSheet="font-size: 16px; font-weight: bold;"))
        lay_top.addStretch()
        self.combo_caja = QComboBox(); self.combo_caja.addItems(["Todas las Cajas", "Caja 1", "Caja 2", "Caja 3"]); self.combo_caja.currentTextChanged.connect(self.cargar_datos)
        lay_top.addWidget(self.combo_caja)
        lay.addLayout(lay_top)

        lay_links = QHBoxLayout()
        def btn_p(txt, t):
            b = QPushButton(txt); b.clicked.connect(lambda ch=False, x=t: self.set_periodo(x)); b.setStyleSheet("background: transparent; color: #0078D7; text-decoration: underline; border: none; font-size: 13px; padding: 0px;"); return b
        lay_links.addWidget(btn_p("Semana Actual", "semana")); lay_links.addWidget(btn_p("Mes Actual", "mes_actual")); lay_links.addWidget(btn_p("Mes Anterior", "mes_anterior")); lay_links.addWidget(btn_p("Año actual", "anio"))
        lay_links.addWidget(QLabel("  Periodo del:")); self.date_ini = QDateEdit(); self.date_ini.setCalendarPopup(True); self.date_fin = QDateEdit(); self.date_fin.setCalendarPopup(True); lay_links.addWidget(self.date_ini); lay_links.addWidget(QLabel("al")); lay_links.addWidget(self.date_fin)
        btn_buscar = QPushButton("Buscar"); btn_buscar.setObjectName("btnAccion"); btn_buscar.clicked.connect(self.cargar_datos); lay_links.addWidget(btn_buscar)
        lay_links.addStretch()
        lay.addLayout(lay_links)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setStyleSheet("color: #ccc;")
        lay.addWidget(line)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        p_izq = QWidget(); l_izq = QVBoxLayout(p_izq); l_izq.setContentsMargins(0,0,20,0)

        l_izq.addWidget(QLabel("Ventas por día", styleSheet="font-size: 15px; color: #555;"))
        self.tabla_dias = QTableWidget(0, 2); self.tabla_dias.horizontalHeader().setVisible(False); self.tabla_dias.verticalHeader().setVisible(False)
        self.tabla_dias.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_dias.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_dias.setShowGrid(False)
        self.tabla_dias.setStyleSheet("QTableWidget { border: none; background: transparent; } QTableWidget::item { border-bottom: 1px dotted #ccc; padding: 4px; }")
        l_izq.addWidget(self.tabla_dias)

        self.lbl_total_dias = QLabel("$0"); self.lbl_total_dias.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_total_dias.setStyleSheet("font-weight: bold; font-size: 15px; padding-right: 10px; border-top: 1px solid #999;")
        l_izq.addWidget(self.lbl_total_dias)

        l_izq.addSpacing(20)
        l_izq.addWidget(QLabel("Ventas por forma de pago", styleSheet="font-size: 15px; color: #555;"))
        self.plot_pago = pg.PlotWidget(axisItems={'left': EjeMoneda(orientation='left')})
        self.plot_pago.setFixedHeight(180)
        l_izq.addWidget(self.plot_pago)

        self.tabla_pagos = QTableWidget(0, 2); self.tabla_pagos.horizontalHeader().setVisible(False); self.tabla_pagos.verticalHeader().setVisible(False)
        self.tabla_pagos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_pagos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_pagos.setShowGrid(False)
        self.tabla_pagos.setStyleSheet("QTableWidget { border: none; background: transparent; } QTableWidget::item { padding: 2px; }")
        self.tabla_pagos.setFixedHeight(100)
        l_izq.addWidget(self.tabla_pagos)

        p_der = QWidget(); l_der = QVBoxLayout(p_der); l_der.setContentsMargins(20,0,0,0)
        l_der.addWidget(QLabel("Ventas por Departamento", styleSheet="font-size: 15px; color: #555;"))
        self.tabla_deptos = QTableWidget(0, 2); self.tabla_deptos.horizontalHeader().setVisible(False); self.tabla_deptos.verticalHeader().setVisible(False)
        self.tabla_deptos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_deptos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_deptos.setShowGrid(False)
        self.tabla_deptos.setStyleSheet("QTableWidget { border: none; background: transparent; } QTableWidget::item { padding: 4px; border-bottom: 1px dotted #e0e0e0; }")
        l_der.addWidget(self.tabla_deptos)

        splitter.addWidget(p_izq); splitter.addWidget(p_der); splitter.setSizes([450, 450])
        lay.addWidget(splitter)

    def cargar_datos(self):
        f_ini = self.date_ini.date().toString("yyyy-MM-dd") + " 00:00:00"; f_fin = self.date_fin.date().toString("yyyy-MM-dd") + " 23:59:59"
        caja = self.combo_caja.currentText(); filtro_caja = "" if caja == "Todas las Cajas" else f" AND caja = '{caja}' "; filtro_caja_kardex = "" if caja == "Todas las Cajas" else f" AND k.tipo_movimiento LIKE '%({caja})%' "

        self.plot_pago.clear(); self.plot_pago.setBackground(self.palette().color(self.backgroundRole())); self.plot_pago.getAxis('left').setPen('#666'); self.plot_pago.getAxis('bottom').setPen('#666')

        q_dias = f"SELECT substr(fecha,1,10) as dia, SUM(CASE WHEN tipo_operacion='VENTA' THEN total ELSE -total END) FROM ventas WHERE fecha >= ? AND fecha <= ? {filtro_caja} GROUP BY dia ORDER BY dia"
        dias_data = self.db.ejecutar_query(q_dias, (f_ini, f_fin), fetch=True); self.tabla_dias.setRowCount(0); tot_dias = 0.0; dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        for r, d in enumerate(dias_data):
            self.tabla_dias.insertRow(r); monto = float(d[1] or 0); tot_dias += monto
            try: nombre_dia = dias_semana[datetime.strptime(d[0], "%Y-%m-%d").weekday()]
            except: nombre_dia = d[0]
            item_dia = QTableWidgetItem(nombre_dia); item_dia.setForeground(QColor("#555")); self.tabla_dias.setItem(r, 0, item_dia)
            item_m = QTableWidgetItem(f"${monto:,.0f}".replace(',', '.')); item_m.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); self.tabla_dias.setItem(r, 1, item_m)
        self.lbl_total_dias.setText(f"${tot_dias:,.0f}".replace(',', '.'))

        pagos_data = self.db.ejecutar_query(f"SELECT metodo_pago, SUM(total) FROM ventas WHERE fecha >= ? AND fecha <= ? AND tipo_operacion='VENTA' {filtro_caja} GROUP BY metodo_pago", (f_ini, f_fin), fetch=True)
        self.tabla_pagos.setRowCount(0); x_p = []; y_p = []; ticks_p = []; colores = ['#0078D7', '#107c41', '#d13438', '#ffb900']
        for r, d in enumerate(pagos_data):
            self.tabla_pagos.insertRow(r); item_p = QTableWidgetItem(d[0]); item_p.setForeground(QColor("#555")); self.tabla_pagos.setItem(r, 0, item_p)
            monto = float(d[1] or 0)
            item_m = QTableWidgetItem(f"${monto:,.0f}".replace(',', '.')); item_m.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); self.tabla_pagos.setItem(r, 1, item_m)
            x_p.append(r); y_p.append(monto); ticks_p.append((r, d[0][:3])); self.plot_pago.addItem(pg.BarGraphItem(x=[r], height=[monto], width=0.5, brush=colores[r % len(colores)]))
        self.plot_pago.getAxis('bottom').setTicks([ticks_p])

        r = self.tabla_pagos.rowCount(); self.tabla_pagos.insertRow(r)
        it_imp = QTableWidgetItem("Impuestos (IVA ref)"); it_imp.setForeground(QColor("#555")); self.tabla_pagos.setItem(r, 0, it_imp)
        it_imp_v = QTableWidgetItem(f"${(tot_dias - (tot_dias/1.19)):,.0f}".replace(',', '.')); it_imp_v.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); self.tabla_pagos.setItem(r, 1, it_imp_v)

        query_deptos = f'''SELECT i.departamento, SUM(CASE WHEN k.tipo_movimiento LIKE 'VENTA%' THEN (k.cantidad * i.precio_venta) ELSE -(k.cantidad * i.precio_venta) END) FROM kardex k JOIN inventario i ON k.codigo = i.codigo WHERE k.fecha >= ? AND k.fecha <= ? {filtro_caja_kardex} AND (k.tipo_movimiento LIKE 'VENTA%' OR k.tipo_movimiento LIKE 'DEVOLUCION%') GROUP BY i.departamento ORDER BY 2 DESC'''
        deptos_data = self.db.ejecutar_query(query_deptos, (f_ini, f_fin), fetch=True); self.tabla_deptos.setRowCount(0)
        for r, d in enumerate(deptos_data):
            monto = float(d[1] or 0)
            if monto == 0: continue
            self.tabla_deptos.insertRow(self.tabla_deptos.rowCount()); r_idx = self.tabla_deptos.rowCount() - 1
            item_nom = QTableWidgetItem(str(d[0]).upper()); item_nom.setForeground(QColor("#555")); self.tabla_deptos.setItem(r_idx, 0, item_nom)
            item_m = QTableWidgetItem(f"${monto:,.0f}".replace(',', '.')); item_m.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); self.tabla_deptos.setItem(r_idx, 1, item_m)

class PantallaCorteDiario(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.cargar()

    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 20, 20, 20)
        p_filtros = QFrame(); lb = QHBoxLayout(p_filtros); lb.setContentsMargins(0,0,0,0)
        self.date_picker = QDateEdit(); self.date_picker.setCalendarPopup(True); self.date_picker.setDate(QDate.currentDate()); self.date_picker.dateChanged.connect(self.cargar); lb.addWidget(self.date_picker)
        self.combo_caja_filtro = QComboBox(); self.combo_caja_filtro.addItems(["Todas las Cajas", "Caja 1", "Caja 2", "Caja 3"]); self.combo_caja_filtro.currentTextChanged.connect(self.cargar); lb.addWidget(self.combo_caja_filtro)
        lb.addStretch()
        btn_imprimir = QPushButton("🖨️ Imprimir Reporte Z"); btn_imprimir.setStyleSheet("background-color: #f57c00; color: white;"); lb.addWidget(btn_imprimir); lay.addWidget(p_filtros)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        p_izq = QWidget(); l_izq = QVBoxLayout(p_izq); l_izq.setContentsMargins(0,0,10,0)

        lay_totales = QHBoxLayout()
        lay_totales.addWidget(QLabel("$ Ventas Totales", styleSheet="font-size: 20px; font-weight: bold; color: #333;"))
        self.lbl_ventas_totales = QLabel("$0", styleSheet="font-size: 20px; font-weight: bold; color: #0078D7;"); self.lbl_ventas_totales.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay_totales.addWidget(self.lbl_ventas_totales)
        l_izq.addLayout(lay_totales)

        l_izq.addWidget(QLabel("Ventas", styleSheet="font-size: 16px; font-weight: bold; color: #555; background: #e0e0e0; padding: 5px;"))
        self.tabla_fin = QTableWidget(0, 2); self.tabla_fin.horizontalHeader().setVisible(False); self.tabla_fin.verticalHeader().setVisible(False); self.tabla_fin.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.tabla_fin.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_fin.setShowGrid(False); self.tabla_fin.setStyleSheet("border: none; background: transparent;")
        l_izq.addWidget(self.tabla_fin)

        l_izq.addWidget(QLabel("Entradas de efectivo", styleSheet="font-size: 16px; font-weight: bold; color: #555; background: #e0e0e0; padding: 5px;"))
        self.lbl_entradas = QLabel("- No hubo Entradas en Efectivo -", styleSheet="color: #666; padding: 10px;"); self.lbl_entradas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_izq.addWidget(self.lbl_entradas)

        l_izq.addWidget(QLabel("Ingresos de contado", styleSheet="font-size: 16px; font-weight: bold; color: #555; background: #e0e0e0; padding: 5px;"))
        self.tabla_contado = QTableWidget(0, 2); self.tabla_contado.horizontalHeader().setVisible(False); self.tabla_contado.verticalHeader().setVisible(False); self.tabla_contado.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.tabla_contado.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_contado.setShowGrid(False); self.tabla_contado.setStyleSheet("border: none; background: transparent;"); self.tabla_contado.setFixedHeight(80)
        l_izq.addWidget(self.tabla_contado)

        p_der = QWidget(); l_der = QVBoxLayout(p_der); l_der.setContentsMargins(10,0,0,0)
        lay_ganancia = QHBoxLayout()
        lay_ganancia.addWidget(QLabel("Ganancia", styleSheet="font-size: 20px; font-weight: bold; color: #333;"))
        lay_ganancia.addStretch()
        self.lbl_ganancia_total = QLabel("$0", styleSheet="font-size: 20px; font-weight: bold; color: #107c41;")
        lay_ganancia.addWidget(self.lbl_ganancia_total)
        l_der.addLayout(lay_ganancia)

        l_der.addWidget(QLabel("Ventas por Departamento", styleSheet="font-size: 16px; font-weight: bold; color: #555; background: #e0e0e0; padding: 5px;"))
        self.tabla_deptos = QTableWidget(0, 2); self.tabla_deptos.horizontalHeader().setVisible(False); self.tabla_deptos.verticalHeader().setVisible(False); self.tabla_deptos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.tabla_deptos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_deptos.setShowGrid(False); self.tabla_deptos.setStyleSheet("border: none; background: transparent;")
        l_der.addWidget(self.tabla_deptos)

        splitter.addWidget(p_izq); splitter.addWidget(p_der); splitter.setSizes([450, 450])
        lay.addWidget(splitter)

    def cargar(self):
        fecha = self.date_picker.date().toString("yyyy-MM-dd"); caja = self.combo_caja_filtro.currentText(); f_caja = "" if caja == "Todas las Cajas" else f" AND caja = '{caja}'"; f_caja_kardex = "" if caja == "Todas las Cajas" else f" AND k.tipo_movimiento LIKE '%({caja})%'"
        datos_pagos = self.db.ejecutar_query(f"SELECT metodo_pago, SUM(total) FROM ventas WHERE fecha LIKE ? AND tipo_operacion='VENTA' {f_caja} GROUP BY metodo_pago", (f"{fecha}%",), fetch=True)
        datos_dev = self.db.ejecutar_query(f"SELECT SUM(total) FROM ventas WHERE fecha LIKE ? AND tipo_operacion='DEVOLUCION' {f_caja}", (f"{fecha}%",), fetch=True)
        total_dev = float(datos_dev[0][0]) if datos_dev and datos_dev[0][0] else 0.0

        self.tabla_fin.setRowCount(0); total_bruto = 0.0; efec = 0.0
        orden_metodos = ["Efectivo", "Tarjeta de Crédito", "Transferencia", "Mixto"]
        map_pagos = {d[0]: float(d[1] or 0) for d in datos_pagos}

        for m in orden_metodos:
            r = self.tabla_fin.rowCount(); self.tabla_fin.insertRow(r)
            self.tabla_fin.setItem(r, 0, QTableWidgetItem(f"En {m}" if m == "Efectivo" else m))
            val = map_pagos.get(m, 0.0); total_bruto += val
            if "Efectivo" in m: efec += val
            it_val = QTableWidgetItem(f"+ ${val:,.0f}".replace(',', '.')); it_val.setTextAlignment(Qt.AlignmentFlag.AlignRight)
            if val == 0: it_val.setForeground(QColor("#999"))
            self.tabla_fin.setItem(r, 1, it_val)

        r = self.tabla_fin.rowCount(); self.tabla_fin.insertRow(r)
        self.tabla_fin.setItem(r, 0, QTableWidgetItem("Devoluciones de Ventas"))
        it_dev = QTableWidgetItem(f"- ${total_dev:,.0f}".replace(',', '.')); it_dev.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        if total_dev > 0: it_dev.setForeground(QColor("#d13438"))
        else: it_dev.setForeground(QColor("#999"))
        self.tabla_fin.setItem(r, 1, it_dev)

        total_neto = total_bruto - total_dev
        self.lbl_ventas_totales.setText(f"${total_neto:,.0f}".replace(',', '.'))
        self.lbl_ganancia_total.setText(f"${total_neto / 1.19:,.0f}".replace(',', '.'))

        self.tabla_contado.setRowCount(0); self.tabla_contado.insertRow(0)
        self.tabla_contado.setItem(0, 0, QTableWidgetItem("Ventas en Efectivo"))
        it_ef_c = QTableWidgetItem(f"+ ${efec:,.0f}".replace(',', '.')); it_ef_c.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        self.tabla_contado.setItem(0, 1, it_ef_c)

        query_deptos = f"SELECT i.departamento, SUM(CASE WHEN k.tipo_movimiento LIKE 'VENTA%' THEN (k.cantidad * i.precio_venta) ELSE -(k.cantidad * i.precio_venta) END) FROM kardex k JOIN inventario i ON k.codigo = i.codigo WHERE k.fecha LIKE ? {f_caja_kardex} AND (k.tipo_movimiento LIKE 'VENTA%' OR k.tipo_movimiento LIKE 'DEVOLUCION%') GROUP BY i.departamento ORDER BY i.departamento"
        datos_deptos = self.db.ejecutar_query(query_deptos, (f"{fecha}%",), fetch=True); self.tabla_deptos.setRowCount(0)
        for d in datos_deptos:
            if float(d[1] or 0) == 0: continue
            r_idx = self.tabla_deptos.rowCount(); self.tabla_deptos.insertRow(r_idx)
            self.tabla_deptos.setItem(r_idx, 0, QTableWidgetItem(str(d[0])))
            it_m = QTableWidgetItem(f"${float(d[1] or 0):,.0f}".replace(',', '.')); it_m.setTextAlignment(Qt.AlignmentFlag.AlignRight)
            self.tabla_deptos.setItem(r_idx, 1, it_m)

class PantallaKardex(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()
    def al_mostrar(self): self.date_picker.setDate(QDate.currentDate()); self.cargar_historial()

    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 20, 20, 20)
        lay.addWidget(QLabel("HISTORIAL DE MOVIMIENTOS DE INVENTARIO", styleSheet="font-size: 16px; font-weight: bold; color: #444;"))

        p_filtros = QFrame(); p_filtros.setStyleSheet("background: #eef2f5; border: 1px solid #ccc;"); lh = QHBoxLayout(p_filtros)
        lh.addWidget(QLabel("Del día:")); self.date_picker = QDateEdit(); self.date_picker.setCalendarPopup(True); self.date_picker.dateChanged.connect(self.cargar_historial); lh.addWidget(self.date_picker)
        lh.addWidget(QLabel(" Buscar por:")); self.txt_busq_h = LineEditEnter(self.cargar_historial); self.txt_busq_h.setPlaceholderText("Cajero, Producto o Departamento"); lh.addWidget(self.txt_busq_h)
        lh.addWidget(QLabel("Movimientos")); self.combo_mov = QComboBox(); self.combo_mov.addItems(["- Todos -", "SALIDA", "ENTRADA"]); self.combo_mov.currentTextChanged.connect(self.cargar_historial); lh.addWidget(self.combo_mov)
        btn_act = QPushButton(" Actualizar"); btn_act.setObjectName("btnAccion"); btn_act.clicked.connect(self.cargar_historial); lh.addWidget(btn_act)
        lay.addWidget(p_filtros)

        self.tabla_h = QTableWidget(0, 9)
        self.tabla_h.setHorizontalHeaderLabels(["Hora", "Descripción del Producto", "Movimiento", "Había", "Tipo", "Cantidad", "Hay", "Cajero", "Departamento"])
        self.tabla_h.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabla_h.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.tabla_h.verticalHeader().setVisible(False)
        self.tabla_h.setAlternatingRowColors(True)
        self.tabla_h.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla_h.setStyleSheet("QTableWidget::item:selected { background-color: #0078D7; color: white; }")
        lay.addWidget(self.tabla_h)

    def cargar_historial(self):
        busq = self.txt_busq_h.text().strip(); f_mov = self.combo_mov.currentText()
        query = '''SELECT k.fecha, k.codigo, i.nombre, i.departamento, k.tipo_movimiento, k.cantidad, k.stock_resultante, k.usuario FROM kardex k LEFT JOIN inventario i ON k.codigo = i.codigo WHERE k.fecha LIKE ? '''
        params = [f"{self.date_picker.date().toString('yyyy-MM-dd')}%"]
        if busq: query += " AND (i.nombre LIKE ? OR k.usuario LIKE ? OR i.departamento LIKE ?)"; params.extend([f"%{busq}%", f"%{busq}%", f"%{busq}%"])

        datos = self.db.ejecutar_query(query + " ORDER BY k.id DESC", tuple(params), fetch=True)
        self.tabla_h.setRowCount(0)

        for r, d in enumerate(datos):
            mov_u = str(d[4]).upper()
            tipo = "SALIDA" if "VENTA" in mov_u or "BAJA" in mov_u else "ENTRADA"

            if f_mov != "- Todos -" and tipo != f_mov: continue

            hay = int(d[6]); cant = int(d[5]); habia = hay + cant if tipo == "SALIDA" else hay - cant
            self.tabla_h.insertRow(self.tabla_h.rowCount()); current_r = self.tabla_h.rowCount() - 1

            self.tabla_h.setItem(current_r, 0, QTableWidgetItem(d[0][11:16]))
            self.tabla_h.setItem(current_r, 1, QTableWidgetItem(str(d[2])))
            self.tabla_h.setItem(current_r, 2, QTableWidgetItem(str(d[4]).capitalize()))
            it_habia = QTableWidgetItem(str(habia)); it_habia.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tabla_h.setItem(current_r, 3, it_habia)

            lbl_tipo = QLabel(tipo); lbl_tipo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_tipo.setStyleSheet(f"background-color: {'#36454F' if tipo=='SALIDA' else '#0078D7'}; color: white; border-radius: 10px; font-size: 10px; font-weight: bold; margin: 2px 10px;")
            self.tabla_h.setCellWidget(current_r, 4, lbl_tipo)

            it_cant = QTableWidgetItem(str(cant)); it_cant.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tabla_h.setItem(current_r, 5, it_cant)
            it_hay = QTableWidgetItem(str(hay)); it_hay.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tabla_h.setItem(current_r, 6, it_hay)

            self.tabla_h.setItem(current_r, 7, QTableWidgetItem(str(d[7])))
            self.tabla_h.setItem(current_r, 8, QTableWidgetItem(str(d[3]).upper()))

class PantallaConfiguracion(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; self.crear_ui()

    def al_mostrar(self):
        self.sp_lineas_top.setValue(int(self.db.obtener_config('ticket_lineas_top') or 0)); self.chk_precio_unit.setChecked(self.db.obtener_config('ticket_precio_unit') == "1"); self.chk_desc_comp.setChecked(self.db.obtener_config('ticket_desc_comp') == "1"); self.chk_datos_cli.setChecked(self.db.obtener_config('ticket_datos_cli') == "1"); self.txt_emp_prev.setText(self.db.obtener_config('ticket_empresa')); self.txt_dir_prev.setText(self.db.obtener_config('ticket_direccion')); self.txt_tel_prev.setText(self.db.obtener_config('ticket_telefono')); self.txt_mail_prev.setText(self.db.obtener_config('ticket_correo')); self.txt_pie_prev.setText(self.db.obtener_config('ticket_pie'))

    def crear_ui(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 20, 20, 20)

        lay_title = QHBoxLayout()
        lay_title.addWidget(QLabel("CONFIGURACIÓN", styleSheet="font-size: 20px; color: white; background-color: #2D3E50; padding: 5px;"))
        lay.addLayout(lay_title)

        self.btn_toggle = QPushButton("✏️ Modificación de diseño de Ticket")
        self.btn_toggle.setStyleSheet("background: #e0e0e0; color: #333; border: 1px solid #aaa; padding: 8px; font-weight: bold;"); self.btn_toggle.setFixedWidth(300)
        self.btn_toggle.clicked.connect(self.toggle_ticket)
        lay.addWidget(self.btn_toggle)
        lay.addSpacing(10)

        self.panel_ticket = QFrame(); self.panel_ticket.hide()
        lay_pt = QVBoxLayout(self.panel_ticket); lay_pt.setContentsMargins(0,0,0,0)

        lay_pt.addWidget(QLabel("PERSONALIZACION DEL TICKET DE VENTA", styleSheet="font-size: 16px; font-weight: bold; color: #333;"))

        lay_main = QHBoxLayout()
        panel_preview = QFrame(); panel_preview.setStyleSheet("background: #f0f0f0; border: 1px solid #ccc;")
        lay_prev = QVBoxLayout(panel_preview)

        lay_top = QHBoxLayout()
        lay_top.addWidget(QLabel("↕")); self.sp_lineas_top = QSpinBox(); self.sp_lineas_top.setRange(0, 15); lay_top.addWidget(self.sp_lineas_top); lay_top.addWidget(QLabel("lineas"))
        lay_prev.addLayout(lay_top)

        panel_papel = QFrame(); panel_papel.setObjectName("ticketPreview")
        lay_papel = QVBoxLayout(panel_papel)

        lay_btn_logo = QHBoxLayout()
        lay_btn_logo.addWidget(QPushButton("🖼️ Agregar logotipo..."))
        lay_btn_logo.addWidget(QPushButton("🗑️ Quitar logotipo..."))
        lay_papel.addLayout(lay_btn_logo)

        self.txt_emp_prev = QLineEdit(); self.txt_emp_prev.setObjectName("ticketInput"); self.txt_emp_prev.setAlignment(Qt.AlignmentFlag.AlignCenter); self.txt_emp_prev.setStyleSheet("font-weight: bold; font-size: 14px; font-family: monospace;")
        self.txt_dir_prev = QLineEdit(); self.txt_dir_prev.setObjectName("ticketInput"); self.txt_dir_prev.setAlignment(Qt.AlignmentFlag.AlignLeft); self.txt_dir_prev.setStyleSheet("font-family: monospace;")
        self.txt_tel_prev = QLineEdit(); self.txt_tel_prev.setObjectName("ticketInput"); self.txt_tel_prev.setAlignment(Qt.AlignmentFlag.AlignLeft); self.txt_tel_prev.setStyleSheet("font-family: monospace;")
        self.txt_mail_prev = QLineEdit(); self.txt_mail_prev.setObjectName("ticketInput"); self.txt_mail_prev.setAlignment(Qt.AlignmentFlag.AlignLeft); self.txt_mail_prev.setStyleSheet("font-family: monospace;")

        lay_papel.addWidget(self.txt_emp_prev); lay_papel.addWidget(self.txt_dir_prev); lay_papel.addWidget(self.txt_tel_prev); lay_papel.addWidget(self.txt_mail_prev)

        txt_mock = QTextEdit(); txt_mock.setReadOnly(True)
        txt_mock.setPlainText("\nCant. Descripcion        Importe\n================================\n1   Agua Ciel 600ml        $7.00\n1   Coca Cola Light        $8.00\n1   Coca Sprite            $8.00\n1Kg Tomate                $10.00\n\n      No. de Articulos:  4\n      Total:  $33.00\n")
        txt_mock.setStyleSheet("background: transparent; border: none; font-family: monospace; font-size: 12px; color: black;"); txt_mock.setFixedHeight(170)
        lay_papel.addWidget(txt_mock)

        self.txt_pie_prev = QLineEdit(); self.txt_pie_prev.setObjectName("ticketInput"); self.txt_pie_prev.setAlignment(Qt.AlignmentFlag.AlignLeft)
        lay_papel.addWidget(self.txt_pie_prev)

        lay_bot = QHBoxLayout(); lay_bot.addWidget(QLabel("Lineas adicionales ...")); lay_bot.addWidget(QLabel("↕")); self.sp_lineas_bot = QSpinBox(); self.sp_lineas_bot.setRange(0, 15); lay_bot.addWidget(self.sp_lineas_bot); lay_bot.addWidget(QLabel("lineas"))
        lay_papel.addLayout(lay_bot)

        lay_prev.addWidget(panel_papel)
        lay_main.addWidget(panel_preview, stretch=1)

        panel_opts = QFrame(); lay_opts = QVBoxLayout(panel_opts); lay_opts.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chk_precio_unit = QCheckBox("Incluir Precio Unitario en la impresión del ticket."); self.chk_desc_comp = QCheckBox("Imprimir descripción completa (Usar varios renglones).")
        lay_opts.addWidget(self.chk_precio_unit); lay_opts.addWidget(self.chk_desc_comp)

        btn_probar = QPushButton("🖨️ Probar impresión con último ticket ..."); btn_probar.setStyleSheet("background-color: #ddd; color: #333; border: 1px solid #aaa; padding: 10px;")
        lay_opts.addWidget(btn_probar)

        lay_opts.addSpacing(20)
        lay_opts.addWidget(QLabel("Impresión de datos de cliente", styleSheet="font-weight: bold; font-size: 14px; color: #003366;"))
        self.chk_datos_cli = QCheckBox("Imprimir en todos los tickets los datos del cliente:"); lay_opts.addWidget(self.chk_datos_cli)

        lay_main.addWidget(panel_opts, stretch=1)
        lay_pt.addLayout(lay_main)

        btn_guardar = QPushButton("💾 Guardar Cambios"); btn_guardar.setObjectName("btnAccion"); btn_guardar.clicked.connect(self.guardar_todo)
        lay_pt.addWidget(btn_guardar, alignment=Qt.AlignmentFlag.AlignRight)

        lay.addWidget(self.panel_ticket)
        lay.addStretch()

    def toggle_ticket(self):
        self.panel_ticket.setVisible(not self.panel_ticket.isVisible())

    def guardar_todo(self):
        self.db.guardar_config('ticket_lineas_top', str(self.sp_lineas_top.value())); self.db.guardar_config('ticket_precio_unit', "1" if self.chk_precio_unit.isChecked() else "0"); self.db.guardar_config('ticket_desc_comp', "1" if self.chk_desc_comp.isChecked() else "0"); self.db.guardar_config('ticket_datos_cli', "1" if self.chk_datos_cli.isChecked() else "0"); self.db.guardar_config('ticket_empresa', self.txt_emp_prev.text()); self.db.guardar_config('ticket_direccion', self.txt_dir_prev.text()); self.db.guardar_config('ticket_telefono', self.txt_tel_prev.text()); self.db.guardar_config('ticket_correo', self.txt_mail_prev.text()); self.db.guardar_config('ticket_pie', self.txt_pie_prev.text()); QMessageBox.information(self, "Éxito", "Configuración de ticket guardada.")

class PantallaStock(QWidget):
    def __init__(self, db, mw): super().__init__(); self.db = db; self.mw = mw; lay = QVBoxLayout(self); lay.addWidget(QLabel("📊 ESTADO DEL INVENTARIO", styleSheet="font-size: 18px; font-weight: bold;")); self.tabla = QTableWidget(0,4); self.tabla.setHorizontalHeaderLabels(["CÓDIGO", "PRODUCTO", "DEPTO", "STOCK"]); self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch); lay.addWidget(self.tabla)
    def al_mostrar(self):
        d = self.db.ejecutar_query("SELECT codigo, nombre, departamento, stock FROM inventario", fetch=True); self.tabla.setRowCount(0)
        for r, row in enumerate(d): self.tabla.insertRow(r); self.tabla.setItem(r,0,QTableWidgetItem(str(row[0]))); self.tabla.setItem(r,1,QTableWidgetItem(str(row[1]))); self.tabla.setItem(r,2,QTableWidgetItem(str(row[2]))); self.tabla.setItem(r,3,QTableWidgetItem(str(row[3])))

# ==========================================
# VENTANA PRINCIPAL
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self, db, usuario, rol):
        super().__init__(); self.db = db; self.usuario_actual = usuario; self.rol_actual = rol; self.es_claro = (self.db.obtener_config("tema_sistema") == "Claro")

        self.setWindowTitle("CORAND.ERP © Todos los derechos reservados por Cristóbal Araya Cortés")

        self.showFullScreen()
        self.construir_ui(); self.aplicar_tema(self.es_claro); QTimer.singleShot(50, self.arranque)

        f_keys = [Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4, Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8, Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12]
        for idx, f_k in enumerate(f_keys):
            QShortcut(QKeySequence(f_k), self).activated.connect(lambda ch=False, x=idx: self.manejar_f_keys(x))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if not self.isMinimized() and not self.isFullScreen():
                QTimer.singleShot(50, self.showFullScreen)
        super().changeEvent(event)

    def manejar_f_keys(self, idx):
        if idx == 9:
            if self.pantallas.currentIndex() == 0:
                self.pantallas.currentWidget().abrir_buscador()
            else:
                self.cambiar_pantalla(9)
        elif idx == 11 and self.pantallas.currentIndex() == 0:
            self.pantallas.currentWidget().cobrar()
        else:
            self.cambiar_pantalla(idx)

    def arranque(self): self.pantallas.setCurrentIndex(0)

    def aplicar_tema(self, es_claro):
        self.es_claro = es_claro; self.setStyleSheet(EstilosGlobales.generar_hoja_estilos(es_claro))
        if hasattr(self, 'sb'): self.sb.setStyleSheet(f"background-color: {EstilosGlobales.obtener_paleta(es_claro)['panel']}; border-right: 1px solid {EstilosGlobales.obtener_paleta(es_claro)['border']};")

    def construir_ui(self):
        c_widget = QWidget(); self.setCentralWidget(c_widget); lay = QHBoxLayout(c_widget); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.sb = QFrame(); self.sb.setFixedWidth(260); ls = QVBoxLayout(self.sb); ls.setContentsMargins(10, 10, 10, 10)

        lbl_easy = QLabel("✚ EASY PHARMA"); lbl_easy.setStyleSheet("color: #0078D7; font-weight: 900; font-size: 20px; letter-spacing: 1px;"); ls.addWidget(lbl_easy)
        self.lusr = QLabel(f"👤 {self.usuario_actual.title()}"); ls.addWidget(self.lusr)

        def bn(t, idx): b = QPushButton(t); b.setObjectName("btnMenu"); b.setFixedHeight(45); b.clicked.connect(lambda checked, x=idx: self.cambiar_pantalla(x)); return b

        self.botones_menu = [
            bn("🛒 Punto de Venta (F1)", 0), bn("📦 Inventario (F2)", 1), bn("📅 Vencimientos (F3)", 2),
            bn("📖 Vademécum (F4)", 3), bn("📊 Stock Actual (F5)", 4), bn("🧾 Facturas (F6)", 5),
            bn("✂️ Corte Diario (F7)", 6), bn("🔻 Bajas / Mermas (F8)", 7), bn("📋 Movimientos (F9)", 8),
            bn("📈 Reportes (F10)", 9), bn("👥 Usuarios (F11)", 10), bn("⚙️ Configuración (F12)", 11),
            bn("🎫 Historial Tickets", 12)
        ]
        for b in self.botones_menu: ls.addWidget(b)

        ls.addStretch()

        btn_minimizar = QPushButton("🔽 Minimizar Ventana")
        btn_minimizar.setStyleSheet("background: #666666; color: white; padding: 10px; border-radius: 5px;")
        btn_minimizar.clicked.connect(self.showMinimized)
        ls.addWidget(btn_minimizar)

        btn_salir = QPushButton("✖️ Cerrar Programa")
        btn_salir.setStyleSheet("background: #d13438; color: white; padding: 10px; border-radius: 5px;")
        btn_salir.clicked.connect(self.close)
        ls.addWidget(btn_salir)

        self.lbl_t_caja = QLabel(""); ls.addWidget(self.lbl_t_caja); lay.addWidget(self.sb)
        self.pantallas = QStackedWidget(); lay.addWidget(self.pantallas)

        for w in [PantallaCaja, PantallaInventario, PantallaVencimientos, PantallaVademecum, PantallaStock, PantallaFacturas, PantallaCorteDiario, PantallaBajas, PantallaKardex, PantallaReportes, PantallaUsuarios, PantallaConfiguracion, PantallaTickets]: self.pantallas.addWidget(w(self.db, self))

    def cambiar_pantalla(self, idx):
        if idx >= self.pantallas.count(): return
        self.pantallas.setCurrentIndex(idx)
        if hasattr(self.pantallas.currentWidget(), 'al_mostrar'): self.pantallas.currentWidget().al_mostrar()

    def actualizar_resumen(self): pass

# ==========================================
# LOGIN CON MENÚ DESPLEGABLE Y FLECHAS
# ==========================================
class PantallaLogin(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db; self.setFixedSize(400, 500)
        self.setStyleSheet(EstilosGlobales.generar_hoja_estilos(self.db.obtener_config("tema_sistema") == "Claro"))
        lay_principal = QVBoxLayout(self); panel = QFrame(); panel.setObjectName("loginPanel")
        lay = QVBoxLayout(panel)

        lbl_icono = QLabel("✚"); lbl_icono.setStyleSheet("font-size: 60px; color: #0078D7;"); lbl_icono.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(lbl_icono)
        lbl_titulo = QLabel("EASY PHARMA"); lbl_titulo.setObjectName("lblTitulo"); lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(lbl_titulo)

        self.t_usr = ComboBoxEnter()
        self.t_usr.setEditable(True)
        self.t_usr.lineEdit().setPlaceholderText("👤 Usuario (Selecciona con la flecha)")
        self.t_usr.lineEdit().returnPressed.connect(self.foco_password)

        usuarios = self.db.ejecutar_query("SELECT usuario FROM usuarios", fetch=True)
        if usuarios:
            self.t_usr.addItems([u[0].title() for u in usuarios])
        else:
            self.t_usr.addItem("Admin")

        self.t_pwd = LineEditEnter(self.verificar)
        self.t_pwd.setPlaceholderText("🔒 Contraseña")
        self.t_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.t_usr); lay.addWidget(self.t_pwd)

        btn = QPushButton("INICIAR SESIÓN (Enter)"); btn.setObjectName("btnAccion"); btn.clicked.connect(self.verificar); lay.addWidget(btn)
        lay_principal.addWidget(panel)

    def foco_password(self):
        self.t_pwd.setFocus()

    def verificar(self):
        self.usr = self.t_usr.currentText().strip()
        self.rol = self.db.validar_login(self.usr, self.t_pwd.text())
        if self.rol: self.accept()
        else: QMessageBox.warning(self, "Error", "Credenciales incorrectas")

if __name__ == "__main__":
    app = QApplication(sys.argv); db = BaseDatos(); login = PantallaLogin(db)
    if login.exec() == QDialog.DialogCode.Accepted:
        ventana = MainWindow(db, login.usr, login.rol); sys.exit(app.exec())
