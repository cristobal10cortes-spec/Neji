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
| Aviso en la venta solo con coincidencia exacta | Aviso con uso, efectos adversos y botones «Ficha» y «Alternativas». |
| Búsqueda `%componente` | Igual, en `F10` y en Productos. |
| — | **Alternativas** con el mismo principio activo (`Ctrl+B`), ofrecidas solas cuando no hay stock. |
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

Verificados contra el código y, cuando se pudo, ejecutándolo. Neji evita cada uno.

1. **Contraseña maestra escrita en el código.**
   - Qué pasa: `validar_login` acepta el usuario `master` con una clave fija, que entra como
     administrador en cualquier instalación.
   - Además: las contraseñas de los usuarios se guardan sin cifrar.
   - Cómo lo evita Neji: claves cifradas con hash y sin accesos fijos.
2. **El total de la receta se trunca al pasarlo a la venta.**
   - Qué pasa: `agregar_item_especial` usa `int(precio_total)`. La calculadora muestra
     $8.821, pero la venta cobra $8.820 (y $9.003 en vez de $9.004).
   - Cómo lo evita Neji: redondea siempre igual en la calculadora, el ticket y la venta.
3. **La venta no guarda sus líneas.**
   - Qué pasa: la reimpresión reconstruye el ticket desde el kardex con los precios
     **actuales**, y la receta magistral (que no pasa por el kardex) aparece como
     «ART. ESPECIAL».
   - Cómo lo evita Neji: guarda cada línea con su precio, y la receta queda en el libro
     de recetas.
4. **La «Ganancia» del corte diario no es ganancia.**
   - Qué pasa: se calcula como `total / 1,19`, que es el monto neto sin IVA, no la
     utilidad.
   - Cómo lo evita Neji: calcula la ganancia con el costo de cada producto.
5. **Efectos adversos invisibles.** Se guardan en el vademécum pero no se muestran en
   ninguna pantalla.
6. **El aviso del vademécum exige el texto exacto** del principio activo.
   - Qué pasa: «Paracetamol» y «PARACETAMOL» se tratan como distintos, y la semilla del
     recetario usa minúsculas, mientras los formularios guardan en mayúsculas.
   - Cómo lo evita Neji: unifica los nombres y no deja duplicarlos.
7. **Python 3.12 obligatorio**, aunque esto no es evidente al instalarlo.

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
