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

async function movimiento(producto, tipo) {
  const campos = [{ nombre: 'cantidad', etiqueta: TIPOS[tipo].etiqueta, tipo: 'cantidad', requerido: true, autofocus: true }];
  if (tipo === 'entrada') {
    campos.push(
      { nombre: 'costo_unitario', etiqueta: 'Costo unitario (opcional)', tipo: 'monto', valor: producto.precio_costo },
      { nombre: 'actualizar_costo', etiqueta: 'Actualizar el costo del producto', tipo: 'check', valor: true },
      { nombre: 'referencia', etiqueta: 'Factura / guía (opcional)' },
    );
  }
  campos.push({ nombre: 'nota', etiqueta: 'Nota', tipo: 'area', ancho: true });
  return formulario({
    titulo: `${TIPOS[tipo].titulo}`,
    aceptar: 'Registrar',
    intro: h('p', h('b', producto.descripcion), ` · existencia actual: ${numero(producto.existencia)}`),
    campos,
    alEnviar: (v) => api.post('/api/inventario/movimiento', { ...v, producto_id: producto.id, tipo }),
  });
}

export async function montar(contenedor) {
  let pestana = 'ajustes';
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
    vaciar(barra, pestanas([['ajustes', 'Entradas y ajustes'], ['sugeridas', 'Compras sugeridas'], ['movimientos', 'Movimientos (kardex)']], pestana, cambiar));
    ({ ajustes: vistaAjustes, sugeridas: vistaSugeridas, movimientos: vistaMovimientos })[pestana]();
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
              if (res) { aviso(`Existencia de «${p.descripcion}»: ${numero(res.existencia)}`, 'ok'); cargar(); cargarResumen(); buscar.select(); }
            },
          }, { entrada: '+ Entrada', salida: '− Salida', ajuste: 'Ajustar' }[t]))),
        },
      ], productos, { vacio: q ? 'Sin resultados (o el producto no controla inventario).' : 'Escribe para buscar.' }));
    };
    buscar.addEventListener('input', debounce(cargar));
    buscar.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      try {
        const p = await api.get(`/api/productos/codigo/${encodeURIComponent(buscar.value.trim())}`);
        const res = await movimiento(p, 'entrada');
        if (res) { aviso(`Existencia de «${p.descripcion}»: ${numero(res.existencia)}`, 'ok'); cargarResumen(); }
        buscar.select();
      } catch {
        cargar();
      }
    });
    vaciar(zona, h('div.panel',
      h('p.suave', 'Escanea un código y presiona Enter para registrar una entrada rápida, o busca y elige el movimiento.'),
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
  cambiar(pestana);
}
