// Recetario magistral: calculadora, libro de recetas y configuración de precios.

import { api, descargar, qs } from '../api.js';
import { ir } from '../app.js';
import { estado, puede } from '../estado.js';
import { cantidadLegible, imprimir, ticketReceta } from '../impresion.js';
import {
  aviso, avisoError, confirmar, debounce, decimalTexto, fecha, formulario, h, hoy, kpi, modal, numero, pesos, pestanas,
  selectorFechas, tabla, unidadPlural, vaciar,
} from '../ui.js';
import { formPrincipio, textoPrecioReceta } from './vademecum.js';

const FAMILIA = { mcg: 'masa', mg: 'masa', g: 'masa', ml: 'volumen', UI: 'UI' };
const UNIDADES_FAMILIA = { masa: ['mg', 'mcg', 'g'], volumen: ['ml'], UI: ['UI'] };
const MEDIDAS_FORMA = [
  ['unidad', 'Unidades (cápsulas, papelillos, óvulos...)'],
  ['g', 'Gramos (cremas, geles, pomadas)'],
  ['ml', 'Mililitros (lociones, jarabes, soluciones)'],
];
const ESTADOS = { pendiente: ['aviso', 'Pendiente'], vendida: ['ok', 'Vendida'], anulada: ['mal', 'Anulada'] };
const MAX_FILAS = 30;

/** 'cápsula blanda' -> 'cápsulas blandas', 'unidad' -> 'unidades', 'ml' -> 'ml'. */
const plural = (forma) => unidadPlural(2, forma.unidad, forma.nombre_unidad);

const etiquetaEstado = (e) => h(`span.etiqueta.${ESTADOS[e][0]}`, ESTADOS[e][1]);

/** Unidades en que se puede escribir la dosis de un principio activo en esta forma. */
function unidadesDosis(pa, forma) {
  const lista = [...UNIDADES_FAMILIA[FAMILIA[pa.unidad_receta]]];
  if (forma && forma.unidad !== 'unidad' && FAMILIA[pa.unidad_receta] !== 'UI') lista.push('%');
  return lista;
}

// --- Detalle de una receta guardada ----------------------------------------------

export async function verReceta(id, alCambiar = () => {}) {
  let r;
  try {
    r = await api.get(`/api/recetario/recetas/${id}`);
  } catch (e) {
    avisoError(e);
    return;
  }
  const m = modal({
    titulo: `Receta magistral N° ${r.folio}`,
    ancho: 'ancho',
    cuerpo: [
      h('div.fila', etiquetaEstado(r.estado), h('span.suave', `${fecha(r.fecha)} · preparó ${r.usuario}`),
        r.venta_folio ? h('span', `Venta folio ${r.venta_folio}`) : null),
      h('p', h('b', r.descripcion)),
      (r.paciente || r.medico) ? h('p', [r.paciente && `Paciente: ${r.paciente}${r.rut_paciente ? ' (' + r.rut_paciente + ')' : ''}`, r.medico && `Médico: ${r.medico}`].filter(Boolean).join(' · ')) : null,
      tabla([
        { titulo: 'Principio activo', valor: (c) => c.nombre },
        { titulo: 'Dosis por unidad', valor: (c) => `${numero(c.dosis)} ${c.unidad}`, clase: 'num' },
        { titulo: 'Total a pesar', valor: (c) => cantidadLegible(c.cantidad_total, c.unidad_precio), clase: 'num' },
        { titulo: 'Subtotal neto', valor: (c) => pesos(c.subtotal), clase: 'num' },
      ], r.componentes, { vacio: 'Sin principios activos (solo base).' }),
      r.indicaciones ? h('p', `Indicaciones: ${r.indicaciones}`) : null,
      h('div.kpis',
        kpi('Neto', pesos(r.neto)), kpi(`IVA`, pesos(r.iva)), kpi('Total', pesos(r.total), true)),
    ],
    botones: [
      r.estado === 'pendiente' ? {
        texto: 'Anular',
        clase: 'peligro',
        accion: async () => {
          if (!(await confirmar('Anular receta', `¿Anular la receta N° ${r.folio}?`, { aceptar: 'Anular', peligro: true }))) return;
          try { await api.post(`/api/recetario/recetas/${r.id}/anular`); m.cerrar(); alCambiar(); } catch (e) { m.error(e.message); }
        },
      } : null,
      { texto: 'Imprimir', accion: () => imprimir(ticketReceta(r)) },
      r.estado === 'pendiente' ? { texto: 'Enviar a la venta', clase: 'primario', accion: () => { m.cerrar(); ir('ventas', { recetaId: r.id }); } } : null,
    ].filter(Boolean),
  });
}

// --- Calculadora -----------------------------------------------------------------

async function vistaCalculadora(zona) {
  let formas = [];
  let principios = [];
  try {
    [formas, principios] = await Promise.all([api.get('/api/recetario/formas'), api.get('/api/principios?recetario=1&limite=10000')]);
  } catch (e) {
    avisoError(e);
  }
  if (!formas.length) {
    vaciar(zona, h('div.panel', h('p', 'No hay formas farmacéuticas activas.'),
      puede('vademecum') ? h('p.suave', 'Créalas en la pestaña Configuración.') : null));
    return {};
  }
  const porId = new Map(principios.map((p) => [String(p.id), p]));

  const selForma = h('select', formas.map((f) => h('option', { value: f.id }, f.nombre)));
  const cantidad = h('input', { inputmode: 'decimal', style: { width: '120px' }, 'aria-label': 'Cantidad' });
  const lblCantidad = h('span');
  const cuerpo = h('tbody');
  const resumen = h('div');
  const errorCalc = h('div.error-modal.oculto', { role: 'alert' });
  const paciente = h('input', { placeholder: 'Nombre del paciente' });
  const rut = h('input', { placeholder: '12.345.678-5' });
  const medico = h('input', { placeholder: 'Nombre del médico' });
  const indicaciones = h('textarea', { placeholder: 'Ej: 1 cápsula cada 8 horas por 10 días' });
  const filas = [];
  let resultado = null;
  let filasResultado = []; // filas con las que se calculó `resultado`, en el mismo orden
  let consulta = 0;
  let enviando = false;

  const formaActual = () => formas.find((f) => String(f.id) === selForma.value);

  function opcionesPrincipio() {
    return [h('option', { value: '' }, '— elegir principio activo —'),
      ...principios.map((p) => h('option', { value: p.id }, `${p.nombre} (${textoPrecioReceta(p)})`))];
  }

  function actualizarUnidades(fila) {
    const pa = porId.get(fila.pa.value);
    const previa = fila.unidad.value;
    if (!pa) {
      vaciar(fila.unidad, h('option', { value: '' }, '—'));
      fila.precio.textContent = '';
      return;
    }
    const lista = unidadesDosis(pa, formaActual());
    vaciar(fila.unidad, lista.map((u) => h('option', { value: u }, u)));
    fila.unidad.value = lista.includes(previa) ? previa : pa.unidad_receta;
    fila.precio.textContent = textoPrecioReceta(pa);
  }

  function agregarFila(datos = {}) {
    if (filas.length >= MAX_FILAS) {
      aviso(`Máximo ${MAX_FILAS} principios activos por receta.`, 'error');
      return null;
    }
    const fila = {
      pa: h('select', { 'aria-label': 'Principio activo' }, opcionesPrincipio()),
      dosis: h('input', { inputmode: 'decimal', placeholder: '0', style: { width: '110px' }, 'aria-label': 'Dosis' }),
      unidad: h('select', { style: { width: 'auto' }, 'aria-label': 'Unidad de la dosis' }),
      precio: h('span.suave'),
      subtotal: h('b'),
      pesar: h('span'),
    };
    fila.tr = h('tr',
      h('td', fila.pa), h('td.num', fila.dosis), h('td', fila.unidad), h('td.num', fila.precio),
      h('td.num', fila.pesar), h('td.num', fila.subtotal),
      h('td', h('button.btn.chico', {
        type: 'button', title: 'Quitar', 'aria-label': 'Quitar fila',
        onclick: () => { filas.splice(filas.indexOf(fila), 1); fila.tr.remove(); recalcular(); },
      }, '×')));
    fila.pa.addEventListener('change', () => { actualizarUnidades(fila); recalcular(); if (fila.pa.value) fila.dosis.focus(); });
    fila.dosis.addEventListener('input', recalcular);
    fila.unidad.addEventListener('change', recalcular);
    if (datos.principio_id) fila.pa.value = String(datos.principio_id);
    actualizarUnidades(fila);
    if (datos.dosis != null) fila.dosis.value = decimalTexto(datos.dosis);
    if (datos.unidad) fila.unidad.value = datos.unidad;
    filas.push(fila);
    cuerpo.append(fila.tr);
    return fila;
  }

  function filasCompletas() {
    return filas.filter((f) => f.pa.value && f.dosis.value.trim() && f.dosis.value.trim() !== '0');
  }

  /** Primera fila a medio llenar: principio activo sin dosis, o dosis sin principio activo. */
  function filaIncompleta() {
    return filas.find((f) => {
      const dosis = f.dosis.value.trim();
      return Boolean(f.pa.value) !== Boolean(dosis && dosis !== '0');
    });
  }

  function datosReceta(completas = filasCompletas()) {
    return {
      forma_id: Number(selForma.value),
      cantidad: cantidad.value.trim(),
      componentes: completas.map((f) => ({ principio_id: Number(f.pa.value), dosis: f.dosis.value.trim(), unidad: f.unidad.value })),
    };
  }

  function pintarResultado() {
    const f = formaActual();
    for (const fila of filas) { fila.subtotal.textContent = ''; fila.pesar.textContent = ''; }
    if (!resultado) {
      vaciar(resumen, h('p.suave', 'Completa la cantidad y los principios activos.'));
      return;
    }
    filasResultado.forEach((fila, i) => {
      const c = resultado.componentes[i];
      if (!filas.includes(fila)) return;
      if (!c) return;
      fila.subtotal.textContent = pesos(c.subtotal);
      fila.pesar.textContent = cantidadLegible(c.cantidad_total, c.unidad_precio);
    });
    vaciar(resumen,
      h('div.kpis',
        kpi('Suma principios activos', pesos(resultado.suma_principios)),
        kpi(`Costo por ${f.nombre_unidad} × ${numero(resultado.cantidad)}`, pesos(resultado.costo_unidades)),
        kpi('Valor base fórmula', pesos(resultado.precio_base)),
        kpi('Total neto', pesos(resultado.neto)),
        kpi(`IVA (${resultado.iva_porcentaje}%)`, pesos(resultado.iva)),
        kpi('Total a cobrar', pesos(resultado.total), true)),
      resultado.redondeo > 1 ? h('p.ayuda', `Total redondeado a $${resultado.redondeo}.`) : null);
  }

  async function calcularAhora() {
    const n = ++consulta;
    errorCalc.classList.add('oculto');
    if (!cantidad.value.trim()) {
      resultado = null;
      pintarResultado();
      return;
    }
    // Las filas se fijan antes de esperar al servidor: si se escribe mientras tanto, cada
    // subtotal igual queda en la fila con la que se calculó.
    const completas = filasCompletas();
    try {
      const r = await api.post('/api/recetario/calcular', datosReceta(completas));
      if (n !== consulta) return;
      resultado = r;
      filasResultado = completas;
    } catch (e) {
      if (n !== consulta) return;
      resultado = null;
      errorCalc.textContent = e.message;
      errorCalc.classList.remove('oculto');
    }
    pintarResultado();
  }
  const recalcular = debounce(calcularAhora, 150);

  function cambiarForma(usarSugerida) {
    const f = formaActual();
    lblCantidad.textContent = `Cantidad de ${plural(f)}`;
    if (usarSugerida || !cantidad.value.trim()) cantidad.value = decimalTexto(f.cantidad_sugerida);
    filas.forEach(actualizarUnidades);
    recalcular();
  }

  function limpiar() {
    filas.splice(0).forEach((f) => f.tr.remove());
    for (let i = 0; i < 4; i++) agregarFila();
    paciente.value = rut.value = medico.value = indicaciones.value = '';
    cambiarForma(true);
  }

  async function guardar() {
    const incompleta = filaIncompleta();
    if (incompleta) {
      aviso(incompleta.pa.value ? 'Falta la dosis de un principio activo.' : 'Falta elegir el principio activo de una dosis.', 'error', 5000);
      (incompleta.pa.value ? incompleta.dosis : incompleta.pa).focus();
      return null;
    }
    // Se guarda exactamente lo que está en pantalla ahora: un cálculo automático que todavía no
    // termina (o que termine después) no puede cambiar las filas que se envían.
    const completas = filasCompletas();
    const n = ++consulta;
    errorCalc.classList.add('oculto');
    try {
      const r = await api.post('/api/recetario/calcular', datosReceta(completas));
      if (n === consulta) {
        resultado = r;
        filasResultado = completas;
        pintarResultado();
      }
    } catch (e) {
      if (n === consulta) {
        resultado = null;
        errorCalc.textContent = e.message;
        errorCalc.classList.remove('oculto');
        pintarResultado();
      }
      aviso(e.message || 'Completa la receta antes de guardarla.', 'error');
      return null;
    }
    try {
      return await api.post('/api/recetario/recetas', {
        ...datosReceta(completas), paciente: paciente.value, rut_paciente: rut.value, medico: medico.value, indicaciones: indicaciones.value,
      });
    } catch (e) {
      avisoError(e);
      return null;
    }
  }

  /** Evita guardar la misma receta dos veces por un doble clic o un Enter repetido. */
  async function sinRepetir(accion) {
    if (enviando) return;
    enviando = true;
    botonesGuardar.forEach((b) => { b.disabled = true; });
    try {
      await accion();
    } finally {
      enviando = false;
      botonesGuardar.forEach((b) => { b.disabled = false; });
    }
  }

  const enviarAVenta = () => sinRepetir(async () => {
    const r = await guardar();
    if (!r) return;
    aviso(`Receta N° ${r.folio} enviada a la venta.`, 'ok');
    limpiar();
    ir('ventas', { recetaId: r.id });
  });

  const guardarEImprimir = () => sinRepetir(async () => {
    const r = await guardar();
    if (!r) return;
    imprimir(ticketReceta(r));
    aviso(`Receta N° ${r.folio} guardada como pendiente. La encuentras en el libro de recetas.`, 'ok', 6000);
    limpiar();
  });

  const botonesGuardar = [
    h('button.btn', { type: 'button', onclick: guardarEImprimir }, 'Guardar e imprimir presupuesto'),
    h('button.btn.primario.grande', { type: 'button', onclick: enviarAVenta }, h('kbd', 'Enter'), 'Enviar a la venta'),
  ];

  selForma.addEventListener('change', () => cambiarForma(true));
  cantidad.addEventListener('input', recalcular);

  vaciar(zona,
    h('div.panel',
      h('div.fila',
        h('label.campo', 'Fórmula magistral', selForma),
        h('label.campo', lblCantidad, cantidad),
        h('span.espacio'),
        principios.length ? null : h('span.rojo', 'No hay principios activos con precio de recetario. Agrégalos en Configuración.')),
      h('div', { style: { height: '.75rem' } }),
      h('div.tabla-caja', h('table',
        h('thead', h('tr', h('th', 'Principio activo'), h('th.num', 'Dosis por unidad'), h('th', 'Unidad'),
          h('th.num', 'Precio'), h('th.num', 'Total a pesar'), h('th.num', 'Subtotal'), h('th', ''))),
        cuerpo)),
      h('div.fila', { style: { marginTop: '.5rem' } },
        h('button.btn', { type: 'button', onclick: () => agregarFila()?.pa.focus() }, '+ Agregar principio activo'),
        h('span.ayuda', 'La dosis es por cada cápsula, gramo o ml. En cremas y lociones también puedes usar %.')),
      errorCalc,
      resumen),
    h('div.panel',
      h('h3', 'Datos de la receta (opcional)'),
      h('div.rejilla',
        h('label.campo', 'Paciente', paciente), h('label.campo', 'RUT del paciente', rut),
        h('label.campo', 'Médico', medico),
        h('label.campo.ancho', 'Indicaciones / posología', indicaciones))),
    h('div.fila.fin', { style: { marginTop: '1rem' } },
      h('button.btn', { type: 'button', onclick: limpiar }, 'Limpiar'),
      ...botonesGuardar));

  limpiar();
  selForma.focus();

  return {
    alTeclear(e) {
      // Solo desde un campo de texto (no desde una lista, un botón o las indicaciones), y sin
      // repetir si se mantiene apretado Enter.
      if (e.key === 'Enter' && !e.repeat && e.target.matches('input')) {
        e.preventDefault();
        enviarAVenta();
      }
    },
  };
}

// --- Libro de recetas ------------------------------------------------------------------

async function vistaLibro(zona) {
  let filtro = { desde: hoy(-30), hasta: hoy() };
  const buscar = h('input', { type: 'search', placeholder: 'Folio, paciente, RUT o médico', style: { maxWidth: '300px' } });
  const estadoSel = h('select', { style: { width: 'auto' } },
    [['', 'Todas'], ['pendiente', 'Pendientes'], ['vendida', 'Vendidas'], ['anulada', 'Anuladas']].map(([v, t]) => h('option', { value: v }, t)));
  const lista = h('div');

  vaciar(zona, h('div.panel',
    h('div.fila.entre', selectorFechas(filtro, (f) => { filtro = f; cargar(); }),
      puede('reportes') ? h('button.btn', { type: 'button', onclick: () => descargar(`/api/recetario/recetas.csv${qs({ ...filtro, q: buscar.value.trim(), estado: estadoSel.value })}`) }, 'Exportar libro CSV') : null),
    h('div.fila', { style: { margin: '.75rem 0' } }, buscar, estadoSel),
    lista));

  async function cargar() {
    let recetas = [];
    try {
      recetas = await api.get(`/api/recetario/recetas${qs({ ...filtro, q: buscar.value.trim(), estado: estadoSel.value })}`);
    } catch (e) {
      avisoError(e);
    }
    vaciar(lista, tabla([
      { titulo: 'Folio', valor: (r) => h('b', r.folio) },
      { titulo: 'Fecha', valor: (r) => fecha(r.fecha) },
      { titulo: 'Paciente', valor: (r) => r.paciente || '' },
      { titulo: 'Médico', valor: (r) => r.medico || '' },
      { titulo: 'Preparado', valor: (r) => `${r.forma} × ${numero(r.cantidad)}` },
      { titulo: 'Estado', valor: (r) => [etiquetaEstado(r.estado), r.venta_folio ? h('span.ayuda', ` folio ${r.venta_folio}`) : null] },
      { titulo: 'Total', valor: (r) => pesos(r.total), clase: 'num' },
    ], recetas, { vacio: 'No hay recetas en estas fechas.', alClic: (r) => verReceta(r.id, cargar) }));
  }

  buscar.addEventListener('input', debounce(cargar));
  estadoSel.addEventListener('change', cargar);
  await cargar();
  return {};
}

// --- Configuración (formas y precios) ---------------------------------------------------

function formForma(f = null) {
  return formulario({
    titulo: f ? `Editar ${f.nombre}` : 'Nueva forma farmacéutica',
    campos: [
      { nombre: 'nombre', etiqueta: 'Nombre', valor: f?.nombre, requerido: true, autofocus: true, placeholder: 'Ej: Cápsulas, Cremas, Papelillos' },
      { nombre: 'unidad', etiqueta: 'Se mide en', tipo: 'select', valor: f?.unidad || 'unidad', opciones: MEDIDAS_FORMA },
      { nombre: 'nombre_unidad', etiqueta: 'Nombre de la unidad', valor: f?.nombre_unidad, placeholder: 'cápsula, gramo, ml' },
      { nombre: 'precio_base', etiqueta: 'Valor base de la fórmula (neto)', valor: decimalTexto(f?.precio_base ?? 0), atributos: { inputmode: 'decimal' } },
      { nombre: 'precio_unidad', etiqueta: 'Precio por cada unidad (neto)', valor: decimalTexto(f?.precio_unidad ?? 0), atributos: { inputmode: 'decimal' }, ayuda: 'Ej: 40 por cápsula, 2,5 por gramo' },
      { nombre: 'cantidad_sugerida', etiqueta: 'Cantidad sugerida', valor: decimalTexto(f?.cantidad_sugerida ?? 30), atributos: { inputmode: 'decimal' } },
      { nombre: 'activa', etiqueta: 'Activa', tipo: 'check', valor: f ? Boolean(f.activa) : true },
    ],
    alEnviar: (v) => (f ? api.put(`/api/recetario/formas/${f.id}`, v) : api.post('/api/recetario/formas', v)),
  });
}

async function vistaConfiguracion(zona) {
  const [formas, principios] = await Promise.all([api.get('/api/recetario/formas?todas=1'), api.get('/api/principios?limite=10000')]);
  const redondeo = h('select', { style: { width: 'auto' } },
    [['1', 'Al peso ($1)'], ['10', 'A $10'], ['50', 'A $50'], ['100', 'A $100']].map(([v, t]) =>
      h('option', { value: v, selected: estado.config.receta_redondeo === v }, t)));
  redondeo.addEventListener('change', async () => {
    try {
      estado.config = await api.put('/api/config', { receta_redondeo: redondeo.value });
      aviso('Redondeo actualizado.', 'ok');
    } catch (e) {
      avisoError(e);
    }
  });
  const recargar = () => vistaConfiguracion(zona);

  vaciar(zona,
    h('div.panel',
      h('div.fila.entre', h('h3', 'Formas farmacéuticas'),
        h('button.btn.primario', { type: 'button', onclick: async () => { if (await formForma()) recargar(); } }, 'Nueva forma')),
      tabla([
        { titulo: 'Forma', valor: (f) => h('b', f.nombre) },
        { titulo: 'Medida', valor: (f) => f.nombre_unidad },
        { titulo: 'Valor base', valor: (f) => pesos(f.precio_base), clase: 'num' },
        { titulo: 'Precio por unidad', valor: (f) => `$${decimalTexto(f.precio_unidad)}`, clase: 'num' },
        { titulo: 'Cantidad sugerida', valor: (f) => numero(f.cantidad_sugerida), clase: 'num' },
        { titulo: 'Estado', valor: (f) => h(`span.etiqueta.${f.activa ? 'ok' : 'mal'}`, f.activa ? 'Activa' : 'Inactiva') },
      ], formas, { alClic: async (f) => { if (await formForma(f)) recargar(); } }),
      h('p.ayuda', 'Precios netos (sin IVA). El IVA se suma al calcular.'),
      h('div.fila', h('span', 'Redondear el total de las recetas:'), redondeo)),
    h('div.panel',
      h('div.fila.entre', h('h3', 'Precio de los principios activos'),
        h('button.btn.primario', { type: 'button', onclick: async () => { if (await formPrincipio(null, { soloRecetario: true })) recargar(); } }, 'Nuevo principio activo')),
      tabla([
        { titulo: 'Principio activo', valor: (p) => h('b', p.nombre) },
        { titulo: 'Precio neto por unidad', valor: (p) => textoPrecioReceta(p), clase: 'num' },
        { titulo: 'Productos', valor: (p) => p.productos, clase: 'num' },
      ], principios, {
        vacio: 'Aún no hay principios activos.',
        alClic: async (p) => { if (await formPrincipio(p, { soloRecetario: true })) recargar(); },
      }),
      h('p.ayuda', 'Haz clic en un principio activo para fijar su unidad (mg, mcg, g, ml o UI) y su precio. La ficha clínica se edita en el Vademécum.')));
  return {};
}

export async function montar(contenedor) {
  const opciones = [['calculadora', 'Calculadora magistral'], ['libro', 'Libro de recetas']];
  if (puede('vademecum')) opciones.push(['configuracion', 'Configuración']);
  const barra = h('div');
  const zona = h('div');
  let actual = null;
  vaciar(contenedor, h('h2', 'Recetario magistral'), barra, zona);

  async function mostrar(p) {
    vaciar(barra, pestanas(opciones, p, mostrar));
    try {
      actual = await ({ calculadora: vistaCalculadora, libro: vistaLibro, configuracion: vistaConfiguracion })[p](zona);
    } catch (e) {
      avisoError(e);
    }
  }
  await mostrar('calculadora');
  return { alTeclear: (e) => actual?.alTeclear?.(e) };
}
