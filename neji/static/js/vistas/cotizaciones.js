// Cotizaciones: no mueven inventario; se pueden cargar en un ticket para venderlas.

import { api, qs } from '../api.js';
import { ir } from '../app.js';
import { imprimir, ticketCotizacion } from '../impresion.js';
import { avisoError, confirmar, debounce, fecha, h, modal, numero, pesos, tabla, vaciar } from '../ui.js';

const ESTADOS = { vigente: ['aviso', 'Vigente'], vendida: ['ok', 'Vendida'], cancelada: ['mal', 'Cancelada'] };

async function verCotizacion(id, alCambiar) {
  let q;
  try {
    q = await api.get(`/api/cotizaciones/${id}`);
  } catch (e) {
    avisoError(e);
    return;
  }
  modal({
    titulo: `Cotización N° ${q.folio}`,
    ancho: 'ancho',
    cuerpo: [
      h('div.fila', h(`span.etiqueta.${ESTADOS[q.estado][0]}`, ESTADOS[q.estado][1]), h('span.suave', `${fecha(q.fecha)} · ${q.usuario}`), q.cliente_nombre ? h('span', `Para: ${q.cliente_nombre}`) : null),
      tabla([
        { titulo: 'Descripción', valor: (i) => i.descripcion },
        { titulo: 'Cant.', valor: (i) => numero(i.cantidad), clase: 'num' },
        { titulo: 'Precio', valor: (i) => pesos(i.precio_unitario), clase: 'num' },
        { titulo: 'Importe', valor: (i) => pesos(i.importe), clase: 'num' },
      ], q.items, { pie: [{ valor: q.descuento ? `Descuento ${pesos(q.descuento)}` : 'Total', colspan: 3 }, { valor: pesos(q.total), clase: 'num' }] }),
      q.nota ? h('p', q.nota) : null,
    ],
    botones: [
      { texto: 'Imprimir', accion: () => imprimir(ticketCotizacion(q)) },
      q.estado === 'vigente' ? {
        texto: 'Cancelar cotización',
        clase: 'peligro',
        accion: async (m) => {
          if (!(await confirmar('Cancelar cotización', `¿Cancelar la cotización N° ${q.folio}?`, { aceptar: 'Sí, cancelar', peligro: true }))) return;
          try { await api.post(`/api/cotizaciones/${q.id}/cancelar`); m.cerrar(); alCambiar(); } catch (e) { m.error(e.message); }
        },
      } : null,
      q.estado === 'vigente' ? { texto: 'Cargar en ticket para vender', clase: 'primario', accion: (m) => { m.cerrar(); ir('ventas', { cotizacionId: q.id }); } } : null,
    ].filter(Boolean),
  });
}

export async function montar(contenedor) {
  const buscar = h('input', { type: 'search', placeholder: 'Cliente o folio', style: { maxWidth: '320px' } });
  const estadoSel = h('select', { style: { width: 'auto' } },
    [['vigente', 'Vigentes'], ['', 'Todas'], ['vendida', 'Vendidas'], ['cancelada', 'Canceladas']].map(([v, t]) => h('option', { value: v }, t)));
  const lista = h('div');

  vaciar(contenedor,
    h('div.fila.entre', h('h2', 'Cotizaciones'), h('span.suave', 'Para crear una, arma el ticket en Ventas y presiona «Cotizar».')),
    h('div.fila', buscar, estadoSel),
    h('div', { style: { height: '.75rem' } }),
    lista);

  async function cargar() {
    let cotizaciones = [];
    try {
      cotizaciones = await api.get(`/api/cotizaciones${qs({ estado: estadoSel.value, q: buscar.value.trim() })}`);
    } catch (e) {
      avisoError(e);
    }
    vaciar(lista, tabla([
      { titulo: 'Folio', valor: (q) => h('b', q.folio) },
      { titulo: 'Fecha', valor: (q) => fecha(q.fecha) },
      { titulo: 'Cliente', valor: (q) => q.cliente_nombre || '' },
      { titulo: 'Hecha por', valor: (q) => q.usuario },
      { titulo: 'Estado', valor: (q) => h(`span.etiqueta.${ESTADOS[q.estado][0]}`, ESTADOS[q.estado][1]) },
      { titulo: 'Total', valor: (q) => pesos(q.total), clase: 'num' },
    ], cotizaciones, { vacio: 'No hay cotizaciones.', alClic: (q) => verCotizacion(q.id, cargar) }));
  }

  buscar.addEventListener('input', debounce(cargar));
  estadoSel.addEventListener('change', cargar);
  await cargar();
}
