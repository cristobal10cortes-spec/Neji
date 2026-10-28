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
en una base SQLite con respaldo automático diario. También puede vivir **en internet**
(así funciona Farmacia Piedra): ver [Farmacia Piedra en internet](#farmacia-piedra-en-internet).

---

## Farmacia Piedra en internet

La misma aplicación, en un servidor: cada caja entra desde Chrome a una dirección
(por ejemplo `https://farmacia-piedra.onrender.com`) con su usuario, sin instalar nada.
Los datos quedan en el servidor, con el mismo respaldo automático diario.

**Dónde vive:** [Render](https://render.com), en Virginia (EE.UU.), con un disco de 1 GB
para la base de datos. La configuración está en `render.yaml` y `Dockerfile`. Usa el plan
Starter más el disco (revisa los precios vigentes en render.com): el plan gratis no
permite disco y los datos se perderían.

**Primera vez:**

1. Crea una cuenta en render.com entrando con GitHub.
2. **New → Blueprint**, elige este repositorio y la rama `main`.
3. Render pide `NEJI_CODIGO_INSTALACION`: escribe un código largo que solo tú sepas.
4. **Apply**. Cuando termine, abre la dirección del servicio (arriba en su página).
5. La primera pantalla pide ese **código de instalación**: así nadie más puede crear
   el administrador.
6. Para traer los datos del programa de Windows, entra como administrador a
   **Configuración → Respaldos → Restaurar un respaldo** y sube el archivo `neji.db`
   (o un respaldo descargado desde el programa).

**Actualizar:** es automático: cada cambio que entra a `main` se publica solo.

**Prueba gratis en PythonAnywhere** (para mostrarla; es más lenta y la cuenta gratis se
debe renovar con un clic cada 3 meses):

1. Crea una cuenta gratis en [pythonanywhere.com](https://www.pythonanywhere.com)
   (el nombre de usuario queda en la dirección: `usuario.pythonanywhere.com`).
2. **Files**: sube `farmacia-piedra.zip` (las carpetas `neji/` y `wsgi_pythonanywhere.py`
   comprimidas).
3. **Consoles → Bash**, y escribe:
   `unzip farmacia-piedra.zip -d farmacia && python3.11 -m pip install --user "flask>=3"`
4. **Web → Add a new web app → Manual configuration → Python 3.11**.
5. En esa página, abre el **WSGI configuration file**, borra todo y deja solo las cuatro
   líneas que están al comienzo de `wsgi_pythonanywhere.py` (con tu código de instalación).
   Guarda, activa **Force HTTPS** y presiona **Reload**.
6. Abre `https://usuario.pythonanywhere.com` y sigue como en Render (código de instalación,
   administrador y, si quieres, restaurar el `neji.db` del programa de Windows).

(También está `fly.toml` para [Fly.io](https://fly.io), con servidor en Santiago:
`fly volumes create datos --region scl --size 1`, `fly secrets set NEJI_CODIGO_INSTALACION=...`
y `fly deploy`.)

**Imprimir tickets:** en el navegador se usa el cuadro de impresión. Para que el ticket
salga directo, deja la impresora de tickets como **predeterminada** en ese computador y
crea un acceso directo de Chrome con:

```
chrome.exe --kiosk-printing --app=https://farmacia-piedra.onrender.com
```

El cajón de dinero se abre si la impresora lo hace al imprimir (opción del controlador).

**Variables del servidor:** `NEJI_WEB=1` (la pone el Dockerfile: HTTPS, código de
instalación), `NEJI_MARCA` (el nombre arriba a la izquierda), `NEJI_CODIGO_INSTALACION`,
`NEJI_DATOS` (carpeta de datos) y `NEJI_CLAVE_SECRETA` (opcional; si falta, se crea una en
la carpeta de datos). Debe correr **una sola máquina**: la base es un archivo SQLite.
Tras 8 contraseñas fallidas seguidas, ese usuario espera 15 minutos (30 desde una misma dirección).

## Instalación en Windows

### Recomendado: el programa NejiPOS.exe

1. Descarga **`NejiPOS-Instalador-<versión>.exe`** (por ejemplo `NejiPOS-Instalador-0.1.12.exe`).
   Cada versión se compila sola en GitHub: pestaña **Actions → NejiPOS.exe (Windows)**, en el
   último resultado con ✓, sección *Artifacts*.
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
- Para actualizar, instala la versión nueva encima de la anterior. Si Neji POS está abierto, el
  instalador lo cierra. La versión que está abierta se ve en el título de la ventana, al entrar
  y en **Configuración**; si abres la nueva con la anterior abierta, la nueva ofrece cerrarla.
- **Versión portátil:** `NejiPOS-portable-<versión>.zip` trae la carpeta del programa sin
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

- Solo elige sola impresoras de tickets, y prefiere una que esté en línea. Las de tinta,
  láser o etiquetas nunca se eligen solas.
- Si el nombre dice 58 (POS-58, XP-58) usa papel de 58 mm; si no, el ancho de
  **Configuración → Ticket** (80 mm de fábrica).
- A las POS-58/POS-80 genéricas les apaga el «modo chino» para que las tildes y la ñ no
  salgan como letras chinas (se puede cambiar en **Avanzado**).
- **USB directo:** si la impresora de tickets está conectada por USB, Neji le manda el
  ticket por el mismo cable USB, sin pasar por la cola de impresión de Windows (no quedan
  trabajos atascados). Una impresora USB **sin controlador instalado** igual aparece en la
  lista, como «POS-80 (USB directo)», y se puede usar. Si el envío directo no resulta, usa el
  controlador de Windows. Se apaga en **Avanzado** («mandar el ticket directo por el USB»).
- Para soporte: `NejiPOS.exe --listar-impresoras` muestra las impresoras que ve y
  `NejiPOS.exe --prueba-impresora "POS-80"` imprime un ticket de prueba.

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

El ancho del ticket se elige en **Configuración → Ticket**.

### Lector de código de barras

Lo que lee el lector **va siempre a la venta**: escanea en cualquier pantalla y el producto
se agrega al ticket, aunque el cursor esté en un botón, en el buscador de clientes o en
otra pantalla (Neji vuelve a Ventas). Lo escaneado no queda escrito donde estaba el cursor.

- Solo se queda donde está el cursor en los campos para códigos: el código de un producto
  nuevo, el verificador de precios (F9), «Varios» o el buscador del inventario.
- Con el cobro u otra ventana abierta no se escribe en ella: avisa «Hay una ventana abierta».
  Con la ventana «Venta registrada», el producto siguiente la cierra y empieza la venta nueva.
- Los lectores **USB de teclado** (la mayoría) no necesitan nada: Neji reconoce la ráfaga
  rápida de letras del lector y la distingue de alguien escribiendo.
- Los lectores **USB COM** («USB serie», «USB CDC») los lee NejiPOS.exe directo del puerto:
  los de marcas conocidas (Honeywell, Zebra/Symbol, Datalogic, Newland, Zebex…) se usan
  solos y los demás se activan en **Configuración → Esta terminal → Lectores por puerto COM**.
  En el navegador solo funcionan los lectores de teclado.
- En **Configuración → Esta terminal** está «Probar el lector» (muestra lo leído sin vender)
  y se puede apagar «siempre a la venta» para que escriba donde está el cursor.
- Los lectores en modo «HID POS» (no teclado ni COM) no se leen: cámbialos a modo teclado
  o COM con el código de configuración de su manual. Si Neji no es la ventana activa, lo
  escaneado va al otro programa.

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

Las pantallas las da el computador principal: para actualizar, basta instalar la versión
nueva ahí. Las otras cajas la cargan solas al cambiar de pantalla (o con el botón del aviso
«Neji POS se actualizó»), sin perder el ticket en curso.

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
- Ticket con desglose de **neto e IVA**, para impresoras de 80 mm (de fábrica) o 58 mm.
- **Configuración → Ticket**: se editan las líneas del encabezado y del pie (agregar,
  quitar, mover, centrar, negrita y letra grande), con los datos del negocio como
  `{nombre}` o `{rut}`, y se elige qué más sale (Atendió, cliente, neto e IVA, cambio).
  La vista previa cambia mientras se edita y, en NejiPOS.exe, muestra los mismos renglones
  que salen en la impresora de tickets.
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
  La fórmula:
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

**Importar el inventario desde Excel o CSV**

En **Configuración → Importar inventario** (o en Productos → Importar Excel o CSV) se sube
la planilla de Excel (`.xlsx`) tal como la exporta eleventa u otro sistema, o un CSV:

- Crea los productos nuevos y actualiza los que ya existen (por código), con su
  principio activo, distribuidor, vencimiento y stock.
- La existencia puede **reemplazar** el stock (conteo de inventario) o **sumarse**
  (entrada de mercadería). Cada cambio queda en el kardex.
- Trae una **planilla de ejemplo** para descargar con todas las columnas.
- Entiende planillas guardadas por Excel en Windows (con tildes, comillas y €).
- Los departamentos que solo cambian en mayúsculas, tildes o la s del plural
  («INYECTABLES» e «inyectable») quedan como uno solo.
- Los códigos con espacios («COBAN 2») se importan juntos («COBAN2») y se avisa.

### Productos e inventario

- Departamentos.
- Precio de costo, % de ganancia, precio de venta y mayoreo.
- Productos exentos de IVA.
- Generador de código interno EAN-13 para productos sin código de barras.
- En **Nuevo producto** y al editar uno, `Enter` pasa al dato siguiente (código,
  descripción, departamento, se vende por, principio activo…) hasta **Guardar**.
- **Etiquetas con código de barras** (Code 128) para imprimir.
- Entradas de mercadería (actualizan el costo), salidas por merma y ajustes por conteo físico.
- **Kardex**: el historial de cada producto.
- **Compras sugeridas**: productos bajo el mínimo, con lo vendido en los últimos 30 días.
- Opción de permitir inventario negativo.
- **Importar el catálogo desde Excel (`.xlsx`) o CSV** y exportarlo a CSV, para traerlo desde eleventa u otro sistema.
  - Entiende columnas como «Código», «Producto», «P. Venta», «Costo», «Stock», «Inv. Mínimo» o «Categoría».
  - Los CSV pueden ir separados por `;` o por `,`.

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
  principal se elige en **Configuración → Cajas**. Cada caja muestra su propio faltante o
  sobrante, y si otra terminal ya cerró una caja, el corte se recarga sin ella. Con una sola
  caja basta el corte normal.
- Un cajero corta el turno que abrió; el turno de otro cajero lo corta quien lo abrió o
  alguien con permiso de corte general.
- Historial de cortes y de cortes generales.

### Devoluciones

- Parciales o del ticket completo.
- Devuelven el producto al inventario.
- Reembolsan en efectivo o como reversa de tarjeta.
- En una venta fiada, descuentan la deuda del cliente.

### Boleta y factura electrónica (SII, opcional)

Si el dueño lo activa, Neji emite los documentos tributarios electrónicos **con su propia firma
electrónica** y los manda solo al SII. Si no se activa, todo sigue igual que antes, con el
comprobante interno.

- **Boleta electrónica** (39), boleta exenta (41), **factura electrónica** (33), factura exenta (34),
  **nota de crédito** (61) y nota de débito (56, en la certificación). Una venta solo con productos exentos sale como documento exento.
- **Al cobrar** se elige *Boleta* (lo normal) o *Factura* (tecla **F7**). La factura pide un cliente
  con RUT, giro, dirección y comuna (se completan en **Clientes**).
- **El ticket** es la representación impresa del documento. Lleva el recuadro con el RUT, el tipo
  y el folio, los datos de la empresa y del cliente, el IVA y el **timbre electrónico** (el código
  PDF417 que se puede verificar en sii.cl). Sale directo en la impresora de tickets, de 80 o 58 mm.
- **Una devolución** emite su nota de crédito. Si se devuelve todo, la nota anula la boleta; si se
  devuelve una parte, corrige el monto. La nota se imprime desde el **Historial**.
- **El envío al SII es automático**: cada minuto, con las boletas en grupos de hasta 50. Si se
  corta internet se sigue vendiendo, y lo pendiente se manda cuando vuelve la conexión. En el
  Historial y en Configuración se ve el estado de cada documento: por enviar, enviado, aceptado,
  con reparos o rechazado.
- Si una boleta no se puede emitir (por ejemplo, porque se acabaron los folios), la venta queda
  igual con su comprobante interno y la caja ve un aviso. La boleta se emite después desde el
  Historial con **Emitir boleta**. La factura, en cambio, no se vende sin emitirse.
- Cuando quedan 20 folios o menos, la caja avisa para que se pidan más al SII.

**Qué se necesita y cómo se activa**

1. **La firma electrónica** (certificado digital `.pfx` o `.p12`) del dueño o de una persona
   autorizada ante el SII: E-Cert, Acepta, E-Sign u otra empresa certificadora.
2. **La certificación del SII.** Para emitir con un sistema propio (como Neji), el SII pide
   certificarlo una vez. Neji hace todos los pasos desde **Configuración → Certificación SII**
   (ver más abajo). Al aprobar, el SII autoriza a emitir en *producción* (con una resolución).
3. En **Configuración → Boleta electrónica**:
   - Completa los datos de la empresa tal como están en el SII: RUT, razón social, giro, código
     de actividad (Acteco), dirección, comuna y oficina del SII.
   - Elige el ambiente. En certificación va la fecha de la postulación y el número de resolución 0;
     en producción, los de tu resolución.
   - Sube la firma con su contraseña y los **folios (CAF)** que se descargan del SII, uno por tipo
     de documento. Los folios de certificación no sirven en producción.
   - Pulsa **Probar conexión** y después **Activar**.

Para pasar a producción se cambia el ambiente, se pone la resolución y se cargan los folios de
producción.

**Modo demostración (sin el SII)**

Para ver y mostrar cómo sale la boleta con su timbre antes de que el SII autorice al negocio, en
**Configuración → Boleta electrónica → Modo demostración** se pulsa **Probar en modo demostración**.
No hace falta firma, folios ni postulación: Neji inventa en ese computador unos folios y una firma de
prueba, con la misma forma que los reales.

- Cada venta sale con su boleta timbrada (o factura, si se pide al cobrar) y cada devolución con su
  nota de crédito. El ticket dice **DEMOSTRACIÓN · SIN VALOR TRIBUTARIO** y no remite a sii.cl.
- **Nada se envía al SII** ni al correo de los clientes. Los documentos quedan aparte, con su propia
  numeración, y el envío automático nunca los toma.
- La firma, los folios, el ambiente y la activación que haya no cambian: al apagarlo, todo sigue como
  estaba. No se puede encender si la boleta electrónica está activada en producción, y activar
  producción lo apaga.
- Salen a nombre de los datos de la empresa de esa pestaña. Si faltan, se usan los de
  **Configuración → Negocio** o unos de ejemplo, y el panel dice cuáles.

**Bueno saber**

- La firma queda guardada en la base de Neji (va en los respaldos). Su contraseña queda cifrada con
  la clave de ese computador: si se restaura el respaldo en otro equipo, hay que volver a subir la firma.
- El SII ya no pide el reporte de consumo de folios (RCOF) de las boletas en la operación normal, así
  que Neji solo lo envía en la certificación de la boleta, donde todavía se exige.
- **Las facturas le llegan al cliente por correo** (intercambio de DTE, lo pide el SII): cuando el SII
  acepta una factura o la nota de crédito de una factura, Neji le manda el XML al correo que tiene el
  cliente en **Clientes**. Se configura la cuenta en **Configuración → Boleta electrónica → Correo para
  mandar las facturas** (con Gmail: `smtp.gmail.com`, puerto 587 y una «contraseña de aplicación»).
  Si el cliente no tiene correo, la factura queda marcada y se manda después con **Enviar XML**.
- Neji no emite guías de despacho (52), facturas de compra (46) ni documentos de exportación: al
  postular, elige solo factura, factura exenta, nota de crédito, nota de débito y boleta.
- Los documentos se validaron con los esquemas oficiales del SII y las firmas con xmlsec y con DTE
  reales aceptados por el SII. Pero desde el desarrollo no se pudo conectar con los servidores del
  SII: el set de pruebas de la certificación es la primera prueba real.

**Certificación ante el SII, paso a paso** (Configuración → Certificación SII)

Antes: en sii.cl → *Factura electrónica → Sistema de certificación* se postula con «software de
mercado o desarrollo propio». La postulación es de la empresa (su RUT) y la hace su representante
legal con su certificado digital. Ahí puede nombrar como usuario administrador a otra persona (por
ejemplo, quien instala Neji), que después pide los folios y firma con su propio certificado. Con un
RUT de persona sin inicio de actividades, el SII no deja pedir folios. En la pestaña **Boleta electrónica**, con el ambiente en
*Certificación*, se cargan los datos de la empresa (tal como salen en sii.cl → *Datos para la
construcción de DTE*), la fecha de resolución de la postulación (número 0), la firma y los folios de
certificación de factura (33), nota de crédito (61), nota de débito (56) y, si se postula a ellas,
factura exenta (34) y boleta (39 y 41). No hace falta activar la boleta electrónica para certificar.

1. **Set de pruebas.** Se descarga de sii.cl el texto del set y se pega en Neji, que emite cada caso
   (precios netos, descuentos por línea y globales, notas de crédito que anulan, corrigen el giro con
   «donde dice… debe decir…» o devuelven, y la nota de débito) y los envía al SII, un envío por set.
2. **Libros.** Con un botón se envían el libro de ventas (los documentos del set básico) y el de
   compras (las facturas recibidas que trae el set: IVA de uso común con su factor de
   proporcionalidad, IVA no recuperable, retención total del IVA y notas de crédito). Si el SII
   responde que el período ya tiene un libro, se reenvían como *Ajuste*.
3. **Simulación.** Neji emite diez documentos como los de la operación diaria (con productos del
   inventario y precios con IVA, igual que al vender) y una factura exenta si hay folios de ella.
4. **Intercambio.** El XML que el SII manda al correo de intercambio se sube a Neji, que arma y firma
   las tres respuestas (recepción del envío, recibo de mercaderías y aceptación comercial) en un ZIP
   para subirlas en sii.cl.
5. **Muestras impresas.** Un ZIP con un PDF por documento (con el timbre legible, a 2 cm del borde, y
   la copia cedible de las facturas con el acuse de recibo), para mandar a SII_dte_impresos@sii.cl.
6. **Boleta electrónica.** Su set de pruebas (CASO-1, CASO-2…) se pega aparte: Neji emite las
   boletas con la referencia que pide el SII y envía también el consumo de folios (RCOF).

Neji sube cada envío y consulta su estado solo; en la pantalla se ve el **número de envío
(TrackID)** de cada paso, que es el que se declara en sii.cl → *Revisar avance*. Al final se firma la
declaración de cumplimiento en sii.cl y, con la resolución, se pasa a producción.

### Reportes (administrador)

- Ventas netas, número de tickets, ticket promedio, ganancia y margen, IVA débito,
  devoluciones y descuentos.
- Ventas por día, por hora, por forma de pago, por cajero y por departamento,
  y los productos más vendidos.
- Exportación del detalle a CSV.

### Usuarios y seguridad

- En **Configuración → Usuarios** se agregan y modifican usuarios.
- Roles **administrador** (puede todo) y **cajero**.
- Cada cajero tiene **sus propios permisos**: cambiar precios y descuentos, vender artículos
  comunes, devoluciones, entradas y salidas de efectivo, corte de su caja, corte general,
  crédito a clientes, productos, inventario, reportes y vademécum. Los costos los ve quien
  tiene productos, inventario o reportes; la ganancia, solo quien tiene reportes.
- Los cambios de permisos se aplican sin que el cajero vuelva a entrar (al cambiar de pantalla).
- **Nombre en el ticket**: cómo aparece cada usuario en «Atendió:» (por ejemplo
  «Cajero 1 · Cristóbal Araya Cortés»), con una vista previa del ticket al lado.
- **Respaldo automático diario**, que guarda los últimos 10 (configurable),
  más respaldo y descarga manual.
- **Protecciones**: contraseñas con hash (scrypt) y freno a quien prueba contraseñas; al cambiar la
  contraseña de alguien se cierran sus otras sesiones; la página no carga nada de otros sitios (CSP),
  no se puede meter dentro de otra (clickjacking) ni recibe pedidos de otras páginas (CSRF) o de
  dominios ajenos (DNS rebinding); en Windows, la clave con la que se cifran la contraseña de la firma
  electrónica y la del correo queda protegida por Windows para ese computador (una copia de la carpeta
  de datos no sirve en otro); el correo solo se manda por conexión cifrada; los XML y planillas subidos
  no pueden traer entidades externas; y antes de instalar WebView2 se revisa que el instalador esté
  firmado por Microsoft.
- Si se abre Neji desde otro equipo con un nombre de dominio propio (por ejemplo
  `caja.mifarmacia.cl`), hay que agregarlo en la variable de entorno `NEJI_DOMINIOS`. Con la IP o el
  nombre del computador (`http://CAJA1:5000`) funciona sin hacer nada.

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
| `F12` | Cobrar. En el cobro, `F1`–`F6` eligen la forma de pago, `F7` cambia entre boleta y factura (con la boleta electrónica activada) y `Enter` confirma |

> Si alguna tecla F hace otra cosa en tu navegador (por ejemplo, `F11` pone pantalla
> completa), usa el acceso directo en modo aplicación o la tecla alternativa.

---

## Respaldos y restauración

- Los datos viven en la carpeta de datos: `neji.db` y la subcarpeta `respaldos/`.
  Con `NejiPOS.exe` es `%LOCALAPPDATA%\NejiPOS\datos`; con Python, `datos/` dentro
  del proyecto. La ruta exacta aparece en **Configuración → Respaldos**.
- Descarga un respaldo de vez en cuando desde **Configuración → Respaldos** y
  guárdalo fuera del computador (en un pendrive o en la nube).

Para restaurar un respaldo, en **Configuración → Respaldos → Restaurar un respaldo**
sube el archivo (antes se guarda un respaldo de lo que había). O, a mano:

1. Cierra Neji.
2. Reemplaza `neji.db` de la carpeta de datos por el archivo del respaldo, renombrado
   a `neji.db`.
3. Vuelve a abrir Neji.

## Migrar desde eleventa u otro sistema

1. En eleventa: **Productos → Exportar a Excel**. En otros sistemas, usa su
   exportación de productos.
2. En Neji: **Configuración → Importar inventario** (o **Productos → Importar Excel o CSV**)
   y sube ese archivo tal cual, sin abrirlo ni convertirlo. También sirve un CSV.
   Un Excel antiguo (`.xls`) hay que guardarlo antes como `.xlsx`.
   - Si el código ya existe, el producto se actualiza.
   - Si no existe, se crea.
   - Elige si la existencia reemplaza el stock o se suma a él.

---

## Licencias (para vender Neji POS)

Neji POS se vende con **licencias de pago único** que crea quien lo vende, sin depender de ningún servicio:

- **Caja**: sirve para una caja (la principal).
- **Local (multicaja)**: sirve para varias cajas del mismo local, o para todas («sin límite»).
- **Prueba**: sin licencia, Neji funciona completo **15 días** desde que se instala. Después se puede ver,
  respaldar y configurar todo, pero no se registran ventas hasta activar la licencia. Una franja bajo la barra
  avisa los días que quedan.

**Cómo funciona.** Cada licencia es un texto (`NEJI-…`) firmado con tu **llave privada**, que solo está en tu
computador. Neji trae tu **llave pública** y con ella comprueba que la licencia sea tuya, así que nadie puede
inventar una. La licencia dice el cliente, el tipo, las cajas y el **código de equipo** del computador donde
vale (el que tiene los datos; las otras cajas se conectan a él). Si se copia la base a otro computador, ahí no
vale: hay que pedir otra.

**Lo que haces tú (una vez):**

1. En tu computador, con Python y `cryptography` instalados (`pip install cryptography`), abre
   `herramientas/Generar licencias.bat` (o `python herramientas/licencias.py`).
2. La primera vez crea tu llave: elige una contraseña y **respalda la carpeta `NejiLicencias`** de tu usuario
   (por ejemplo, en un pendrive). Sin ella no puedes hacer licencias.
3. El programa muestra tu **llave pública**: va en `neji/licencia.py` (`LLAVES_PUBLICAS`). Desde la versión
   que la incluya, Neji empieza a pedir licencia. Mientras esa lista esté vacía no hay prueba ni licencias.

**Por cada venta:**

1. El cliente abre **Configuración → Licencia** y te manda el **código de equipo** (`XXXX-XXXX-XXXX-XXXX`).
2. Abres el generador → «Crear una licencia»: cliente, RUT, tipo, cajas y ese código. Si lo dejas vacío, la
   licencia sirve en cualquier computador; úsalo solo con clientes de confianza.
3. Le mandas el texto `NEJI-…` (o el archivo de `NejiLicencias/licencias`). Él lo pega en
   **Configuración → Licencia → Activar licencia**.

Cada licencia queda anotada en `NejiLicencias/registro.csv`, con una nota para el precio o la forma de pago. La
llave privada nunca va al repositorio (está en `.gitignore`). Para que sea difícil saltarse la revisión de
licencia, conviene además compilar el código (ver «Código cifrado»).

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
  sii/                 boleta y factura electrónica: firma, folios (CAF), DTE, timbre PDF417, envío al SII
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
iscc empaquetado\NejiPOS.iss                # instalador (Inno Setup 6) -> dist\NejiPOS-Instalador-<versión>.exe
                                            # (antes, deja build\MicrosoftEdgeWebview2Setup.exe)
```

### Código cifrado con PyArmor (opcional)

Dentro de `NejiPOS.exe` el código va compilado, pero un entendido puede sacarlo y leerlo. Con
[PyArmor](https://pyarmor.readthedocs.io) el código de Neji (`escritorio.py` y todo `neji/`) va
**cifrado**: quien abra el programa ve un bloque ilegible en vez del código, y el programa funciona
igual. El workflow de Windows ya lo hace solo si encuentra la licencia; si no, compila como siempre (y
lo dice en el resumen de la compilación).

Qué se necesita:

1. **La licencia de PyArmor.** Para un programa que se usa en un negocio hace falta una licencia
   pagada (Pyarmor Basic alcanza; se compra en el sitio de PyArmor o con `pyarmor reg --buy`). La
   versión de prueba gratis no sirve: es solo para uso no comercial y no cifra archivos del tamaño de
   los de Neji (responde «out of license»).
2. **Registrarla una vez en tu computador** con el código que llega por correo:
   `pip install pyarmor` y `pyarmor reg -p "Neji POS" pyarmor-regcode-XXXX.txt`. Queda un archivo
   `pyarmor-regfile-XXXX.zip`: guárdalo bien (es la licencia).
3. **Pedir el archivo para GitHub** (la compilación corre en un equipo que cambia cada vez):
   `pyarmor reg -C pyarmor-regfile-XXXX.zip`, que deja un `pyarmor-ci-XXXX.zip`.
4. **Guardarlo como secreto del repositorio**: en GitHub → *Settings → Secrets and variables →
   Actions → New repository secret*, con el nombre `PYARMOR_LICENCIA` y como valor el archivo en
   base64. En PowerShell:
   `[Convert]::ToBase64String([IO.File]::ReadAllBytes("pyarmor-ci-XXXX.zip")) | Set-Clipboard`
   (y pegar). Desde la siguiente compilación el código sale cifrado.
5. Opcional: la variable de repositorio `PYARMOR_OPCIONES` agrega opciones de `pyarmor gen`, por
   ejemplo `--mix-str` para cifrar también los textos (según lo que permita tu licencia).

Bueno saber: el cifrado hace mucho más difícil leer o copiar el código, pero ningún cifrado de un
programa que corre en el computador del usuario es imposible de romper. Lo realmente delicado (la
firma electrónica, las contraseñas) no depende de esto: está protegido aparte (ver *Usuarios y
seguridad*). Algunos antivirus desconfían de los programas cifrados con PyArmor: si pasa, se puede
reportar el falso positivo al antivirus. Y el repositorio debe seguir siendo privado.

Para agregar una función nueva:

1. Agrega la tabla o columna en `schema.sql`.
2. Escribe la regla en `servicios/` y la ruta en `api/`.
3. Haz la pantalla en `static/js/vistas/` y regístrala en `static/js/app.js`.

## Hoja de ruta

- [x] **Boleta y factura electrónica SII** con la firma del dueño (certificación propia; ver
  [Boleta y factura electrónica](#boleta-y-factura-electrónica-sii-opcional)).
- [ ] Guía de despacho y nota de débito electrónicas.
- [ ] Integración con máquinas de tarjeta (Transbank, Getnet, Mercado Pago, SumUp).
- [ ] Lotes con fecha de vencimiento propia (hoy hay una fecha por producto).
- [ ] Kits, paquetes y promociones (2x1, 3x2).
- [ ] Puntos de fidelización (Loyverse).
- [ ] Varios niveles de precio (menudeo, medio mayoreo, mayoreo).
- [ ] Balanzas con etiqueta de peso (códigos que empiezan con 2).
- [ ] Enviar el ticket por correo o WhatsApp.

---

## El programa anterior: CORAND.ERP / Easy Pharma (`corand_erp.py`)

Este repositorio también guarda el programa original de la farmacia, como referencia. Su
análisis está en [`docs/analisis-corand.md`](docs/analisis-corand.md).

Para pasar su inventario a Neji POS (el programa no tiene una opción para exportarlo):

1. Abre `corand_erp_pro.db` con [DB Browser for SQLite](https://sqlitebrowser.org/) (gratis).
2. **Archivo → Exportar → Tabla(s) como archivo CSV…**, elige la tabla `inventario` y guárdala.
3. En Neji POS, súbela en **Configuración → Importar inventario**. Neji reconoce sus
   columnas (código, nombre, costo, precio de venta, stock, distribuidor, departamento,
   vencimiento y principio activo).

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
