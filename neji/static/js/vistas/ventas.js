// Pantalla de ventas, pensada para usarse solo con teclado (al estilo eleventa).

import { api } from '../api.js';
import { estado, guardarTickets, leerTickets, nuevoTicket, opcion, puede } from '../estado.js';
import { imprimir, ticketCotizacion, ticketVenta } from '../impresion.js';
import {
  aviso, avisoError, confirmar, formulario, h, importe, leerMonto, modal, numero, pesos, pitido,
  redondeoEfectivo, vaciar,
} from '../ui.js';
import { elegirCliente } from './clientes.js';
import { abrirTurno, movimientoCaja } from './caja.js';

const METODOS = [
  ['efectivo', 'Efectivo', 'F1'],
  ['debito', 'Débito', 'F2'],
  ['credito', 'Crédito', 'F3'],
  ['transferencia', 'Transferencia', 'F4'],
  ['fiado', 'Fiado', 'F5'],
  ['mixto', 'Mixto', 'F6'],
];

export function precioLinea(item) {
  if (item.tipo_precio === 'comun' || item.tipo_precio === 'manual') return { precio: item.precio, tipo: item.tipo_precio };
  const p = item.producto;
  if (item.tipo_precio === 'mayoreo' && p.precio_mayoreo != null) return { precio: p.precio_mayoreo, tipo: 'mayoreo' };
  if (p.precio_mayoreo != null && p.cantidad_mayoreo && item.cantidad >= p.cantidad_mayoreo) return { precio: p.precio_mayoreo, tipo: 'mayoreo' };
  return { precio: p.precio_venta, tipo: 'normal' };
}

export function totalesTicket(t) {
  const subtotal = t.items.reduce((s, it) => s + importe(it.cantidad, precioLinea(it).precio), 0);
  const articulos = t.items.reduce((s, it) => s + (it.producto?.tipo_venta === 'granel' ? 1 : it.cantidad), 0);
  return { subtotal, descuento: t.descuento || 0, total: subtotal - (t.descuento || 0), articulos };
}

/** Líneas como las espera la API (el servidor recalcula los precios). */
export function itemsParaApi(t) {
  return t.items.map((it) => {
    if (it.tipo_precio === 'comun') return { descripcion: it.descripcion, cantidad: it.cantidad, precio: it.precio, tipo_precio: 'comun' };
    const linea = { producto_id: it.producto.id, cantidad: it.cantidad, tipo_precio: it.tipo_precio };
    if (it.tipo_precio === 'manual') linea.precio = it.precio;
    return linea;
  });
}

function snapshot(p) {
  const { id, codigo, descripcion, precio_venta, precio_mayoreo, cantidad_mayoreo, tipo_venta, existencia, usa_inventario, departamento } = p;
  return { id, codigo, descripcion, precio_venta, precio_mayoreo, cantidad_mayoreo, tipo_venta, existencia, usa_inventario, departamento };
}

export async function montar(contenedor, parametros = {}) {
  let tickets = leerTickets();
  let turnoAbierto = null;
  const actual = () => tickets.lista[tickets.activo];

  // --- Elementos ---------------------------------------------------------------
  const codigo = h('input', { placeholder: 'Código de barras (o 3*código) + Enter', autocomplete: 'off', 'aria-label': 'Código del producto' });
  const avisoTurno = h('div.panel.oculto', { style: { background: '#fff7e0', borderColor: '#f3d27a' } });
  const pestanasTickets = h('div.tickets');
  const cuerpoTabla = h('tbody');
  const lblCliente = h('span');
  const lblArticulos = h('div.suave');
  const lblTotal = h('div.monto', '$0');
  const lblDescuento = h('div.suave');

  const boton = (tecla, texto, accion, extra = {}) =>
    h('button.btn', { type: 'button', onclick: () => { accion(); }, ...extra }, tecla ? h('kbd', tecla) : null, texto);

  vaciar(contenedor, h('div.ventas',
    avisoTurno,
    h('div.captura',
      h('div.codigo', codigo, boton('', 'Agregar', () => procesarCodigo(), { class: 'primario' })),
      h('div.atajos',
        boton('INS', 'Varios', varios),
        boton('Ctrl+P', 'Art. común', articuloComun),
        boton('F10', 'Buscar', buscarProducto),
        boton('F11', 'Mayoreo', alternarMayoreo, { title: 'También Ctrl+M' }),
        boton('F9', 'Verificador', verificador),
        boton('F7', 'Entrada', () => movimiento('entrada')),
        boton('F8', 'Salida', () => movimiento('salida')))),
    h('div.fila.entre', pestanasTickets,
      h('div.fila', boton('F6', 'Nuevo ticket', nuevo), boton('', 'Cancelar ticket', cancelarTicket, { class: 'peligro' }))),
    h('div.tabla-caja.ticket-tabla', h('table',
      h('thead', h('tr',
        h('th', '#'), h('th', 'Código'), h('th', 'Descripción'), h('th.num', 'Precio'), h('th.num', 'Cant.'),
        h('th.num', 'Importe'), h('th.num.ocultar-movil', 'Existencia'))),
      cuerpoTabla)),
    h('div.pie-venta',
      h('div.atajos',
        boton('Supr', 'Borrar', borrarLinea),
        boton('*', 'Cantidad', editarCantidad),
        boton('Ctrl+D', 'Descuento', descuento),
        boton('', 'Precio', cambiarPrecio),
        boton('F5', 'Cliente', asignarCliente),
        boton('', 'Cotizar', guardarCotizacion)),
      h('div.cliente-ticket', lblCliente),
      h('div.total-grande', lblArticulos, lblDescuento, h('div.etq', 'Total'), lblTotal),
      h('button.btn.primario.grande', { type: 'button', onclick: cobrar }, h('kbd', 'F12'), 'Cobrar'))));

  codigo.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      procesarCodigo();
    }
  });

  // --- Dibujo ------------------------------------------------------------------
  function guardar() {
    guardarTickets(tickets);
  }

  function enfocar() {
    if (!document.querySelector('.fondo-modal')) codigo.focus();
  }

  function dibujar() {
    const t = actual();
    vaciar(pestanasTickets, tickets.lista.map((tk, i) => {
      const tot = totalesTicket(tk).total;
      return h('button', { type: 'button', class: i === tickets.activo ? 'activo' : null, onclick: () => { cambiarA(i); } },
        `Ticket ${tk.numero}`, tk.items.length ? h('span.suave', ` · ${pesos(tot)}`) : null);
    }));

    if (!t.items.length) {
      vaciar(cuerpoTabla, h('tr', h('td.vacio', { colspan: 7 }, 'Escanea un producto o presiona F10 para buscar.')));
    } else {
      vaciar(cuerpoTabla, t.items.map((it, i) => {
        const { precio, tipo } = precioLinea(it);
        const p = it.producto;
        const sinStock = p && p.usa_inventario && p.existencia - it.cantidad < 0;
        return h('tr', {
          class: i === t.sel ? 'sel' : null,
          onclick: () => { t.sel = i; dibujar(); enfocar(); },
          ondblclick: () => { t.sel = i; editarCantidad(); },
        },
        h('td.suave', i + 1),
        h('td.mono', p?.codigo || '—'),
        h('td.desc', it.descripcion || p.descripcion, ' ',
          tipo === 'mayoreo' ? h('span.etiqueta.aviso', 'mayoreo') : null,
          tipo === 'manual' ? h('span.etiqueta.aviso', 'precio manual') : null,
          tipo === 'comun' ? h('span.etiqueta', 'común') : null),
        h('td.num', pesos(precio)),
        h('td.num.cant', numero(it.cantidad), p?.tipo_venta === 'granel' ? ' kg' : ''),
        h('td.num.negrita', pesos(importe(it.cantidad, precio))),
        h('td.num.ocultar-movil', { class: sinStock ? 'rojo' : 'suave' }, p?.usa_inventario ? numero(p.existencia) : '—'));
      }));
      cuerpoTabla.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
    }

    const tot = totalesTicket(t);
    lblTotal.textContent = pesos(tot.total);
    lblArticulos.textContent = `${numero(tot.articulos)} artículo${tot.articulos === 1 ? '' : 's'}`;
    lblDescuento.textContent = tot.descuento ? `Subtotal ${pesos(tot.subtotal)} · Descuento -${pesos(tot.descuento)}` : '';
    vaciar(lblCliente, t.cliente
      ? [h('span.etiqueta.ok', 'Cliente'), ` ${t.cliente.nombre}`, t.cliente.saldo ? h('span.suave', ` (debe ${pesos(t.cliente.saldo)})`) : null,
        h('button.btn.chico', { type: 'button', onclick: () => { t.cliente = null; guardar(); dibujar(); } }, 'Quitar')]
      : t.cotizacionId ? h('span.etiqueta', `Desde cotización`) : '');
    guardar();
  }

  function cambiarA(i) {
    tickets.activo = (i + tickets.lista.length) % tickets.lista.length;
    dibujar();
    enfocar();
  }

  // --- Turno ---------------------------------------------------------------------
  async function revisarTurno() {
    try {
      turnoAbierto = (await api.get(`/api/caja/${estado.cajaId}/turno`)).turno;
    } catch (e) {
      avisoError(e);
      return;
    }
    avisoTurno.classList.toggle('oculto', Boolean(turnoAbierto));
    vaciar(avisoTurno, h('div.fila.entre',
      h('span', h('b', 'La caja está cerrada. '), 'Abre el turno indicando con cuánto dinero inicia la caja.'),
      h('button.btn.primario', { type: 'button', onclick: pedirAbrirTurno }, 'Abrir caja')));
  }

  async function pedirAbrirTurno() {
    const t = await abrirTurno();
    if (t) {
      turnoAbierto = t;
      avisoTurno.classList.add('oculto');
    }
    enfocar();
    return t;
  }

  // --- Agregar productos -------------------------------------------------------------
  function agregarProducto(producto, cantidad = 1) {
    const t = actual();
    const p = snapshot(producto);
    if (!Number.isFinite(cantidad) || cantidad <= 0) {
      aviso('Cantidad no válida.', 'error');
      return;
    }
    if (p.tipo_venta === 'unidad' && !Number.isInteger(cantidad)) {
      aviso(`«${p.descripcion}» se vende por unidad.`, 'error');
      return;
    }
    const existente = p.tipo_venta === 'unidad'
      ? t.items.findIndex((it) => it.producto?.id === p.id && (it.tipo_precio === 'normal' || it.tipo_precio === 'mayoreo'))
      : -1;
    const enTicket = t.items.filter((it) => it.producto?.id === p.id).reduce((s, it) => s + it.cantidad, 0);
    if (p.usa_inventario && !opcion('permitir_stock_negativo') && enTicket + cantidad > p.existencia) {
      pitido();
      aviso(`No hay existencia suficiente de «${p.descripcion}» (hay ${numero(p.existencia)}).`, 'error', 5000);
      return;
    }
    if (existente >= 0) {
      t.items[existente].cantidad = Math.round((t.items[existente].cantidad + cantidad) * 1000) / 1000;
      t.items[existente].producto = p;
      t.sel = existente;
    } else {
      t.items.push({ producto: p, cantidad, tipo_precio: 'normal' });
      t.sel = t.items.length - 1;
    }
    dibujar();
  }

  async function pedirCantidad(producto, titulo) {
    const granel = producto.tipo_venta === 'granel';
    const r = await formulario({
      titulo: titulo || producto.descripcion,
      aceptar: 'Agregar',
      intro: h('p', `${pesos(producto.precio_venta)}${granel ? ' por kg' : ''}`),
      campos: [{ nombre: 'cantidad', etiqueta: granel ? 'Peso o cantidad (ej: 0,755)' : 'Cantidad', tipo: 'cantidad', valor: granel ? '' : '1', requerido: true, autofocus: true }],
    });
    return r ? r.cantidad : null;
  }

  async function procesarCodigo() {
    let texto = codigo.value.trim();
    if (!texto) return;
    let cantidad = null;
    const m = texto.match(/^(\d+(?:[.,]\d+)?)\s*\*\s*(.+)$/);
    if (m) {
      cantidad = parseFloat(m[1].replace(',', '.'));
      texto = m[2].trim();
    }
    codigo.value = '';
    let producto;
    try {
      producto = await api.get(`/api/productos/codigo/${encodeURIComponent(texto)}`);
    } catch (e) {
      pitido();
      avisoError(e);
      enfocar();
      return;
    }
    if (cantidad === null && producto.tipo_venta === 'granel') {
      cantidad = await pedirCantidad(producto);
      if (cantidad === null) { enfocar(); return; }
    }
    agregarProducto(producto, cantidad ?? 1);
    enfocar();
  }

  async function varios() {
    const r = await formulario({
      titulo: 'Agregar varios',
      aceptar: 'Agregar',
      campos: [
        { nombre: 'cantidad', etiqueta: 'Cantidad', tipo: 'cantidad', valor: '1', requerido: true, autofocus: true },
        { nombre: 'codigo', etiqueta: 'Código del producto', requerido: true },
      ],
      alEnviar: async (v) => ({ producto: await api.get(`/api/productos/codigo/${encodeURIComponent(v.codigo)}`), cantidad: v.cantidad }),
    });
    if (r) agregarProducto(r.producto, r.cantidad);
    enfocar();
  }

  async function articuloComun() {
    const r = await formulario({
      titulo: 'Artículo común (sin registrar)',
      aceptar: 'Agregar',
      campos: [
        { nombre: 'descripcion', etiqueta: 'Descripción', valor: 'Artículo común', autofocus: true },
        { nombre: 'precio', etiqueta: 'Precio unitario', tipo: 'monto', requerido: true },
        { nombre: 'cantidad', etiqueta: 'Cantidad', tipo: 'cantidad', valor: '1', requerido: true },
      ],
      alEnviar: (v) => {
        if (!(v.precio > 0)) throw new Error('El precio debe ser mayor que cero.');
        if (!(v.cantidad > 0)) throw new Error('La cantidad debe ser mayor que cero.');
      },
    });
    if (r) {
      const t = actual();
      t.items.push({ producto: null, descripcion: r.descripcion || 'Artículo común', precio: r.precio, cantidad: r.cantidad, tipo_precio: 'comun' });
      t.sel = t.items.length - 1;
      dibujar();
    }
    enfocar();
  }

  function buscarProducto() {
    return new Promise((resolver) => {
      const entrada = h('input', { placeholder: 'Escribe parte de la descripción o del código', autocomplete: 'off', autofocus: true });
      const lista = h('div.lista-busqueda');
      let resultados = [];
      let sel = 0;
      let elegido = null;
      let consulta = 0;

      const pintar = () => {
        vaciar(lista, resultados.length
          ? h('table', h('tbody', resultados.map((p, i) => h('tr.clic', {
            class: i === sel ? 'sel' : null,
            onclick: () => { sel = i; elegir(); },
          },
          h('td.mono', p.codigo), h('td', p.descripcion, p.departamento ? h('span.suave', ` · ${p.departamento}`) : null),
          h('td.num', pesos(p.precio_venta)),
          h('td.num', { class: p.usa_inventario && p.existencia <= 0 ? 'rojo' : 'suave' }, p.usa_inventario ? numero(p.existencia) : '—')))))
          : h('p.vacio', entrada.value ? 'Sin resultados.' : 'Escribe para buscar.'));
        lista.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
      };
      const cargar = async () => {
        const n = ++consulta;
        const q = entrada.value.trim();
        const r = q ? await api.get(`/api/productos?q=${encodeURIComponent(q)}&por_pagina=60`).catch(() => ({ productos: [] })) : { productos: [] };
        if (n !== consulta) return;
        resultados = r.productos;
        sel = 0;
        pintar();
      };
      let espera;
      entrada.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(cargar, 180); });

      const m = modal({
        titulo: 'Buscar producto',
        ancho: 'ancho',
        cuerpo: [entrada, h('p.ayuda', '↑ ↓ para moverte, Enter para agregar, Esc para cerrar.'), lista],
        alCerrar: () => resolver(elegido),
        alTeclear: (e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, resultados.length - 1); pintar(); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); pintar(); }
          else if (e.key === 'Enter') { e.preventDefault(); elegir(); }
        },
      });
      function elegir() {
        if (!resultados[sel]) return;
        elegido = resultados[sel];
        m.cerrar();
      }
      pintar();
    }).then(async (producto) => {
      if (producto) {
        let cantidad = 1;
        if (producto.tipo_venta === 'granel') cantidad = await pedirCantidad(producto);
        if (cantidad !== null) agregarProducto(producto, cantidad);
      }
      enfocar();
    });
  }

  async function verificador() {
    await formulario({
      titulo: 'Verificador de precios',
      aceptar: 'Consultar',
      campos: [{ nombre: 'codigo', etiqueta: 'Código', requerido: true, autofocus: true }],
      alEnviar: async (v) => {
        const p = await api.get(`/api/productos/codigo/${encodeURIComponent(v.codigo)}`);
        modal({
          titulo: p.descripcion,
          cuerpo: h('div',
            h('div.cobro-total', h('div.monto', pesos(p.precio_venta)), p.tipo_venta === 'granel' ? h('div', 'por kg') : null),
            p.precio_mayoreo != null ? h('p', `Mayoreo: ${pesos(p.precio_mayoreo)}${p.cantidad_mayoreo ? ` desde ${numero(p.cantidad_mayoreo)}` : ''}`) : null,
            h('p', `Código: ${p.codigo}`, p.usa_inventario ? ` · Existencia: ${numero(p.existencia)}` : '')),
          botones: [{ texto: 'Cerrar', clase: 'primario', accion: (mm) => mm.cerrar() }],
        });
      },
    });
    enfocar();
  }

  // --- Editar líneas ---------------------------------------------------------------
  function lineaSeleccionada() {
    const t = actual();
    if (t.sel < 0 || t.sel >= t.items.length) {
      if (t.items.length) aviso('Selecciona una línea del ticket.', 'error');
      return null;
    }
    return t.items[t.sel];
  }

  function borrarLinea() {
    const t = actual();
    if (!lineaSeleccionada()) return;
    t.items.splice(t.sel, 1);
    t.sel = Math.min(t.sel, t.items.length - 1);
    dibujar();
    enfocar();
  }

  function sumarCantidad(delta) {
    const it = lineaSeleccionada();
    if (!it) return;
    const nueva = Math.round((it.cantidad + delta) * 1000) / 1000;
    if (nueva <= 0) return borrarLinea();
    const p = it.producto;
    if (delta > 0 && p?.usa_inventario && !opcion('permitir_stock_negativo') && nueva > p.existencia) {
      pitido();
      aviso(`No hay existencia suficiente (hay ${numero(p.existencia)}).`, 'error');
      return;
    }
    it.cantidad = nueva;
    dibujar();
  }

  async function editarCantidad() {
    const it = lineaSeleccionada();
    if (!it) return;
    const r = await formulario({
      titulo: `Cantidad: ${it.descripcion || it.producto.descripcion}`,
      aceptar: 'Aplicar',
      campos: [{ nombre: 'cantidad', etiqueta: 'Nueva cantidad', tipo: 'cantidad', valor: String(it.cantidad).replace('.', ','), requerido: true, autofocus: true }],
      alEnviar: (v) => {
        if (!(v.cantidad > 0)) throw new Error('La cantidad debe ser mayor que cero.');
        if (it.producto?.tipo_venta === 'unidad' && !Number.isInteger(v.cantidad)) throw new Error('Este producto se vende por unidad.');
        if (it.producto?.usa_inventario && !opcion('permitir_stock_negativo') && v.cantidad > it.producto.existencia) {
          throw new Error(`No hay existencia suficiente (hay ${numero(it.producto.existencia)}).`);
        }
      },
    });
    if (r) {
      it.cantidad = r.cantidad;
      dibujar();
    }
    enfocar();
  }

  function alternarMayoreo() {
    const it = lineaSeleccionada();
    if (!it) return;
    if (!it.producto || it.producto.precio_mayoreo == null) {
      aviso('Este producto no tiene precio de mayoreo.', 'error');
      return;
    }
    it.tipo_precio = precioLinea(it).tipo === 'mayoreo' ? 'normal' : 'mayoreo';
    if (it.tipo_precio === 'normal' && precioLinea(it).tipo === 'mayoreo') {
      aviso('Se aplica mayoreo automático por la cantidad.', '');
    }
    dibujar();
    enfocar();
  }

  async function cambiarPrecio() {
    const it = lineaSeleccionada();
    if (!it) return;
    if (!puede('cajero_puede_cambiar_precio')) {
      aviso('No tienes permiso para cambiar precios.', 'error');
      return;
    }
    const r = await formulario({
      titulo: 'Cambiar precio de la línea',
      aceptar: 'Aplicar',
      campos: [{ nombre: 'precio', etiqueta: 'Precio unitario', tipo: 'monto', valor: precioLinea(it).precio, requerido: true, autofocus: true }],
    });
    if (r) {
      it.precio = r.precio;
      if (it.tipo_precio !== 'comun') it.tipo_precio = 'manual';
      dibujar();
    }
    enfocar();
  }

  async function descuento() {
    const t = actual();
    if (!t.items.length) return;
    if (!puede('cajero_puede_cambiar_precio')) {
      aviso('No tienes permiso para aplicar descuentos.', 'error');
      return;
    }
    const { subtotal } = totalesTicket(t);
    const r = await formulario({
      titulo: 'Descuento al ticket',
      aceptar: 'Aplicar',
      intro: h('p', `Subtotal: ${pesos(subtotal)}. Escribe un monto (ej: 500) o un porcentaje (ej: 10%).`),
      campos: [{ nombre: 'valor', etiqueta: 'Descuento', valor: t.descuento || '', autofocus: true }],
      alEnviar: (v) => {
        const texto = String(v.valor).trim();
        const monto = texto.endsWith('%') ? Math.round(subtotal * parseFloat(texto.replace(',', '.')) / 100) : leerMonto(texto);
        if (!(monto >= 0) || monto > subtotal) throw new Error('El descuento no puede superar el subtotal.');
        return { monto };
      },
    });
    if (r) {
      t.descuento = r.monto;
      dibujar();
    }
    enfocar();
  }

  async function asignarCliente() {
    const c = await elegirCliente();
    if (c) {
      actual().cliente = { id: c.id, nombre: c.nombre, saldo: c.saldo, limite_credito: c.limite_credito, credito_disponible: c.credito_disponible };
      dibujar();
    }
    enfocar();
  }

  // --- Tickets ----------------------------------------------------------------------
  function nuevo() {
    if (tickets.lista.length >= 9) {
      aviso('Máximo 9 tickets abiertos.', 'error');
      return;
    }
    const numeroTicket = Math.max(...tickets.lista.map((t) => t.numero)) + 1;
    tickets.lista.push(nuevoTicket(numeroTicket));
    cambiarA(tickets.lista.length - 1);
  }

  function cerrarTicketActual() {
    if (tickets.lista.length > 1) {
      tickets.lista.splice(tickets.activo, 1);
      tickets.activo = Math.min(tickets.activo, tickets.lista.length - 1);
    } else {
      tickets.lista = [nuevoTicket(1)];
      tickets.activo = 0;
    }
    dibujar();
  }

  async function cancelarTicket() {
    const t = actual();
    if (t.items.length && !(await confirmar('Cancelar ticket', '¿Borrar todos los productos de este ticket?', { aceptar: 'Sí, cancelar', peligro: true }))) {
      enfocar();
      return;
    }
    cerrarTicketActual();
    enfocar();
  }

  async function guardarCotizacion() {
    const t = actual();
    if (!t.items.length) {
      aviso('El ticket está vacío.', 'error');
      return;
    }
    const r = await formulario({
      titulo: 'Guardar como cotización',
      aceptar: 'Guardar e imprimir',
      intro: h('p.suave', 'La cotización no descuenta inventario. Después la puedes cargar en un ticket para venderla.'),
      campos: [
        { nombre: 'cliente_nombre', etiqueta: 'Para (cliente)', valor: t.cliente?.nombre || '', autofocus: true },
        { nombre: 'nota', etiqueta: 'Nota', tipo: 'area', ancho: true },
      ],
      alEnviar: (v) => api.post('/api/cotizaciones', {
        items: itemsParaApi(t), descuento: t.descuento, cliente_id: t.cliente?.id, cliente_nombre: v.cliente_nombre, nota: v.nota,
      }),
    });
    if (r) {
      aviso(`Cotización N° ${r.folio} guardada.`, 'ok');
      imprimir(ticketCotizacion(r));
      cerrarTicketActual();
    }
    enfocar();
  }

  async function movimiento(tipo) {
    await movimientoCaja(tipo);
    enfocar();
  }

  // --- Cobro --------------------------------------------------------------------
  async function cobrar() {
    const t = actual();
    if (!t.items.length) {
      aviso('El ticket está vacío.', 'error');
      enfocar();
      return;
    }
    if (!turnoAbierto && !(await pedirAbrirTurno())) return;
    const { total } = totalesTicket(t);
    const redondear = opcion('redondeo_efectivo');
    let metodo = 'efectivo';
    let enviando = false;

    const pagaCon = h('input', { inputmode: 'numeric', placeholder: 'Exacto', autocomplete: 'off', 'aria-label': 'Paga con' });
    const mixtos = Object.fromEntries(['debito', 'credito', 'transferencia', 'fiado'].map((k) => [k, h('input', { inputmode: 'numeric', placeholder: '0', autocomplete: 'off' })]));
    const imprimirTicket = h('input', { type: 'checkbox', checked: opcion('imprimir_automatico') });
    const botonesMetodo = h('div.metodos');
    const zona = h('div');
    const resumen = h('div');

    function efectivoACobrar() {
      let noEfectivo = 0;
      if (metodo === 'mixto') noEfectivo = Object.values(mixtos).reduce((s, el) => s + leerMonto(el.value), 0);
      else if (metodo !== 'efectivo') noEfectivo = total;
      const efectivo = total - noEfectivo;
      return { efectivo, aCobrar: efectivo > 0 && redondear ? redondeoEfectivo(efectivo) : efectivo, noEfectivo };
    }

    function actualizarResumen() {
      const { efectivo, aCobrar, noEfectivo } = efectivoACobrar();
      const recibido = pagaCon.value.trim() ? leerMonto(pagaCon.value) : aCobrar;
      const filas = [];
      if (noEfectivo > total) filas.push(h('div.error-modal', 'Los pagos superan el total.'));
      if (efectivo > 0) {
        if (aCobrar !== efectivo) filas.push(h('p.suave', `Efectivo ${pesos(efectivo)} → se cobran ${pesos(aCobrar)} (redondeo Ley 20.956)`));
        else if (metodo === 'mixto') filas.push(h('p.suave', `Resto en efectivo: ${pesos(aCobrar)}`));
        filas.push(h('div.etq.suave', { style: { textAlign: 'center' } }, 'Cambio'));
        filas.push(h('div.cambio', { class: recibido < aCobrar ? 'rojo' : 'verde' }, recibido < aCobrar ? `Faltan ${pesos(aCobrar - recibido)}` : pesos(recibido - aCobrar)));
      }
      vaciar(resumen, filas);
    }

    function elegirMetodo(m) {
      metodo = m;
      vaciar(botonesMetodo, METODOS.map(([clave, texto, tecla]) => h('button', { type: 'button', class: clave === metodo ? 'activo' : null, onclick: () => elegirMetodo(clave) }, h('kbd', tecla), texto)));
      const c = t.cliente;
      const billetes = [1000, 2000, 5000, 10000, 20000].filter((b) => b >= efectivoACobrar().aCobrar).slice(0, 4);
      const filaEfectivo = [
        h('label.campo.paga-con', 'Paga con', pagaCon),
        h('div.billetes',
          h('button.btn.chico', { type: 'button', onclick: () => { pagaCon.value = ''; actualizarResumen(); pagaCon.focus(); } }, 'Exacto'),
          billetes.map((b) => h('button.btn.chico', { type: 'button', onclick: () => { pagaCon.value = String(b); actualizarResumen(); pagaCon.focus(); } }, pesos(b)))),
      ];
      if (m === 'efectivo') vaciar(zona, filaEfectivo);
      else if (m === 'fiado') {
        vaciar(zona, c
          ? h('div.panel', h('b', c.nombre), h('div', `Debe: ${pesos(c.saldo)}`),
            h('div', c.limite_credito == null ? 'Sin límite de crédito' : `Crédito disponible: ${pesos(c.credito_disponible)}`))
          : h('div.fila', h('span.rojo', 'Para vender fiado elige un cliente.'),
            h('button.btn', { type: 'button', onclick: async () => { await asignarClienteEnCobro(); } }, 'Elegir cliente')));
      } else if (m === 'mixto') {
        vaciar(zona,
          h('div.rejilla',
            h('label.campo', 'Débito', mixtos.debito), h('label.campo', 'Crédito', mixtos.credito),
            h('label.campo', 'Transferencia', mixtos.transferencia),
            h('label.campo', `Fiado${c ? ' (' + c.nombre + ')' : ' (requiere cliente)'}`, mixtos.fiado)),
          h('p.ayuda', 'Lo que falte se paga en efectivo.'),
          filaEfectivo);
      } else {
        vaciar(zona, h('p', `Se cobra el total con ${texto(m)}. Pasa la tarjeta o confirma la transferencia antes de aceptar.`));
      }
      actualizarResumen();
      setTimeout(() => (m === 'mixto' ? mixtos.debito : pagaCon).focus(), 0);
    }
    const texto = (m) => METODOS.find(([k]) => k === m)[1].toLowerCase();

    async function asignarClienteEnCobro() {
      const c = await elegirCliente();
      if (c) {
        t.cliente = { id: c.id, nombre: c.nombre, saldo: c.saldo, limite_credito: c.limite_credito, credito_disponible: c.credito_disponible };
        dibujar();
      }
      elegirMetodo(metodo);
    }

    pagaCon.addEventListener('input', actualizarResumen);
    Object.values(mixtos).forEach((el) => el.addEventListener('input', actualizarResumen));

    const m = modal({
      titulo: `Cobrar · Ticket ${t.numero}`,
      ancho: 'ancho',
      cuerpo: [
        h('div.cobro-total', h('div.suave', 'Total a pagar'), h('div.monto', pesos(total)),
          t.cliente ? h('div', `Cliente: ${t.cliente.nombre}`) : null),
        botonesMetodo, zona, resumen,
        h('label.check', imprimirTicket, 'Imprimir ticket'),
      ],
      botones: [
        { texto: 'Cancelar', tecla: 'Esc', accion: (mm) => mm.cerrar() },
        { texto: 'Cobrar', tecla: 'Enter', clase: 'primario', accion: () => confirmarCobro() },
      ],
      alTeclear: (e) => {
        const i = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6'].indexOf(e.key);
        if (i >= 0) { e.preventDefault(); elegirMetodo(METODOS[i][0]); }
        else if (e.key === 'Enter' && !e.target.matches('button')) { e.preventDefault(); confirmarCobro(); }
      },
      alCerrar: () => enfocar(),
    });
    elegirMetodo('efectivo');

    async function confirmarCobro() {
      if (enviando) return;
      const { aCobrar, noEfectivo } = efectivoACobrar();
      const pagos = {};
      if (metodo === 'mixto') {
        for (const [k, el] of Object.entries(mixtos)) if (leerMonto(el.value)) pagos[k] = leerMonto(el.value);
      } else if (metodo !== 'efectivo') {
        pagos[metodo] = total;
      }
      if (noEfectivo > total) return m.error('Los pagos superan el total.');
      if (pagos.fiado && !t.cliente) return m.error('Para vender fiado elige un cliente.');
      const recibido = pagaCon.value.trim() ? leerMonto(pagaCon.value) : aCobrar;
      if (total - noEfectivo > 0 && recibido < aCobrar) return m.error(`Faltan ${pesos(aCobrar - recibido)}.`);

      enviando = true;
      m.error('');
      try {
        const venta = await api.post('/api/ventas', {
          caja_id: estado.cajaId,
          items: itemsParaApi(t),
          descuento: t.descuento || 0,
          cliente_id: t.cliente?.id,
          cotizacion_id: t.cotizacionId,
          pagos,
          efectivo_recibido: total - noEfectivo > 0 ? recibido : null,
        });
        const imprimirlo = imprimirTicket.checked;
        m.cerrar();
        cerrarTicketActual();
        mostrarResultado(venta, imprimirlo);
      } catch (e) {
        if (e.codigo === 'sin_turno') {
          turnoAbierto = null;
          m.cerrar();
          await revisarTurno();
          aviso(e.message, 'error', 6000);
        } else {
          m.error(e.message);
        }
      } finally {
        enviando = false;
      }
    }
  }

  function mostrarResultado(venta, imprimirlo) {
    if (imprimirlo) imprimir(ticketVenta(venta));
    const efectivo = venta.pagos.some((p) => p.metodo === 'efectivo');
    const m = modal({
      titulo: `Venta registrada · Folio ${venta.folio}`,
      cuerpo: h('div.resultado-venta',
        h('div.suave', `Total ${pesos(venta.total)}`),
        efectivo ? [h('div.suave', 'Cambio'), h('div.cambio', pesos(venta.cambio))] : h('div.cambio', '¡Listo!')),
      botones: [
        { texto: 'Reimprimir', accion: () => imprimir(ticketVenta(venta)) },
        { texto: 'Aceptar', tecla: 'Enter', clase: 'primario', accion: (mm) => mm.cerrar() },
      ],
      alTeclear: (e) => {
        if (e.key === 'Enter' && !e.target.matches('button')) { e.preventDefault(); m.cerrar(); }
      },
      alCerrar: () => { enfocar(); },
    });
  }

  // --- Cargar desde una cotización ----------------------------------------------------
  async function cargarCotizacion(id) {
    try {
      const q = await api.get(`/api/cotizaciones/${id}`);
      const items = [];
      for (const linea of q.items) {
        if (linea.producto_id == null) {
          items.push({ producto: null, descripcion: linea.descripcion, precio: linea.precio_unitario, cantidad: linea.cantidad, tipo_precio: 'comun' });
          continue;
        }
        try {
          const p = await api.get(`/api/productos/${linea.producto_id}`);
          if (!p.activo) throw new Error();
          items.push({ producto: snapshot(p), cantidad: linea.cantidad, tipo_precio: linea.tipo_precio === 'mayoreo' ? 'mayoreo' : 'normal' });
        } catch {
          aviso(`«${linea.descripcion}» ya no existe y no se cargó.`, 'error', 6000);
        }
      }
      let t = actual();
      if (t.items.length) {
        nuevo();
        t = actual();
      }
      t.items = items;
      t.sel = items.length - 1;
      t.cotizacionId = q.id;
      t.descuento = Math.min(q.descuento || 0, totalesTicket(t).subtotal);
      if (q.cliente_id) t.cliente = { id: q.cliente_id, nombre: q.cliente_nombre, saldo: 0, limite_credito: null };
      dibujar();
      aviso(`Cotización N° ${q.folio} cargada. Los precios se toman del catálogo actual.`, 'ok', 5000);
    } catch (e) {
      avisoError(e);
    }
  }

  dibujar();
  await revisarTurno();
  if (parametros.cotizacionId) await cargarCotizacion(parametros.cotizacionId);
  enfocar();

  return {
    alTeclear(e) {
      const enCodigo = document.activeElement === codigo;
      const codigoVacio = codigo.value === '';
      const ctrl = e.ctrlKey || e.metaKey;
      const t = actual();
      if (e.key === 'F12') { e.preventDefault(); cobrar(); }
      else if (e.key === 'F10') { e.preventDefault(); buscarProducto(); }
      else if (e.key === 'F11' || (ctrl && e.key.toLowerCase() === 'm')) { e.preventDefault(); alternarMayoreo(); }
      else if (e.key === 'F9') { e.preventDefault(); verificador(); }
      else if (e.key === 'F8') { e.preventDefault(); movimiento('salida'); }
      else if (e.key === 'F7') { e.preventDefault(); movimiento('entrada'); }
      else if (e.key === 'F6') { e.preventDefault(); nuevo(); }
      else if (e.key === 'F5') { e.preventDefault(); asignarCliente(); }
      else if (e.key === 'Insert') { e.preventDefault(); varios(); }
      else if (ctrl && e.key.toLowerCase() === 'p') { e.preventDefault(); articuloComun(); }
      else if (ctrl && e.key.toLowerCase() === 'd') { e.preventDefault(); descuento(); }
      else if (e.key === 'PageDown') { e.preventDefault(); cambiarA(tickets.activo + 1); }
      else if (e.key === 'PageUp') { e.preventDefault(); cambiarA(tickets.activo - 1); }
      else if (e.key === 'ArrowDown' && t.items.length) { e.preventDefault(); t.sel = Math.min(t.sel + 1, t.items.length - 1); dibujar(); }
      else if (e.key === 'ArrowUp' && t.items.length) { e.preventDefault(); t.sel = Math.max(t.sel - 1, 0); dibujar(); }
      else if (e.key === 'Delete' && (!enCodigo || codigoVacio)) { e.preventDefault(); borrarLinea(); }
      else if ((e.key === '+' || e.key === '-') && (!enCodigo || codigoVacio)) { e.preventDefault(); sumarCantidad(e.key === '+' ? 1 : -1); }
      else if (e.key === '*' && (!enCodigo || codigoVacio)) { e.preventDefault(); editarCantidad(); }
      else if (!enCodigo && e.key.length === 1 && !ctrl && !e.altKey && !e.target.matches('input, textarea, select')) {
        codigo.focus(); // escribir en cualquier parte va al campo de código (lector de barras)
      }
    },
  };
}
