# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller para NejiPOS.exe. Desde la raíz del proyecto:
#     python -m PyInstaller --noconfirm --clean empaquetado/NejiPOS.spec
# Resultado: dist/NejiPOS/NejiPOS.exe + dist/NejiPOS/_internal/ (modo carpeta: arranca rápido,
# menos alertas de antivirus y se actualiza reemplazando la carpeta; los datos van aparte).
import os
import re
import sys

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))

# Versión: NEJI_VERSION=1.2.0 (la compilación en GitHub la toma del tag vX.Y.Z)
version = os.environ.get("NEJI_VERSION", "0.0.0")
numeros = ([int(n) for n in re.findall(r"\d+", version)] + [0, 0, 0, 0])[:4]
version_txt = ".".join(map(str, numeros))

info_version = None
if sys.platform == "win32":  # versioninfo usa pefile, que PyInstaller instala solo en Windows
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                     StringTable, VarFileInfo, VarStruct,
                                                     VSVersionInfo)
    info_version = VSVersionInfo(
        ffi=FixedFileInfo(filevers=tuple(numeros), prodvers=tuple(numeros)),
        kids=[
            StringFileInfo([StringTable("040A04B0", [  # español, Unicode
                StringStruct("CompanyName", "Neji POS"),
                StringStruct("FileDescription", "Neji POS - punto de venta"),
                StringStruct("FileVersion", version_txt),
                StringStruct("InternalName", "NejiPOS"),
                StringStruct("OriginalFilename", "NejiPOS.exe"),
                StringStruct("ProductName", "Neji POS"),
                StringStruct("ProductVersion", version_txt),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x040A, 1200])]),
        ],
    )

a = Analysis(
    [os.path.join(RAIZ, "escritorio.py")],
    pathex=[RAIZ],
    datas=[
        (os.path.join(RAIZ, "neji", "static"), os.path.join("neji", "static")),
        (os.path.join(RAIZ, "neji", "schema.sql"), "neji"),
    ],
    # pywebview trae su propio hook (DLL de WebView2 y su JS) y pyinstaller-hooks-contrib
    # los de pythonnet (clr, clr_loader): no hacen falta hiddenimports.
    hiddenimports=[],
    # CORAND.ERP (en el mismo repositorio) usa PyQt6 y pandas: no son parte de Neji POS.
    excludes=["tkinter", "pytest", "PyQt6", "PyQt5", "PySide6", "PySide2", "qtpy", "pyqtgraph",
              "pandas", "numpy", "openpyxl"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NejiPOS",
    console=False,  # sin ventana negra de consola
    icon=os.path.join(RAIZ, "empaquetado", "neji.ico"),
    version=info_version,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="NejiPOS", upx=False)
