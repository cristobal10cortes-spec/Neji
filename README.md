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

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>.
   En el instalador marca **«Add Python to PATH»**.
2. Descarga esta carpeta (botón *Code → Download ZIP* en GitHub) y descomprímela,
   por ejemplo en `C:\NejiPOS`.
3. Haz doble clic en **`iniciar.bat`**.
   - La primera vez instala lo necesario; demora un minuto.
   - Después se abre el navegador en <http://localhost:5000>.
4. Configura el nombre del negocio y el usuario administrador (si es farmacia, marca
   «Es una farmacia»). ¡Listo para vender!

Para cerrarlo, cierra la ventana negra.
En Linux o macOS se usa `./iniciar.sh`.

### Recomendado: abrirlo como aplicación

Crea un acceso directo en el escritorio con este destino:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:5000 --kiosk-printing
```

- `--app` lo abre en su propia ventana, sin barra de direcciones.
- `--kiosk-printing` imprime el ticket directo en la impresora predeterminada,
  sin mostrar el cuadro de impresión.

Deja tu impresora térmica (58 u 80 mm) como predeterminada en Windows.
El ancho del ticket se elige en **Configuración → Negocio y ticket**.

### Lector de código de barras

Los lectores USB funcionan como un teclado: escanea en la pantalla de ventas y
el producto se agrega solo. Si el cursor no está en el campo de código, cualquier
tecla lo devuelve ahí.

### Varias cajas (multicaja)

1. En el computador principal abre **`iniciar-red.bat`**. La ventana muestra una
   dirección del tipo `http://192.168.1.20:5000`.
2. En los otros computadores o tablets de la misma red, abre esa dirección en
   el navegador.
3. Crea las cajas en **Configuración → Cajas**.
4. En cada equipo elige qué caja es en **Configuración → Esta terminal**.

Cada caja tiene su propio turno y su propio corte.

---

## Qué incluye

### Ventas (estilo eleventa)

- Captura por código de barras, con la sintaxis `3*código` para varias unidades.
- Búsqueda por descripción.
- Artículo común (un producto sin registrar).
- Venta **por unidad o a granel**: kilos con decimales, por ejemplo `0,755`.
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
- Al vender, el **aviso del vademécum** muestra para qué sirve el producto y sus
  efectos adversos, como en CORAND.ERP.
- **Búsqueda por componente**: en `F10` escribe `%paracetamol` para ver todos los
  productos que lo contienen.
- **Alternativas** (`Ctrl+B`): productos con el mismo principio activo (bioequivalentes
  u otras marcas), ordenados por parecido:
  - **misma dosis**: mismos principios activos y misma concentración (500 mg = 0,5 g);
  - **mismo principio, revisar dosis**: otra concentración, o no está registrada;
  - **comparte principio**: solo coincide alguno de sus principios activos.

  Dentro de cada grupo van primero los que tienen stock y los más baratos. Si un
  producto no tiene stock, el aviso recuerda usar `Ctrl+B`.
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

**Importar desde CORAND.ERP / Easy Pharma**

En **Configuración → Importar**, elige el archivo `corand_erp_pro.db` y Neji trae:

- Productos con su principio activo, distribuidor y vencimiento.
- El stock.
- El vademécum.
- Los precios de los principios activos del recetario y las fórmulas magistrales.
- Los datos del ticket.

Cómo funciona:

- Antes de importar hace un respaldo.
- No modifica el archivo original.
- No duplica si importas dos veces.

También se puede desde la línea de comandos:

```
python importar_corand.py ruta/a/corand_erp_pro.db
```

El detalle del análisis del programa anterior está en
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
- Historial de cortes.

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

- Roles **administrador** y **cajero**.
- Los cajeros no ven costos, reportes ni configuración.
- Se puede permitir o no que un cajero cambie precios o haga devoluciones.
- **Respaldo automático diario**, que guarda los últimos 10 (configurable),
  más respaldo y descarga manual.

---

## Atajos de teclado

| Tecla | Acción |
|---|---|
| `F1` `F2` `F3` `F4` | Ventas · Clientes · Productos · Inventario |
| `Enter` | Agregar el código escrito (`3*código` = 3 unidades) |
| `F10` | Buscar producto (`%paracetamol` busca por principio activo) |
| `INS` | Varios (cantidad + código) |
| `Ctrl+P` | Artículo común |
| `F11` o `Ctrl+M` | Precio de mayoreo en la línea |
| `↑` `↓` | Moverse por el ticket |
| `+` `-` `*` | Sumar, restar o escribir la cantidad |
| `Supr` | Borrar línea |
| `Ctrl+D` | Descuento |
| `F5` | Asignar cliente |
| `Ctrl+B` | Alternativas con el mismo principio activo (farmacia) |
| `F6` | Nuevo ticket (deja el actual pendiente) |
| `RePág` `AvPág` | Cambiar de ticket |
| `F7` `F8` | Entrada y salida de efectivo |
| `F9` | Verificador de precios |
| `F12` | Cobrar. En el cobro, `F1`–`F6` eligen la forma de pago y `Enter` confirma |

> Si alguna tecla F hace otra cosa en tu navegador (por ejemplo, `F11` pone pantalla
> completa), usa el acceso directo en modo aplicación o la tecla alternativa.

---

## Respaldos y restauración

- Los datos viven en la carpeta `datos/`: `neji.db` y la subcarpeta `respaldos/`.
- Descarga un respaldo de vez en cuando desde **Configuración → Respaldos** y
  guárdalo fuera del computador (en un pendrive o en la nube).

Para restaurar un respaldo:

1. Cierra Neji.
2. Reemplaza `datos/neji.db` por el archivo del respaldo, renombrado a `neji.db`.
3. Vuelve a abrir Neji.

## Migrar desde eleventa u otro sistema

1. En eleventa: **Productos → Exportar a Excel**. En otros sistemas, usa su
   exportación de productos.
2. Abre el archivo en Excel y guárdalo como **CSV (delimitado por punto y coma)**.
3. En Neji: **Productos → Importar CSV**.
   - Si el código ya existe, el producto se actualiza.
   - Si no existe, se crea.

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
importar_corand.py     importación desde CORAND.ERP por línea de comandos
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
