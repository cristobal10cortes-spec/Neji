// Caja: estado del turno en vivo, entradas/salidas, corte e historial de cortes.

import { api, qs } from '../api.js';
import { estado, nombreCaja, puede } from '../estado.js';
import { imprimir, nombreMetodo, ticketCorte, ticketCorteGeneral } from '../impresion.js';
import { aviso, avisoError, confirmar, fecha, formulario, h, hoy, kpi, leerMonto, modal, pesos, selectorFechas, tabla, vaciar } from '../ui.js';

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
  if (!puede('movimientos_caja')) {
    aviso('No tienes permiso para registrar entradas y salidas de efectivo.', 'error');
    return null;
  }
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

const cajaPrincipal = () => estado.cajas.find((c) => c.principal);
const esPrincipalConCorteGeneral = () => puede('corte_general') && cajaPrincipal()?.id === estado.cajaId;
/** Con una sola caja (una caja activa no puede tener otras abiertas) el corte general no aporta nada: basta el corte. */
const variasCajas = () => estado.cajas.filter((c) => c.activa).length > 1;
/** «Faltan $100», «Sobran $50» o «Cuadrada». */
const textoDiferencia = (d) => (d < 0 ? `Faltan ${pesos(-d)}` : d > 0 ? `Sobran ${pesos(d)}` : 'Cuadrada');

export async function montar(contenedor) {
  const cuerpo = h('div');
  const general = h('div');
  const historial = h('div');
  let filtro = { desde: hoy(-7), hasta: hoy() };
  vaciar(contenedor, cuerpo, general, historial);

  async function cargar() {
    let turno;
    try {
      // Las cajas se vuelven a leer: la principal pudo cambiar en otra terminal.
      [turno, estado.cajas] = await Promise.all([api.get(`/api/caja/${estado.cajaId}/turno`).then((r) => r.turno), api.get('/api/cajas')]);
    } catch (e) {
      avisoError(e);
      return;
    }
    if (!turno) {
      vaciar(cuerpo, h('div.panel',
        h('h2', `${nombreCaja()} · cerrada`),
        h('p', 'No hay un turno abierto en esta caja.'),
        h('button.btn.primario.grande', { type: 'button', onclick: async () => { if (await abrirTurno()) cargar(); } }, 'Abrir caja')));
    } else if (turno.ajeno) {
      // Turno que abrió otro cajero (relevo): se vende en él, pero el dinero y el corte son de quien lo abrió.
      vaciar(cuerpo, h('div.panel',
        h('h2', `${nombreCaja()} · turno abierto por ${turno.usuario} (${fecha(turno.abierto)})`),
        h('p', 'Puedes vender en este turno. El detalle del dinero y el corte los ve quien lo abrió o alguien con permiso de corte general.'),
        puede('movimientos_caja') ? h('div.fila',
          h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('entrada')) cargar(); } }, h('kbd', 'F7'), 'Entrada'),
          h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('salida')) cargar(); } }, h('kbd', 'F8'), 'Salida')) : null));
    } else {
      // En la caja principal, quien hace el corte general lo tiene como acción destacada.
      const principal = esPrincipalConCorteGeneral() && variasCajas();
      vaciar(cuerpo,
        h('div.fila.entre',
          h('h2', `${nombreCaja()} · turno abierto por ${turno.usuario} (${fecha(turno.abierto)})`),
          h('div.fila',
            puede('movimientos_caja') ? [
              h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('entrada')) cargar(); } }, h('kbd', 'F7'), 'Entrada'),
              h('button.btn', { type: 'button', onclick: async () => { if (await movimientoCaja('salida')) cargar(); } }, h('kbd', 'F8'), 'Salida'),
            ] : null,
            h('button.btn', { type: 'button', onclick: () => imprimir(ticketCorte(turno)) }, 'Imprimir estado'),
            puede('corte') ? h(`button.btn${principal ? '' : '.primario'}`, { type: 'button', onclick: () => hacerCorte(turno) }, principal ? 'Corte solo de esta caja' : 'Hacer corte') : null,
            principal ? h('button.btn.primario', { type: 'button', onclick: () => abrirCorteGeneral() }, 'Corte general') : null)),
        detalleTurno(turno));
    }
    if (puede('corte_general')) {
      cargarGeneral();
      cargarHistorial();
    }
  }

  // --- Corte general: desde la caja principal, el de todas las cajas -----------------------
  async function cargarGeneral() {
    if (!variasCajas()) {
      vaciar(general);
      return;
    }
    const principal = cajaPrincipal();
    if (principal?.id !== estado.cajaId) {
      vaciar(general, h('div.panel',
        h('h2', 'Corte general'),
        h('p', 'El corte de todas las cajas se hace desde la caja principal', principal ? [': ', h('b', principal.nombre)] : '', '.'),
        h('p.ayuda', 'La caja principal se elige en Configuración → Cajas.')));
      return;
    }
    let abiertos = [];
    try {
      abiertos = await api.get('/api/caja/turnos-abiertos');
    } catch (e) {
      avisoError(e);
      return;
    }
    vaciar(general, h('div.panel',
      h('div.fila.entre',
        h('h2', 'Corte general · todas las cajas'),
        h('button.btn.primario', { type: 'button', disabled: !abiertos.length, onclick: () => abrirCorteGeneral() }, 'Hacer corte general')),
      tabla([
        { titulo: 'Caja', valor: (t) => h('b', t.caja) },
        { titulo: 'Abrió', valor: (t) => `${t.usuario} · ${fecha(t.abierto)}` },
        { titulo: 'Ventas', valor: (t) => `${t.n_ventas} · ${pesos(t.total_ventas)}`, clase: 'num' },
        { titulo: 'Debe haber en caja', valor: (t) => h('b', pesos(t.efectivo_esperado)), clase: 'num' },
      ], abiertos, { vacio: 'No hay cajas abiertas.' }),
      abiertos.length ? h('p.ayuda', 'Cuenta el efectivo de cada cajón: el corte general cierra todos los turnos juntos y suma lo de todas las cajas y cajeros.') : null));
  }

  /** Abre el corte general con lo que hay en este momento en cada caja (no con lo que se cargó antes). */
  async function abrirCorteGeneral(aviso = '') {
    let abiertos;
    try {
      abiertos = await api.get('/api/caja/turnos-abiertos');
    } catch (e) {
      avisoError(e);
      return;
    }
    if (!abiertos.length) {
      avisoError(new Error('No hay cajas abiertas para cortar.'));
      return;
    }
    hacerCorteGeneral(abiertos, aviso);
  }

  async function hacerCorteGeneral(abiertos, avisoInicial = '') {
    const filas = abiertos.map((t) => ({
      t,
      incluir: h('input', { type: 'checkbox', checked: true, 'aria-label': `Incluir ${t.caja}` }),
      contado: h('input', { inputmode: 'numeric', placeholder: 'Contado', autocomplete: 'off', 'aria-label': `Efectivo contado en ${t.caja}` }),
      diferencia: h('span'),
    }));
    const nota = h('textarea', { placeholder: 'Nota (opcional)', 'aria-label': 'Nota del corte general' });
    const total = h('div.total-corte');
    const claseDiferencia = (d) => (d < 0 ? 'rojo' : d > 0 ? 'verde' : '');
    const pintarTotal = () => {
      // Cada caja con su diferencia: un faltante en una y un sobrante en otra no se ven como «cuadrado».
      for (const f of filas) {
        const contado = f.contado.value.trim() ? leerMonto(f.contado.value) : null;
        const d = contado === null || !f.incluir.checked ? null : contado - f.t.efectivo_esperado;
        f.diferencia.className = d === null ? 'suave' : claseDiferencia(d);
        f.diferencia.textContent = d === null ? '—' : textoDiferencia(d);
      }
      const incluidas = filas.filter((f) => f.incluir.checked);
      const esperado = incluidas.reduce((s, f) => s + f.t.efectivo_esperado, 0);
      const contado = incluidas.reduce((s, f) => s + (leerMonto(f.contado.value) || 0), 0);
      vaciar(total, h('span', `Esperado ${pesos(esperado)}`), h('span', `Contado ${pesos(contado)}`),
        h('b', { class: claseDiferencia(contado - esperado) }, `Total: ${textoDiferencia(contado - esperado)}`));
    };
    filas.forEach((f) => { f.contado.addEventListener('input', pintarTotal); f.incluir.addEventListener('change', pintarTotal); });
    // Enter pasa al «Contado» de la caja siguiente y, en la última, confirma (como el corte de una caja).
    filas.forEach((f, i) => f.contado.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const siguiente = filas.slice(i + 1).find((x) => x.incluir.checked);
      if (siguiente) siguiente.contado.focus();
      else enviarCorte();
    }));
    pintarTotal();
    const m = modal({
      titulo: 'Corte general',
      ancho: 'ancho',
      cuerpo: [
        h('p', 'Escribe el efectivo contado en el cajón de cada caja. Se cierran todos los turnos marcados.'),
        tabla([
          { titulo: '', valor: (f) => f.incluir },
          { titulo: 'Caja', valor: (f) => h('b', f.t.caja) },
          { titulo: 'Cajero', valor: (f) => f.t.usuario },
          { titulo: 'Esperado', valor: (f) => pesos(f.t.efectivo_esperado), clase: 'num' },
          { titulo: 'Contado', valor: (f) => f.contado },
          { titulo: 'Diferencia', valor: (f) => f.diferencia, clase: 'num' },
        ], filas),
        total,
        nota,
      ],
      botones: [
        { texto: 'Cancelar', accion: (mm) => mm.cerrar() },
        { texto: 'Cerrar las cajas marcadas', clase: 'primario', accion: () => enviarCorte() },
      ],
    });
    if (avisoInicial) m.error(avisoInicial);
    setTimeout(() => filas[0]?.contado.focus(), 0);
    let enviando = false;
    async function enviarCorte() {
      if (enviando) return;
      const incluidas = filas.filter((f) => f.incluir.checked);
      if (!incluidas.length) return m.error('Marca al menos una caja.');
      const sinContar = incluidas.find((f) => !f.contado.value.trim());
      if (sinContar) {
        sinContar.contado.focus();
        return m.error(`Escribe el efectivo contado en ${sinContar.t.caja}.`);
      }
      enviando = true;
      try {
        const r = await api.post(`/api/caja/${estado.cajaId}/corte-general`, {
          cortes: incluidas.map((f) => ({ turno_id: f.t.id, efectivo_contado: leerMonto(f.contado.value) })),
          nota: nota.value.trim(),
        });
        m.cerrar();
        resultadoCorteGeneral(r);
        cargar();
      } catch (e) {
        if (e.codigo === 'turno_cerrado') {
          // Otra terminal cerró un turno mientras se contaba: se vuelve a abrir con lo que queda abierto.
          m.cerrar();
          await cargar();
          abrirCorteGeneral(`${e.message} Revisa los montos y vuelve a confirmar.`);
        } else {
          m.error(e.message);
        }
      } finally {
        enviando = false;
      }
      return null;
    }
  }

  function resultadoCorteGeneral(g) {
    const t = g.totales;
    const cuadrado = g.turnos.every((x) => x.diferencia === 0);
    modal({
      titulo: `Corte general #${g.id}`,
      cuerpo: [
        h('div.resultado-venta',
          h('div.suave', `${g.turnos.length} cajas · Esperado ${pesos(t.efectivo_esperado)} · Contado ${pesos(t.efectivo_contado)}`),
          h('div.cambio', { class: cuadrado ? 'verde' : 'rojo' }, cuadrado ? 'Todo cuadrado'
            : t.diferencia === 0 ? `${g.turnos.filter((x) => x.diferencia !== 0).length} cajas con diferencia` : `Total: ${textoDiferencia(t.diferencia)}`)),
        tabla([
          { titulo: 'Caja', valor: (x) => h('b', x.caja) },
          { titulo: 'Cajero', valor: (x) => x.usuario },
          { titulo: 'Esperado', valor: (x) => pesos(x.efectivo_esperado), clase: 'num' },
          { titulo: 'Contado', valor: (x) => pesos(x.efectivo_contado), clase: 'num' },
          { titulo: 'Diferencia', valor: (x) => h('span', { class: x.diferencia < 0 ? 'rojo' : x.diferencia > 0 ? 'verde' : '' }, textoDiferencia(x.diferencia)), clase: 'num' },
        ], g.turnos),
      ],
      botones: [
        { texto: 'Imprimir corte general', clase: 'primario', accion: () => imprimir(ticketCorteGeneral(g)) },
        { texto: 'Cerrar', accion: (mm) => mm.cerrar() },
      ],
    });
  }

  async function hacerCorte(turno) {
    if (esPrincipalConCorteGeneral()) {
      // En la caja principal, cortar solo esta caja la deja fuera del corte general: se avisa antes.
      let otras = [];
      try {
        otras = (await api.get('/api/caja/turnos-abiertos')).filter((x) => x.id !== turno.id);
      } catch { /* sin datos: se sigue con el corte de esta caja */ }
      if (otras.length && !(await confirmar('Corte solo de esta caja',
        `Hay ${otras.length === 1 ? 'otra caja abierta' : `${otras.length} cajas abiertas más`} (${otras.map((x) => x.caja).join(', ')}). `
        + `Este corte cierra solo ${nombreCaja()} y no se sumará al corte general. Para cerrar todas juntas usa «Corte general».`,
        { aceptar: 'Cortar solo esta caja', peligro: true }))) return;
    }
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
    let generales = [];
    try {
      [turnos, generales] = await Promise.all([api.get(`/api/turnos${qs(filtro)}`), api.get(`/api/cortes-generales${qs(filtro)}`)]);
    } catch (e) {
      avisoError(e);
    }
    vaciar(historial, generales.length ? h('div.panel',
      h('h2', 'Cortes generales'),
      tabla([
        { titulo: 'Corte', valor: (g) => `#${g.id}` },
        { titulo: 'Fecha', valor: (g) => fecha(g.fecha) },
        { titulo: 'Hizo', valor: (g) => `${g.usuario} · ${g.caja}` },
        { titulo: 'Cajas', valor: (g) => g.n_turnos, clase: 'num' },
        { titulo: 'Ventas', valor: (g) => pesos(g.total_ventas), clase: 'num' },
        {
          titulo: 'Diferencia',
          // «Cuadrada» solo si ninguna caja tuvo diferencia (un faltante y un sobrante se compensan en el total).
          valor: (g) => h('span', { class: g.con_diferencia ? 'rojo' : '' },
            g.con_diferencia && !g.diferencia ? `${g.con_diferencia} cajas con diferencia` : textoDiferencia(g.diferencia)),
          clase: 'num',
        },
      ], generales, {
        alClic: async (g) => {
          try {
            resultadoCorteGeneral(await api.get(`/api/cortes-generales/${g.id}`));
          } catch (e) {
            avisoError(e);
          }
        },
      })) : null, h('div.panel',
      h('div.fila.entre', h('h2', 'Historial de cortes'), selectorFechas(filtro, (f) => { filtro = f; cargarHistorial(); })),
      tabla([
        { titulo: 'Turno', valor: (t) => `#${t.id}` },
        { titulo: 'Caja', valor: (t) => t.caja },
        { titulo: 'Abrió', valor: (t) => `${t.usuario} · ${fecha(t.abierto)}` },
        { titulo: 'Cerró', valor: (t) => (t.cerrado ? [fecha(t.cerrado), t.corte_general_id ? [' ', h('span.etiqueta', `general #${t.corte_general_id}`)] : null] : h('span.etiqueta.aviso', 'abierto')) },
        { titulo: 'Ventas', valor: (t) => `${t.n_ventas} · ${pesos(t.total_ventas)}`, clase: 'num' },
        { titulo: 'Diferencia', valor: (t) => (t.diferencia == null ? '—' : h('span', { class: t.diferencia < 0 ? 'rojo' : t.diferencia > 0 ? 'verde' : '' }, textoDiferencia(t.diferencia))), clase: 'num' },
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
