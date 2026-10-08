// Vademécum: principios activos, su ficha clínica y los productos que los contienen.

import { api, qs } from '../api.js';
import { ir } from '../app.js';
import { esAdmin } from '../estado.js';
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
      { nombre: 'accion_terapeutica', etiqueta: 'Acción / uso terapéutico', tipo: 'area', valor: pa?.accion_terapeutica, ancho: true, autofocus: Boolean(pa) },
      { nombre: 'efectos_adversos', etiqueta: 'Efectos adversos', tipo: 'area', valor: pa?.efectos_adversos, ancho: true },
      { nombre: 'contraindicaciones', etiqueta: 'Contraindicaciones e interacciones', tipo: 'area', valor: pa?.contraindicaciones, ancho: true },
      { nombre: 'notas', etiqueta: 'Notas (posología habitual, embarazo, conservación...)', tipo: 'area', valor: pa?.notas, ancho: true },
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
        accion_terapeutica: pa.accion_terapeutica, efectos_adversos: pa.efectos_adversos,
        contraindicaciones: pa.contraindicaciones, notas: pa.notas,
      } : {};
      const datos = { ...ficha, ...v, unidad_receta: v.unidad_receta || null, precio_receta: v.precio_receta === '' ? null : v.precio_receta };
      return pa ? api.put(`/api/principios/${pa.id}`, datos) : api.post('/api/principios', datos);
    },
  });
}

function bloque(titulo, texto) {
  return texto ? h('div', h('h3', titulo), h('p', { style: { whiteSpace: 'pre-wrap', marginTop: 0 } }, texto)) : null;
}

/** Ficha de un principio activo con los productos que lo contienen. */
export async function fichaPrincipio(id, alCambiar = () => {}) {
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
      bloque('Acción terapéutica', pa.accion_terapeutica) || h('p.suave', 'Sin ficha clínica todavía.'),
      bloque('Efectos adversos', pa.efectos_adversos),
      bloque('Contraindicaciones e interacciones', pa.contraindicaciones),
      bloque('Notas', pa.notas),
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
            onclick: () => { m.cerrar(); ir('ventas', { codigo: p.codigo }); },
          }, 'Vender'),
        },
      ], pa.lista_productos, { vacio: 'Ningún producto del catálogo tiene este principio activo.' }),
      h('p.ayuda', 'Información de referencia ingresada por la farmacia. No reemplaza la indicación del médico ni la del químico farmacéutico.'),
    ],
    botones: esAdmin() ? [
      {
        texto: 'Eliminar',
        clase: 'peligro',
        accion: async () => {
          if (!(await confirmar('Eliminar principio activo', `¿Eliminar ${pa.nombre} del vademécum?`, { aceptar: 'Eliminar', peligro: true }))) return;
          try { await api.del(`/api/principios/${pa.id}`); m.cerrar(); alCambiar(); aviso('Principio activo eliminado.', 'ok'); } catch (e) { m.error(e.message); }
        },
      },
      { texto: 'Editar', clase: 'primario', accion: async () => { if (await formPrincipio(pa)) { m.cerrar(); alCambiar(); fichaPrincipio(id, alCambiar); } } },
    ] : [],
  });
}

const SECCIONES_FICHA = [
  ['accion_terapeutica', 'Acción terapéutica'],
  ['efectos_adversos', 'Efectos adversos'],
  ['contraindicaciones', 'Contraindicaciones e interacciones'],
  ['notas', 'Notas'],
];

const celda = (titulo, valor, clase = '') => h(`div.celda${clase}`, h('span.t', titulo), h('span.v', valor));

/**
 * Panel con la ficha del vademécum del producto en foco (al buscar o al elegir una línea del ticket).
 * Muestra lo mismo que la pantalla Vademécum para cada principio activo, y quien es administrador
 * puede editarlo desde aquí. `fichas` guarda los productos ya leídos del servidor (id -> producto).
 * Devuelve { el, mostrar(producto, contexto), recordar(producto), producto }.
 */
export function panelVademecum({ fichas = new Map(), alternativas = null, alTerminar = () => {} } = {}) {
  const contexto = h('span.etiqueta.oculto');
  const cuerpo = h('div.ficha-cuerpo');
  const pie = h('div.ficha-pie.oculto');
  // Los botones no le quitan el foco al buscador: así su lista de resultados no se cierra al hacer clic.
  const el = h('aside.vademecum', { 'aria-label': 'Vademécum', onmousedown: (e) => { if (e.target.closest('button')) e.preventDefault(); } },
    h('div.ficha-titulo', h('span', 'Vademécum'), contexto),
    cuerpo, pie);
  let producto = null;
  let clave = null;

  const actual = () => (producto && fichas.get(producto.id)) || producto;

  function recordar(p) {
    if (p?.id && p.principios_detalle) fichas.set(p.id, p);
  }

  function mostrar(p, texto = '') {
    const nueva = p ? `${p.id}|${texto}` : null;
    if (nueva === clave) return;
    clave = nueva;
    producto = p;
    contexto.textContent = texto;
    contexto.className = `etiqueta${texto ? '' : ' oculto'}${texto === 'sin stock' ? ' mal' : ''}`;
    pintar();
    if (p?.id && !fichas.has(p.id)) cargar(p.id);
  }

  async function cargar(id) {
    try {
      fichas.set(id, await api.get(`/api/productos/${id}`));
    } catch {
      return; // se queda con lo que traía el ticket
    }
    if (producto?.id === id) pintar();
  }

  function refrescar() {
    fichas.clear();
    if (producto?.id) cargar(producto.id);
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
      if (await formProducto(await api.get(`/api/productos/${id}`))) {
        aviso('Producto actualizado.', 'ok');
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
          h('button.btn.chico', { type: 'button', title: 'Ficha completa y productos que lo contienen', onclick: () => fichaPrincipio(pa.id, refrescar) }, 'Ficha'),
          esAdmin() ? h('button.btn.chico', { type: 'button', title: `Editar lo que dice el vademécum de ${pa.nombre}`, onclick: () => editar(pa.id) }, 'Editar') : null)),
      textos.length
        ? h('dl', textos.map(([k, titulo]) => [h('dt', titulo), h('dd', pa[k])]))
        : h('p.suave', esAdmin() ? 'Sin ficha en el vademécum. Usa Editar para escribirla.' : 'Sin ficha en el vademécum.'));
  }

  function pintar() {
    const p = actual();
    if (!p) {
      pie.classList.add('oculto');
      vaciar(cuerpo, h('div.ficha-vacia',
        h('p', 'Escribe en el buscador o elige una línea del ticket para ver aquí su ficha.'),
        h('p.ayuda', 'Escribe % y el principio activo para buscar por componente (ej: %paracetamol).')));
      return;
    }
    const detalle = p.principios_detalle || [];
    const sinStock = p.usa_inventario && p.existencia <= 0;
    vaciar(cuerpo,
      h('div.ficha-producto',
        h('div.ficha-nombre', p.descripcion),
        h('div.celdas',
          celda('Código', p.codigo, '.ancha.mono'),
          celda('Precio', pesos(p.precio_venta)),
          celda('Existencia', p.usa_inventario ? numero(p.existencia) : '—', sinStock ? '.rojo' : ''))),
      detalle.length
        ? detalle.map(seccion)
        : h('div.ficha-pa',
          h('p.suave', 'Este producto no tiene principio activo asignado.'),
          esAdmin() && p.id ? h('button.btn.chico', { type: 'button', onclick: () => asignarPrincipio(p.id) }, 'Asignar principio activo') : null),
      detalle.length ? h('p.ayuda', 'Información de referencia de la farmacia. No reemplaza la indicación del médico ni la del químico farmacéutico.') : null);
    const conAlternativas = alternativas && detalle.length && p.id;
    pie.classList.toggle('oculto', !conAlternativas);
    if (conAlternativas) {
      vaciar(pie, h(`button.btn.chico${sinStock ? '.primario' : ''}`, { type: 'button', onclick: () => alternativas(p) },
        h('kbd', 'Ctrl+B'), sinStock ? 'Sin stock: ver alternativas' : 'Alternativas'));
    }
  }

  pintar();
  return {
    el,
    mostrar,
    recordar,
    get producto() { return actual(); },
  };
}

export async function montar(contenedor) {
  const buscar = h('input', { type: 'search', placeholder: 'Principio activo o uso terapéutico (ej: losartán, antihipertensivo)', autofocus: true, style: { maxWidth: '460px' } });
  const conStock = h('input', { type: 'checkbox' });
  const lista = h('div');
  const contador = h('span.suave');

  vaciar(contenedor,
    h('div.fila.entre',
      h('h2', 'Vademécum'),
      esAdmin() ? h('button.btn.primario', { type: 'button', onclick: async () => { if (await formPrincipio()) cargar(); } }, 'Nuevo principio activo') : null),
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
      { titulo: 'Acción terapéutica', valor: (p) => p.accion_terapeutica || h('span.suave', 'sin ficha') },
      { titulo: 'Productos', valor: (p) => h('span', { class: p.con_stock ? 'verde' : 'suave' }, `${p.con_stock} con stock / ${p.productos}`), clase: 'num' },
      { titulo: 'Recetario', valor: (p) => textoPrecioReceta(p), clase: 'num' },
    ], principios, {
      vacio: buscar.value ? 'Sin resultados.' : 'Aún no hay principios activos. Se crean al asignarlos a un producto, al importar desde CORAND.ERP o con «Nuevo principio activo».',
      alClic: (p) => fichaPrincipio(p.id, cargar),
    }));
  }

  buscar.addEventListener('input', debounce(cargar));
  conStock.addEventListener('change', cargar);
  await cargar();
  buscar.focus();
}
