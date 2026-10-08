// Catálogo de productos: alta, edición, departamentos, CSV, kardex y etiquetas.

import { api, descargar, qs } from '../api.js';
import { esAdmin, esFarmacia } from '../estado.js';
import { hojaEtiquetas, imprimir } from '../impresion.js';
import {
  aviso, avisoError, confirmar, debounce, fecha, formulario, h, leerCantidad, leerMonto, modal, numero, pesos, tabla, vaciar,
} from '../ui.js';

const POR_PAGINA = 50;

/** Alta o edición de producto. Devuelve el producto guardado o null. */
export async function formProducto(producto = null) {
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
    { nombre: 'codigo', etiqueta: 'Código de barras', valor: producto?.codigo, requerido: true, autofocus: true },
    { nombre: 'descripcion', etiqueta: 'Descripción', valor: producto?.descripcion, requerido: true },
    { nombre: 'departamento', etiqueta: 'Departamento', valor: producto?.departamento, atributos: { list: 'lista-departamentos' }, placeholder: 'Ej: Bebidas' },
    { nombre: 'tipo_venta', etiqueta: 'Se vende por', tipo: 'select', valor: producto?.tipo_venta || 'unidad', opciones: [['unidad', 'Unidad / pieza'], ['granel', 'Granel (kg, litro, metro)']] },
    farmacia ? { nombre: 'principios', etiqueta: 'Principio(s) activo(s)', valor: producto?.principios, ancho: true, placeholder: 'Ej: PARACETAMOL 500 mg + CAFEINA 65 mg', atributos: { list: 'lista-principios' }, ayuda: 'Separa con + si tiene varios. Quedan unidos al vademécum y permiten buscar con %.' } : null,
    { nombre: 'precio_costo', etiqueta: 'Precio de costo', tipo: 'monto', valor: producto?.precio_costo ?? '' },
    { nombre: 'margen', etiqueta: '% de ganancia', tipo: 'cantidad', valor: margen, ayuda: 'Calcula el precio de venta desde el costo' },
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
    campos: campos.filter(Boolean),
    extra: listaDeps,
    alMostrar: (e) => {
      const generar = h('button.btn.chico', { type: 'button' }, 'Generar código interno');
      generar.addEventListener('click', async () => {
        try { e.codigo.value = (await api.get('/api/productos/siguiente-codigo')).codigo; } catch (err) { avisoError(err); }
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
      e.margen.addEventListener('input', desdeMargen);
      e.precio_costo.addEventListener('input', () => (e.margen.value ? desdeMargen() : haciaMargen()));
      e.precio_venta.addEventListener('input', haciaMargen);
    },
    alEnviar: (v) => {
      delete v.margen;
      return producto ? api.put(`/api/productos/${producto.id}`, v) : api.post('/api/productos', v);
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

async function importarCsv() {
  const archivo = h('input', { type: 'file', accept: '.csv,text/csv' });
  const resultado = h('div');
  modal({
    titulo: 'Importar productos desde CSV',
    ancho: 'ancho',
    cuerpo: [
      h('p', 'Sirve para traer tu catálogo desde Excel, eleventa u otro sistema. Guarda la planilla como CSV (separado por punto y coma o coma).'),
      h('p.ayuda', 'Columnas reconocidas: codigo, descripcion, precio_venta, precio_costo, precio_mayoreo, cantidad_mayoreo, departamento, tipo_venta (unidad/granel), existencia, minimo, maximo, usa_inventario (si/no), exento (si/no), principio_activo, proveedor y vencimiento. También entiende nombres como "Código", "Precio Venta", "Costo", "Stock", "Categoría", "Distribuidor" o "Principio Activo".'),
      h('p.ayuda', 'Si el código ya existe, el producto se actualiza con las columnas que traigan datos.'),
      archivo, resultado,
    ],
    botones: [
      { texto: 'Cerrar', accion: (m) => m.cerrar() },
      {
        texto: 'Importar',
        clase: 'primario',
        accion: async (m) => {
          if (!archivo.files[0]) return m.error('Elige un archivo.');
          const datos = new FormData();
          datos.append('archivo', archivo.files[0]);
          m.error('');
          try {
            const r = await api.subir('/api/productos/importar', datos);
            vaciar(resultado, h('div.panel',
              h('p', h('b', `${r.creados} creados, ${r.actualizados} actualizados.`)),
              r.errores.length ? [h('p.rojo', `${r.errores.length} filas con problemas:`),
                h('ul', r.errores.map((e) => h('li', `Fila ${e.fila}: ${e.error}`)))] : null));
          } catch (err) {
            m.error(err.message);
          }
        },
      },
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

function imprimirEtiquetas(productos) {
  const copias = new Map(productos.map((p) => [p.id, h('input', { type: 'number', min: '0', max: '200', value: '1', style: { width: '90px' } })]));
  modal({
    titulo: 'Imprimir etiquetas con código de barras',
    ancho: 'ancho',
    cuerpo: [
      h('p.ayuda', 'Etiquetas de 50 × 30 mm con descripción, precio y código de barras (Code 128).'),
      tabla([
        { titulo: 'Producto', valor: (p) => p.descripcion },
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Precio', valor: (p) => pesos(p.precio_venta), clase: 'num' },
        { titulo: 'Copias', valor: (p) => copias.get(p.id) },
      ], productos),
    ],
    botones: [{
      texto: 'Imprimir',
      clase: 'primario',
      accion: (m) => {
        const items = productos.map((p) => ({ producto: p, copias: Math.min(parseInt(copias.get(p.id).value, 10) || 0, 200) })).filter((i) => i.copias > 0);
        if (!items.length) return m.error('Indica al menos una copia.');
        imprimir(hojaEtiquetas(items));
      },
    }],
  });
}

export async function montar(contenedor) {
  const admin = esAdmin();
  const buscar = h('input', { type: 'search', placeholder: esFarmacia() ? 'Descripción, código o %principio activo' : 'Buscar por descripción o código', autofocus: true, style: { maxWidth: '380px' } });
  const departamento = h('select', { style: { width: 'auto' } });
  const bajoMinimo = h('input', { type: 'checkbox' });
  const lista = h('div');
  const paginacion = h('div.fila.fin');
  const seleccionados = new Map();
  let pagina = 1;
  let ultimos = [];

  const btnEtiquetas = h('button.btn', { type: 'button', onclick: () => imprimirEtiquetas([...seleccionados.values()]) }, 'Etiquetas (0)');

  async function cargarDepartamentos() {
    const actual = departamento.value;
    const deps = await api.get('/api/departamentos').catch(() => []);
    vaciar(departamento, h('option', { value: '' }, 'Todos los departamentos'), deps.map((d) => h('option', { value: d.id, selected: String(d.id) === actual }, d.nombre)));
  }

  function actualizarSeleccion() {
    btnEtiquetas.textContent = `Etiquetas (${seleccionados.size})`;
    btnEtiquetas.disabled = seleccionados.size === 0;
  }

  vaciar(contenedor,
    h('div.fila.entre',
      h('h2', 'Productos'),
      h('div.fila',
        btnEtiquetas,
        admin ? [
          h('button.btn', { type: 'button', onclick: () => administrarDepartamentos(cargarDepartamentos) }, 'Departamentos'),
          h('button.btn', { type: 'button', onclick: async () => { await importarCsv(); } }, 'Importar CSV'),
          h('button.btn', { type: 'button', onclick: () => descargar('/api/productos/exportar') }, 'Exportar CSV'),
          h('button.btn.primario', { type: 'button', onclick: async () => { if (await formProducto()) { aviso('Producto guardado.', 'ok'); cargar(); } } }, 'Nuevo producto'),
        ] : null)),
    h('div.fila', buscar, departamento, h('label.check', bajoMinimo, 'Solo bajo el mínimo')),
    h('div', { style: { height: '.75rem' } }),
    lista,
    paginacion);

  async function cargar() {
    let r = { productos: [], total: 0 };
    try {
      r = await api.get(`/api/productos${qs({ q: buscar.value.trim(), departamento_id: departamento.value, bajo_minimo: bajoMinimo.checked ? 1 : '', pagina, por_pagina: POR_PAGINA })}`);
    } catch (e) {
      avisoError(e);
    }
    ultimos = r.productos;
    const columnas = [
      {
        titulo: '',
        valor: (p) => h('input', {
          type: 'checkbox',
          checked: seleccionados.has(p.id),
          'aria-label': 'Seleccionar para etiquetas',
          onclick: (e) => e.stopPropagation(),
          onchange: (e) => { if (e.target.checked) seleccionados.set(p.id, p); else seleccionados.delete(p.id); actualizarSeleccion(); },
        }),
      },
      { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
      { titulo: 'Descripción', valor: (p) => [p.descripcion, p.tipo_venta === 'granel' ? h('span.etiqueta', ' granel') : null, p.exento ? h('span.etiqueta', ' exento') : null, esFarmacia() && p.principios ? h('div.ayuda.pa', p.principios) : null] },
      { titulo: 'Departamento', valor: (p) => p.departamento || '' },
      admin ? { titulo: 'Costo', valor: (p) => pesos(p.precio_costo), clase: 'num' } : null,
      { titulo: 'Precio', valor: (p) => h('b', pesos(p.precio_venta)), clase: 'num' },
      { titulo: 'Mayoreo', valor: (p) => (p.precio_mayoreo != null ? pesos(p.precio_mayoreo) : ''), clase: 'num' },
      { titulo: 'Existencia', valor: (p) => (p.usa_inventario ? h('span', { class: p.existencia <= p.minimo ? 'rojo negrita' : '' }, numero(p.existencia)) : '—'), clase: 'num' },
      {
        titulo: '',
        valor: (p) => h('div.fila.fin',
          h('button.btn.chico', { type: 'button', onclick: (e) => { e.stopPropagation(); verKardex(p); } }, 'Kardex'),
          admin ? h('button.btn.chico.peligro', {
            type: 'button',
            onclick: async (e) => {
              e.stopPropagation();
              if (!(await confirmar('Eliminar producto', `¿Eliminar «${p.descripcion}»?`, { aceptar: 'Eliminar', peligro: true }))) return;
              try { await api.del(`/api/productos/${p.id}`); seleccionados.delete(p.id); actualizarSeleccion(); cargar(); } catch (err) { avisoError(err); }
            },
          }, 'Eliminar') : null),
      },
    ].filter(Boolean);
    vaciar(lista, tabla(columnas, ultimos, {
      vacio: 'No hay productos. Crea uno nuevo o importa tu catálogo desde CSV.',
      alClic: admin ? async (p) => { if (await formProducto(p)) { aviso('Producto guardado.', 'ok'); cargar(); } } : null,
    }));
    const paginas = Math.max(1, Math.ceil(r.total / POR_PAGINA));
    vaciar(paginacion,
      h('span.suave', `${r.total} productos · página ${pagina} de ${paginas}`),
      h('button.btn.chico', { type: 'button', disabled: pagina <= 1, onclick: () => { pagina--; cargar(); } }, '‹ Anterior'),
      h('button.btn.chico', { type: 'button', disabled: pagina >= paginas, onclick: () => { pagina++; cargar(); } }, 'Siguiente ›'));
  }

  const reiniciar = () => { pagina = 1; cargar(); };
  buscar.addEventListener('input', debounce(reiniciar));
  departamento.addEventListener('change', reiniciar);
  bajoMinimo.addEventListener('change', reiniciar);
  actualizarSeleccion();
  await cargarDepartamentos();
  await cargar();
  buscar.focus();
}
