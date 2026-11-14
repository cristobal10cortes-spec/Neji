// Catálogo de productos: alta, edición, departamentos, CSV, kardex y etiquetas.

import { api, descargar, qs } from '../api.js';
import { esFarmacia, estado, puede } from '../estado.js';
import { hojaEtiquetas, imprimir } from '../impresion.js';
import { completarFichasDe, completarFichasVacias } from './vademecum.js';
import {
  aviso, avisoError, confirmar, debounce, fecha, formulario, h, leerCantidad, leerMonto, modal, numero, pesos, tabla, vaciar,
} from '../ui.js';

const POR_PAGINA = 50;

let formularioAbierto = false;

/**
 * Alta o edición de producto. Devuelve el producto guardado o null. Un doble clic en la fila abre una
 * sola ventana: la segunda llamada, mientras la primera está abierta, no hace nada.
 * Opciones: `codigo` (el de un producto nuevo, p. ej. recién escaneado) y `acciones` (más botones en la ventana,
 * como Kardex y Eliminar: { texto, clase, accion(ventana) }).
 */
export async function formProducto(producto = null, opciones = {}) {
  if (formularioAbierto) return null;
  formularioAbierto = true;
  try {
    const guardado = await abrirFormProducto(producto, opciones);
    // Farmacia: si su principio activo es nuevo en el vademécum (sin ficha), la planilla para completarla.
    if (guardado && esFarmacia()) await completarFichasDe(guardado.principios_detalle);
    return guardado;
  } finally {
    formularioAbierto = false;
  }
}

async function abrirFormProducto(producto, { codigo = '', acciones = [] } = {}) {
  const farmacia = esFarmacia();
  const [departamentos, principios] = await Promise.all([
    api.get('/api/departamentos').catch(() => []),
    farmacia ? api.get('/api/principios?limite=5000').catch(() => []) : [],
  ]);
  const listaDeps = h('div',
    h('datalist', { id: 'lista-departamentos' }, departamentos.map((d) => h('option', { value: d.nombre }))),
    h('datalist', { id: 'lista-principios' }, principios.map((p) => h('option', { value: p.nombre }))));
  const margen = producto && producto.precio_costo
    ? Math.round(((producto.precio_venta / producto.precio_costo) - 1) * 1000) / 10 : '';

  const campos = [
    { nombre: 'codigo', etiqueta: 'Código de barras', valor: producto?.codigo ?? codigo, requerido: true, autofocus: !codigo },
    { nombre: 'descripcion', etiqueta: 'Descripción', valor: producto?.descripcion, requerido: true, autofocus: Boolean(codigo) },
    { nombre: 'departamento', etiqueta: 'Departamento', valor: producto?.departamento, atributos: { list: 'lista-departamentos' }, placeholder: 'Ej: Bebidas' },
    { nombre: 'tipo_venta', etiqueta: 'Se vende por', tipo: 'select', valor: producto?.tipo_venta || 'unidad', opciones: [['unidad', 'Unidad / pieza'], ['granel', 'Granel (kg, litro, metro)']] },
    farmacia ? { nombre: 'principios', etiqueta: 'Principio(s) activo(s)', valor: producto?.principios, ancho: true, placeholder: 'Ej: PARACETAMOL 500 mg + CAFEINA 65 mg', atributos: { list: 'lista-principios' }, ayuda: producto ? 'Separa con + si tiene varios. Quedan unidos al vademécum y permiten buscar con %.' : 'Si lo dejas vacío, Neji lo busca en la descripción (ej: KITADOL 500 MG PARACETAMOL X 24 COMP). Separa con + si tiene varios.' } : null,
    { nombre: 'precio_costo', etiqueta: 'Precio de costo (con IVA)', tipo: 'monto', valor: producto?.precio_costo ?? '' },
    { nombre: 'margen', etiqueta: '% de ganancia sobre el costo', tipo: 'cantidad', valor: margen, ayuda: 'Calcula el precio de venta. Es el mismo con o sin IVA.' },
    { nombre: 'precio_venta', etiqueta: 'Precio de venta (con IVA)', tipo: 'monto', valor: producto?.precio_venta ?? '', requerido: true },
    { nombre: 'precio_mayoreo', etiqueta: 'Precio de mayoreo', tipo: 'monto', valor: producto?.precio_mayoreo ?? '', ayuda: 'Opcional. Se aplica con F11.' },
    { nombre: 'cantidad_mayoreo', etiqueta: 'Mayoreo automático desde', tipo: 'cantidad', valor: producto?.cantidad_mayoreo ?? '', ayuda: 'Opcional. Ej: 6 unidades' },
    { nombre: 'usa_inventario', etiqueta: 'Controlar inventario', tipo: 'check', valor: producto ? Boolean(producto.usa_inventario) : true },
  ];
  if (!producto) campos.push({ nombre: 'existencia', etiqueta: 'Existencia inicial', tipo: 'cantidad', valor: '0' });
  campos.push(
    { nombre: 'minimo', etiqueta: 'Inventario mínimo', tipo: 'cantidad', valor: producto?.minimo ?? '0' },
    { nombre: 'maximo', etiqueta: 'Inventario máximo', tipo: 'cantidad', valor: producto?.maximo ?? '' },
    { nombre: 'proveedor', etiqueta: farmacia ? 'Distribuidor / laboratorio' : 'Proveedor', valor: producto?.proveedor },
    { nombre: 'vencimiento', etiqueta: 'Vencimiento', tipo: 'fecha', valor: producto?.vencimiento },
    { nombre: 'exento', etiqueta: 'Exento de IVA', tipo: 'check', valor: producto ? Boolean(producto.exento) : false },
  );

  return formulario({
    titulo: producto ? 'Editar producto' : 'Nuevo producto',
    ancho: 'ancho',
    enterAvanza: true,   // Enter pasa de un dato al siguiente, hasta «Guardar»
    intro: h('p.ayuda', 'Enter pasa al dato siguiente; al final, Enter en «Guardar» guarda el producto.'),
    campos: campos.filter(Boolean),
    extra: listaDeps,
    botonesExtra: producto ? acciones : [],
    alMostrar: (e) => {
      const generar = h('button.btn.chico', { type: 'button' }, 'Generar código interno');
      generar.addEventListener('click', async () => {
        try {
          e.codigo.value = (await api.get('/api/productos/siguiente-codigo')).codigo;
          // Sigue el recorrido con Enter: el próximo dato es la descripción.
          e.descripcion.focus();
          e.descripcion.select();
        } catch (err) { avisoError(err); }
      });
      e.codigo.after(generar);
      const desdeMargen = () => {
        const costo = leerMonto(e.precio_costo.value);
        const m = leerCantidad(e.margen.value);
        if (costo > 0 && Number.isFinite(m)) e.precio_venta.value = Math.round(costo * (1 + m / 100));
      };
      const haciaMargen = () => {
        const costo = leerMonto(e.precio_costo.value);
        const venta = leerMonto(e.precio_venta.value);
        e.margen.value = costo > 0 && venta > 0 ? String(Math.round(((venta / costo) - 1) * 1000) / 10).replace('.', ',') : '';
      };
      // La ganancia real por unidad: venta menos costo, los dos sin IVA (el IVA no es ganancia: va al SII).
      const real = h('span.ayuda', { 'aria-live': 'polite' });
      e.precio_venta.after(real);
      const mostrarReal = () => {
        const costo = leerMonto(e.precio_costo.value);
        const venta = leerMonto(e.precio_venta.value);
        if (!(venta > 0) || !(costo >= 0) || !e.precio_costo.value.trim()) {
          real.textContent = '';
          return;
        }
        const factor = e.exento.checked ? 1 : 1 + (Number(String(estado.config.iva_porcentaje || 19).replace(',', '.')) || 19) / 100;
        const ganancia = Math.round((venta - costo) / factor);
        const sobreVenta = Math.round(1000 * (venta - costo) / venta) / 10;
        real.textContent = `Ganancia real: ${pesos(ganancia)} por unidad, sin IVA (${String(sobreVenta).replace('.', ',')}% del precio de venta).`;
        real.classList.toggle('rojo', ganancia < 0);
      };
      e.margen.addEventListener('input', () => { desdeMargen(); mostrarReal(); });
      e.precio_costo.addEventListener('input', () => { if (e.margen.value) desdeMargen(); else haciaMargen(); mostrarReal(); });
      e.precio_venta.addEventListener('input', () => { haciaMargen(); mostrarReal(); });
      e.exento.addEventListener('change', mostrarReal);
      mostrarReal();
    },
    alEnviar: async (v) => {
      delete v.margen;
      if (producto) return api.put(`/api/productos/${producto.id}`, v);
      const nuevo = await api.post('/api/productos', v);
      if (nuevo.principios_detectados) aviso(`Unido al vademécum: ${nuevo.principios_detectados}.`, 'ok', 6000);
      return nuevo;
    },
  });
}

async function verKardex(p) {
  try {
    const movs = await api.get(`/api/productos/${p.id}/kardex`);
    modal({
      titulo: `Kardex · ${p.descripcion}`,
      ancho: 'muy-ancho',
      cuerpo: [
        h('p', `Existencia actual: `, h('b', numero(p.existencia))),
        tabla([
          { titulo: 'Fecha', valor: (m) => fecha(m.fecha) },
          { titulo: 'Tipo', valor: (m) => h('span.etiqueta', m.tipo) },
          { titulo: 'Referencia', valor: (m) => [m.referencia, m.nota].filter(Boolean).join(' · ') },
          { titulo: 'Usuario', valor: (m) => m.usuario || '' },
          { titulo: 'Cantidad', valor: (m) => h('span', { class: m.cantidad < 0 ? 'rojo' : 'verde' }, (m.cantidad > 0 ? '+' : '') + numero(m.cantidad)), clase: 'num' },
          { titulo: 'Antes', valor: (m) => numero(m.existencia_anterior), clase: 'num' },
          { titulo: 'Después', valor: (m) => numero(m.existencia_nueva), clase: 'num' },
        ], movs, { vacio: 'Sin movimientos.' }),
      ],
    });
  } catch (e) {
    avisoError(e);
  }
}

/**
 * Importación del catálogo y del inventario desde una planilla: Excel (.xlsx) o CSV (eleventa u otro sistema).
 * Devuelve { el, importar() }: se usa en Productos (en una ventana) y en Configuración → Importar inventario.
 */
export function importadorCsv({ alTerminar = () => {} } = {}) {
  const archivo = h('input', {
    type: 'file', 'aria-label': 'Planilla Excel o CSV',
    accept: '.xlsx,.csv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const reemplazar = h('input', { type: 'radio', name: 'existencias-csv', value: 'reemplazar', checked: true });
  const sumar = h('input', { type: 'radio', name: 'existencias-csv', value: 'sumar' });
  const resultado = h('div');
  const error = h('div.error-modal.oculto', { role: 'alert' });
  const mostrarError = (texto) => { error.textContent = texto; error.classList.toggle('oculto', !texto); };
  // Al elegir otro archivo deja de verse el resultado del anterior.
  archivo.addEventListener('change', () => { mostrarError(''); vaciar(resultado); });
  let enviando = false;

  /** Sube el archivo. Un segundo clic mientras sube no hace nada (con «Se suma al stock» sumaría dos veces). */
  async function importar() {
    if (enviando) return null;
    if (!archivo.files[0]) return mostrarError('Elige la planilla (Excel .xlsx o CSV).');
    const datos = new FormData();
    datos.append('archivo', archivo.files[0]);
    datos.append('existencias', sumar.checked ? 'sumar' : 'reemplazar');
    enviando = true;
    mostrarError('');
    vaciar(resultado, h('p.suave', 'Importando… no cierres esta ventana.'));
    try {
      const r = await api.subir('/api/productos/importar', datos);
      vaciar(resultado, h('div.panel',
        h('p', h('b', `${r.creados} creados, ${r.actualizados} actualizados.`)),
        r.vinculados ? h('p', `${r.vinculados === 1 ? '1 producto quedó unido' : `${r.vinculados} productos quedaron unidos`} al vademécum por su descripción (Vademécum → «Vincular productos» muestra los que faltan).`) : null,
        r.principios_sin_ficha && puede('vademecum') ? h('p', `${r.principios_sin_ficha === 1 ? 'Hay 1 principio activo' : `Hay ${r.principios_sin_ficha} principios activos`} de tus productos sin ficha en el vademécum. `,
          h('button.btn.chico.primario', { type: 'button', onclick: () => completarFichasVacias() }, 'Completar fichas')) : null,
        r.errores.length ? [h('p.rojo', r.errores.length === 1 ? 'Revisa esta fila:' : `Revisa estas ${r.errores.length} filas:`),
          h('ul', r.errores.map((e) => h('li', `Fila ${e.fila}: ${e.error}`)))] : null));
      archivo.value = '';
      alTerminar(r);
    } catch (err) {
      vaciar(resultado);
      mostrarError(err.message);
    } finally {
      enviando = false;
    }
    return null;
  }

  const el = h('div.importador-csv',
    h('p', 'Sirve para traer tu catálogo y tu inventario desde Excel, eleventa u otro sistema. Sube la planilla de Excel (.xlsx) tal como la exporta tu sistema, o un CSV (separado por punto y coma o coma).'),
    h('p.ayuda', 'Columnas reconocidas: codigo, descripcion, precio_venta, precio_costo, precio_mayoreo, cantidad_mayoreo, departamento, tipo_venta (unidad/granel), existencia, minimo, maximo, usa_inventario (si/no), exento (si/no), principio_activo, proveedor y vencimiento. También entiende los nombres de eleventa ("Código", "Producto", "P. Costo", "P. Venta", "Existencia", "Inv. Mínimo") y otros como "Stock", "Categoría", "Distribuidor" o "Principio Activo".'),
    h('p.ayuda', 'Si el código ya existe, el producto se actualiza con las columnas que traigan datos. Para cargar solo el stock basta con las columnas codigo, descripcion y existencia.'),
    h('div.fila',
      h('button.btn.chico', { type: 'button', onclick: () => descargar('/api/productos/plantilla.csv') }, 'Descargar planilla de ejemplo'),
      h('button.btn.chico', { type: 'button', onclick: () => descargar('/api/productos/exportar') }, 'Exportar mi catálogo actual')),
    error,
    archivo,
    puede('inventario')
      ? h('fieldset.opciones-csv',
        h('legend', 'La columna existencia de los productos que ya tienes'),
        h('label.check', reemplazar, 'Reemplaza el stock (conteo de inventario)'),
        h('label.check', sumar, 'Se suma al stock (entrada de mercadería)'))
      : h('p.ayuda', 'Sin permiso de inventario, la existencia solo se usa en los productos nuevos: la de los que ya tienes no cambia.'),
    resultado);
  return { el, importar };
}

async function importarCsv(alTerminar) {
  const importador = importadorCsv({ alTerminar });
  modal({
    titulo: 'Importar productos (Excel o CSV)',
    ancho: 'ancho',
    cuerpo: importador.el,
    botones: [
      { texto: 'Cerrar', accion: (m) => m.cerrar() },
      { texto: 'Importar', clase: 'primario', accion: () => importador.importar() },
    ],
  });
}

async function administrarDepartamentos(alCambiar) {
  const lista = h('div');
  const cargar = async () => {
    const deps = await api.get('/api/departamentos');
    vaciar(lista, tabla([
      { titulo: 'Departamento', valor: (d) => d.nombre },
      { titulo: 'Productos', valor: (d) => d.productos, clase: 'num' },
      {
        titulo: '',
        valor: (d) => h('div.fila.fin',
          h('button.btn.chico', {
            type: 'button',
            onclick: async () => {
              const r = await formulario({ titulo: 'Renombrar departamento', campos: [{ nombre: 'nombre', etiqueta: 'Nombre', valor: d.nombre, requerido: true }], alEnviar: (v) => api.put(`/api/departamentos/${d.id}`, v) });
              if (r) { cargar(); alCambiar(); }
            },
          }, 'Renombrar'),
          h('button.btn.chico.peligro', {
            type: 'button',
            onclick: async () => {
              if (!(await confirmar('Eliminar departamento', `Los productos de «${d.nombre}» quedarán sin departamento.`, { aceptar: 'Eliminar', peligro: true }))) return;
              await api.del(`/api/departamentos/${d.id}`).catch(avisoError);
              cargar();
              alCambiar();
            },
          }, 'Eliminar')),
      },
    ], deps, { vacio: 'Aún no hay departamentos.' }));
  };
  modal({
    titulo: 'Departamentos',
    ancho: 'ancho',
    cuerpo: lista,
    botones: [{
      texto: 'Nuevo departamento',
      clase: 'primario',
      accion: async () => {
        const r = await formulario({ titulo: 'Nuevo departamento', campos: [{ nombre: 'nombre', etiqueta: 'Nombre', requerido: true }], alEnviar: (v) => api.post('/api/departamentos', v) });
        if (r) { cargar(); alCambiar(); }
      },
    }],
  });
  cargar();
}

/**
 * Etiquetas con código de barras: se escanean (o se buscan) los productos que las llevan; escanear dos veces el
 * mismo suma una copia. `enLista` son los productos que se ven en la lista, para agregarlos todos de una vez.
 */
function imprimirEtiquetas(enLista = []) {
  const elegidos = new Map(); // id del producto → { producto, copias (campo) }
  const entrada = h('input', {
    type: 'search', placeholder: 'Escanea el código o busca el producto', autocomplete: 'off', autofocus: true,
    'data-lector': 'aqui', 'aria-label': 'Código o descripción del producto',
  });
  const resultados = h('div');
  const elegidosEl = h('div');
  const copiasDe = (id) => Math.min(parseInt(elegidos.get(id).copias.value, 10) || 0, 200);

  const pintar = () => vaciar(elegidosEl, elegidos.size
    ? tabla([
      { titulo: 'Producto', valor: ({ producto: p }) => p.descripcion },
      { titulo: 'Código', valor: ({ producto: p }) => h('span.mono', p.codigo) },
      { titulo: 'Precio', valor: ({ producto: p }) => pesos(p.precio_venta), clase: 'num' },
      { titulo: 'Copias', valor: (e) => e.copias },
      { titulo: '', valor: ({ producto: p }) => h('button.btn.chico', { type: 'button', title: 'Quitar', 'aria-label': `Quitar ${p.descripcion}`, onclick: () => { elegidos.delete(p.id); pintar(); entrada.focus(); } }, '×') },
    ], [...elegidos.values()])
    : h('p.vacio', 'Escanea o busca los productos que llevan etiqueta.'));

  const agregar = (p) => {
    const ya = elegidos.get(p.id);
    if (ya) ya.copias.value = String(copiasDe(p.id) + 1);
    else elegidos.set(p.id, { producto: p, copias: h('input', { type: 'number', min: '0', max: '200', value: '1', style: { width: '90px' }, 'aria-label': `Copias de ${p.descripcion}` }) });
    vaciar(resultados);
    entrada.value = '';
    pintar();
    entrada.focus();
  };

  async function buscar() {
    const q = entrada.value.trim();
    if (!q) return;
    try {
      agregar(await api.get(`/api/productos/codigo/${encodeURIComponent(q)}`));
      return;
    } catch { /* no es un código: se busca por descripción */ }
    const r = await api.get(`/api/productos${qs({ q, por_pagina: 10 })}`).catch(() => ({ productos: [] }));
    if (r.productos.length === 1) {
      agregar(r.productos[0]);
      return;
    }
    vaciar(resultados, r.productos.length
      ? [h('p.ayuda', 'Haz clic en el producto para agregarlo.'), tabla([
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Producto', valor: (p) => p.descripcion },
        { titulo: 'Precio', valor: (p) => pesos(p.precio_venta), clase: 'num' },
      ], r.productos, { alClic: agregar })]
      : h('p.vacio', `Sin resultados para «${q}».`));
    entrada.select(); // lo próximo que se escanee reemplaza lo escrito
  }
  entrada.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    buscar();
  });

  pintar();
  modal({
    titulo: 'Imprimir etiquetas con código de barras',
    ancho: 'ancho',
    cuerpo: [
      h('p.ayuda', 'Etiquetas de 50 × 30 mm con descripción, precio y código de barras (Code 128). Escanea un producto una vez por cada etiqueta, o cambia las copias.'),
      h('div.fila', entrada,
        enLista.length ? h('button.btn', { type: 'button', onclick: () => { enLista.forEach(agregar); } }, `Agregar los de la lista (${enLista.length})`) : null),
      resultados,
      h('div', { style: { height: '.5rem' } }),
      elegidosEl,
    ],
    botones: [{
      texto: 'Imprimir',
      clase: 'primario',
      accion: (m) => {
        const items = [...elegidos.values()].map((e) => ({ producto: e.producto, copias: copiasDe(e.producto.id) })).filter((i) => i.copias > 0);
        if (!items.length) return m.error('Escanea o busca al menos un producto.');
        imprimir(hojaEtiquetas(items));
      },
    }],
  });
}

export async function montar(contenedor) {
  const admin = puede('productos');
  const buscar = h('input', { type: 'search', placeholder: esFarmacia() ? 'Descripción, código o %principio activo' : 'Buscar por descripción o código', autofocus: true, style: { maxWidth: '380px' } });
  const departamento = h('select', { style: { width: 'auto' } });
  const existencia = h('select', { style: { width: 'auto' }, 'aria-label': 'Existencia' },
    h('option', { value: '' }, 'Todas las existencias'),
    h('option', { value: 'con' }, 'Con existencia (1 o más)'),
    h('option', { value: 'agotados' }, 'Agotados (en 0)'));
  const bajoMinimo = h('input', { type: 'checkbox' });
  const lista = h('div');
  const paginacion = h('div.fila.fin');
  let pagina = 1;
  let ultimos = [];

  const btnEtiquetas = h('button.btn', { type: 'button', onclick: () => imprimirEtiquetas(ultimos) }, 'Etiquetas');

  async function cargarDepartamentos() {
    const actual = departamento.value;
    const deps = await api.get('/api/departamentos').catch(() => []);
    vaciar(departamento, h('option', { value: '' }, 'Todos los departamentos'), deps.map((d) => h('option', { value: d.id, selected: String(d.id) === actual }, d.nombre)));
  }

  vaciar(contenedor,
    h('div.fila.entre',
      h('h2', 'Productos'),
      h('div.fila',
        btnEtiquetas,
        admin ? [
          h('button.btn', { type: 'button', onclick: () => administrarDepartamentos(cargarDepartamentos) }, 'Departamentos'),
          h('button.btn', { type: 'button', onclick: () => importarCsv(() => cargar()) }, 'Importar Excel o CSV'),
          h('button.btn', { type: 'button', onclick: () => descargar('/api/productos/exportar') }, 'Exportar CSV'),
          h('button.btn.primario', { type: 'button', onclick: async () => { if (await formProducto()) { aviso('Producto guardado.', 'ok'); cargar(); } } }, 'Nuevo producto'),
        ] : null)),
    h('div.fila', buscar, departamento, existencia, h('label.check', bajoMinimo, 'Solo bajo el mínimo')),
    h('div', { style: { height: '.75rem' } }),
    lista,
    paginacion);

  async function cargar() {
    let r = { productos: [], total: 0 };
    try {
      r = await api.get(`/api/productos${qs({ q: buscar.value.trim(), departamento_id: departamento.value, existencia: existencia.value, bajo_minimo: bajoMinimo.checked ? 1 : '', pagina, por_pagina: POR_PAGINA })}`);
    } catch (e) {
      avisoError(e);
    }
    ultimos = r.productos;
    const columnas = [
      { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
      { titulo: 'Descripción', valor: (p) => [p.descripcion, p.tipo_venta === 'granel' ? [' ', h('span.etiqueta', 'granel')] : null, p.exento ? [' ', h('span.etiqueta', 'exento')] : null, esFarmacia() && p.principios ? h('div.ayuda.pa', p.principios) : null] },
      { titulo: 'Departamento', valor: (p) => p.departamento || '' },
      admin ? { titulo: 'Costo', valor: (p) => pesos(p.precio_costo), clase: 'num' } : null,
      { titulo: 'Precio', valor: (p) => h('b', pesos(p.precio_venta)), clase: 'num' },
      { titulo: 'Mayoreo', valor: (p) => (p.precio_mayoreo != null ? pesos(p.precio_mayoreo) : ''), clase: 'num' },
      { titulo: 'Existencia', valor: (p) => (p.usa_inventario ? h('span', { class: p.existencia <= p.minimo ? 'rojo negrita' : '' }, numero(p.existencia)) : '—'), clase: 'num' },
    ].filter(Boolean);
    vaciar(lista, tabla(columnas, ultimos, {
      vacio: 'No hay productos. Crea uno nuevo o importa tu catálogo desde Excel o CSV.',
      alClic: (p) => abrirProducto(p),
    }));
    const paginas = Math.max(1, Math.ceil(r.total / POR_PAGINA));
    vaciar(paginacion,
      h('span.suave', `${r.total} ${r.total === 1 ? 'producto' : 'productos'} · página ${pagina} de ${paginas}`),
      h('button.btn.chico', { type: 'button', disabled: pagina <= 1, onclick: () => { pagina--; cargar(); } }, '‹ Anterior'),
      h('button.btn.chico', { type: 'button', disabled: pagina >= paginas, onclick: () => { pagina++; cargar(); } }, 'Siguiente ›'));
  }

  /** La ventana de un producto: editarlo, con Kardex y Eliminar al lado (sin permiso para editar, su kardex). */
  async function abrirProducto(p) {
    if (!admin) {
      verKardex(p);
      return;
    }
    const guardado = await formProducto(p, {
      acciones: [
        { texto: 'Kardex', accion: (m) => { m.cerrar(); verKardex(p); } },
        {
          texto: 'Eliminar',
          clase: 'peligro',
          accion: async (m) => {
            if (!(await confirmar('Eliminar producto', `¿Eliminar «${p.descripcion}»?`, { aceptar: 'Eliminar', peligro: true }))) return;
            try {
              await api.del(`/api/productos/${p.id}`);
              m.cerrar();
              aviso('Producto eliminado.', 'ok');
              cargar();
            } catch (err) {
              m.error(err.message);
            }
          },
        },
      ],
    });
    if (guardado) { aviso('Producto guardado.', 'ok'); cargar(); }
  }

  /** Un código escaneado (o escrito y Enter): abre ese producto; si no existe, «Nuevo producto» con ese código. */
  async function abrirPorCodigo(codigo, nuevoSiFalta = true) {
    if (!codigo) return false;
    try {
      abrirProducto(await api.get(`/api/productos/codigo/${encodeURIComponent(codigo)}`));
      return true;
    } catch (e) {
      if (e.status !== 404) {
        avisoError(e);
        return true;
      }
      if (!nuevoSiFalta || !admin) {
        if (nuevoSiFalta) avisoError(e);
        return false;
      }
    }
    aviso(`No hay un producto con el código ${codigo}: se abre «Nuevo producto».`, '', 4000);
    const nuevo = await formProducto(null, { codigo });
    if (nuevo) { aviso('Producto guardado.', 'ok'); cargar(); }
    return true;
  }

  buscar.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    // Escrito a mano: si es el código exacto de un producto, se abre; si no, la lista ya muestra lo buscado.
    if (await abrirPorCodigo(buscar.value.trim(), false)) buscar.select();
  });

  const reiniciar = () => { pagina = 1; cargar(); };
  buscar.addEventListener('input', debounce(reiniciar));
  departamento.addEventListener('change', reiniciar);
  existencia.addEventListener('change', reiniciar);
  bajoMinimo.addEventListener('change', reiniciar);
  await cargarDepartamentos();
  await cargar();
  buscar.focus();

  return {
    /** Lo que lee el lector en Productos abre ese producto (o «Nuevo producto» si el código no existe). */
    recibirCodigo(codigo) {
      abrirPorCodigo(codigo);
    },
  };
}
