// Vademécum: principios activos, su ficha clínica y los productos que los contienen.

import { api, qs } from '../api.js';
import { ir } from '../app.js';
import { esAdmin } from '../estado.js';
import { aviso, avisoError, confirmar, debounce, formulario, h, modal, numero, pesos, tabla, vaciar } from '../ui.js';

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
      principios = await api.get(`/api/principios${qs({ q: buscar.value.trim(), con_stock: conStock.checked ? 1 : '' })}`);
    } catch (e) {
      avisoError(e);
    }
    contador.textContent = `${principios.length} principios activos`;
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
