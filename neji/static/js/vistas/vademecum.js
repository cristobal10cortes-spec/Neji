// Vademécum: principios activos, su ficha clínica y los productos que los contienen.

import { api, descargar, qs } from '../api.js';
import { ir } from '../app.js';
import { puede } from '../estado.js';
import { formProducto } from './productos.js';
import { aviso, avisoError, confirmar, debounce, formulario, h, modal, numero, pesos, tabla, vaciar } from '../ui.js';

const LIMITE = 5000; // principios activos que se listan de una vez (la búsqueda filtra en el servidor)
const UNIDADES = [['', '— no se usa en el recetario —'], ['mg', 'mg'], ['mcg', 'mcg'], ['g', 'g'], ['ml', 'ml'], ['UI', 'UI']];

export const textoPrecioReceta = (pa) => (pa.precio_receta == null ? '—'
  : `$${String(pa.precio_receta).replace('.', ',')} por ${pa.unidad_receta}`);

/** Alta o edición de un principio activo (ficha clínica + precio para el recetario). */
export function formPrincipio(pa = null, { soloRecetario = false } = {}) {
  const campos = [{ nombre: 'nombre', etiqueta: 'Principio activo', valor: pa?.nombre, requerido: true, autofocus: !pa }];
  if (!soloRecetario) {
    campos.push(
      { nombre: 'accion_terapeutica', etiqueta: 'Para qué sirve (acción / uso terapéutico)', tipo: 'area', valor: pa?.accion_terapeutica, ancho: true, autofocus: Boolean(pa) },
      { nombre: 'dosis', etiqueta: 'Dosis habitual', tipo: 'area', valor: pa?.dosis, ancho: true, placeholder: 'Ej: Adultos: 500 mg a 1 g cada 6 a 8 horas. Máximo 4 g al día.' },
      { nombre: 'efectos_adversos', etiqueta: 'Efectos adversos', tipo: 'area', valor: pa?.efectos_adversos, ancho: true },
      { nombre: 'contraindicaciones', etiqueta: 'Contraindicaciones e interacciones', tipo: 'area', valor: pa?.contraindicaciones, ancho: true },
      { nombre: 'notas', etiqueta: 'Notas (embarazo, lactancia, conservación...)', tipo: 'area', valor: pa?.notas, ancho: true },
      { nombre: 'otros_nombres', etiqueta: 'Otros nombres (marcas, sinónimos o sales)', valor: (pa?.otros_nombres || '').split('|').join(' | '), ancho: true, placeholder: 'Ej: KITADOL | ACETAMINOFENO', ayuda: 'Separados por |. Sirven para reconocer el principio activo en la descripción de los productos.' },
    );
  }
  campos.push(
    { nombre: 'unidad_receta', etiqueta: 'Unidad de precio en el recetario', tipo: 'select', valor: pa?.unidad_receta || '', opciones: UNIDADES },
    { nombre: 'precio_receta', etiqueta: 'Precio neto por unidad ($)', valor: pa?.precio_receta == null ? '' : String(pa.precio_receta).replace('.', ','), atributos: { inputmode: 'decimal' }, ayuda: 'Ej: 0,1 por mg. Déjalo vacío si no se usa en fórmulas.' },
  );
  return formulario({
    titulo: pa ? `Editar ${pa.nombre}` : 'Nuevo principio activo',
    ancho: 'ancho',
    campos,
    alEnviar: (v) => {
      // Al editar solo el precio se conserva la ficha clínica tal como estaba.
      const ficha = soloRecetario && pa ? {
        accion_terapeutica: pa.accion_terapeutica, dosis: pa.dosis, efectos_adversos: pa.efectos_adversos,
        contraindicaciones: pa.contraindicaciones, notas: pa.notas, otros_nombres: pa.otros_nombres,
      } : {};
      const datos = { ...ficha, ...v, unidad_receta: v.unidad_receta || null, precio_receta: v.precio_receta === '' ? null : v.precio_receta };
      return pa ? api.put(`/api/principios/${pa.id}`, datos) : api.post('/api/principios', datos);
    },
  });
}

// --- Planilla del vademécum -------------------------------------------------------------------------------
// Varios principios activos a la vez, como en Excel: una fila por principio activo y las columnas en el mismo
// orden que la planilla de importar/exportar. Se abre al crear principios activos, al guardar un producto cuyo
// principio activo todavía no tiene ficha y al importar el inventario.

const COLUMNAS_PLANILLA = [
  ['nombre', 'Principio activo', 'Ej: PARACETAMOL'],
  ['accion_terapeutica', 'Para qué sirve', 'Ej: Analgésico y antipirético: dolor leve a moderado y fiebre.'],
  ['dosis', 'Dosis habitual', 'Ej: Adultos: 500 mg a 1 g cada 6 a 8 horas. Máximo 4 g al día.'],
  ['efectos_adversos', 'Efectos adversos', 'Ej: Náuseas; en exceso daña el hígado.'],
  // Guion suave: en una columna angosta el título se corta como «CONTRA-INDICACIONES».
  ['contraindicaciones', 'Contra\u00adindicaciones y precauciones', 'Ej: Daño hepático grave.'],
  ['notas', 'Notas', 'Ej: Se puede usar en el embarazo.'],
  ['otros_nombres', 'Otros nombres', 'Ej: KITADOL | PANADOL'],
];

/**
 * Abre la planilla. `filas`: principios activos (con id si ya existen) o [] para empezar con una fila en blanco.
 * Devuelve true si se guardó algo.
 */
export function planillaVademecum(filas = [], { titulo = 'Principios activos nuevos', intro = null, agregar = true } = {}) {
  return new Promise((resolver) => {
    let guardado = false;
    const cuerpo = h('tbody');
    const filaVacia = () => ({ nombre: '' });
    const agregarFila = (pa) => {
      const n = cuerpo.children.length + 1;
      const celdas = COLUMNAS_PLANILLA.map(([clave, titulo_, ejemplo]) => {
        const valor = clave === 'otros_nombres' ? (pa[clave] || '').split('|').filter(Boolean).join(' | ') : (pa[clave] || '');
        if (clave === 'nombre' && pa.id) {
          // Ya existe: el nombre se muestra completo y no se cambia aquí.
          const fijo = h('input', { type: 'hidden', value: valor });
          fijo.dataset.clave = clave;
          return h('td', h('b.pa-fijo', valor), fijo);
        }
        const control = clave === 'nombre'
          ? h('input', { value: valor, placeholder: n === 1 ? ejemplo : '', 'aria-label': `${titulo_} (fila ${n})` })
          : h('textarea', { rows: 3, placeholder: n === 1 ? ejemplo : '', 'aria-label': `${titulo_} (fila ${n})` }, valor);
        control.dataset.clave = clave;
        return h('td', control);
      });
      const tr = h('tr', h('td.num.suave', String(n)), celdas);
      tr.dataset.id = pa.id || '';
      cuerpo.append(tr);
      return tr;
    };
    (filas.length ? filas : [filaVacia()]).forEach(agregarFila);
    const leer = () => [...cuerpo.children].map((tr) => {
      const datos = Object.fromEntries([...tr.querySelectorAll('[data-clave]')].map((c) => [c.dataset.clave, c.value.trim()]));
      return tr.dataset.id ? { ...datos, id: Number(tr.dataset.id) } : datos;
    });
    const tablaPlanilla = h('div.tabla-caja.planilla-pa', h('table',
      h('thead', h('tr', h('th', 'N°'), COLUMNAS_PLANILLA.map(([, t]) => h('th', t)))),
      cuerpo));
    const m = modal({
      titulo,
      ancho: 'muy-ancho',
      cuerpo: [
        intro ? h('p', intro) : null,
        h('p.ayuda', 'Escribe en palabras simples, como para explicarlo en el mesón. Tab pasa a la casilla siguiente. Lo que quede vacío se puede completar después en Vademécum. Es información de referencia: que la revise el químico farmacéutico.'),
        tablaPlanilla,
      ],
      alCerrar: () => resolver(guardado),
      botones: [
        agregar ? { texto: 'Agregar fila', accion: () => agregarFila(filaVacia()).querySelector('input, textarea').focus() } : null,
        { texto: filas.length ? 'Después' : 'Cancelar', accion: (mm) => mm.cerrar() },
        { texto: 'Guardar en el vademécum', clase: 'primario', accion: async (mm) => {
          const principios = leer().filter((p) => p.id || Object.values(p).some(Boolean));
          if (!principios.length) return mm.error('Escribe al menos un principio activo.');
          if (principios.some((p) => !p.nombre)) return mm.error('Cada fila necesita el nombre del principio activo.');
          try {
            const r = await api.post('/api/principios/lote', { principios });
            guardado = true;
            aviso(`Vademécum guardado: ${[r.creados ? `${r.creados} nuevos` : '', r.actualizados ? `${r.actualizados} completados` : ''].filter(Boolean).join(', ')}.`, 'ok', 5000);
            return mm.cerrar();
          } catch (e) {
            return mm.error(e.message);
          }
        } },
      ].filter(Boolean),
    });
    requestAnimationFrame(() => m.el.querySelector('.planilla-pa input:not([type=hidden]), .planilla-pa textarea')?.focus());
  });
}

/** Si alguno de esos principios activos (de un producto recién guardado) no tiene ficha, ofrece completarla. */
export async function completarFichasDe(principios) {
  if (!puede('vademecum')) return false;
  const vacios = (principios || []).filter((p) => !p.accion_terapeutica && !p.dosis);
  if (!vacios.length) return false;
  return planillaVademecum(vacios, {
    titulo: vacios.length === 1 ? `${vacios[0].nombre}: nuevo en el vademécum` : 'Principios activos nuevos en el vademécum',
    intro: vacios.length === 1 ? 'Este principio activo todavía no tiene ficha. Complétala ahora (o después, en Vademécum).'
      : 'Estos principios activos todavía no tienen ficha. Complétalas ahora (o después, en Vademécum).',
    agregar: false,
  });
}

/** Los principios activos sin ficha (todavía no dicen para qué sirven ni su dosis), en la planilla. */
export async function completarFichasVacias() {
  let vacios;
  try {
    vacios = await api.get('/api/principios?sin_ficha=1&limite=300');
  } catch (e) {
    avisoError(e);
    return false;
  }
  if (!vacios.length) {
    aviso('Todos los principios activos tienen su ficha.', 'ok');
    return false;
  }
  return planillaVademecum(vacios, {
    titulo: `Completar fichas vacías (${numero(vacios.length)}${vacios.length >= 300 ? ' primeras' : ''})`,
    intro: 'Principios activos que todavía no dicen para qué sirven ni su dosis (por ejemplo, los que llegaron con un producto o al importar el inventario).',
    agregar: false,
  });
}

function bloque(titulo, texto) {
  return texto ? h('div', h('h3', titulo), h('p', { style: { whiteSpace: 'pre-wrap', marginTop: 0 } }, texto)) : null;
}

/**
 * Ficha de un principio activo con los productos que lo contienen. Desde la venta, `alVender(codigo)`
 * agrega el producto al ticket a la vista; si no, «Vender» abre la pantalla de ventas.
 */
export async function fichaPrincipio(id, alCambiar = () => {}, { alVender = null } = {}) {
  let pa;
  try {
    pa = await api.get(`/api/principios/${id}`);
  } catch (e) {
    avisoError(e);
    return;
  }
  const m = modal({
    titulo: pa.nombre,
    ancho: 'muy-ancho',
    cuerpo: [
      h('div.fila',
        h(`span.etiqueta.${pa.con_stock ? 'ok' : 'mal'}`, `${pa.con_stock} de ${pa.productos} productos con stock`),
        pa.precio_receta != null ? h('span.etiqueta', `Recetario: ${textoPrecioReceta(pa)}`) : null),
      bloque('Para qué sirve', pa.accion_terapeutica) || h('p.suave', 'Sin ficha clínica todavía.'),
      bloque('Dosis habitual', pa.dosis),
      bloque('Efectos adversos', pa.efectos_adversos),
      bloque('Contraindicaciones e interacciones', pa.contraindicaciones),
      bloque('Notas', pa.notas),
      pa.otros_nombres ? h('p.ayuda', `También se reconoce como: ${pa.otros_nombres.split('|').join(', ')}.`) : null,
      h('h3', 'Productos que lo contienen'),
      tabla([
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Producto', valor: (p) => [p.descripcion, h('div.ayuda', p.principios)] },
        { titulo: 'Depto.', valor: (p) => p.departamento || '' },
        { titulo: 'Existencia', valor: (p) => (p.usa_inventario ? h('b', { class: p.existencia > 0 ? 'verde' : 'rojo' }, numero(p.existencia)) : '—'), clase: 'num' },
        { titulo: 'Precio', valor: (p) => pesos(p.precio_venta), clase: 'num' },
        {
          titulo: '',
          valor: (p) => h('button.btn.chico.primario', {
            type: 'button',
            disabled: p.usa_inventario && p.existencia <= 0,
            onclick: () => {
              m.cerrar();
              if (alVender) alVender(p.codigo);
              else ir('ventas', { codigo: p.codigo });
            },
          }, 'Vender'),
        },
      ], pa.lista_productos, { vacio: 'Ningún producto del catálogo tiene este principio activo.' }),
      h('p.ayuda', 'Información de referencia. No reemplaza la indicación del médico ni la del químico farmacéutico.'),
    ],
    botones: puede('vademecum') ? [
      {
        texto: 'Eliminar',
        clase: 'peligro',
        accion: async () => {
          if (!(await confirmar('Eliminar principio activo', `¿Eliminar ${pa.nombre} del vademécum?`, { aceptar: 'Eliminar', peligro: true }))) return;
          try { await api.del(`/api/principios/${pa.id}`); m.cerrar(); alCambiar(); aviso('Principio activo eliminado.', 'ok'); } catch (e) { m.error(e.message); }
        },
      },
      { texto: 'Editar', clase: 'primario', accion: async () => { if (await formPrincipio(pa)) { m.cerrar(); alCambiar(); fichaPrincipio(id, alCambiar, { alVender }); } } },
    ] : [],
  });
}

const SECCIONES_FICHA = [
  ['accion_terapeutica', 'Para qué sirve'],
  ['dosis', 'Dosis habitual'],
  ['efectos_adversos', 'Efectos adversos'],
  ['contraindicaciones', 'Contraindicaciones e interacciones'],
  ['notas', 'Notas'],
];

const celda = (titulo, valor, clase = '') => h(`div.celda${clase}`, h('span.t', titulo), h('span.v', valor));

/**
 * Panel con la ficha del vademécum del producto en foco (al buscar o al elegir una línea del ticket).
 * Muestra lo mismo que la pantalla Vademécum para cada principio activo, y quien es administrador
 * puede editarlo desde aquí. `fichas` guarda los productos ya leídos del servidor (id -> producto) y puede
 * compartirse entre paneles: si otro panel lo renueva al editar, este se vuelve a pintar al mostrarla.
 * Mientras `retenerFoco()` sea verdadero, un clic en el panel no le quita el foco al buscador.
 * `alActualizar(producto)` recibe los datos frescos de un producto (al leerlo o al asignarle un principio),
 * para que el ticket muestre lo mismo; `alVender(codigo)` se usa en el botón «Vender» de la ficha completa.
 * Devuelve { el, mostrar(producto, contexto), recordar(producto), producto }.
 */
export function panelVademecum({
  fichas = new Map(), alternativas = null, alTerminar = () => {}, retenerFoco = () => false, alActualizar = () => {}, alVender = null,
} = {}) {
  const contexto = h('span.etiqueta.oculto');
  const anuncio = h('span.solo-lector', { role: 'status' }); // el lector de pantalla anuncia el producto en foco
  const cuerpo = h('div.ficha-cuerpo');
  const pie = h('div.ficha-pie.oculto');
  // Los botones no le quitan el foco al buscador, y con su lista abierta tampoco leer o desplazar la ficha:
  // así la lista no se cierra ni la ficha cambia de producto.
  const el = h('aside.vademecum', {
    'aria-label': 'Vademécum',
    onmousedown: (e) => {
      if (e.target.closest('button') || (retenerFoco() && !e.target.closest('input, textarea, select'))) e.preventDefault();
    },
  },
    h('div.ficha-titulo', h('span', 'Vademécum'), contexto, anuncio),
    cuerpo, pie);
  let producto = null;
  let clave = null;
  let alerta = false; // sin stock o no alcanza: Ctrl+B se destaca
  let pintado = null; // con qué datos se pintó: si el caché cambió (otro panel editó), se vuelve a pintar
  const cargando = new Set();

  const actual = () => (producto && fichas.get(producto.id)) || producto;

  function recordar(p) {
    if (p?.id && p.principios_detalle) fichas.set(p.id, p);
  }

  function mostrar(p, texto = '') {
    const nueva = p ? `${p.id}|${texto}` : null;
    if (nueva === clave && (!p || (fichas.get(p.id) || p) === pintado)) return;
    clave = nueva;
    producto = p;
    alerta = texto === 'sin stock' || texto === 'no alcanza';
    contexto.textContent = texto;
    contexto.className = `etiqueta${texto ? '' : ' oculto'}${alerta ? ' mal' : ''}`;
    pintar();
    if (p?.id && !fichas.has(p.id)) cargar(p);
  }

  async function cargar(p) {
    const { id } = p;
    if (cargando.has(id)) return;
    cargando.add(id);
    let fresco = null;
    try {
      fresco = await api.get(`/api/productos/${id}`);
    } catch (e) {
      // Borrado del catálogo: se avisa. Sin conexión: se queda con lo que traía el ticket, sin volver a pedirlo a cada rato.
      fichas.set(id, e.status === 404 ? { ...p, principios_detalle: [], eliminado: true } : null);
      return;
    } finally {
      cargando.delete(id);
    }
    fichas.set(id, fresco.activo ? fresco : { ...p, principios_detalle: [], eliminado: true });
    if (fresco.activo) alActualizar(fresco);
    if (producto?.id === id) pintar();
  }

  function refrescar() {
    fichas.clear();
    if (producto?.id) cargar(producto);
  }

  async function editar(id) {
    try {
      const pa = await api.get(`/api/principios/${id}`);
      if (await formPrincipio(pa)) {
        aviso('Vademécum actualizado.', 'ok');
        refrescar();
      }
    } catch (e) {
      avisoError(e);
    }
    alTerminar();
  }

  async function asignarPrincipio(id) {
    try {
      const guardado = await formProducto(await api.get(`/api/productos/${id}`));
      if (guardado) {
        aviso('Producto actualizado.', 'ok');
        alActualizar(guardado); // el ticket toma el principio y, si cambió, el precio nuevo
        refrescar();
      }
    } catch (e) {
      avisoError(e);
    }
    alTerminar();
  }

  function seccion(pa) {
    const textos = SECCIONES_FICHA.filter(([k]) => pa[k]);
    return h('section.ficha-pa',
      h('div.pa-nombre',
        h('b', pa.nombre), pa.concentracion ? h('span.etiqueta', pa.concentracion) : null,
        h('span.pa-botones',
          h('button.btn.chico', { type: 'button', title: 'Ficha completa y productos que lo contienen', onclick: () => fichaPrincipio(pa.id, refrescar, { alVender }) }, 'Ficha'),
          puede('vademecum') ? h('button.btn.chico', { type: 'button', title: `Editar lo que dice el vademécum de ${pa.nombre}`, onclick: () => editar(pa.id) }, 'Editar') : null)),
      textos.length
        ? h('dl', textos.map(([k, titulo]) => [h('dt', titulo), h('dd', { onclick: (e) => alternarTexto(e.currentTarget) }, pa[k])]))
        : h('p.suave', puede('vademecum') ? 'Sin ficha en el vademécum. Usa Editar para escribirla.' : 'Sin ficha en el vademécum.'));
  }

  // Cada texto largo se muestra en unas líneas; con un clic se ve completo (y la ficha completa está en «Ficha»).
  function marcarCortados() {
    for (const dd of cuerpo.querySelectorAll('dd:not(.abierto)')) {
      const cortado = dd.scrollHeight > dd.clientHeight + 1;
      dd.classList.toggle('cortado', cortado);
      dd.title = cortado ? 'Clic para ver el texto completo' : '';
    }
  }

  function alternarTexto(dd) {
    if (dd.classList.contains('abierto')) {
      dd.classList.remove('abierto');
      marcarCortados();
    } else if (dd.classList.contains('cortado')) {
      dd.classList.replace('cortado', 'abierto');
      dd.title = 'Clic para acortar';
    }
  }

  function pintar() {
    const p = actual();
    pintado = p;
    anuncio.textContent = p ? `Ficha de ${p.descripcion}` : '';
    if (!p) {
      pie.classList.add('oculto');
      vaciar(cuerpo, h('div.ficha-vacia',
        h('p', 'Escribe en el buscador o elige una línea del ticket para ver aquí su ficha.'),
        h('p.ayuda', 'Escribe % y el principio activo para buscar por componente (ej: %paracetamol).')));
      return;
    }
    if (p.eliminado) {
      pie.classList.add('oculto');
      vaciar(cuerpo, h('div.ficha-producto',
        h('div.ficha-nombre', { title: p.descripcion }, p.descripcion),
        h('p.rojo', 'Este producto ya no está en el catálogo. Quítalo del ticket con Supr.')));
      return;
    }
    const detalle = p.principios_detalle || [];
    const sinStock = p.usa_inventario && p.existencia <= 0;
    vaciar(cuerpo,
      h('div.ficha-producto',
        h('div.ficha-nombre', { title: p.descripcion }, p.descripcion),
        h('div.celdas',
          celda('Código', p.codigo, '.ancha.mono'),
          celda('Precio', pesos(p.precio_venta)),
          celda('Existencia', p.usa_inventario ? numero(p.existencia) : '—', sinStock ? '.rojo' : ''))),
      detalle.length
        ? detalle.map(seccion)
        : h('div.ficha-pa',
          h('p.suave', 'Este producto no tiene principio activo asignado.'),
          puede('productos') && p.id ? h('button.btn.chico', { type: 'button', onclick: () => asignarPrincipio(p.id) }, 'Asignar principio activo') : null),
      detalle.length ? h('p.ayuda', 'Información de referencia. No reemplaza la indicación del médico ni la del químico farmacéutico.') : null);
    const conAlternativas = alternativas && detalle.length && p.id;
    pie.classList.toggle('oculto', !conAlternativas);
    if (conAlternativas) {
      vaciar(pie, h(`button.btn.chico${sinStock || alerta ? '.primario' : ''}`, { type: 'button', onclick: () => alternativas(p) },
        h('kbd', 'Ctrl+B'), sinStock ? 'Sin stock: ver alternativas' : 'Alternativas'));
    }
    requestAnimationFrame(marcarCortados);
  }

  pintar();
  return {
    el,
    mostrar,
    recordar,
    get producto() { return actual(); },
  };
}

// --- Importar, exportar y vademécum base -----------------------------------------------------------------

const cuantos = (n, uno, varios) => `${numero(n)} ${n === 1 ? uno : varios}`;

const MODOS = [
  ['completar', 'Solo completar lo que está vacío (lo que ya escribiste se respeta)'],
  ['reemplazar', 'Reemplazar con lo del archivo (las celdas vacías no borran nada)'],
];

function mostrarResultado(titulo, r) {
  modal({
    titulo,
    cuerpo: [
      h('p', `${cuantos(r.creados, 'principio activo nuevo', 'principios activos nuevos')}, ${cuantos(r.actualizados, 'ficha completada o cambiada', 'fichas completadas o cambiadas')}, ${numero(r.sin_cambios)} sin cambios.`),
      r.errores.length ? [h('p.rojo', `${r.errores.length} filas con problemas:`),
        h('ul', r.errores.map((e) => h('li', `Fila ${e.fila}: ${e.error}`)))] : null,
    ],
    botones: [{ texto: 'Aceptar', clase: 'primario', accion: (m) => m.cerrar() }],
  });
}

function importarPlanilla(alTerminar) {
  const archivo = h('input', { type: 'file', accept: '.xlsx,.csv,.txt' });
  const modo = h('select', MODOS.map(([v, t]) => h('option', { value: v }, t)));
  const crear = h('input', { type: 'checkbox', checked: true });
  modal({
    titulo: 'Importar vademécum (Excel o CSV)',
    cuerpo: [
      h('p', 'Una fila por principio activo, con estas columnas (la primera fila, los títulos):'),
      h('p.mono', 'Principio activo · Para qué sirve · Dosis habitual · Efectos adversos · Contraindicaciones y precauciones · Notas'),
      h('p.ayuda', 'Es el mismo formato de «Exportar»: puedes exportar, corregir en Excel e importar. Cada principio activo se busca por su nombre, sin importar tildes, mayúsculas ni la sal (LOSARTÁN completa la ficha de LOSARTAN POTASICO).'),
      h('label.campo', 'Archivo', archivo),
      h('label.campo', 'Si el principio activo ya tiene ficha', modo),
      h('label.check', crear, 'Agregar los principios activos que todavía no están'),
    ],
    botones: [
      { texto: 'Cancelar', accion: (m) => m.cerrar() },
      { texto: 'Importar', clase: 'primario', accion: async (m) => {
        if (!archivo.files?.[0]) return m.error('Elige el archivo (Excel .xlsx o CSV).');
        const datos = new FormData();
        datos.append('archivo', archivo.files[0]);
        datos.append('modo', modo.value);
        datos.append('crear', crear.checked ? '1' : '0');
        try {
          const r = await api.subir('/api/principios/importar', datos);
          m.cerrar();
          alTerminar();
          return mostrarResultado('Vademécum importado', r);
        } catch (e) {
          return m.error(e.message);
        }
      } },
    ],
  });
}

function cargarBase(alTerminar) {
  const modo = h('select', MODOS.map(([v, t]) => h('option', { value: v }, t)));
  modal({
    titulo: 'Vademécum base de Neji POS',
    cuerpo: [
      h('p', 'Los principios activos más comunes de las farmacias, escritos en palabras simples: para qué sirven, la dosis habitual, los efectos adversos y las precauciones. Los que no tengas se agregan; los que ya tienes (aunque estén con su sal, como LOSARTAN POTASICO) reciben la ficha.'),
      h('p.rojo', 'Es información de referencia: que el químico farmacéutico la revise antes de usarla con los pacientes.'),
      h('label.campo', 'Si el principio activo ya tiene ficha', modo),
      h('p.ayuda', 'Para cambiar fichas técnicas por las simples elige «Reemplazar». También puedes descargar la planilla para revisarla en Excel e importarla después.'),
    ],
    botones: [
      { texto: 'Descargar planilla', accion: () => descargar('/static/referencia/vademecum_base.csv').catch(avisoError) },
      { texto: 'Cancelar', accion: (m) => m.cerrar() },
      { texto: 'Cargar vademécum base', clase: 'primario', accion: async (m) => {
        try {
          const r = await api.post('/api/principios/base', { modo: modo.value });
          m.cerrar();
          alTerminar();
          return mostrarResultado('Vademécum base cargado', r);
        } catch (e) {
          return m.error(e.message);
        }
      } },
    ],
  });
}

/**
 * Productos sin principio activo: Neji lo busca en la descripción («KITADOL 500 MG PARACETAMOL X 24 COMP») y
 * muestra lo que encontró para aprobarlo (o desmarcar lo que esté mal). Lista también los que no reconoció.
 */
async function vincularProductos(alTerminar) {
  let r;
  try {
    r = await api.get('/api/principios/vincular');
  } catch (e) {
    avisoError(e);
    return;
  }
  const elegidos = new Set(r.sugerencias.map((s) => s.id));
  const contador = h('b');
  const actualizar = () => { contador.textContent = `${numero(elegidos.size)} de ${numero(r.sugerencias.length)} elegidos`; };
  const todos = h('input', { type: 'checkbox', checked: true, 'aria-label': 'Elegir todos', onchange: (e) => {
    r.sugerencias.forEach((s) => (e.target.checked ? elegidos.add(s.id) : elegidos.delete(s.id)));
    lista.querySelectorAll('input[data-producto]').forEach((c) => { c.checked = e.target.checked; });
    actualizar();
  } });
  const lista = tabla([
    { titulo: todos, valor: (s) => h('input', { type: 'checkbox', checked: true, 'data-producto': s.id, 'aria-label': `Vincular ${s.descripcion}`,
      onchange: (e) => { if (e.target.checked) elegidos.add(s.id); else elegidos.delete(s.id); actualizar(); } }) },
    { titulo: 'Código', valor: (s) => h('span.mono', s.codigo) },
    { titulo: 'Producto', valor: (s) => s.descripcion },
    { titulo: 'Principio activo encontrado', valor: (s) => h('b', s.principios) },
  ], r.sugerencias, { vacio: 'No hay productos para vincular: todos tienen principio activo o no se reconoció ninguno.' });
  actualizar();
  const sinReconocer = r.total_sin_reconocer ? h('details', { style: { marginTop: '.8rem' } },
    h('summary', r.total_sin_reconocer === 1 ? '1 producto sin principio activo que no se reconoció' : `${numero(r.total_sin_reconocer)} productos sin principio activo que no se reconocieron`),
    h('p.ayuda', 'Por ejemplo, insumos o productos que no son medicamentos, o una marca sin el nombre del principio activo en la descripción. Para una marca, agrégala en «Otros nombres» del principio activo (Editar) y vuelve a vincular; o escribe el principio activo en el producto.'),
    h('ul', r.sin_reconocer.slice(0, 200).map((p) => h('li', `${p.codigo} · ${p.descripcion}`))),
    r.total_sin_reconocer > 200 ? h('p.suave', `… y ${numero(r.total_sin_reconocer - 200)} más.`) : null) : null;
  modal({
    titulo: 'Vincular productos con el vademécum',
    ancho: 'muy-ancho',
    cuerpo: [
      h('p', 'Neji buscó el principio activo en la descripción de los productos que no lo tienen. Revisa la lista, desmarca lo que esté mal y vincula el resto.'),
      h('p', contador),
      lista,
      sinReconocer,
    ],
    botones: [
      { texto: 'Cancelar', accion: (m) => m.cerrar() },
      { texto: 'Vincular los elegidos', clase: 'primario', accion: async (m) => {
        if (!elegidos.size) return m.error('Elige al menos un producto.');
        try {
          const res = await api.post('/api/principios/vincular', { ids: [...elegidos] });
          m.cerrar();
          aviso(`${cuantos(res.vinculados, 'producto quedó unido', 'productos quedaron unidos')} al vademécum.`, 'ok', 6000);
          return alTerminar();
        } catch (e) {
          return m.error(e.message);
        }
      } },
    ],
  });
}

export async function montar(contenedor) {
  const buscar = h('input', { type: 'search', placeholder: 'Principio activo o uso terapéutico (ej: losartán, antihipertensivo)', autofocus: true, style: { maxWidth: '460px' } });
  const conStock = h('input', { type: 'checkbox' });
  const lista = h('div');
  const contador = h('span.suave');

  vaciar(contenedor,
    h('div.fila.entre',
      h('h2', 'Vademécum'),
      puede('vademecum') ? h('div.fila',
        h('button.btn', { type: 'button', onclick: () => cargarBase(cargar) }, 'Vademécum base'),
        puede('productos') ? h('button.btn', { type: 'button', onclick: () => vincularProductos(cargar) }, 'Vincular productos') : null,
        h('button.btn', { type: 'button', onclick: () => importarPlanilla(cargar) }, 'Importar'),
        h('button.btn', { type: 'button', onclick: () => descargar('/api/principios/exportar').catch(avisoError) }, 'Exportar'),
        h('button.btn', { type: 'button', onclick: async () => { if (await completarFichasVacias()) cargar(); } }, 'Completar fichas vacías'),
        h('button.btn.primario', { type: 'button', onclick: async () => { if (await planillaVademecum()) cargar(); } }, 'Nuevo principio activo')) : null),
    h('div.fila', buscar, h('label.check', conStock, 'Solo con productos en stock'), h('span.espacio'), contador),
    h('p.ayuda', 'En la venta, escribe % antes del nombre para buscar productos por componente (ej: %paracetamol).'),
    lista);

  async function cargar() {
    let principios = [];
    try {
      principios = await api.get(`/api/principios${qs({ q: buscar.value.trim(), con_stock: conStock.checked ? 1 : '', limite: LIMITE })}`);
    } catch (e) {
      avisoError(e);
    }
    contador.textContent = principios.length >= LIMITE
      ? `Primeros ${numero(LIMITE)} principios activos: escribe para buscar`
      : `${numero(principios.length)} principios activos`;
    vaciar(lista, tabla([
      { titulo: 'Principio activo', valor: (p) => h('b', p.nombre) },
      { titulo: 'Para qué sirve', valor: (p) => p.accion_terapeutica || h('span.suave', 'sin ficha') },
      { titulo: 'Productos', valor: (p) => h('span', { class: p.con_stock ? 'verde' : 'suave' }, `${p.con_stock} con stock / ${p.productos}`), clase: 'num' },
      { titulo: 'Recetario', valor: (p) => textoPrecioReceta(p), clase: 'num' },
    ], principios, {
      vacio: buscar.value ? 'Sin resultados.' : 'Aún no hay principios activos. Se crean al asignarlos a un producto, al importar el inventario en CSV (columna principio_activo) o con «Nuevo principio activo».',
      alClic: (p) => fichaPrincipio(p.id, cargar),
    }));
  }

  buscar.addEventListener('input', debounce(cargar));
  conStock.addEventListener('change', cargar);
  await cargar();
  buscar.focus();
}
