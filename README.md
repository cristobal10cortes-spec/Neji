# Neji — CORAND.ERP (Easy Pharma)

Sistema de punto de venta e inventario para farmacia, escrito en **Python** con **PyQt6**.

> **VS Code no es un lenguaje**: es el editor donde se escribe y ejecuta este código.
> El programa sigue siendo Python, y funciona igual dentro de VS Code.

## Cómo abrirlo y ejecutarlo en VS Code

1. Instala **Python 3.10 o superior** desde https://www.python.org
   (en Windows marca la casilla **"Add Python to PATH"** al instalar).
2. Instala **VS Code** desde https://code.visualstudio.com
3. En VS Code: `Archivo → Abrir carpeta…` y elige esta carpeta (`Neji`).
   VS Code te sugerirá instalar la extensión **Python** de Microsoft: acepta.
4. Abre la terminal de VS Code (`Ver → Terminal`, o `Ctrl + ñ` / `` Ctrl + ` ``) y escribe:

   ```bash
   python -m venv .venv
   ```

   Activa el entorno:
   - Windows: `.venv\Scripts\activate`
   - Mac / Linux: `source .venv/bin/activate`

   Instala las librerías:

   ```bash
   pip install -r requirements.txt
   ```

5. Presiona **F5** (o el botón ▶️ arriba a la derecha) para ejecutar el programa.
   También puedes escribir en la terminal: `python corand_erp.py`

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `corand_erp.py` | El programa completo |
| `requirements.txt` | Lista de librerías que necesita (`pip install -r requirements.txt`) |
| `.vscode/launch.json` | Hace que **F5** ejecute el programa en VS Code |
| `.vscode/extensions.json` | Recomienda las extensiones de Python para VS Code |

La base de datos `corand_erp_pro.db` se crea sola la primera vez, en la misma carpeta del programa.

Usuario inicial: `admin` / contraseña `admin`.
