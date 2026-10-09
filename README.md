# Neji POS

Punto de venta para negocios en Chile: almacenes, minimarkets, botillerías,
ferreterías, tiendas en general y **farmacias con recetario magistral**.

Está inspirado en lo que los usuarios más valoran de **eleventa**, **SICAR**,
**Bsale** y **Loyverse**. Por ejemplo:

- Se maneja casi todo con el teclado, como eleventa.
- Tiene inventario y crédito a clientes al estilo SICAR.
- Considera reglas de Chile: IVA, RUT y redondeo del efectivo.
- La interfaz es limpia, como la de Loyverse.

El detalle de esa investigación está en [`docs/investigacion.md`](docs/investigacion.md).
No se copió código de ningún programa: todo está escrito desde cero.

Funciona **sin internet**: los datos quedan en el computador del negocio,
en una base SQLite con respaldo automático diario.

---

## Instalación en Windows

### Recomendado: el programa NejiPOS.exe

1. Descarga **`NejiPOS-Instalador.exe`**. Cada versión se compila sola en GitHub:
   pestaña **Actions → NejiPOS.exe (Windows)**, en el último resultado con ✓, sección
   *Artifacts*.
2. Ábrelo y sigue los pasos. No pide clave de administrador y crea el acceso directo
   **Neji POS** en el escritorio.
   - Windows puede mostrar «Windows protegió su PC» porque el programa no tiene firma
     digital pagada: haz clic en **Más información → Ejecutar de todas formas**.
3. Configura el nombre del negocio y el usuario administrador (si es farmacia, marca
   «Es una farmacia»). ¡Listo para vender!

Neji POS se abre en **su propia ventana**, sin navegador ni ventana negra:

- Funciona con **Microsoft Edge WebView2**, que ya viene en Windows 10 y 11. Si falta,
  el programa lo avisa y ofrece instalarlo.
- Si en vez de su ventana se abre el navegador, el mensaje explica por qué. Si falta
  WebView2, ofrece instalarlo, y el detalle queda en `neji.log`, dentro de la carpeta de datos.
- **Tus datos no están en la carpeta del programa**, sino en
  `%LOCALAPPDATA%\NejiPOS\datos`; la ruta exacta aparece en
  **Configuración → Respaldos**. Por eso actualizar o desinstalar el programa no los toca.
- Para actualizar, instala la versión nueva encima de la anterior.
- **Versión portátil:** `NejiPOS-portable.zip` trae la carpeta del programa sin
  instalador. Si junto a `NejiPOS.exe` pones una carpeta `datos` con tu `neji.db`, usa
  esa (útil para llevarlo en un pendrive o para pasar los datos de la versión anterior).
- F5 y F12 no hacen nada fuera de la venta: son atajos de Neji (cliente, cobrar).
  Para recargar la pantalla usa `Ctrl+Shift+R`.

**Impresora de tickets:** NejiPOS.exe encuentra sola las impresoras instaladas en el
computador (USB, red o serie: POS-80, POS-58, XP-80, SLK, Epson TM, Bixolon…) y manda
el ticket directo a la de tickets, sin cuadro de impresión. Basta con tener instalado
el controlador de la impresora. En **Configuración → Impresora de tickets** se ve cuál
encontró y se puede elegir otra, el papel (80 o 58 mm), cortar el papel, abrir el cajón
de dinero al cobrar en efectivo e imprimir una prueba. Cada caja usa su propia impresora,
también las que se conectan a otro equipo con `--conectar`.

### Con Python (para quien prefiera el navegador)

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>.
   En el instalador marca **«Add Python to PATH»**.
2. Descarga esta carpeta (botón *Code → Download ZIP* en GitHub) y descomprímela,
   por ejemplo en `C:\NejiPOS`.
3. Haz doble clic en **`iniciar.bat`**.
   - La primera vez instala lo necesario; demora un minuto.
   - Después se abre el navegador en <http://localhost:5000>.

Para cerrarlo, cierra la ventana negra. En Linux o macOS se usa `./iniciar.sh`.
Los datos quedan en la carpeta `datos/` del proyecto.

Para abrirlo como aplicación desde el navegador, crea un acceso directo con este destino:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:5000 --kiosk-printing
```

- `--app` lo abre en su propia ventana, sin barra de direcciones.
- `--kiosk-printing` imprime el ticket directo en la impresora predeterminada.

El ancho del ticket se elige en **Configuración → Negocio y ticket**.

### Lector de código de barras

Los lectores USB funcionan como un teclado: escanea en la pantalla de ventas y
el producto se agrega solo. Si el cursor no está en el campo de código, cualquier
tecla lo devuelve ahí.

### Varias cajas (multicaja)

1. En el computador principal, marca **Configuración → Cajas → Permitir que otras
   cajas de la red se conecten** y vuelve a abrir Neji POS. Ahí mismo aparece la
   dirección para las otras cajas, del tipo `http://192.168.1.20:5000`.
   - La primera vez Windows pregunta si permite el acceso a la red: acepta en
     **Redes privadas**.
   - Con Python, `iniciar-red.bat` hace lo mismo.
2. En los otros computadores abre esa dirección en el navegador, o crea un acceso
   directo a `NejiPOS.exe --conectar 192.168.1.20` para usarla en su propia ventana.
3. Crea las cajas en **Configuración → Cajas**.
4. En cada equipo elige qué caja es en **Configuración → Esta terminal**.

El computador principal debe quedar encendido y con Neji POS abierto mientras las
otras cajas vendan. Cada caja tiene su propio turno y su propio corte.

---

## Qué incluye

### Ventas (estilo eleventa)

- Captura por código de barras, con la sintaxis `3*código` para varias unidades.
- **Buscador en vivo**: al escribir un nombre en el mismo campo del código aparece la
  lista de productos con su código, nombre, precio y existencia. Se elige con `↑` `↓` y
  `Enter`, o con un clic. Si el nombre calza con un solo producto, `Enter` lo agrega
  directo; si lo escrito solo se parece a un código (o son solo números), pide
  confirmar con `Enter`. `3*nombre` también funciona.
- Los atajos (`INS` Varios, `Ctrl+P` Art. común, `F10` Buscar, `F11` Mayoreo,
  `F9` Verificador, `F7` Entrada, `F8` Salida) van en una fila bajo el buscador, como en
  eleventa, y **Cancelar ticket** queda justo encima de **Cobrar**.
- Artículo común (un producto sin registrar).
- Venta **por unidad o a granel**: kilos con decimales, por ejemplo `0,755`.
- **Números a la chilena** en todas las pantallas y en los CSV: la coma es decimal y el
  punto separa miles (`5.000` son cinco mil; `1,25` es uno coma veinticinco).
- **Precio de mayoreo**: con `F11`, o automático desde cierta cantidad.
- **Varios tickets abiertos** a la vez (`F6`), para atender a otro cliente
  mientras el primero busca algo.
- Descuento por monto o porcentaje, y cambio de precio en una línea, ambos con permiso.
- **Cobro** en efectivo (botones de billetes y cálculo del cambio), débito,
  crédito, transferencia, **fiado** o **pago mixto**.
- **Redondeo del efectivo según la Ley 20.956**. La boleta y los reportes guardan
  el monto exacto.
- Ticket con desglose de **neto e IVA**, para impresoras de 58 u 80 mm.
- **Cotizaciones** que no descuentan inventario y después se cargan en un ticket
  para venderlas.

### Farmacia: vademécum y recetario magistral

Se activa en **Configuración → Opciones → Farmacia**, o al configurar Neji por primera vez.

**Vademécum**

- Cada producto tiene sus **principios activos** con concentración, por ejemplo
  `PARACETAMOL 500 mg + CAFEINA 65 mg`.
- Cada principio activo tiene su ficha: acción terapéutica, efectos adversos,
  contraindicaciones y notas.
- Al vender, la **ficha del vademécum** se muestra a la izquierda del buscador: para
  qué sirve, efectos adversos, contraindicaciones y notas de cada principio activo.
  Sigue al producto marcado en el buscador o a la línea elegida del ticket.
- Lo que se escribe en el vademécum se ve igual en la venta. El administrador puede
  **editar la ficha desde la misma venta** (botón Editar, también en la ficha de `F10`) y
  el cambio aparece al tiro. Los textos largos se ven resumidos: un clic los abre
  completos, y el botón Ficha muestra todo.
- **Búsqueda por componente**: en el buscador (o en `F10`) escribe `%paracetamol` para
  ver todos los productos que lo contienen.
- **Alternativas** (`Ctrl+B`): productos con el mismo principio activo (bioequivalentes
  u otras marcas), ordenados por parecido:
  - **misma dosis**: mismos principios activos y misma concentración (500 mg = 0,5 g);
  - **mismo principio, revisar dosis**: otra concentración, o no está registrada;
  - **comparte principio**: solo coincide alguno de sus principios activos.

  Dentro de cada grupo van primero los que tienen stock y los más baratos. Si un
  producto no tiene stock, la ficha lo marca y recuerda usar `Ctrl+B`.
- La pantalla **Vademécum** lista los principios activos con cuántos productos hay en
  stock. Desde la ficha se puede vender directamente.

**Recetario magistral**

- **Calculadora** para cápsulas, cremas, lociones o cualquier forma que crees.
  Usa la misma fórmula que CORAND.ERP:
  - Cada principio activo suma: precio × dosis por unidad × cantidad.
  - A eso se agrega el precio por cápsula/gramo/ml × cantidad, más el valor base.
  - Al final se suma el IVA.
- **Unidades**: convierte entre mg, mcg y g (500 mg = 0,5 g). En cremas y lociones
  acepta **porcentajes** (2 % = 0,02 g por gramo).
- Calcula **cuánto pesar** de cada principio activo, por ejemplo: 15 g de paracetamol
  para 30 cápsulas de 500 mg.
- **Libro de recetas**:
  - Cada receta queda guardada con folio, paciente, RUT, médico, indicaciones,
    composición y precio.
  - Estado: pendiente, vendida o anulada.
  - Se exporta a CSV.
- **Enviar a la venta** (`Enter`):
  - La receta entra al ticket con su precio, fijado por el servidor.
  - Al cobrar queda "vendida". Si se devuelve, queda "anulada".
  - En reportes y en el corte aparece como "Recetario magistral".
- **Orden de preparación / presupuesto** impreso, con la composición y lo que hay que pesar.
- **Configuración**: formas farmacéuticas, precios netos de cada principio activo y
  redondeo del total ($1, $10, $50 o $100).

**Vencimientos**

- Cada producto puede tener **proveedor/distribuidor** y **fecha de vencimiento**.
- **Inventario → Vencimientos** lista lo que vence pronto.

**Importar el inventario desde CSV**

En **Configuración → Importar inventario (CSV)** (o en Productos → Importar CSV) se sube
una planilla guardada como CSV desde Excel, eleventa u otro sistema:

- Crea los productos nuevos y actualiza los que ya existen (por código), con su
  principio activo, distribuidor, vencimiento y stock.
- La existencia puede **reemplazar** el stock (conteo de inventario) o **sumarse**
  (entrada de mercadería). Cada cambio queda en el kardex.
- Trae una **planilla de ejemplo** para descargar con todas las columnas.

El análisis del programa anterior (CORAND.ERP) está en
[`docs/analisis-corand.md`](docs/analisis-corand.md).

### Productos e inventario

- Departamentos.
- Precio de costo, % de ganancia, precio de venta y mayoreo.
- Productos exentos de IVA.
- Generador de código interno EAN-13 para productos sin código de barras.
- **Etiquetas con código de barras** (Code 128) para imprimir.
- Entradas de mercadería (actualizan el costo), salidas por merma y ajustes por conteo físico.
- **Kardex**: el historial de cada producto.
- **Compras sugeridas**: productos bajo el mínimo, con lo vendido en los últimos 30 días.
- Opción de permitir inventario negativo.
- **Importar y exportar CSV**, para traer el catálogo desde Excel o eleventa.
  - Entiende columnas como «Código», «Precio Venta», «Costo», «Stock» o «Categoría».
  - Acepta archivos separados por `;` o por `,`.

### Clientes y crédito

- RUT validado con su dígito verificador.
- Límite de crédito: una cantidad fija, sin crédito o sin límite.
- Ventas **fiadas**, **abonos** y **estado de cuenta** imprimible.

### Caja y corte

- Apertura de turno con fondo inicial.
- Entradas y salidas de efectivo (`F7` y `F8`).
- **Estado de caja en vivo**: cuánto debería haber en el cajón.
- **Corte de caja**: se compara lo contado con lo esperado y se indica el faltante o sobrante.
  También muestra las ventas por forma de pago y por departamento.
- **Corte general** desde la caja principal: se cuenta el efectivo de cada caja y se cierran
  todas juntas. El ticket suma todas las cajas y muestra lo vendido por cada cajero. La caja
  principal se elige en **Configuración → Cajas**.
- Historial de cortes y de cortes generales.

### Devoluciones

- Parciales o del ticket completo.
- Devuelven el producto al inventario.
- Reembolsan en efectivo o como reversa de tarjeta.
- En una venta fiada, descuentan la deuda del cliente.

### Reportes (administrador)

- Ventas netas, número de tickets, ticket promedio, ganancia y margen, IVA débito,
  devoluciones y descuentos.
- Ventas por día, por hora, por forma de pago, por cajero y por departamento,
  y los productos más vendidos.
- Exportación del detalle a CSV.

### Usuarios y seguridad

- En **Configuración → Usuarios** se agregan y modifican usuarios.
- Roles **administrador** (puede todo) y **cajero**.
- Cada cajero tiene **sus propios permisos**: cambiar precios y descuentos, devoluciones,
  entradas y salidas de efectivo, corte de su caja, corte general, crédito a clientes,
  productos, inventario, reportes y costos, y vademécum.
- **Nombre en el ticket**: cómo aparece cada usuario en «Atendió:» (por ejemplo
  «Cajero 1 · Cristóbal Araya Cortés»), con una vista previa del ticket al lado.
- **Respaldo automático diario**, que guarda los últimos 10 (configurable),
  más respaldo y descarga manual.

---

## Atajos de teclado

| Tecla | Acción |
|---|---|
| `F1` `F2` `F3` `F4` | Ventas · Clientes · Productos · Inventario |
| `Enter` | Agregar el código escrito (`3*código` = 3 unidades) o el producto elegido en la lista |
| `↑` `↓` con texto escrito | Moverse por la lista del buscador (la ficha del vademécum la sigue) |
| `Esc` | Cerrar la lista del buscador y borrar lo escrito (o cancelar un `Enter` que espera al servidor) |
| `F10` | Buscar producto en una ventana grande (`%paracetamol` busca por principio activo) |
| `INS` | Varios (cantidad + código) |
| `Ctrl+P` | Artículo común |
| `F11` o `Ctrl+M` | Precio de mayoreo en la línea |
| `↑` `↓` | Moverse por el ticket (con el buscador vacío) |
| `+` `-` `*` | Sumar, restar o escribir la cantidad |
| `Supr` | Borrar línea |
| `Ctrl+D` | Descuento |
| `F5` | Asignar cliente |
| `Ctrl+B` | Alternativas con el mismo principio activo del producto que muestra la ficha (farmacia) |
| `F6` | Nuevo ticket (deja el actual pendiente) |
| `RePág` `AvPág` | Cambiar de ticket |
| `F7` `F8` | Entrada y salida de efectivo |
| `F9` | Verificador de precios |
| `F12` | Cobrar. En el cobro, `F1`–`F6` eligen la forma de pago y `Enter` confirma |

> Si alguna tecla F hace otra cosa en tu navegador (por ejemplo, `F11` pone pantalla
> completa), usa el acceso directo en modo aplicación o la tecla alternativa.

---

## Respaldos y restauración

- Los datos viven en la carpeta de datos: `neji.db` y la subcarpeta `respaldos/`.
  Con `NejiPOS.exe` es `%LOCALAPPDATA%\NejiPOS\datos`; con Python, `datos/` dentro
  del proyecto. La ruta exacta aparece en **Configuración → Respaldos**.
- Descarga un respaldo de vez en cuando desde **Configuración → Respaldos** y
  guárdalo fuera del computador (en un pendrive o en la nube).

Para restaurar un respaldo:

1. Cierra Neji.
2. Reemplaza `neji.db` de la carpeta de datos por el archivo del respaldo, renombrado
   a `neji.db`.
3. Vuelve a abrir Neji.

## Migrar desde eleventa u otro sistema

1. En eleventa: **Productos → Exportar a Excel**. En otros sistemas, usa su
   exportación de productos.
2. Abre el archivo en Excel y guárdalo como **CSV (delimitado por punto y coma)**.
3. En Neji: **Configuración → Importar inventario (CSV)** (o **Productos → Importar CSV**).
   - Si el código ya existe, el producto se actualiza.
   - Si no existe, se crea.
   - Elige si la existencia reemplaza el stock o se suma a él.

---

## Para desarrolladores

Tecnologías:

- **Backend**: Python 3, Flask y SQLite (con `waitress` para servirlo).
- **Frontend**: HTML, CSS y JavaScript sin dependencias ni paso de compilación.

```
neji/
  __init__.py          crea la app Flask
  schema.sql           tablas (montos en pesos enteros, cantidades con 3 decimales)
  db.py                conexión, transacciones y configuración por defecto
  chile.py             RUT, IVA y redondeo Ley 20.956
  validar.py           lectura segura de datos y errores de negocio
  respaldos.py         respaldo automático
  auth.py              sesión y permisos
  servicios/           reglas de negocio (ventas, devoluciones, caja, inventario, fiado)
  api/                 rutas JSON bajo /api
  static/              interfaz (index.html, css/, js/, js/vistas/)
tests/                 pruebas con pytest
run.py                 inicia el servidor y abre el navegador
escritorio.py          NejiPOS.exe: servidor + ventana propia (pywebview / WebView2)
empaquetado/           receta de PyInstaller, instalador (Inno Setup) e ícono
docs/investigacion.md  lo mejor de cada POS y qué se tomó de cada uno
```

- Los precios **siempre los calcula el servidor** a partir del catálogo: el
  navegador solo envía producto, cantidad y tipo de precio.
- Cada venta se guarda en una sola transacción. El folio, el inventario, los
  pagos y el fiado quedan consistentes aunque haya varias cajas.

Para correr las pruebas:

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip ...
.venv/bin/python -m pytest
```

Para compilar `NejiPOS.exe` (lo hace solo el workflow
`.github/workflows/windows-exe.yml` en cada cambio; a mano, en Windows con Python 3.12):

```
py -3.12 -m pip install -r requirements-exe.txt pytest
py -3.12 -m PyInstaller --noconfirm --clean empaquetado\NejiPOS.spec
dist\NejiPOS\NejiPOS.exe --prueba          # prueba sin ventana: sale con 0 si todo responde
iscc empaquetado\NejiPOS.iss                # instalador (Inno Setup 6) -> dist\NejiPOS-Instalador.exe
                                            # (antes, deja build\MicrosoftEdgeWebview2Setup.exe)
```

Para agregar una función nueva:

1. Agrega la tabla o columna en `schema.sql`.
2. Escribe la regla en `servicios/` y la ruta en `api/`.
3. Haz la pantalla en `static/js/vistas/` y regístrala en `static/js/app.js`.

## Hoja de ruta

- [ ] **Boleta y factura electrónica SII**, a través de un proveedor certificado
  (LibreDTE, OpenFactura, etc.) o con certificación propia.
- [ ] Integración con máquinas de tarjeta (Transbank, Getnet, Mercado Pago, SumUp).
- [ ] Lotes con fecha de vencimiento propia (hoy hay una fecha por producto).
- [ ] Kits, paquetes y promociones (2x1, 3x2).
- [ ] Puntos de fidelización (Loyverse).
- [ ] Varios niveles de precio (menudeo, medio mayoreo, mayoreo).
- [ ] Balanzas con etiqueta de peso (códigos que empiezan con 2).
- [ ] Enviar el ticket por correo o WhatsApp.

---

## El programa anterior: CORAND.ERP / Easy Pharma (`corand_erp.py`)

Este repositorio también guarda el programa original de la farmacia, como referencia. Para
pasar el inventario a Neji POS, expórtalo a una planilla y súbela en **Configuración →
Importar inventario (CSV)**.

Sistema de punto de venta e inventario para farmacia, escrito en **Python** con **PyQt6**.

> **VS Code no es un lenguaje**: es el editor donde se escribe y ejecuta este código.
> El programa sigue siendo Python, y funciona igual dentro de VS Code.

### Cómo abrirlo y ejecutarlo en VS Code

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

### Archivos

| Archivo | Para qué sirve |
|---|---|
| `corand_erp.py` | El programa completo |
| `requirements.txt` | Librerías de los dos programas, CORAND.ERP y Neji POS (`pip install -r requirements.txt`) |
| `.vscode/launch.json` | Hace que **F5** ejecute el programa en VS Code |
| `.vscode/extensions.json` | Recomienda las extensiones de Python para VS Code |

La base de datos `corand_erp_pro.db` se crea sola la primera vez, en la misma carpeta del programa.

Usuario inicial: `admin` / contraseña `admin`.
