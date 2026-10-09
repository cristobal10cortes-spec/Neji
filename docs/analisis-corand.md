# Análisis de CORAND.ERP / Easy Pharma y cómo se llevó a Neji POS

El programa original es una sola aplicación PyQt6 (≈1.000 líneas) con base SQLite
`corand_erp_pro.db`. Para analizarlo se ejecutó tal cual, sin pantalla, con
datos de ejemplo:

- se capturaron sus pantallas;
- se obtuvieron los valores reales de su calculadora;
- se hizo una venta con una receta magistral.

Ese código no está en este repositorio: incluye datos de la farmacia y una
contraseña escrita en el programa.

## Requisitos para ejecutarlo

- **Python 3.12 o superior.** En Python 3.11 no arranca: la línea que arma el
  ticket (`imprimir_ticket_generico`) usa comillas anidadas dentro de un f-string,
  algo que recién se permite desde 3.12.
- Librerías: PyQt6 y pyqtgraph; pandas y openpyxl solo para importar Excel.

## Cómo funciona el vademécum en CORAND

| Pieza | Comportamiento |
|---|---|
| Tabla `vademecum` | Una fila por principio activo con uso terapéutico, efectos adversos e imagen (la imagen nunca se usa). |
| `inventario.principio_activo` | Un solo texto libre por producto, guardado en MAYÚSCULAS desde los formularios. |
| Aviso en la venta | Al escanear un producto con principio activo que tenga ficha, muestra «ℹ️ PRINCIPIO: uso terapéutico». Exige coincidencia exacta de texto. |
| Buscador `F10` | Busca por nombre o código. Si empieza con `%`, busca por componente (nombre o principio activo). Muestra la columna «Info. clínica / P.A.». |
| Pantalla Vademécum | Lista principio activo y uso. Permite crear o reemplazar fichas. Los efectos adversos se guardan pero no se muestran en ninguna parte. |

## Cómo funciona la calculadora magistral en CORAND

Datos:

- `recetario_insumos`: nombre, unidad (mg, mcg, gr, ml) y precio por unidad.
- `recetario_formulas`: nombre, precio base, medida y precio por medida.

Fórmula (con `cantidad` = número de cápsulas, gramos o ml):

```
subtotal de cada principio activo = precio por unidad × dosis por unidad de forma × cantidad
costo de la forma                  = precio por medida × cantidad
neto                               = Σ subtotales + costo de la forma + precio base
IVA                                = neto × 19 %
total                              = neto + IVA
```

Al enviarla a la venta agrega una línea `RM-001 · RECETA MAGISTRAL` que no mueve
inventario.

**Valores reales obtenidos al ejecutar CORAND**, que Neji reproduce en sus pruebas
(`tests/test_recetario.py`):

| Receta | Total CORAND | Total Neji |
|---|---|---|
| 30 cápsulas: paracetamol 500 mg + cafeína 50 mg | $8.330 | $8.330 |
| 50 g de crema: aloe vera 10 mg/g | $5.682 (5.682,25) | $5.682 |
| 60 cápsulas: vitamina C 0,5 g | $9.004 (9.003,66) | $9.004 |
| 30 cápsulas: biotina 5.000 mcg | $184.688 | $184.688 |
| 100 ml de loción sin principio activo | $4.879 | $4.879 |
| 45 cápsulas: paracetamol 333,33 mg + cafeína 12,5 mg | $8.821 (8.820,86) | $8.821 |

## Qué se llevó a Neji y qué se mejoró

| CORAND.ERP | Neji POS |
|---|---|
| Un texto de principio activo por producto | Varios principios activos por producto con concentración (`PARACETAMOL 500 mg + CAFEINA 65 mg`), unidos a su ficha. |
| Aviso en la venta solo con coincidencia exacta | Ficha del vademécum a la izquierda de la venta (sigue al producto buscado o a la línea del ticket), con «Ficha», «Editar» y «Alternativas». |
| Búsqueda `%componente` | Igual, en `F10` y en Productos. |
| — | **Alternativas** con el mismo principio activo (`Ctrl+B`), separadas en misma dosis, otra dosis o que solo comparten un principio. Si no hay stock, la ficha lo marca. |
| Fichas sin efectos adversos visibles | Ficha completa: acción terapéutica, efectos adversos, contraindicaciones y notas, más los productos en stock y un botón «Vender». |
| Vademécum y precios del recetario en tablas separadas | Un solo principio activo con ficha clínica y precio de recetario. |
| Dosis solo en la unidad del precio | Conversión mg/mcg/g y porcentajes en cremas y lociones. |
| — | Cantidad total a pesar de cada principio activo. |
| La receta se pierde al venderla (solo queda «ART. ESPECIAL») | **Libro de recetas**: folio, paciente, RUT, médico, indicaciones, composición, estado y CSV. |
| Precio de la receta tomado de la pantalla | Precio calculado y guardado en el servidor. La receta no se puede vender dos veces. |
| — | Orden de preparación / presupuesto impreso. |
| Total con decimales truncado al pasarlo a la venta | Redondeo consistente al peso, o a $10/$50/$100 si se configura. |
| Vencimiento y distribuidor por producto | Igual, más la pestaña Inventario → Vencimientos. |
| — | Importación directa de `corand_erp_pro.db`. |

## Problemas encontrados en CORAND.ERP

Ocho agentes revisaron el código de forma independiente: cuatro lo analizaron y
otros cuatro intentaron refutar cada hallazgo, ejecutando el programa cuando se
pudo. Aquí van los confirmados más importantes. Neji evita todos los de esta lista.

### Seguridad

1. **Clave maestra escrita en el código.**
   - El usuario `master` con una clave fija entra como administrador en cualquier
     instalación.
   - Además se crea `admin`/`admin` por defecto, y las contraseñas se guardan sin cifrar.
2. **Los roles no se aplican.**
   - El rol se guarda al iniciar sesión, pero ninguna pantalla lo revisa.
   - Un cajero puede crear administradores, cambiar precios o ver reportes.
3. **SQL armado con texto** en Reportes y Corte diario. Hoy el riesgo es bajo, porque
   el valor viene de una lista fija.

### Ventas y caja

4. **La venta no guarda sus líneas** (solo el total).
   - La reimpresión reconstruye el ticket con los precios **actuales**.
   - Mezcla ventas hechas en el mismo segundo.
   - La receta magistral y el envío aparecen como «ART. ESPECIAL».
5. **El stock solo se revisa al agregar al carrito.**
   - Al cobrar se descuenta sin validar y puede quedar negativo.
   - El modo «Devolución» se salta la revisión.
6. **Devoluciones sin venta original**: sin autorización y siempre en efectivo, aunque se
   haya pagado con tarjeta.
7. **Pago mixto sin desglose.**
   - Se pierde cuánto fue en efectivo y cuánto con tarjeta.
   - El efectivo del corte no cuadra.
8. **La «Ganancia» del corte diario es `total / 1,19`**: es la venta neta sin IVA, no la
   utilidad.
9. **Los tickets nunca se imprimen.** La impresora de cada caja no se configura en
   ninguna pantalla, así que la función termina sin imprimir.
10. **Un error de base de datos al cobrar puede cerrar el programa** con el cliente ya
    pagado (no hay manejo de errores).

### Inventario

11. **«Ingresar / Sumar» pisa los datos de un producto existente** (precio, costo,
    distribuidor, departamento y principio activo) si no se buscó el código con Enter.
    Además cambia el vencimiento por la fecha de **hoy**.
12. **«Modificar producto» guarda sobre el código escrito en ese momento.** Si se cambia
    el código después de cargar otro producto, se modifica el equivocado.
13. **Importar Excel:**
    - Reimportar el mismo archivo **duplica el stock**.
    - No deja kardex.
    - Lee mal los montos con punto de miles.
    - Si la columna no se llama exactamente `Principio_Activo`, **borra** el principio
      activo de todos los productos.

### Recetario magistral

14. **El total se trunca al pasarlo a la venta** (`int()`): la calculadora muestra $8.821
    y se cobran $8.820.
15. **Duplicados entre mayúsculas y minúsculas.**
    - La semilla trae «Paracetamol» y «Cápsulas»; lo que se guarda desde la pantalla queda
      en MAYÚSCULAS («PARACETAMOL», «CÁPSULAS»).
    - Quedan dos registros, y los de la semilla no se pueden editar ni borrar.
16. **No hay conversión de unidades.** Vitamina C se cobra por gramo: si se escribe 500
    pensando en mg, cobra mil veces más.
17. **Enter envía la receta de inmediato** desde la dosis. Si la caja está cerrada, la
    receta se pierde sin aviso.
18. **Precio inicial de biotina: $1 por mcg** ($1.000.000 por gramo). Con 5.000 mcg × 30
    cápsulas da $184.688. Conviene revisar ese precio al importar.

### Vademécum

19. **El vínculo producto ↔ ficha es por texto exacto.**
    - Mayúsculas, tildes o un espacio de más lo rompen sin avisar.
    - Un producto con dos principios activos («PARACETAMOL + CAFEINA») nunca muestra
      aviso.
20. **Efectos adversos invisibles.** Se guardan pero no se muestran en ninguna pantalla.
21. **Las fichas no se pueden editar.** Hay que reescribir la clave exacta y todo el texto.
22. **La búsqueda no reconoce tildes.** `%acido` no encuentra «ÁCIDO FÓLICO».
23. **Python 3.12 obligatorio.** En 3.11 el programa no arranca.

## Funciones de CORAND que todavía no están en Neji

Quedan para las próximas entregas:

- **Facturas de ingreso por distribuidor**: número de factura, total y suma de
  varias facturas.
- **Costo de envío** como línea especial (`Ctrl+E` en CORAND).
- **Modo devolución libre**: devolver sin buscar la venta original.
  - En Neji la devolución se hace sobre la venta, lo que es más seguro.
- **Panel de últimas ventas** en la pantalla de venta, con reimpresión rápida.
- **Tema oscuro.**
- **Diseño del ticket** con líneas en blanco arriba y abajo, y logotipo.
