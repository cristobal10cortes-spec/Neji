// Historial de ventas: buscar tickets, reimprimir y hacer devoluciones.

import { api, qs } from '../api.js';
import { esAdmin, estado, opcion, puede } from '../estado.js';
import { documentoDeVenta, imprimir, nombreMetodo, ticketNotaCredito, ticketVenta } from '../impresion.js';
import { aviso, avisoError, fecha, h, hoy, leerCantidad, modal, numero, pesos, selectorFechas, tabla, vaciar } from '../ui.js';

const ESTADOS = { completada: ['ok', 'Completada'], devuelta_parcial: ['aviso', 'Devolución parcial'], devuelta: ['mal', 'Devuelta'] };
export const etiquetaEstado = (e) => h(`span.etiqueta.${ESTADOS[e][0]}`, ESTADOS[e][1]);

// Estado de un documento electrónico en el SII.
const CLASE_SII = { pendiente: '', enviado: '', aceptado: 'ok', reparo: 'aviso', rechazado: 'mal' };
export const etiquetaSii = (d) => h(`span.etiqueta${CLASE_SII[d.estado] ? '.' + CLASE_SII[d.estado] : ''}`, { title: d.glosa || '' }, d.estado_texto);

/** Emite la boleta (o factura) de una venta que quedó sin documento electrónico. */
async function emitirDocumento(venta, documento, alTerminar) {
  try {
    const v = await api.post(`/api/sii/ventas/${venta.id}/emitir`, { documento });
    const doc = documentoDeVenta(v);
    aviso(doc ? `${doc.nombre} N° ${doc.folio} emitida.` : 'Documento emitido.', 'ok', 6000);
    imprimir(ticketVenta(v));
    alTerminar(v);
  } catch (e) {
    avisoError(e);
  }
}

function devolver(venta, alTerminar) {
  const entradas = new Map();
  const filas = venta.items.map((i) => {
    const pendiente = Math.round((i.cantidad - i.cantidad_devuelta) * 1000) / 1000;
    const entrada = h('input', { inputmode: 'decimal', value: '0', style: { width: '90px' }, disabled: pendiente <= 0 });
    entradas.set(i.id, { entrada, pendiente, item: i });
    return i;
  });
  const todo = h('input', { type: 'checkbox' });
  todo.addEventListener('change', () => {
    for (const { entrada, pendiente } of entradas.values()) {
      entrada.value = todo.checked ? String(pendiente).replace('.', ',') : '0';
      entrada.disabled = todo.checked || pendiente <= 0;
    }
  });
  const pagoFiado = venta.pagos.some((p) => p.metodo === 'fiado');
  const reembolso = h('select', h('option', { value: 'efectivo' }, 'En efectivo (sale de la caja)'), h('option', { value: 'otro' }, 'Reversa en tarjeta / transferencia (no sale de la caja)'));
  const motivo = h('input', { placeholder: 'Ej: producto vencido, cliente se arrepintió' });

  modal({
    titulo: `Devolución · Folio ${venta.folio}`,
    ancho: 'ancho',
    cuerpo: [
      tabla([
        { titulo: 'Producto', valor: (i) => i.descripcion },
        { titulo: 'Vendido', valor: (i) => numero(i.cantidad), clase: 'num' },
        { titulo: 'Ya devuelto', valor: (i) => numero(i.cantidad_devuelta), clase: 'num' },
        { titulo: 'Devolver', valor: (i) => entradas.get(i.id).entrada, clase: 'num' },
      ], filas),
      h('label.check', todo, 'Devolver todo el ticket'),
      pagoFiado ? h('p.ayuda', 'La parte pagada con fiado se descuenta primero de la deuda del cliente.') : null,
      h('label.campo', 'Reembolso', reembolso),
      h('label.campo', 'Motivo', motivo),
    ],
    botones: [
      { texto: 'Cancelar', accion: (m) => m.cerrar() },
      {
        texto: 'Registrar devolución',
        clase: 'peligro',
        accion: async (m) => {
          const items = [];
          for (const [id, { entrada, pendiente }] of entradas) {
            const c = leerCantidad(entrada.value || '0');
            if (Number.isNaN(c) || c < 0) return m.error('Hay una cantidad no válida.');
            if (c > pendiente) return m.error(`No puedes devolver más de ${numero(pendiente)} en una línea.`);
            if (c > 0) items.push({ venta_item_id: id, cantidad: c });
          }
          if (!todo.checked && !items.length) return m.error('Indica qué se devuelve.');
          try {
            const v = await api.post(`/api/ventas/${venta.id}/devolucion`, {
              caja_id: estado.cajaId, todo: todo.checked, items, reembolso: reembolso.value, motivo: motivo.value,
            });
            const ultima = v.devoluciones[v.devoluciones.length - 1];
            aviso(ultima.monto_efectivo ? `Devolución registrada. Entrega ${pesos(ultima.monto_efectivo)} al cliente.` : 'Devolución registrada.', 'ok', 6000);
            for (const a of v.avisos || []) aviso(a, 'error', 9000);
            // Con boleta o factura electrónica, la devolución lleva su nota de crédito.
            const nota = (v.documentos || []).find((d) => d.tipo === 61 && d.devolucion_id === ultima.id);
            if (nota) {
              aviso(`${nota.nombre} N° ${nota.folio} emitida.`, 'ok', 6000);
              if (opcion('imprimir_automatico')) imprimir(ticketNotaCredito(v, nota));
            }
            m.cerrar();
            alTerminar(v);
          } catch (e) {
            m.error(e.message);
          }
        },
      },
    ],
  });
}

export async function verVenta(id, alCambiar = () => {}) {
  let v;
  try {
    v = await api.get(`/api/ventas/${id}`);
  } catch (e) {
    avisoError(e);
    return;
  }
  // Una venta sin boleta electrónica (o con la boleta rechazada por el SII) se puede emitir después.
  const sinDocumento = estado.config.sii_activo === '1' && v.estado === 'completada' && !documentoDeVenta(v) && puede('devoluciones');
  const recargar = () => { m.cerrar(); alCambiar(); verVenta(id, alCambiar); };
  const m = modal({
    titulo: `Venta folio ${v.folio}`,
    ancho: 'muy-ancho',
    cuerpo: [
      h('div.fila', etiquetaEstado(v.estado), h('span.suave', `${fecha(v.fecha)} · ${v.caja} · ${v.usuario}`), v.cliente ? h('span', `Cliente: ${v.cliente}`) : null),
      tabla([
        { titulo: 'Código', valor: (i) => h('span.mono', i.codigo || '—') },
        { titulo: 'Descripción', valor: (i) => [i.descripcion, ' ', i.receta_id ? h('span.etiqueta.ok', 'receta magistral') : i.tipo_precio !== 'normal' ? h('span.etiqueta', { mayoreo: 'mayoreo', manual: 'precio manual', comun: 'común' }[i.tipo_precio]) : null] },
        { titulo: 'Cant.', valor: (i) => numero(i.cantidad), clase: 'num' },
        { titulo: 'Precio', valor: (i) => pesos(i.precio_unitario), clase: 'num' },
        { titulo: 'Importe', valor: (i) => pesos(i.importe), clase: 'num' },
        { titulo: 'Devuelto', valor: (i) => (i.cantidad_devuelta ? h('span.rojo', numero(i.cantidad_devuelta)) : ''), clase: 'num' },
      ], v.items, {
        pie: [
          { valor: v.descuento ? `Subtotal ${pesos(v.subtotal)} · Descuento ${pesos(v.descuento)}` : '', colspan: 4 },
          { valor: pesos(v.total), clase: 'num' }, { valor: v.devuelto ? `-${pesos(v.devuelto)}` : '', clase: 'num rojo' },
        ],
      }),
      h('div.columnas',
        h('div.panel', h('h3', 'Pagos'), v.pagos.map((p) => h('div.fila.entre', h('span', nombreMetodo(p.metodo)), h('span.num', pesos(p.monto)))),
          v.redondeo ? h('div.fila.entre.suave', h('span', 'Redondeo'), h('span.num', pesos(v.redondeo))) : null,
          v.efectivo_recibido ? h('div.fila.entre.suave', h('span', 'Recibido / cambio'), h('span.num', `${pesos(v.efectivo_recibido)} / ${pesos(v.cambio)}`)) : null),
        h('div.panel', h('h3', 'IVA'),
          h('div.fila.entre', h('span', 'Neto'), h('span.num', pesos(v.neto))),
          h('div.fila.entre', h('span', 'IVA'), h('span.num', pesos(v.iva))),
          v.exento ? h('div.fila.entre', h('span', 'Exento'), h('span.num', pesos(v.exento))) : null),
        v.documentos?.length ? h('div.panel', h('h3', 'Documentos SII'), v.documentos.map((d) => h('div',
          h('div.fila.entre', h('span', `${d.nombre} N° ${d.folio}`), etiquetaSii(d)),
          d.glosa ? h('div.ayuda', d.glosa) : null,
          d.correo ? h('div.ayuda', { class: d.correo.estado === 'sin_correo' ? 'rojo' : null }, `${d.correo.texto}${d.correo.a ? ` (${d.correo.a})` : ''}`) : null,
          d.tipo === 61 ? h('button.btn.chico', { type: 'button', onclick: () => imprimir(ticketNotaCredito(v, d)) }, 'Imprimir nota de crédito') : null))) : null,
        v.devoluciones.length ? h('div.panel', h('h3', 'Devoluciones'), v.devoluciones.map((d) => h('div',
          h('div.fila.entre', h('span', `${fecha(d.fecha)} · ${d.usuario}`), h('b.num', pesos(d.monto))),
          h('div.ayuda', [d.monto_efectivo ? `efectivo ${pesos(d.monto_efectivo)}` : '', d.monto_fiado ? `fiado ${pesos(d.monto_fiado)}` : '', d.monto_otro ? `tarjeta/transf. ${pesos(d.monto_otro)}` : '', d.motivo].filter(Boolean).join(' · '))))) : null),
    ],
    botones: [
      { texto: 'Reimprimir ticket', accion: () => imprimir(ticketVenta(v)) },
      ...(sinDocumento ? [
        { texto: 'Emitir boleta', accion: () => emitirDocumento(v, 'boleta', recargar) },
        v.cliente ? { texto: 'Emitir factura', accion: () => emitirDocumento(v, 'factura', recargar) } : null,
      ] : []),
      v.estado !== 'devuelta' && puede('devoluciones')
        ? { texto: 'Devolución', clase: 'peligro', accion: () => devolver(v, () => { m.cerrar(); alCambiar(); verVenta(id, alCambiar); }) }
        : null,
      { texto: 'Cerrar', clase: 'primario', accion: (mm) => mm.cerrar() },
    ].filter(Boolean),
  });
}

export async function montar(contenedor) {
  let filtro = { desde: hoy(), hasta: hoy() };
  const folio = h('input', { placeholder: 'Folio', inputmode: 'numeric', style: { width: '120px' } });
  const lista = h('div');
  const totales = h('span.suave');

  vaciar(contenedor,
    h('h2', 'Historial de ventas'),
    h('div.fila', selectorFechas(filtro, (f) => { filtro = f; folio.value = ''; cargar(); }), h('span.espacio'), folio,
      h('button.btn', { type: 'button', onclick: () => cargar() }, 'Buscar folio')),
    h('div.fila.entre', { style: { margin: '.75rem 0' } }, totales),
    lista);

  folio.addEventListener('keydown', (e) => { if (e.key === 'Enter') cargar(); });

  async function cargar() {
    let ventas = [];
    try {
      ventas = await api.get(`/api/ventas${qs(folio.value.trim() ? { folio: folio.value.trim() } : filtro)}`);
    } catch (e) {
      avisoError(e);
    }
    const total = ventas.reduce((s, v) => s + v.total - v.devuelto, 0);
    totales.textContent = `${ventas.length} ventas · ${pesos(total)} (descontando devoluciones)`;
    vaciar(lista, tabla([
      { titulo: 'Folio', valor: (v) => h('b', v.folio) },
      { titulo: 'Fecha', valor: (v) => fecha(v.fecha) },
      { titulo: 'Caja', valor: (v) => v.caja },
      { titulo: 'Cajero', valor: (v) => v.usuario },
      { titulo: 'Cliente', valor: (v) => v.cliente || '' },
      { titulo: 'Pago', valor: (v) => (v.metodos || '').split(',').filter(Boolean).map(nombreMetodo).join(' + ') },
      { titulo: 'Estado', valor: (v) => etiquetaEstado(v.estado) },
      { titulo: 'Total', valor: (v) => pesos(v.total), clase: 'num' },
    ], ventas, { vacio: 'No hay ventas en estas fechas.', alClic: (v) => verVenta(v.id, cargar) }));
  }

  await cargar();
  if (!esAdmin()) folio.focus();
}
