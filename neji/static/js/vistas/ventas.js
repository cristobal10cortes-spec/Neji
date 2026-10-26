// Pantalla de ventas, pensada para usarse solo con teclado (al estilo eleventa).

import { api, qs } from '../api.js';
import { esFarmacia, estado, guardarTickets, leerTickets, nuevoTicket, opcion, puede } from '../estado.js';
import { abrirCajon, documentoDeVenta, imprimir, ticketCotizacion, ticketVenta } from '../impresion.js';
import {
  aviso, avisoError, confirmar, formulario, h, importe, leerCantidad, leerMonto, modal, modalAbierto, numero, pesos, pitido,
  redondeoEfectivo, vaciar,
} from '../ui.js';
import { elegirCliente } from './clientes.js';
import { abrirTurno, movimientoCaja } from './caja.js';
import { panelVademecum } from './vademecum.js';

const METODOS = [
  ['efectivo', 'Efectivo', 'F1'],
  ['debito', 'Débito', 'F2'],
  ['credito', 'Crédito', 'F3'],
  ['transferencia', 'Transferencia', 'F4'],
  ['fiado', 'Fiado', 'F5'],
  ['mixto', 'Mixto', 'F6'],
];

export function precioLinea(item) {
  if (item.tipo_precio === 'receta') return { precio: item.receta.total, tipo: 'receta' };
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
    if (it.tipo_precio === 'receta') return { receta_id: it.receta.id, cantidad: 1 };
    if (it.tipo_precio === 'comun') return { descripcion: it.descripcion, cantidad: it.cantidad, precio: it.precio, tipo_precio: 'comun' };
    const linea = { producto_id: it.producto.id, cantidad: it.cantidad, tipo_precio: it.tipo_precio };
    if (it.tipo_precio === 'manual') linea.precio = it.precio;
    return linea;
  });
}

function snapshot(p) {
  const { id, codigo, descripcion, precio_venta, precio_mayoreo, cantidad_mayoreo, tipo_venta, existencia, usa_inventario, departamento, principios, principios_detalle } = p;
  return { id, codigo, descripcion, precio_venta, precio_mayoreo, cantidad_mayoreo, tipo_venta, existencia, usa_inventario, departamento, principios, principios_detalle };
}

// Al elegir de una lista con un clic, la lista se cierra y el segundo clic de un doble clic caería en lo que estaba
// debajo (una línea del ticket, un atajo): ese clic se descarta (ver montar).
let ultimoClicLista = -Infinity; // performance.now() parte en 0 al cargar la página
const marcarClicLista = () => { ultimoClicLista = performance.now(); };
const clicRecienEnLista = () => performance.now() - ultimoClicLista < 500;

/** Resultados del buscador en celdas: código, nombre, precio y existencia. `idFila(i)` da el id de cada fila (combobox). */
function tablaResultados(lista, sel, { alElegir, alMarcar = null, idFila = null }) {
  return h('table.tabla-resultados', { role: 'grid', 'aria-label': 'Resultados de la búsqueda' },
    h('thead', h('tr', h('th', 'Código'), h('th', 'Nombre'), h('th.num', 'Precio'), h('th.num', 'Existencia'))),
    h('tbody', lista.map((p, i) => h('tr.clic', {
      id: idFila ? idFila(i) : null,
      'aria-selected': String(i === sel),
      class: i === sel ? 'sel' : null,
      onclick: () => { marcarClicLista(); alElegir(i); },
      onmousemove: alMarcar ? () => alMarcar(i) : null,
    },
    h('td.mono', p.codigo),
    h('td', p.descripcion, p.departamento ? h('span.suave', ` · ${p.departamento}`) : null,
      esFarmacia() && p.principios ? h('div.ayuda.pa', p.principios) : null),
    h('td.num', pesos(p.precio_venta)),
    h('td.num', { class: p.usa_inventario && p.existencia <= 0 ? 'rojo' : 'suave' }, p.usa_inventario ? numero(p.existencia) : '—')))));
}

/** '3*parac' -> cantidad 3 y búsqueda 'parac' (igual que al escanear '3*código'). */
function separarCantidad(texto) {
  const m = texto.match(/^(\d+(?:[.,]\d+)?)\s*\*\s*(.+)$/);
  return m ? { cantidad: leerCantidad(m[1]), consulta: m[2].trim() } : { cantidad: null, consulta: texto };
}

const consultaValida = (q) => !q.includes('*') && q.replace(/^%/, '').trim().length >= 2;

const sinTildes = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

/**
 * El único resultado se agrega directo solo si calza por el nombre (o por principio activo con %).
 * Si solo coincide el comienzo del código ('10' -> '100'), puede ser un código mal escaneado: se pide confirmar.
 */
function calzaPorNombre(p, consulta) {
  if (consulta.startsWith('%')) return true;
  if (!/\p{L}/u.test(consulta)) return false; // solo números: es un código que no existe, aunque el nombre diga «60ML»
  const descripcion = sinTildes(p.descripcion);
  return sinTildes(consulta).split(/\s+/).every((palabra) => descripcion.includes(palabra));
}

// Qué tan parecida es la alternativa (ver servicios/farmacia.py: alternativas).
function etiquetaCoincidencia(coincidencia) {
  if (coincidencia === 'misma_dosis') return h('span.etiqueta.ok', 'misma dosis');
  if (coincidencia === 'mismo_principio') {
    return h('span.etiqueta.aviso', { title: 'Mismos principios activos, pero otra concentración o sin concentración registrada' }, 'mismo principio, revisar dosis');
  }
  return h('span.etiqueta', 'comparte principio');
}

export async function montar(contenedor, parametros = {}) {
  let tickets = leerTickets();
  let turnoAbierto = null;
  const actual = () => tickets.lista[tickets.activo];

  // --- Elementos ---------------------------------------------------------------
  const farmacia = esFarmacia();
  const codigo = h('input', {
    id: 'codigo-producto',
    placeholder: farmacia ? 'Escanea o escribe código, nombre o %principio activo' : 'Escanea o escribe el código o el nombre del producto',
    autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Código del producto',
    role: 'combobox', 'aria-autocomplete': 'list', 'aria-haspopup': 'grid', 'aria-expanded': 'false', 'aria-controls': 'resultados-busqueda',
  });
  // Lista del buscador. No le quita el foco al campo: se elige con el mouse o con ↑ ↓ y Enter.
  const listaBusqueda = h('div.resultados.oculto', { id: 'resultados-busqueda', onmousedown: (e) => e.preventDefault() });
  const busqueda = {
    lista: [], total: 0, sel: 0, texto: '', abierta: false, suspendida: false, elegida: false, mensaje: '', pedido: 0, espera: null,
    cancelados: 0, // sube con Esc: el Enter que esperaba al servidor ya no agrega ni abre nada
  };
  const fichas = new Map(); // productos leídos del servidor con su ficha del vademécum
  const ficha = farmacia
    ? panelVademecum({
      fichas,
      alternativas: (p) => alternativas(p, textoBuscado()),
      alTerminar: () => enfocar(),
      retenerFoco: () => busqueda.abierta,
      alActualizar: (p) => refrescarProducto(p),
      alVender: (c) => venderCodigo(c),
    })
    : null;
  let productoSinStock = null; // último producto que no se pudo agregar por falta de stock (Ctrl+B)
  const avisoTurno = h('div.panel.oculto', { style: { background: '#fff7e0', borderColor: '#f3d27a' } });
  const pestanasTickets = h('div.tickets');
  const cuerpoTabla = h('tbody');
  const lblCliente = h('div.cliente-ticket');
  const lblArticulos = h('div.suave');
  const lblTotal = h('div.monto', '$0');
  const lblDescuento = h('div.suave');

  const boton = (tecla, texto, accion, extra = {}) =>
    h('button.btn', { type: 'button', onclick: () => { accion(); }, ...extra }, tecla ? h('kbd', tecla) : null, texto);
  // Fila de atajos bajo el buscador, como en eleventa.
  const tecla = (teclaTexto, texto, accion, extra = {}) =>
    h('button.btn', { type: 'button', title: `${texto} (${teclaTexto})`, onclick: () => { accion(); }, ...extra }, h('kbd', teclaTexto), h('span', texto));
  // Lo que el usuario no tiene permitido queda a la vista (la fila es la misma en todas las cajas) pero apagado.
  const sinPermiso = (permiso) => (puede(permiso) ? {} : { disabled: true, title: 'No tienes permiso (Configuración → Usuarios)' });
  const filaTeclas = h('div.teclas',
    tecla('INS', 'Varios', varios),
    tecla('Ctrl+P', 'Art. común', articuloComun, sinPermiso('articulo_comun')),
    tecla('F10', 'Buscar', buscarProducto),
    tecla('F11', 'Mayoreo', alternarMayoreo, { title: 'Mayoreo (F11 o Ctrl+M)' }),
    tecla('F9', 'Verificador', verificador),
    tecla('F7', 'Entrada', () => movimiento('entrada'), { title: 'Entrada de efectivo (F7)', ...sinPermiso('movimientos_caja') }),
    tecla('F8', 'Salida', () => movimiento('salida'), { title: 'Salida de efectivo (F8)', ...sinPermiso('movimientos_caja') }));
  // Si con la tecla al lado del texto los 7 no quedan del mismo ancho (depende del ancho y de la fuente), la tecla va
  // sobre el texto.
  const ajusteTeclas = new ResizeObserver(() => {
    filaTeclas.classList.remove('apiladas');
    const anchos = [...filaTeclas.children].map((b) => b.getBoundingClientRect().width);
    filaTeclas.classList.toggle('apiladas', Math.max(...anchos) - Math.min(...anchos) > 1);
  });

  vaciar(contenedor, h('div.ventas',
    avisoTurno,
    h(`div.venta-cuerpo${ficha ? '.con-ficha' : ''}`,
      ficha?.el,
      h('div.venta-principal',
        h('div.captura',
          h('label', { for: 'codigo-producto' }, 'Código del producto'),
          codigo,
          boton('Enter', 'Agregar producto', () => enterEnCodigo(), { class: 'primario', onmousedown: (e) => e.preventDefault() }),
          listaBusqueda),
        filaTeclas,
        h('div.fila.entre', pestanasTickets, boton('F6', 'Nuevo ticket', nuevo)),
        h('div.tabla-caja.ticket-tabla', h('table',
          h('thead', h('tr',
            h('th', '#'), h('th', 'Código'), h('th', 'Descripción'), h('th.num', 'Precio'), h('th.num', 'Cant.'),
            h('th.num', 'Importe'), h('th.num.ocultar-movil', 'Existencia'))),
          cuerpoTabla)))),
    h('div.pie-venta',
      h('div.pie-acciones',
        h('div.atajos',
          boton('Supr', 'Borrar', borrarLinea),
          boton('*', 'Cantidad', editarCantidad),
          boton('Ctrl+D', 'Descuento', descuento, sinPermiso('cambiar_precio')),
          boton('', 'Precio', cambiarPrecio, sinPermiso('cambiar_precio')),
          boton('F5', 'Cliente', asignarCliente),
          boton('', 'Cotizar', guardarCotizacion)),
        lblCliente),
      h('div.total-grande', lblArticulos, lblDescuento, h('div.etq', 'Total'), lblTotal),
      h('div.cobrar',
        boton('', 'Cancelar ticket', cancelarTicket, { class: 'peligro' }),
        h('button.btn.primario.grande', { type: 'button', onclick: cobrar }, h('kbd', 'F12'), 'Cobrar')))));

  ajusteTeclas.observe(filaTeclas.parentElement);

  for (const tipo of ['mousedown', 'click', 'dblclick']) {
    contenedor.addEventListener(tipo, (e) => {
      if (clicRecienEnLista() && !listaBusqueda.contains(e.target)) {
        e.preventDefault();
        e.stopPropagation();
      }
    }, true);
  }

  codigo.addEventListener('input', alEscribir);
  codigo.addEventListener('keydown', (e) => {
    if (modalAbierto()) return; // las teclas son de la ventana abierta
    if (e.key === 'Enter') {
      e.preventDefault();
      enterEnCodigo();
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && consultaValida(separarCantidad(codigo.value.trim()).consulta)) {
      // Con algo escrito, las flechas recorren los resultados (sin texto mueven la línea del ticket).
      e.preventDefault();
      e.stopPropagation();
      if (busqueda.abierta) moverResultado(e.key === 'ArrowDown' ? 1 : -1);
      else reabrirBusqueda();
    } else if (e.key === 'Escape') {
      busqueda.cancelados++;
      if (!busqueda.abierta && !codigo.value) return;
      e.preventDefault();
      e.stopPropagation();
      codigo.value = '';
      cerrarBusqueda();
    }
  });
  codigo.addEventListener('blur', () => {
    // Si se abre una ventana (ficha, Ctrl+B, F9...) la lista vuelve al regresar; con un clic en otra parte se cierra.
    if (busqueda.abierta) cerrarBusqueda({ suspender: Boolean(document.querySelector('.fondo-modal')) || !document.hasFocus() });
  });
  codigo.addEventListener('focus', () => {
    if (busqueda.suspendida && separarCantidad(codigo.value.trim()).consulta === busqueda.texto) abrirBusqueda();
    busqueda.suspendida = false;
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
    pestanasTickets.querySelector('.activo')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });

    if (!t.items.length) {
      vaciar(cuerpoTabla, h('tr', h('td.vacio', { colspan: 7 }, 'Escanea un producto o escribe su nombre en el buscador. 3*código agrega 3 unidades.')));
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
        h('td.mono', p?.codigo || (it.receta ? `RM-${it.receta.folio}` : '—')),
        h('td.desc', it.descripcion || p.descripcion, ' ',
          tipo === 'mayoreo' ? h('span.etiqueta.aviso', 'mayoreo') : null,
          tipo === 'manual' ? h('span.etiqueta.aviso', 'precio manual') : null,
          tipo === 'comun' ? h('span.etiqueta', 'común') : null,
          tipo === 'receta' ? h('span.etiqueta.ok', 'receta magistral') : null,
          p?.principios && esFarmacia() ? h('div.ayuda', p.principios) : null),
        h('td.num', pesos(precio)),
        h('td.num.cant', numero(it.cantidad), p?.tipo_venta === 'granel' ? ' kg' : ''),
        h('td.num.negrita', pesos(importe(it.cantidad, precio))),
        h('td.num.ocultar-movil', { class: sinStock ? 'rojo' : 'suave' }, p?.usa_inventario ? numero(p.existencia) : '—'));
      }));
    }

    const tot = totalesTicket(t);
    lblTotal.textContent = pesos(tot.total);
    lblArticulos.textContent = `${numero(tot.articulos)} artículo${tot.articulos === 1 ? '' : 's'}`;
    lblDescuento.textContent = tot.descuento ? `Subtotal ${pesos(tot.subtotal)} · Descuento -${pesos(tot.descuento)}` : '';
    // La ficha del vademécum sigue a la línea seleccionada (o al resultado marcado en el buscador).
    productoSinStock = null;
    actualizarFicha();
    vaciar(lblCliente, t.cliente
      ? [h('span.etiqueta.ok', 'Cliente'),
        h('span.cliente-nombre', { title: t.cliente.nombre }, t.cliente.nombre, t.cliente.saldo ? h('span.suave', ` (debe ${pesos(t.cliente.saldo)})`) : null),
        h('button.btn.chico', { type: 'button', onclick: () => { t.cliente = null; guardar(); dibujar(); } }, 'Quitar')]
      : t.cotizacionId ? h('span.etiqueta', `Desde cotización`) : '');
    // Al final, con el pie ya armado (el cliente o el descuento lo agrandan y achican la tabla).
    cuerpoTabla.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
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
    cuerpoTabla.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' }); // el aviso le quita alto al ticket
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
    ficha?.recordar(producto);
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
      const conAlternativas = esFarmacia() && p.principios;
      aviso(`No hay existencia suficiente de «${p.descripcion}» (hay ${numero(p.existencia)}).`
        + (conAlternativas ? ' Ctrl+B para ver alternativas.' : ''), 'error', 6000);
      // Muestra su ficha para que Ctrl+B ofrezca alternativas de este producto, sin abrir nada solo.
      if (conAlternativas) {
        productoSinStock = producto;
        actualizarFicha();
      }
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
    const escrito = codigo.value.trim();
    if (!escrito) return;
    const { cantidad, consulta: texto } = separarCantidad(escrito); // '3*código', '0,755*código'
    const turno = busqueda.cancelados;
    codigo.value = '';
    cerrarBusqueda();
    let producto;
    try {
      producto = await api.get(`/api/productos/codigo/${encodeURIComponent(texto)}`);
    } catch (e) {
      // No es un código: si el nombre calza con un solo producto se agrega; si no, se elige de la lista.
      // Es una búsqueda aparte de la del buscador en vivo: lo que se escriba mientras tanto no la anula.
      const r = e.status === 404 && consultaValida(texto) ? await api.get(urlBusqueda(texto)).catch(() => null) : null;
      if (turno !== busqueda.cancelados) return;
      const n = r?.productos.length || 0;
      if (n === 1 && calzaPorNombre(r.productos[0], texto)) {
        producto = r.productos[0];
      } else if (n && codigo.value === '') {
        if (n === 1) pitido(); // parecido a un código, pero no igual
        cargarResultados(r, texto);
        codigo.value = escrito;
        busqueda.elegida = true;
        busqueda.mensaje = n === 1
          ? `No hay un producto con el código «${texto}». ¿Es este? Confirma con Enter.`
          : `${n === r.total ? n : 'Varios'} productos coinciden con «${texto}»: elige con ↑ ↓ y confirma con Enter.`;
        if (document.activeElement === codigo) abrirBusqueda();
        return;
      } else {
        pitido();
        avisoError(e);
        enfocar();
        return;
      }
    }
    if (turno !== busqueda.cancelados) return;
    await agregarConCantidad(producto, cantidad);
  }

  /** «Vender» desde la ficha de un principio: agrega al ticket a la vista, sin volver a montar la venta. */
  async function venderCodigo(c) {
    let producto;
    try {
      producto = await api.get(`/api/productos/codigo/${encodeURIComponent(c)}`);
    } catch (e) {
      pitido();
      avisoError(e);
      enfocar();
      return;
    }
    await agregarConCantidad(producto, null);
  }

  /**
   * Datos frescos de un producto (leídos por la ficha o recién editados): las líneas de los tickets y los
   * resultados del buscador los toman, así lo que se ve coincide con lo que el servidor va a cobrar.
   */
  function refrescarProducto(p) {
    let cambio = false;
    for (const tk of tickets.lista) {
      for (const it of tk.items) {
        if (it.producto?.id === p.id && it.producto.codigo === p.codigo) {
          it.producto = snapshot(p);
          cambio = true;
        }
      }
    }
    if (busqueda.lista.some((x) => x.id === p.id)) {
      busqueda.lista = busqueda.lista.map((x) => (x.id === p.id ? { ...x, ...p } : x));
      if (busqueda.abierta) pintarBusqueda();
    }
    if (cambio) {
      const sinStock = productoSinStock; // dibujar() vuelve la ficha a la línea elegida
      dibujar();
      if (sinStock) {
        productoSinStock = sinStock;
        actualizarFicha();
      }
    }
  }

  async function agregarConCantidad(producto, cantidad) {
    if (cantidad === null && producto.tipo_venta === 'granel') {
      cantidad = await pedirCantidad(producto);
      if (cantidad === null) { enfocar(); return; }
    }
    agregarProducto(producto, cantidad ?? 1);
    enfocar();
  }

  // --- Buscador en vivo ----------------------------------------------------------------
  // Al escribir un nombre aparecen los productos en celdas y la ficha del vademécum del marcado.
  const textoBuscado = () => (busqueda.abierta ? codigo.value : null);

  const urlBusqueda = (q) => `/api/productos${qs({ q, por_pagina: 30, vademecum: farmacia ? 1 : '' })}`;

  function alEscribir() {
    clearTimeout(busqueda.espera);
    busqueda.pedido++; // lo que venía en camino era de otro texto (aunque se vuelva a él con Retroceso)
    const { consulta } = separarCantidad(codigo.value.trim());
    if (!consultaValida(consulta)) {
      cerrarBusqueda();
      return;
    }
    if (busqueda.abierta && consulta === busqueda.texto) return;
    busqueda.espera = setTimeout(async () => {
      const r = await buscarEnVivo(consulta);
      if (r && document.activeElement === codigo && separarCantidad(codigo.value.trim()).consulta === consulta) abrirBusqueda();
    }, 200);
  }

  async function buscarEnVivo(consulta) {
    clearTimeout(busqueda.espera);
    const n = ++busqueda.pedido;
    let r;
    try {
      r = await api.get(urlBusqueda(consulta));
    } catch (e) {
      if (n === busqueda.pedido) avisoError(e);
      return null;
    }
    if (n !== busqueda.pedido) return null; // llegó tarde: ya se escribió o escaneó otra cosa
    cargarResultados(r, consulta);
    return r;
  }

  function cargarResultados(r, consulta) {
    r.productos.forEach((p) => ficha?.recordar(p));
    Object.assign(busqueda, { lista: r.productos, total: r.total, sel: 0, texto: consulta, elegida: false, mensaje: '' });
  }

  async function reabrirBusqueda() {
    const { consulta } = separarCantidad(codigo.value.trim());
    if (consulta === busqueda.texto && busqueda.lista.length) abrirBusqueda();
    else if (await buscarEnVivo(consulta) && document.activeElement === codigo) abrirBusqueda();
  }

  function abrirBusqueda() {
    busqueda.abierta = true;
    busqueda.suspendida = false;
    listaBusqueda.classList.remove('oculto');
    codigo.setAttribute('aria-expanded', 'true');
    pintarBusqueda();
    actualizarFicha();
  }

  function cerrarBusqueda({ suspender = false } = {}) {
    clearTimeout(busqueda.espera);
    busqueda.pedido++; // descarta las búsquedas que vienen en camino
    busqueda.suspendida = suspender && busqueda.abierta;
    if (!suspender) Object.assign(busqueda, { elegida: false, mensaje: '' });
    if (!busqueda.abierta) return;
    busqueda.abierta = false;
    listaBusqueda.classList.add('oculto');
    codigo.setAttribute('aria-expanded', 'false');
    codigo.removeAttribute('aria-activedescendant');
    actualizarFicha();
  }

  function pintarBusqueda() {
    const { lista, sel, total, texto, mensaje } = busqueda;
    vaciar(listaBusqueda,
      h('div.resultados-lista', lista.length
        ? tablaResultados(lista, sel, { alElegir: elegirResultado, alMarcar: (i) => { if (i !== busqueda.sel) marcarResultado(i); }, idFila: idResultado })
        : h('p.vacio', `Sin resultados para «${texto}». Enter busca el código exacto.`)),
      h('div.resultados-pie',
        mensaje ? h('b', mensaje) : h('span', '↑ ↓ elegir · Enter agregar · Esc cerrar', farmacia ? ' · Ctrl+B alternativas' : ''),
        total > lista.length ? h('span', `Primeros ${lista.length} de ${numero(total)}: escribe más para afinar`) : null));
    listaBusqueda.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
    anunciarMarcado();
  }

  // El lector de pantalla anuncia la fila marcada aunque el foco siga en el campo.
  const idResultado = (i) => `resultado-${i}`;
  function anunciarMarcado() {
    if (busqueda.lista.length) codigo.setAttribute('aria-activedescendant', idResultado(busqueda.sel));
    else codigo.removeAttribute('aria-activedescendant');
  }

  function marcarResultado(i, desplazar = false) {
    busqueda.sel = i;
    const filas = listaBusqueda.querySelectorAll('tbody tr');
    filas.forEach((tr, j) => {
      tr.classList.toggle('sel', j === i);
      tr.setAttribute('aria-selected', String(j === i));
    });
    anunciarMarcado();
    if (desplazar) filas[i]?.scrollIntoView({ block: 'nearest' });
    actualizarFicha();
  }

  function moverResultado(delta) {
    if (!busqueda.lista.length) return;
    busqueda.elegida = true;
    marcarResultado(Math.max(0, Math.min(busqueda.sel + delta, busqueda.lista.length - 1)), true);
  }

  /** Enter (o el botón Agregar): el código exacto, el único resultado o el marcado con ↑ ↓. */
  function enterEnCodigo() {
    const { consulta } = separarCantidad(codigo.value.trim());
    const { abierta, texto, lista, elegida, sel } = busqueda;
    if (abierta && texto === consulta && lista.length) {
      if (elegida) return elegirResultado(sel);
      const exacto = lista.findIndex((p) => p.codigo === consulta);
      if (exacto >= 0) return elegirResultado(exacto);
      if (lista.length === 1 && calzaPorNombre(lista[0], consulta)) return elegirResultado(0);
    }
    return procesarCodigo();
  }

  async function elegirResultado(i) {
    const elegido = busqueda.lista[i];
    if (!elegido) return;
    const { cantidad } = separarCantidad(codigo.value.trim());
    const turno = busqueda.cancelados;
    codigo.value = '';
    cerrarBusqueda();
    let producto;
    try {
      producto = await api.get(`/api/productos/codigo/${encodeURIComponent(elegido.codigo)}`);
    } catch (e) {
      pitido();
      avisoError(e);
      enfocar();
      return;
    }
    if (turno !== busqueda.cancelados) return;
    await agregarConCantidad(producto, cantidad);
  }

  /** Producto que muestra la ficha: el marcado en el buscador, el que no tenía stock o la línea elegida. */
  function actualizarFicha() {
    if (!ficha) return;
    const enBusqueda = busqueda.abierta ? busqueda.lista[busqueda.sel] : null;
    const t = actual();
    const linea = t.items[t.sel]?.producto;
    if (enBusqueda) ficha.mostrar(enBusqueda, 'búsqueda');
    else if (productoSinStock) ficha.mostrar(productoSinStock, productoSinStock.existencia > 0 ? 'no alcanza' : 'sin stock');
    else ficha.mostrar(linea || null, linea ? `línea ${t.sel + 1}` : '');
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
    if (!puede('articulo_comun')) {
      aviso('No tienes permiso para vender artículos comunes.', 'error');
      return;
    }
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
      const entrada = h('input', {
        placeholder: farmacia ? 'Descripción o código. Empieza con % para buscar por principio activo (ej: %paracetamol)' : 'Escribe parte de la descripción o del código',
        autocomplete: 'off', autofocus: true,
      });
      const lista = h('div.lista-busqueda');
      const fichaBusqueda = farmacia
        ? panelVademecum({
          fichas,
          alTerminar: () => entrada.focus(),
          alActualizar: (p) => refrescarProducto(p),
          alVender: (c) => { elegido = { codigo: c }; m.cerrar(); },
        })
        : null;
      let resultados = [];
      let sel = 0;
      let elegido = null;
      let consulta = 0;

      const pintar = () => {
        vaciar(lista, resultados.length
          ? tablaResultados(resultados, sel, { alElegir: (i) => { sel = i; elegir(); } })
          : h('p.vacio', entrada.value ? 'Sin resultados.' : 'Escribe para buscar.'));
        lista.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
        fichaBusqueda?.mostrar(resultados[sel] || null);
      };
      const cargar = async () => {
        const n = ++consulta;
        const q = entrada.value.trim();
        const r = q
          ? await api.get(`/api/productos${qs({ q, por_pagina: 60, vademecum: farmacia ? 1 : '' })}`).catch(() => ({ productos: [] }))
          : { productos: [] };
        if (n !== consulta) return;
        resultados = r.productos;
        resultados.forEach((p) => fichaBusqueda?.recordar(p));
        sel = 0;
        pintar();
      };
      let espera;
      entrada.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(cargar, 180); });

      const m = modal({
        titulo: 'Buscar producto',
        ancho: farmacia ? 'muy-ancho' : 'ancho',
        cuerpo: [entrada, h('p.ayuda', '↑ ↓ para moverte, Enter para agregar, Esc para cerrar.'),
          fichaBusqueda ? h('div.busqueda-con-ficha', fichaBusqueda.el, lista) : lista],
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
    }).then(async (elegido) => {
      actualizarFicha();
      if (!elegido) {
        enfocar();
        return;
      }
      let producto = elegido;
      try {
        producto = await api.get(`/api/productos/codigo/${encodeURIComponent(elegido.codigo)}`);
      } catch (e) {
        if (!elegido.id) { // «Vender» desde la ficha solo trae el código
          pitido();
          avisoError(e);
          enfocar();
          return;
        }
      }
      await agregarConCantidad(producto, null);
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
          alCerrar: () => enfocar(),
        });
      },
    });
    enfocar();
  }

  // --- Alternativas ---------------------------------------------------------------
  /** Productos con el mismo principio activo (bioequivalentes u otras marcas). */
  async function alternativas(producto, textoBusqueda = null) {
    if (!producto?.id) {
      aviso('Selecciona un producto del ticket.', 'error');
      return;
    }
    let lista = [];
    try {
      lista = await api.get(`/api/productos/${producto.id}/alternativas`);
    } catch (e) {
      avisoError(e);
      return;
    }
    if (!lista.length) {
      aviso('No hay otros productos con el mismo principio activo.', '');
      enfocar();
      return;
    }
    const sinStock = producto.usa_inventario && producto.existencia <= 0;
    let sel = 0;
    const cuerpo = h('div.lista-busqueda');
    const pintar = () => {
      vaciar(cuerpo, h('table', h('tbody', lista.map((a, i) => h('tr.clic', {
        class: i === sel ? 'sel' : null,
        onclick: () => { marcarClicLista(); sel = i; elegir(); },
      },
      h('td.mono', a.codigo),
      h('td', a.descripcion, h('div.ayuda.pa', a.principios || '')),
      h('td', etiquetaCoincidencia(a.coincidencia)),
      h('td.num', pesos(a.precio_venta)),
      h('td.num', { class: a.con_stock ? 'verde' : 'rojo' }, a.usa_inventario ? numero(a.existencia) : '—'))))));
      cuerpo.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
    };
    const m = modal({
      titulo: sinStock ? `Sin stock: alternativas a ${producto.descripcion}` : `Alternativas a ${producto.descripcion}`,
      ancho: 'ancho',
      cuerpo: [h('p.ayuda', `Mismo principio activo: ${producto.principios || ''}. ↑ ↓ y Enter para agregar.`), cuerpo],
      alTeclear: (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, lista.length - 1); pintar(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); pintar(); }
        else if (e.key === 'Enter') { e.preventDefault(); elegir(); }
      },
      alCerrar: () => enfocar(),
    });
    async function elegir() {
      const a = lista[sel];
      if (!a) return;
      // Si se abrió desde el buscador, la búsqueda ya cumplió su objetivo.
      if (textoBusqueda !== null && codigo.value === textoBusqueda) {
        codigo.value = '';
        cerrarBusqueda();
      }
      m.cerrar();
      try {
        const p = await api.get(`/api/productos/codigo/${encodeURIComponent(a.codigo)}`);
        let cantidad = 1;
        if (p.tipo_venta === 'granel') cantidad = await pedirCantidad(p);
        if (cantidad !== null) agregarProducto(p, cantidad);
      } catch (e) {
        avisoError(e);
      }
      enfocar();
    }
    pintar();
  }

  function alternativasDeLinea() {
    const t = actual();
    // De lo que muestra la ficha: el resultado marcado, el último producto sin stock o la línea elegida.
    alternativas(ficha?.producto || t.items[t.sel]?.producto, textoBuscado());
  }

  // --- Recetas magistrales ------------------------------------------------------------
  async function cargarReceta(id) {
    let r;
    try {
      r = await api.get(`/api/recetario/recetas/${id}`);
    } catch (e) {
      avisoError(e);
      return;
    }
    if (r.estado !== 'pendiente') {
      aviso(`La receta N° ${r.folio} ya está ${r.estado}.`, 'error');
      return;
    }
    const enTicket = tickets.lista.findIndex((tk) => tk.items.some((it) => it.receta?.id === r.id));
    if (enTicket >= 0) {
      cambiarA(enTicket);
      aviso(`La receta N° ${r.folio} ya está en el Ticket ${tickets.lista[enTicket].numero}.`, '');
      return;
    }
    const t = actual();
    t.items.push({
      producto: null, cantidad: 1, tipo_precio: 'receta', descripcion: r.descripcion,
      receta: { id: r.id, folio: r.folio, total: r.total, descripcion: r.descripcion },
    });
    t.sel = t.items.length - 1;
    dibujar();
    aviso(`Receta N° ${r.folio} agregada: ${pesos(r.total)}.`, 'ok');
  }

  // --- Editar líneas ---------------------------------------------------------------
  /** Línea seleccionada si se puede modificar (las recetas tienen precio y cantidad fijos). */
  function lineaEditable() {
    const it = lineaSeleccionada();
    if (it?.tipo_precio === 'receta') {
      aviso('La receta magistral tiene precio y cantidad fijos. Para cambiarla, bórrala y recalcúlala en el Recetario.', 'error', 5000);
      return null;
    }
    return it;
  }

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
    const it = lineaEditable();
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
    const it = lineaEditable();
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
    const it = lineaEditable();
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
    const it = lineaEditable();
    if (!it) return;
    if (!puede('cambiar_precio')) {
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
    if (!puede('cambiar_precio')) {
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
    codigo.value = ''; // el cliente siguiente parte con el buscador vacío
    cerrarBusqueda();
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
    // Con la boleta electrónica activada se elige el documento: boleta (lo normal) o factura (con cliente).
    const conSii = estado.config.sii_activo === '1';
    let metodo = 'efectivo';
    let documento = 'boleta';
    let enviando = false;

    const pagaCon = h('input', { inputmode: 'numeric', placeholder: 'Exacto', autocomplete: 'off', 'aria-label': 'Paga con' });
    const mixtos = Object.fromEntries(['debito', 'credito', 'transferencia', 'fiado'].map((k) => [k, h('input', { inputmode: 'numeric', placeholder: '0', autocomplete: 'off' })]));
    const imprimirTicket = h('input', { type: 'checkbox', checked: opcion('imprimir_automatico') });
    const botonesMetodo = h('div.metodos');
    const zona = h('div');
    const resumen = h('div');
    const zonaDocumento = h('div.documento-sii');

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

    function elegirDocumento(d) {
      documento = d;
      if (!conSii) return;
      const c = t.cliente;
      vaciar(zonaDocumento,
        h('div.metodos.documentos', [['boleta', 'Boleta'], ['factura', 'Factura']].map(([clave, nombre]) => h('button', {
          type: 'button', class: clave === documento ? 'activo' : null, title: 'Boleta o factura (F7)', onclick: () => elegirDocumento(clave),
        }, nombre))),
        documento === 'factura'
          ? (c ? h('p.ayuda', `Factura a ${c.nombre}. Debe tener RUT, giro, dirección y comuna (se editan en Clientes).`)
            : h('div.fila', h('span.rojo', 'Para la factura elige el cliente.'),
              h('button.btn.chico', { type: 'button', onclick: () => asignarClienteEnCobro() }, 'Elegir cliente')))
          : null);
    }

    async function asignarClienteEnCobro() {
      const c = await elegirCliente();
      if (c) {
        t.cliente = { id: c.id, nombre: c.nombre, saldo: c.saldo, limite_credito: c.limite_credito, credito_disponible: c.credito_disponible };
        dibujar();
      }
      elegirDocumento(documento);
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
        zonaDocumento, botonesMetodo, zona, resumen,
        h('label.check', imprimirTicket, 'Imprimir ticket'),
      ],
      botones: [
        { texto: 'Cancelar', tecla: 'Esc', accion: (mm) => mm.cerrar() },
        { texto: 'Cobrar', tecla: 'Enter', clase: 'primario', accion: () => confirmarCobro() },
      ],
      alTeclear: (e) => {
        const i = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6'].indexOf(e.key);
        if (i >= 0) { e.preventDefault(); elegirMetodo(METODOS[i][0]); }
        else if (e.key === 'F7' && conSii) { e.preventDefault(); elegirDocumento(documento === 'boleta' ? 'factura' : 'boleta'); }
        else if (e.key === 'Enter' && !e.target.matches('button')) { e.preventDefault(); confirmarCobro(); }
      },
      alCerrar: () => enfocar(),
    });
    elegirDocumento('boleta');
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
      if (conSii && documento === 'factura' && !t.cliente) return m.error('Para la factura elige el cliente (con RUT, giro, dirección y comuna).');
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
          documento: conSii ? documento : undefined,
        });
        const imprimirlo = imprimirTicket.checked;
        cerrarTicketActual();
        m.cerrar();
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
    const efectivo = venta.pagos.some((p) => p.metodo === 'efectivo');
    const doc = documentoDeVenta(venta);
    // Con efectivo se abre el cajón de dinero (si está conectado a la impresora de tickets).
    if (imprimirlo) imprimir(ticketVenta(venta), { abrirCajon: efectivo });
    else if (efectivo) abrirCajon();
    // Lo que la caja tiene que saber: p. ej. que la boleta electrónica no se pudo emitir o que quedan pocos folios.
    for (const a of venta.avisos || []) aviso(a, 'error', 9000);
    const m = modal({
      titulo: `Venta registrada · Folio ${venta.folio}`,
      cuerpo: h('div.resultado-venta',
        doc ? h('div', h('b', `${doc.nombre} N° ${doc.folio}`)) : null,
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
    // Si se escanea el producto del cliente siguiente, esta ventana se cierra sola (lector.js).
    m.el.dataset.lector = 'cerrar';
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
  if (parametros.recetaId) await cargarReceta(parametros.recetaId);
  if (parametros.codigo) {
    codigo.value = parametros.codigo;
    await procesarCodigo();
  }
  enfocar();

  return {
    desmontar() {
      ajusteTeclas.disconnect();
    },
    /** Un código del lector de barras (lector.js): va directo al ticket, esté donde esté el foco. */
    recibirCodigo(c) {
      codigo.value = c;
      procesarCodigo();
    },
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
      else if (ctrl && e.key.toLowerCase() === 'b' && esFarmacia()) { e.preventDefault(); alternativasDeLinea(); }
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
