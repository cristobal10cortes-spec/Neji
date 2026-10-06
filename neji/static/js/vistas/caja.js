// Caja: estado del turno en vivo, entradas/salidas, corte e historial de cortes.

import { api, qs } from '../api.js';
import { esAdmin, estado, nombreCaja } from '../estado.js';
import { imprimir, nombreMetodo, ticketCorte } from '../impresion.js';
import { aviso, avisoError, fecha, formulario, h, hoy, kpi, modal, pesos, selectorFechas, tabla, vaciar } from '../ui.js';

/** Pide el fondo inicial y abre el turno. Devuelve el turno o null. */
export async function abrirTurno() {
  return formulario({
    titulo: `Abrir ${nombreCaja()}`,
    aceptar: 'Abrir caja',
    intro: h('p', '¿Con cuánto dinero en efectivo empieza la caja?'),
    campos: [{ nombre: 'fondo_inicial', etiqueta: 'Dinero inicial', tipo: 'monto', valor: '0', autofocus: true }],
    alEnviar: async (v) => {
      const r = await api.post(`/api/caja/${estado.cajaId}/abrir`, { fondo_inicial: v.fondo_inicial || 0 });
      aviso('Caja abierta.', 'ok');
      return r.turno;
    },
  });
}

/** Entrada o salida de efectivo del turno actual. */
export async function movimientoCaja(tipo) {
  const r = await formulario({
    titulo: tipo === 'entrada' ? 'Entrada de efectivo' : 'Salida de efectivo',
    aceptar: 'Registrar',
    campos: [
      { nombre: 'monto', etiqueta: 'Monto', tipo: 'monto', requerido: true, autofocus: true },
      { nombre: 'concepto', etiqueta: 'Concepto', requerido: true, placeholder: tipo === 'entrada' ? 'Ej: sencillo, cambio' : 'Ej: pago a proveedor, retiro' },
    ],
    alEnviar: (v) => api.post(`/api/caja/${estado.cajaId}/movimiento`, { tipo, ...v }),
  });
  if (r) aviso(`${tipo === 'entrada' ? 'Entrada' : 'Salida'} registrada.`, 'ok');
  return r;
}

function detalleTurno(t) {
  const m = t.por_metodo;
  const filasDinero = [
    ['Fondo inicial', t.fondo_inicial],
    ['+ Ventas en efectivo', t.ventas_efectivo],
    ['+ Abonos de clientes en efectivo', t.abonos_efectivo],
    ['+ Entradas', t.entradas],
    ['− Salidas', -t.salidas],
    ['− Devoluciones en efectivo', -t.devoluciones_efectivo],
  ];
  return h('div',
    h('div.kpis',
      kpi('Debe haber en caja', pesos(t.efectivo_esperado), true),
      kpi('Ventas', `${t.n_ventas} · ${pesos(t.total_ventas)}`),
      t.ganancia != null ? kpi('Ganancia estimada', pesos(t.ganancia)) : null,
      t.estado === 'cerrado' ? kpi(t.diferencia < 0 ? 'Faltante' : t.diferencia > 0 ? 'Sobrante' : 'Cuadrada', pesos(t.diferencia)) : null),
    h('div.columnas',
      h('div.panel',
        h('h3', 'Dinero en caja'),
        tabla([{ titulo: 'Concepto', valor: (f) => f[0] }, { titulo: 'Monto', valor: (f) => pesos(f[1]), clase: 'num' }],
          filasDinero, { pie: [{ valor: 'Esperado' }, { valor: pesos(t.efectivo_esperado), clase: 'num' }] })),
      h('div.panel',
        h('h3', 'Ventas por forma de pago'),
        tabla([{ titulo: 'Forma', valor: (f) => nombreMetodo(f[0]) }, { titulo: 'Monto', valor: (f) => pesos(f[1]), clase: 'num' }],
          Object.entries(m).filter(([, v]) => v), { vacio: 'Sin ventas aún.' }),
        t.redondeo ? h('p.ayuda', `Redondeo de efectivo acumulado: ${pesos(t.redondeo)}`) : null,
        t.devoluciones ? h('p.ayuda', `Devoluciones: ${pesos(t.devoluciones)}`) : null,
        t.abonos_otros ? h('p.ayuda', `Abonos con tarjeta/transferencia: ${pesos(t.abonos_otros)}`) : null),
      h('div.panel',
        h('h3', 'Ventas por departamento'),
        tabla([{ titulo: 'Departamento', valor: (d) => d.departamento }, { titulo: 'Total', valor: (d) => pesos(d.total), clase: 'num' }],
          t.departamentos, { vacio: 'Sin ventas aún.' }))),
    h('div.panel',
      h('h3', 'Entradas y salidas de efectivo'),
      tabla([
        { titulo: 'Hora', valor: (x) => fecha(x.fecha) },
        { titulo: 'Tipo', valor: (x) => h(`span.etiqueta.${x.tipo === 'entrada' ? 'ok' : 'mal'}`, x.tipo) },
        { titulo: 'Concepto', valor: (x) => x.concepto },
        { titulo: 'Usuario', valor: (x) => x.usuario },
        { titulo: 'Monto', valor: (x) => pesos(x.monto), clase: 'num' },
      ], t.movimientos, { vacio: 'Sin movimientos.' })));
}

export async function montar(contenedor) {
  const cuerpo = h('div');
  const historial = h('div');
  let filtro = { desde: hoy(-7), hasta: hoy() };
  vaciar(contenedor, cuerpo, historial);

  async function cargar() {
    let turno;
    try {
      turno = (await api.get(`/api/caja/${estado.cajaId}/turno`)).turno;
    } catch (e) {
      avisoError(e);
      return;
    }
    if (!turno) {
      vaciar(cuerpo, h('div.panel',
        h('h2', `${nombreCaja()} · cerrada`),
        h('p', 'No hay un turno abierto en esta caja.'),
        h('button.btn.primario.grande', { type: 'button', onclick: async () => { if (await abrirTurno()) cargar(); } }, 'Abrir caja')));
    } else {
      vaciar(cuerpo,
        h('div.fila.entre',
          h('h2', `${nombreCaja()} · turno abierto por ${turno.usuario} (${fecha(turno.abierto)})`),
          h('div.fila',
            h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('entrada')) cargar(); } }, h('kbd', 'F7'), 'Entrada'),
            h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('salida')) cargar(); } }, h('kbd', 'F8'), 'Salida'),
            h('button.btn', { type: 'button', onclick: () => imprimir(ticketCorte(turno)) }, 'Imprimir estado'),
            h('button.btn.primario', { type: 'button', onclick: () => hacerCorte(turno) }, 'Hacer corte'))),
        detalleTurno(turno));
    }
    if (esAdmin()) cargarHistorial();
  }

  async function hacerCorte(turno) {
    const r = await formulario({
      titulo: 'Corte de caja',
      aceptar: 'Cerrar turno',
      intro: h('p', 'Cuenta el efectivo del cajón y escribe el total.'),
      campos: [
        { nombre: 'efectivo_contado', etiqueta: 'Efectivo contado', tipo: 'monto', requerido: true, autofocus: true },
        { nombre: 'nota', etiqueta: 'Nota (opcional)', tipo: 'area', ancho: true },
      ],
      alEnviar: (v) => api.post(`/api/caja/${estado.cajaId}/cerrar`, v),
    });
    if (!r) return;
    const t = r.turno;
    modal({
      titulo: 'Turno cerrado',
      cuerpo: h('div.resultado-venta',
        h('div.suave', `Esperado ${pesos(t.efectivo_esperado)} · Contado ${pesos(t.efectivo_contado)}`),
        h('div.cambio', { class: t.diferencia < 0 ? 'rojo' : 'verde' },
          t.diferencia === 0 ? 'Caja cuadrada' : `${t.diferencia < 0 ? 'Faltan' : 'Sobran'} ${pesos(Math.abs(t.diferencia))}`)),
      botones: [
        { texto: 'Imprimir corte', clase: 'primario', accion: () => imprimir(ticketCorte(t)) },
        { texto: 'Cerrar', accion: (m) => m.cerrar() },
      ],
    });
    cargar();
  }

  async function cargarHistorial() {
    let turnos = [];
    try {
      turnos = await api.get(`/api/turnos${qs(filtro)}`);
    } catch (e) {
      avisoError(e);
    }
    vaciar(historial, h('div.panel',
      h('div.fila.entre', h('h2', 'Historial de cortes'), selectorFechas(filtro, (f) => { filtro = f; cargarHistorial(); })),
      tabla([
        { titulo: 'Turno', valor: (t) => `#${t.id}` },
        { titulo: 'Caja', valor: (t) => t.caja },
        { titulo: 'Abrió', valor: (t) => `${t.usuario} · ${fecha(t.abierto)}` },
        { titulo: 'Cerró', valor: (t) => (t.cerrado ? fecha(t.cerrado) : h('span.etiqueta.aviso', 'abierto')) },
        { titulo: 'Ventas', valor: (t) => `${t.n_ventas} · ${pesos(t.total_ventas)}`, clase: 'num' },
        { titulo: 'Diferencia', valor: (t) => (t.diferencia == null ? '—' : h('span', { class: t.diferencia < 0 ? 'rojo' : t.diferencia > 0 ? 'verde' : '' }, pesos(t.diferencia))), clase: 'num' },
      ], turnos, {
        vacio: 'No hay turnos en estas fechas.',
        alClic: async (t) => {
          try {
            const d = await api.get(`/api/turnos/${t.id}`);
            modal({
              titulo: `Turno #${d.id} · ${d.caja}`,
              ancho: 'muy-ancho',
              cuerpo: detalleTurno(d),
              botones: [{ texto: 'Imprimir', clase: 'primario', accion: () => imprimir(ticketCorte(d)) }, { texto: 'Cerrar', accion: (m) => m.cerrar() }],
            });
          } catch (e) {
            avisoError(e);
          }
        },
      })));
  }

  await cargar();
  return {
    alTeclear(e) {
      if (e.key === 'F7' || e.key === 'F8') {
        e.preventDefault();
        movimientoCaja(e.key === 'F7' ? 'entrada' : 'salida').then((r) => r && cargar());
      }
    },
  };
}
