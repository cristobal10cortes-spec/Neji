// Inventario: entradas de mercadería, salidas, ajustes por conteo, compras sugeridas y movimientos.

import { api, qs } from '../api.js';
import { hojaComprasSugeridas, imprimir } from '../impresion.js';
import {
  aviso, avisoError, debounce, fecha, formulario, h, hoy, kpi, numero, pesos, pestanas, selectorFechas, tabla, vaciar,
} from '../ui.js';

const TIPOS = {
  entrada: { titulo: 'Entrada de mercadería', etiqueta: 'Cantidad que entra' },
  salida: { titulo: 'Salida (merma, consumo, vencido)', etiqueta: 'Cantidad que sale' },
  ajuste: { titulo: 'Ajuste por conteo físico', etiqueta: 'Existencia real contada' },
};

// La factura de la última entrada: los productos de una misma factura se ingresan uno tras otro, así que el
// proveedor y el número quedan escritos para el siguiente.
let ultimaFactura = { proveedor: '', factura: '' };
let nombresProveedores = null;

async function proveedores() {
  nombresProveedores ??= await api.get('/api/inventario/proveedores').catch(() => []);
  return nombresProveedores;
}

async function movimiento(producto, tipo, arriba = null) {
  const campos = [];
  let extra = null;
  let intro = [arriba, h('p', h('b', producto.descripcion), ` · existencia actual: ${numero(producto.existencia)}`)];
  if (tipo === 'entrada') {
    // Toda entrada viene con su factura: cantidad × costo se suma a esa factura en Proveedores.
    const lista = `proveedores-entrada-${Date.now()}`;
    extra = h('datalist', { id: lista }, (await proveedores()).map((n) => h('option', { value: n })));
    const misma = Boolean(ultimaFactura.proveedor && ultimaFactura.factura);
    if (misma) intro = [intro, h('p.ayuda', `Sigue en la factura N° ${ultimaFactura.factura} de ${ultimaFactura.proveedor}. Si es otra, cambia el proveedor o el número.`)];
    campos.push(
      { nombre: 'proveedor', etiqueta: 'Proveedor', valor: ultimaFactura.proveedor, requerido: true, autofocus: !misma, atributos: { list: lista } },
      { nombre: 'factura', etiqueta: 'N° de factura', valor: ultimaFactura.factura, requerido: true },
      { nombre: 'cantidad', etiqueta: TIPOS[tipo].etiqueta, tipo: 'cantidad', requerido: true, autofocus: misma },
      { nombre: 'costo_unitario', etiqueta: 'Costo unitario (con IVA)', tipo: 'monto', valor: producto.precio_costo, requerido: true, ayuda: 'Cantidad × costo se suma a la factura en Proveedores.' },
      { nombre: 'actualizar_costo', etiqueta: 'Actualizar el costo del producto', tipo: 'check', valor: true },
    );
  } else {
    campos.push({ nombre: 'cantidad', etiqueta: TIPOS[tipo].etiqueta, tipo: 'cantidad', requerido: true, autofocus: true });
  }
  campos.push({ nombre: 'nota', etiqueta: 'Nota', tipo: 'area', ancho: true });
  return formulario({
    titulo: `${TIPOS[tipo].titulo}`,
    aceptar: 'Registrar',
    intro,
    extra,
    campos,
    alEnviar: async (v) => {
      const r = await api.post('/api/inventario/movimiento', { ...v, producto_id: producto.id, tipo });
      if (r.factura) {
        ultimaFactura = { proveedor: r.factura.proveedor, factura: r.factura.numero };
        if (r.factura.proveedor_nuevo) nombresProveedores = null;
      }
      return r;
    },
  });
}

/**
 * El movimiento de un producto escaneado: parte en Entrada y arriba se cambia a Salida o Ajuste (la ventana se
 * vuelve a abrir con lo de ese movimiento). Devuelve { tipo, ...respuesta } o null.
 */
async function movimientoElegible(producto, tipo = 'entrada') {
  for (;;) {
    let otro = null;
    const opciones = h('div.metodos.movimientos', { role: 'group', 'aria-label': 'Movimiento' },
      [['entrada', '+ Entrada'], ['salida', '− Salida'], ['ajuste', 'Ajuste']].map(([t, texto]) => h('button', {
        type: 'button',
        class: t === tipo ? 'activo' : null,
        'aria-pressed': String(t === tipo),
        onclick: (e) => {
          if (t === tipo) return;
          otro = t;
          e.currentTarget.closest('.modal').querySelector('footer .btn:not(.primario)').click(); // cierra esta
        },
      }, texto)));
    const r = await movimiento(producto, tipo, opciones);
    if (otro === null) return r ? { ...r, tipo } : null;
    tipo = otro;
  }
}

/** El aviso después de un movimiento: la existencia nueva y, en una entrada, cómo va su factura. */
function avisarMovimiento(producto, r) {
  const f = r.factura;
  const enFactura = f ? ` · Factura N° ${f.numero} de ${f.proveedor}: ${pesos(f.monto)} (${f.productos === 1 ? '1 producto' : `${f.productos} productos`})` : '';
  aviso(`Existencia de «${producto.descripcion}»: ${numero(r.existencia)}${enFactura}`, 'ok', f ? 6000 : 3500);
}

export async function montar(contenedor) {
  let pestana = 'ajustes';
  let entradaDeAjustes = null; // al volver de una entrada, la pestaña «Entradas y ajustes» se pone al día
  let filtro = { desde: hoy(-7), hasta: hoy() };
  const resumen = h('div.kpis');
  const zona = h('div');
  const barra = h('div');

  vaciar(contenedor, h('h2', 'Inventario'), resumen, barra, zona);

  async function cargarResumen() {
    try {
      const r = await api.get('/api/inventario/resumen');
      vaciar(resumen,
        kpi('Valor a costo', pesos(r.valor_costo), true),
        kpi('Valor a precio de venta', pesos(r.valor_venta)),
        kpi('Productos', numero(r.productos)),
        kpi('Bajo el mínimo', numero(r.bajo_minimo)),
        kpi('Agotados', numero(r.agotados)));
    } catch (e) {
      avisoError(e);
    }
  }

  function cambiar(p) {
    pestana = p;
    vaciar(barra, pestanas([['ajustes', 'Entradas y ajustes'], ['sugeridas', 'Compras sugeridas'], ['vencimientos', 'Vencimientos'], ['movimientos', 'Movimientos (kardex)']], pestana, cambiar));
    ({ ajustes: vistaAjustes, sugeridas: vistaSugeridas, vencimientos: vistaVencimientos, movimientos: vistaMovimientos })[pestana]();
  }

  function vistaAjustes() {
    const buscar = h('input', { type: 'search', placeholder: 'Escanea o busca el producto', autofocus: true, style: { maxWidth: '420px' } });
    const lista = h('div');
    const cargar = async () => {
      const q = buscar.value.trim();
      const r = await api.get(`/api/productos${qs({ q, por_pagina: 30 })}`).catch(() => ({ productos: [] }));
      const productos = r.productos.filter((p) => p.usa_inventario);
      vaciar(lista, tabla([
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Producto', valor: (p) => p.descripcion },
        { titulo: 'Existencia', valor: (p) => h('b', { class: p.existencia <= p.minimo ? 'rojo' : '' }, numero(p.existencia)), clase: 'num' },
        { titulo: 'Mín.', valor: (p) => numero(p.minimo), clase: 'num' },
        {
          titulo: '',
          valor: (p) => h('div.fila.fin', ['entrada', 'salida', 'ajuste'].map((t) => h('button.btn.chico', {
            type: 'button',
            class: t === 'entrada' ? 'primario' : null,
            onclick: async () => {
              const res = await movimiento(p, t);
              if (res) { avisarMovimiento(p, res); cargar(); cargarResumen(); buscar.select(); }
            },
          }, { entrada: '+ Entrada', salida: '− Salida', ajuste: 'Ajustar' }[t]))),
        },
      ], productos, { vacio: q ? 'Sin resultados (o el producto no controla inventario).' : 'Escribe para buscar.' }));
    };
    buscar.addEventListener('input', debounce(cargar));
    buscar.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (!(await entradaPorCodigo(buscar.value.trim(), false))) cargar();
    });
    entradaDeAjustes = async () => { cargar(); buscar.select(); };
    vaciar(zona, h('div.panel',
      h('p.suave', 'Escanea un producto y se abre su entrada de mercadería, con el proveedor y el N° de factura. También puedes buscarlo y elegir el movimiento.'),
      buscar, h('div', { style: { height: '.75rem' } }), lista));
    buscar.focus();
    cargar();
  }

  async function vistaSugeridas() {
    let productos = [];
    try {
      productos = await api.get('/api/inventario/sugeridos');
    } catch (e) {
      avisoError(e);
    }
    const total = productos.reduce((s, p) => s + p.costo_estimado, 0);
    vaciar(zona, h('div.panel',
      h('div.fila.entre',
        h('p', 'Productos en o bajo su mínimo. La cantidad sugerida llega al máximo o, si no tiene, al doble del mínimo o a lo vendido en 30 días.'),
        h('button.btn', { type: 'button', disabled: !productos.length, onclick: () => imprimir(hojaComprasSugeridas(productos)) }, 'Imprimir lista')),
      tabla([
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Producto', valor: (p) => p.descripcion },
        { titulo: 'Departamento', valor: (p) => p.departamento || '' },
        { titulo: 'Existencia', valor: (p) => h('span.rojo', numero(p.existencia)), clase: 'num' },
        { titulo: 'Mínimo', valor: (p) => numero(p.minimo), clase: 'num' },
        { titulo: 'Vendido 30 días', valor: (p) => numero(p.vendidos_30d), clase: 'num' },
        { titulo: 'Comprar', valor: (p) => h('b', numero(p.sugerido)), clase: 'num' },
        { titulo: 'Costo est.', valor: (p) => pesos(p.costo_estimado), clase: 'num' },
      ], productos, { vacio: '¡Todo en orden! No hay productos bajo el mínimo.', pie: productos.length ? [{ valor: 'Total estimado', colspan: 7 }, { valor: pesos(total), clase: 'num' }] : null })));
  }

  async function vistaVencimientos() {
    const dias = h('select', { style: { width: 'auto' } },
      [['30', 'Próximos 30 días'], ['90', 'Próximos 90 días'], ['180', 'Próximos 6 meses'], ['3650', 'Todos']]
        .map(([v, t]) => h('option', { value: v, selected: v === '90' }, t)));
    const conStock = h('input', { type: 'checkbox', checked: true });
    const lista = h('div');
    const cargar = async () => {
      let productos = [];
      try {
        productos = await api.get(`/api/inventario/vencimientos${qs({ dias: dias.value, con_stock: conStock.checked ? 1 : 0 })}`);
      } catch (e) {
        avisoError(e);
      }
      vaciar(lista, tabla([
        { titulo: 'Vence', valor: (p) => fecha(p.vencimiento, false) },
        { titulo: 'Días', valor: (p) => h('b', { class: p.dias_restantes < 30 ? 'rojo' : p.dias_restantes < 90 ? '' : 'verde' }, p.dias_restantes < 0 ? `vencido hace ${-p.dias_restantes}` : String(p.dias_restantes)), clase: 'num' },
        { titulo: 'Código', valor: (p) => h('span.mono', p.codigo) },
        { titulo: 'Producto', valor: (p) => p.descripcion },
        { titulo: 'Proveedor', valor: (p) => p.proveedor || '' },
        { titulo: 'Existencia', valor: (p) => (p.usa_inventario ? numero(p.existencia) : '—'), clase: 'num' },
      ], productos, { vacio: 'No hay productos por vencer en este período.' }));
    };
    dias.addEventListener('change', cargar);
    conStock.addEventListener('change', cargar);
    vaciar(zona, h('div.panel',
      h('div.fila', dias, h('label.check', conStock, 'Solo con existencia'),
        h('span.ayuda', 'La fecha de vencimiento se ingresa en la ficha de cada producto.')),
      h('div', { style: { height: '.75rem' } }), lista));
    cargar();
  }

  async function vistaMovimientos() {
    const tipo = h('select', { style: { width: 'auto' } },
      [['', 'Todos'], ['venta', 'Ventas'], ['devolucion', 'Devoluciones'], ['entrada', 'Entradas'], ['salida', 'Salidas'], ['ajuste', 'Ajustes'], ['inicial', 'Iniciales']]
        .map(([v, t]) => h('option', { value: v }, t)));
    const lista = h('div');
    const cargar = async () => {
      let movs = [];
      try {
        movs = await api.get(`/api/inventario/movimientos${qs({ ...filtro, tipo: tipo.value })}`);
      } catch (e) {
        avisoError(e);
      }
      vaciar(lista, tabla([
        { titulo: 'Fecha', valor: (m) => fecha(m.fecha) },
        { titulo: 'Producto', valor: (m) => m.descripcion },
        { titulo: 'Tipo', valor: (m) => h('span.etiqueta', m.tipo) },
        { titulo: 'Referencia', valor: (m) => [m.referencia, m.nota].filter(Boolean).join(' · ') },
        { titulo: 'Usuario', valor: (m) => m.usuario || '' },
        { titulo: 'Cantidad', valor: (m) => h('span', { class: m.cantidad < 0 ? 'rojo' : 'verde' }, (m.cantidad > 0 ? '+' : '') + numero(m.cantidad)), clase: 'num' },
        { titulo: 'Queda', valor: (m) => numero(m.existencia_nueva), clase: 'num' },
      ], movs, { vacio: 'Sin movimientos en estas fechas.' }));
    };
    tipo.addEventListener('change', cargar);
    vaciar(zona, h('div.panel', h('div.fila', selectorFechas(filtro, (f) => { filtro = f; cargar(); }), tipo), h('div', { style: { height: '.75rem' } }), lista));
    cargar();
  }

  await cargarResumen();
  /**
   * Entrada de mercadería del producto con ese código (lo escaneado o escrito y Enter). Devuelve false si no hay
   * un producto con ese código (con `avisar`, lo dice).
   */
  async function entradaPorCodigo(codigo, avisar = true) {
    if (!codigo) return false;
    let p;
    try {
      p = await api.get(`/api/productos/codigo/${encodeURIComponent(codigo)}`);
    } catch (e) {
      if (avisar) avisoError(e);
      return false;
    }
    if (!p.usa_inventario) {
      aviso(`«${p.descripcion}» no lleva control de inventario.`, 'error');
      return true;
    }
    const res = await movimientoElegible(p, 'entrada');
    if (res) {
      avisarMovimiento(p, res);
      cargarResumen();
      if (pestana === 'ajustes') await entradaDeAjustes?.();
    }
    return true;
  }

  cambiar(pestana);

  return {
    /** Lo que lee el lector en Inventario (en cualquier pestaña o campo) abre la entrada de ese producto. */
    recibirCodigo(codigo) {
      if (pestana !== 'ajustes') cambiar('ajustes');
      entradaPorCodigo(codigo);
    },
  };
}
