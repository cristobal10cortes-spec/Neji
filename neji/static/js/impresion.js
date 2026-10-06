// Impresión: ticket de venta, corte de caja, cotización y etiquetas con código de barras.

import { estado } from './estado.js';
import { fecha, h, numero, pesos, unidadPlural } from './ui.js';

const NOMBRE_METODO = {
  efectivo: 'Efectivo', debito: 'Débito', credito: 'Crédito', transferencia: 'Transferencia', fiado: 'Fiado (crédito cliente)',
};
export const nombreMetodo = (m) => NOMBRE_METODO[m] || m;

export function imprimir(contenido) {
  const zona = document.getElementById('impresion');
  zona.replaceChildren(contenido);
  const limpiar = () => { zona.replaceChildren(); window.removeEventListener('afterprint', limpiar); };
  window.addEventListener('afterprint', limpiar);
  setTimeout(() => window.print(), 50);
}

const ln = (izq, der, clase = '') => h(`div.ln${clase ? '.' + clase : ''}`, h('span', izq), h('span', der));

function encabezadoNegocio() {
  const c = estado.config;
  return [
    h('div.c.xl', c.negocio_nombre || ''),
    c.negocio_rut ? h('div.c', `RUT: ${c.negocio_rut}`) : null,
    c.negocio_giro ? h('div.c', c.negocio_giro) : null,
    c.negocio_direccion ? h('div.c', c.negocio_direccion) : null,
    c.negocio_telefono ? h('div.c', `Tel: ${c.negocio_telefono}`) : null,
    c.ticket_encabezado ? h('div.c', c.ticket_encabezado) : null,
  ];
}

const claseTicket = () => `div.ticket${estado.config.ticket_ancho === '58' ? '.t58' : ''}`;

export function ticketVenta(v) {
  const c = estado.config;
  const pagos = v.pagos.map((p) => ln(nombreMetodo(p.metodo), pesos(p.monto)));
  const efectivo = v.pagos.find((p) => p.metodo === 'efectivo');
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    ln(`Folio: ${v.folio}`, fecha(v.fecha)),
    h('div', `${v.caja} · Atendió: ${v.usuario}`),
    v.cliente ? h('div', `Cliente: ${v.cliente}${v.cliente_rut ? ' · ' + v.cliente_rut : ''}`) : null,
    h('hr'),
    v.items.map((i) => [
      h('div', i.descripcion),
      ln(`  ${numero(i.cantidad)} x ${pesos(i.precio_unitario)}${i.tipo_precio === 'mayoreo' ? ' (may.)' : ''}`, pesos(i.importe)),
    ]),
    h('hr'),
    v.descuento ? [ln('Subtotal', pesos(v.subtotal)), ln('Descuento', `-${pesos(v.descuento)}`)] : null,
    ln('TOTAL', pesos(v.total), 'xl'),
    ln(`Neto`, pesos(v.neto)),
    ln(`IVA (${c.iva_porcentaje || 19}%)`, pesos(v.iva)),
    v.exento ? ln('Exento', pesos(v.exento)) : null,
    h('hr'),
    pagos,
    efectivo ? [
      v.redondeo ? ln('Redondeo (Ley 20.956)', pesos(v.redondeo)) : null,
      ln('Recibido', pesos(v.efectivo_recibido)),
      ln('Cambio', pesos(v.cambio), 'g'),
    ] : null,
    v.pagos.some((p) => p.metodo === 'fiado') && v.cliente_saldo != null ? ln('Saldo pendiente cliente', pesos(v.cliente_saldo)) : null,
    v.devuelto ? ln('Devuelto', `-${pesos(v.devuelto)}`) : null,
    h('hr'),
    c.ticket_pie ? h('div.c', c.ticket_pie) : null,
    c.ticket_leyenda ? h('div.c', c.ticket_leyenda) : null,
    h('div', { style: { height: '8mm' } }));
}

export function ticketCorte(t) {
  const m = t.por_metodo || {};
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', t.estado === 'cerrado' ? 'CORTE DE CAJA' : 'ESTADO DE CAJA (turno abierto)'),
    h('div', `${t.caja} · Turno #${t.id}`),
    h('div', `Abrió: ${t.usuario} ${fecha(t.abierto)}`),
    t.cerrado ? h('div', `Cerró: ${t.usuario_cierre || ''} ${fecha(t.cerrado)}`) : null,
    h('hr'),
    h('div.g', 'Dinero en caja'),
    ln('Fondo inicial', pesos(t.fondo_inicial)),
    ln('+ Ventas en efectivo', pesos(t.ventas_efectivo)),
    ln('+ Abonos en efectivo', pesos(t.abonos_efectivo)),
    ln('+ Entradas', pesos(t.entradas)),
    ln('- Salidas', pesos(t.salidas)),
    ln('- Devoluciones', pesos(t.devoluciones_efectivo)),
    ln('= Esperado en caja', pesos(t.efectivo_esperado), 'g'),
    t.estado === 'cerrado' ? [
      ln('Contado', pesos(t.efectivo_contado)),
      ln(t.diferencia < 0 ? 'FALTANTE' : t.diferencia > 0 ? 'SOBRANTE' : 'Diferencia', pesos(t.diferencia), 'g'),
    ] : null,
    h('hr'),
    h('div.g', `Ventas (${t.n_ventas})`),
    Object.entries(m).filter(([, v]) => v).map(([k, v]) => ln(nombreMetodo(k), pesos(v))),
    t.redondeo ? ln('Redondeo', pesos(t.redondeo)) : null,
    ln('Total ventas', pesos(t.total_ventas), 'g'),
    t.devoluciones ? ln('Devoluciones', pesos(t.devoluciones)) : null,
    t.abonos_otros ? ln('Abonos con tarjeta/transf.', pesos(t.abonos_otros)) : null,
    t.ganancia != null ? ln('Ganancia estimada', pesos(t.ganancia)) : null,
    t.departamentos?.length ? [h('hr'), h('div.g', 'Por departamento'), t.departamentos.map((d) => ln(d.departamento, pesos(d.total)))] : null,
    t.movimientos?.length ? [h('hr'), h('div.g', 'Entradas y salidas'), t.movimientos.map((mv) => ln(`${mv.tipo === 'entrada' ? '+' : '-'} ${mv.concepto}`, pesos(mv.monto)))] : null,
    t.nota ? [h('hr'), h('div', `Nota: ${t.nota}`)] : null,
    h('div', { style: { height: '8mm' } }));
}

export function ticketCotizacion(q) {
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', `COTIZACIÓN N° ${q.folio}`),
    h('div', fecha(q.fecha)),
    q.cliente_nombre ? h('div', `Cliente: ${q.cliente_nombre}${q.cliente_rut ? ' · ' + q.cliente_rut : ''}`) : null,
    h('hr'),
    q.items.map((i) => [h('div', i.descripcion), ln(`  ${numero(i.cantidad)} x ${pesos(i.precio_unitario)}`, pesos(i.importe))]),
    h('hr'),
    q.descuento ? [ln('Subtotal', pesos(q.subtotal)), ln('Descuento', `-${pesos(q.descuento)}`)] : null,
    ln('TOTAL', pesos(q.total), 'xl'),
    h('hr'),
    h('div.c', 'Precios sujetos a cambio y a disponibilidad de stock.'),
    q.nota ? h('div', q.nota) : null,
    h('div', { style: { height: '8mm' } }));
}

/** Cantidad de principio activo en la unidad más legible: 15000 mg -> "15 g". */
export function cantidadLegible(valor, unidad) {
  let v = valor;
  let u = unidad;
  if (u === 'mcg' && Math.abs(v) >= 1000) { v /= 1000; u = 'mg'; }
  if (u === 'mg' && Math.abs(v) >= 1000) { v /= 1000; u = 'g'; }
  if (u === 'g' && Math.abs(v) > 0 && Math.abs(v) < 1) { v *= 1000; u = 'mg'; }
  if (u === 'mg' && Math.abs(v) > 0 && Math.abs(v) < 1) { v *= 1000; u = 'mcg'; }
  return `${numero(Math.round(v * 1000) / 1000)} ${u}`;
}

const ESTADO_RECETA = { pendiente: 'PENDIENTE DE PAGO', vendida: 'VENDIDA', anulada: 'ANULADA' };

/** Orden de preparación / presupuesto de una receta magistral. */
export function ticketReceta(r) {
  const c = estado.config;
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', `RECETA MAGISTRAL N° ${r.folio}`),
    ln(fecha(r.fecha), ESTADO_RECETA[r.estado] || ''),
    r.paciente ? h('div', `Paciente: ${r.paciente}${r.rut_paciente ? ' · ' + r.rut_paciente : ''}`) : null,
    r.medico ? h('div', `Médico: ${r.medico}`) : null,
    h('hr'),
    h('div.g', `${r.forma} × ${numero(r.cantidad)} ${unidadPlural(r.cantidad, r.unidad, r.nombre_unidad)}`),
    r.componentes.length ? [
      h('div', 'Composición por unidad:'),
      r.componentes.map((x) => ln(`  ${x.nombre}`, `${numero(x.dosis)} ${x.unidad}`)),
      h('hr'),
      h('div', 'Total a pesar:'),
      r.componentes.map((x) => ln(`  ${x.nombre}`, cantidadLegible(x.cantidad_total, x.unidad_precio))),
    ] : h('div', 'Sin principios activos (solo base).'),
    r.indicaciones ? [h('hr'), h('div', `Indicaciones: ${r.indicaciones}`)] : null,
    h('hr'),
    ln('Neto', pesos(r.neto)),
    ln(`IVA (${c.iva_porcentaje || 19}%)`, pesos(r.iva)),
    ln('TOTAL', pesos(r.total), 'xl'),
    r.venta_folio ? h('div', `Vendida en folio ${r.venta_folio}`) : null,
    h('hr'),
    h('div', `Preparó: ${r.usuario || ''}`),
    h('div', { style: { height: '8mm' } }));
}

export function hojaComprasSugeridas(productos) {
  return h('div.hoja',
    h('h2', `Compras sugeridas — ${estado.config.negocio_nombre}`),
    h('p', `Generado: ${new Date().toLocaleString('es-CL')}`),
    h('table', { border: '1', cellpadding: '4', style: { borderCollapse: 'collapse', width: '100%' } },
      h('thead', h('tr', ['Código', 'Producto', 'Existencia', 'Mínimo', 'Vendido 30 días', 'Comprar', 'Costo est.'].map((t) => h('th', t)))),
      h('tbody', productos.map((p) => h('tr',
        h('td', p.codigo), h('td', p.descripcion), h('td', numero(p.existencia)), h('td', numero(p.minimo)),
        h('td', numero(p.vendidos_30d)), h('td', h('b', numero(p.sugerido))), h('td', pesos(p.costo_estimado)))))),
    h('p', h('b', `Total estimado: ${pesos(productos.reduce((s, p) => s + p.costo_estimado, 0))}`)));
}

// --- Código de barras Code 128 ----------------------------------------------

const PATRONES = [
  '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
  '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
  '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
  '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
  '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
  '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
  '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
  '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
  '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
];
const INICIO_B = 104, INICIO_C = 105, CAMBIO_A_B = 100, PARADA = 106;

/** Valores Code 128 para un texto: usa el set C en códigos numéricos (más compacto) y B para el resto. */
export function valoresCode128(texto) {
  const valores = [];
  if (/^\d{4,}$/.test(texto)) {
    const pares = texto.length - (texto.length % 2);
    valores.push(INICIO_C);
    for (let i = 0; i < pares; i += 2) valores.push(parseInt(texto.slice(i, i + 2), 10));
    if (pares < texto.length) valores.push(CAMBIO_A_B, texto.charCodeAt(pares) - 32);
  } else {
    valores.push(INICIO_B);
    for (const ch of texto) {
      const cod = ch.charCodeAt(0);
      valores.push(cod >= 32 && cod <= 127 ? cod - 32 : 0);
    }
  }
  let suma = valores[0];
  for (let i = 1; i < valores.length; i++) suma += valores[i] * i;
  valores.push(suma % 103, PARADA);
  return valores;
}

export function svgCode128(texto) {
  const anchos = valoresCode128(texto).map((v) => PATRONES[v]).join('');
  const margen = 10;
  let x = margen;
  const rects = [];
  for (let i = 0; i < anchos.length; i++) {
    const w = parseInt(anchos[i], 10);
    if (i % 2 === 0) rects.push(`<rect x="${x}" y="0" width="${w}" height="50"/>`);
    x += w;
  }
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${x + margen} 50" preserveAspectRatio="none" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><g fill="#000">${rects.join('')}</g></svg>`,
    'image/svg+xml').documentElement;
  return document.importNode(svg, true);
}

/** items: [{ producto, copias }] */
export function hojaEtiquetas(items) {
  const etiquetas = [];
  for (const { producto, copias } of items) {
    for (let i = 0; i < copias; i++) {
      etiquetas.push(h('div.etiqueta-prod',
        h('div.d', producto.descripcion),
        h('div.p', pesos(producto.precio_venta) + (producto.tipo_venta === 'granel' ? ' /kg' : '')),
        svgCode128(producto.codigo),
        h('div.cod', producto.codigo)));
    }
  }
  return h('div.etiquetas', etiquetas);
}
