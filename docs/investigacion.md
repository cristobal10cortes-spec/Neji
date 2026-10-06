# Investigación: lo mejor (y lo peor) de los puntos de venta usados en Chile

Este documento resume lo que **dicen los usuarios** (reseñas en comparadores,
foros de sugerencias, comparativas) sobre los puntos de venta más usados en
Chile y Latinoamérica, y qué se tomó de cada uno para Neji POS.

No se copió código de ningún programa: se estudiaron sus **funciones públicas,
manuales y opiniones** y se escribió todo desde cero.

---

## eleventa

**Lo que la gente valora**

- Es "el más fácil de usar": instalación rápida y el cajero aprende en minutos.
- Se opera casi solo con teclado:
  - `F12` cobrar, `F10` buscar producto, `INS` varios (cantidad + código).
  - `Ctrl+P` artículo común (producto no registrado), `F11` precio de mayoreo.
  - `F6` dejar un ticket pendiente para atender a otro cliente.
- Venta por **unidad o a granel** (kilos, metros, litros).
- **Créditos a clientes (fiado)** de forma simple.
- **Corte de caja** por turno y por día: fondo inicial, ventas en efectivo,
  entradas, salidas, abonos y devoluciones. Muestra el "dinero esperado" en
  caja en tiempo real.
- Inventario con **mínimos**, **compras sugeridas** y **kardex**
  (historial de cada producto).
- **Respaldo automático** diario que guarda las últimas 10 copias.
- Precio: licencia barata y sin cobro por caja.

**Lo que la gente critica**

- Depende del PC donde está instalado: si el equipo se daña, se pierde todo.
- Se queda corto al crecer: reportes y análisis limitados, poca gestión de
  usuarios y sucursales.
- Algunos usuarios reportan descuadres de inventario o cambios de precio.

**Sugerencias más votadas por usuarios de eleventa** (foro oficial de ideas):

| Idea | Votos |
|---|---|
| Generar e imprimir **códigos de barra** | ~1.957 |
| Módulo de **cotizaciones** (sin mover inventario) | ~1.610 |
| Puntos de **lealtad / monedero** | ~1.421 |
| **Varios niveles de precio** (menudeo, medio mayoreo, mayoreo) | ~1.061 |
| Permitir **inventario negativo** | ~565 |
| Facturas con formato configurable | ~471 |
| Enviar el ticket por correo | — |

## SICAR

**Lo que la gente valora**

- Inventario más preciso, con más configuraciones y reportes.
- **Lotes y fechas de caducidad**, con alertas antes de que venzan.
- Especialista en **créditos a clientes**.
- **Multicaja y multisucursal**.
- **Cotizaciones**, ventas en espera, apartados.
- **Kits/paquetes**, **promociones**, recargas y pago de servicios.

**Lo que la gente critica**

- Sincronización entre cajas lenta, con retraso al teclear códigos.
- Soporte técnico y postventa irregulares, y fallas del programa.
- Cobro de licencia por cada caja.

## Bsale (Chile)

**Lo que la gente valora**

- Boleta y factura electrónica **integradas con el SII**.
- Inventario en tiempo real.
- Reportes que ayudan a decidir.
- Integración con e-commerce y marketplaces.
- Interfaz amigable.

**Lo que la gente critica**

- Inestabilidad de la plataforma (depende de internet).
- Postventa deficiente en algunos casos.

## Loyverse

**Lo que la gente valora**

- Gratis.
- Interfaz limpia que se aprende rápido.
- Funciona en tablet y celular.
- Programa de **fidelización**.
- Recibos personalizables.

**Lo que la gente critica**

- Funciones avanzadas de pago.
- No emite boleta electrónica certificada en Chile.
- Sincronización con terceros que requiere arreglos manuales.

## Otros del mercado chileno

| Sistema | En qué destaca | Limitación |
|---|---|---|
| **Defontana (Tivendo)** | ERP completo, varias bodegas | Pesado para un almacén |
| **Relbase** | Consumo masivo; integra delivery y pagos | — |
| **TUU (Haulmer)** | Cobro con tarjeta y boleta | No es un POS completo: le faltan inventario y reportes |
| **Toteat / Fudo** | Restaurantes (mesas, comandas) | — |

## Requisitos propios de Chile

- **IVA 19%** incluido en el precio, con desglose neto + IVA.
- **RUT** con dígito verificador (módulo 11).
- **Redondeo en efectivo** (Ley 20.956): el total pagado en efectivo se
  redondea a la decena.
  - Si termina en 1 a 5, baja.
  - Si termina en 6 a 9, sube.
  - El documento tributario se emite por el monto exacto.
- **Medios de pago:** efectivo, débito, crédito, transferencia y fiado.
- **Boleta/factura electrónica (DTE):** requiere estar certificado ante el SII
  o usar un proveedor ya certificado. Queda como módulo siguiente
  (ver `README.md`, Hoja de ruta).

---

## Qué tomó Neji POS de cada uno

| Función | Inspirada en | Estado |
|---|---|---|
| Pantalla de venta 100% con teclado (`F12`, `F10`, `INS`, `Ctrl+P`, `F11`, `F6`) | eleventa | ✅ |
| Varios tickets abiertos a la vez | eleventa / SICAR | ✅ |
| Venta por unidad y a granel | eleventa | ✅ |
| Precio de mayoreo (manual con `F11` o automático por cantidad) | eleventa + sugerencia más votada | ✅ |
| Artículo común (sin registrar) | eleventa | ✅ |
| Fiado con límite de crédito y abonos | eleventa / SICAR | ✅ |
| Turnos y corte de caja con dinero esperado vs contado | eleventa | ✅ |
| Entradas y salidas de efectivo | eleventa | ✅ |
| Inventario con mínimos, compras sugeridas y kardex | eleventa | ✅ |
| Permitir inventario negativo (opcional) | sugerencia votada | ✅ |
| Cotizaciones que no mueven inventario | SICAR + sugerencia votada | ✅ |
| Generar e imprimir etiquetas con código de barras | sugerencia más votada | ✅ |
| Devoluciones parciales o totales | eleventa / SICAR | ✅ |
| Multicaja en red local (un servidor, varias cajas por navegador) | SICAR, sin depender de la nube | ✅ |
| Funciona sin internet (local primero) | Respuesta a la inestabilidad de Bsale | ✅ |
| Respaldo automático (10 copias) y descarga manual | eleventa | ✅ |
| Usuarios con rol administrador y cajero | SICAR | ✅ |
| Importar y exportar productos en CSV (migrar desde eleventa/Excel) | eleventa (exporta a Excel) | ✅ |
| Reportes: ventas, ganancia, por pago/departamento/cajero, más vendidos | Bsale / SICAR | ✅ |
| IVA desglosado, RUT validado, redondeo legal | Chile | ✅ |
| Interfaz que funciona en tablet | Loyverse | ✅ |
| Boleta/factura electrónica SII | Bsale | 🔜 |
| Lotes y caducidades | SICAR | 🔜 |
| Kits/paquetes y promociones | SICAR | 🔜 |
| Puntos de fidelización | Loyverse + sugerencia votada | 🔜 |
| Integración POS de tarjetas (Transbank, Getnet, Mercado Pago, SumUp) | TUU | 🔜 |

---

## Fuentes

- [ComparaSoftware: Eleventa](https://www.comparasoftware.com/eleventa-punto-de-venta)
- [Pulpos: Sicar vs Eleventa](https://pulpos.com/blog/sicar-vs-eleventa/)
- [Pulpos: SicarX vs Eleventa](https://pulpos.com/blog/sicarx-vs-eleventa/)
- [Posnetify: ¿Eleventa o SICAR?](https://posnetify.com/eleventa-o-sicar-cual-es-mejor-comparativa/)
- [SICAR vs Eleventa (sicar.mx)](https://www.sicar.mx/centro-de-soluciones/comparativas/sicar-vs-eleventa)
- [eleventa: atender a varios clientes](https://eleventa.com/aprender/atender-a-varios)
- [eleventa: descuentos y mayoreo](https://eleventa.com/aprender/descuentos-precio-mayoreo)
- [eleventa: producto común](https://eleventa.com/aprender/productos-comunes)
- [eleventa: corte de caja](https://eleventa.com/aprender/corte-de-caja)
- [eleventa: compras sugeridas](https://eleventa.com/aprender/compras-sugeridas)
- [eleventa: respaldo automático](https://eleventa.com/blog/respaldo-automatico-y-descripcion-de-producto-mas-larga)
- [Foro de sugerencias eleventa (más votadas)](https://puntodeventa.uservoice.com/forums/13335-sugerencias-para-eleventa-punto-de-venta)
- [ComparaSoftware: SICAR](https://www.comparasoftware.com/sicar-punto-de-venta)
- [Trustpilot: SICAR](https://es.trustpilot.com/review/sicar.mx)
- [SICAR: lotes y caducidades](https://cursos.sicar.mx/sicar-cursos/curso-completo-1/agregar-lotes-y-caducidades)
- [ComparaSoftware: Bsale](https://www.comparasoftware.cl/bsale)
- [Capterra: Loyverse](https://www.capterra.com/p/150632/Loyverse-POS/reviews/)
- [Fit Small Business: Loyverse](https://fitsmallbusiness.com/loyverse-review/)
- [Granloop: POS para minimarket en Chile](https://granloop.com/blog/mejor-pos-para-minimarket-chile)
- [Laudus: Top 5 punto de venta](https://laudus.cl/contenidos/gestion-erp/punto-de-venta-para-negocios/)
- [Banco Central: regla de redondeo](https://www.billetesymonedas.cl/Monedas/ReglaRedondeo)
- [Laudus: ajuste por redondeo](https://laudus.cl/contenidos/contabilidad-sii/software-contabilidad-ajuste-redondeo-pagos-efectivo/)
