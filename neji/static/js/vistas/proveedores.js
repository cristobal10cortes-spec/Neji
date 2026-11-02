// Proveedores: las facturas de cada proveedor, cuánto se les debe y qué ya se pagó (neji/servicios/proveedores.py).

import { api, qs } from '../api.js';
import { aviso, avisoError, confirmar, debounce, fecha, formulario, h, hoy, kpi, modal, numero, pesos, pestanas, tabla, vaciar } from '../ui.js';

const fechaCorta = (texto) => (texto ? fecha(texto, false) : '');
// Las notas de crédito restan: «-$30.500» (y no «$-30.500»).
const conSigno = (n) => (n < 0 ? `-${pesos(-n)}` : pesos(n));

let filtro = { estado: 'por_pagar', proveedor_id: '', q: '' };

/** Formulario de una factura (o nota de crédito) nueva o para editar. Devuelve la guardada o null. */
function formFactura(datos, factura = null) {
  const lista = `prov-sugeridos-${Date.now()}`;
  const sugeridos = h('datalist', { id: lista }, datos.sugeridos.map((n) => h('option', { value: n })));
  return formulario({
    titulo: factura ? `Editar ${factura.tipo === 'nota_credito' ? 'nota de crédito' : 'factura'}` : 'Anotar factura de proveedor',
    ancho: 'ancho',
    enterAvanza: true,
    extra: sugeridos,
    campos: [
      { nombre: 'proveedor', etiqueta: 'Proveedor', valor: factura?.proveedor, requerido: true, autofocus: true, atributos: { list: lista }, ayuda: 'Si es nuevo, queda agregado a la lista de proveedores.' },
      { nombre: 'tipo', etiqueta: 'Documento', tipo: 'select', valor: factura?.tipo || 'factura', opciones: Object.entries(datos.tipos) },
      { nombre: 'numero', etiqueta: 'N° de factura', valor: factura?.numero, requerido: true },
      { nombre: 'monto', etiqueta: 'Monto total (con IVA)', tipo: 'monto', valor: factura?.monto, requerido: true },
      { nombre: 'fecha', etiqueta: 'Fecha de la factura', tipo: 'fecha', valor: factura?.fecha || hoy() },
      { nombre: 'vence', etiqueta: 'Vence (pagar hasta)', tipo: 'fecha', valor: factura?.vence, ayuda: 'Opcional. Las notas de crédito no vencen.' },
      { nombre: 'nota', etiqueta: 'Nota', valor: factura?.nota, ancho: true, placeholder: 'Opcional: pedido, despacho, observación…' },
    ],
    alEnviar: (v) => (factura ? api.put(`/api/proveedores/facturas/${factura.id}`, v) : api.post('/api/proveedores/facturas', v)),
  });
}

/** Marcar como pagadas (fecha y cómo se pagó). Devuelve la respuesta o null. */
function formPago(datos, facturas) {
  const total = facturas.reduce((s, f) => s + f.con_signo, 0);
  const cuantas = facturas.length === 1 ? `la factura N° ${facturas[0].numero} de ${facturas[0].proveedor}` : `${facturas.length} documentos`;
  return formulario({
    titulo: 'Marcar como pagado',
    intro: h('p', `Pagar ${cuantas}: `, h('b', conSigno(total)), '.'),
    aceptar: 'Marcar como pagado',
    campos: [
      { nombre: 'fecha', etiqueta: 'Fecha del pago', tipo: 'fecha', valor: hoy(), requerido: true },
      { nombre: 'medio', etiqueta: 'Cómo se pagó', tipo: 'select', valor: 'transferencia', opciones: Object.entries(datos.medios) },
    ],
    alEnviar: (v) => api.post('/api/proveedores/facturas/pagar', { ...v, ids: facturas.map((f) => f.id) }),
  });
}

function formProveedor(p = null) {
  return formulario({
    titulo: p ? 'Editar proveedor' : 'Nuevo proveedor',
    campos: [
      { nombre: 'nombre', etiqueta: 'Nombre', valor: p?.nombre, requerido: true, autofocus: true },
      { nombre: 'rut', etiqueta: 'RUT', valor: p?.rut, placeholder: '76.123.456-7' },
      { nombre: 'contacto', etiqueta: 'Contacto', valor: p?.contacto, placeholder: 'Vendedor, teléfono o correo' },
      { nombre: 'notas', etiqueta: 'Notas', tipo: 'area', valor: p?.notas, ancho: true },
    ],
    alEnviar: (v) => (p ? api.put(`/api/proveedores/${p.id}`, v) : api.post('/api/proveedores', v)),
  });
}

export async function montar(contenedor) {
  let datos;
  const resumen = h('div.kpis');
  const barra = h('div');
  const zonaLista = h('div');
  const zonaProveedores = h('div');
  const seleccion = new Set();
  let facturas = [];

  vaciar(contenedor,
    h('div.fila.entre', h('h2', 'Proveedores'),
      h('div.fila',
        h('button.btn', { type: 'button', onclick: () => administrarProveedores() }, 'Lista de proveedores'),
        h('button.btn.primario', { type: 'button', onclick: () => nuevaFactura() }, 'Anotar factura'))),
    resumen, barra, zonaLista, zonaProveedores);

  async function cargarTodo() {
    try {
      datos = await api.get('/api/proveedores');
    } catch (e) {
      avisoError(e);
      return;
    }
    const r = datos.resumen;
    vaciar(resumen,
      kpi(`Total por pagar · ${numero(r.n_por_pagar)} ${r.n_por_pagar === 1 ? 'factura' : 'facturas'}`, conSigno(r.por_pagar), true),
      kpi(`Vencidas · ${numero(r.n_vencidas)}`, h('span', { class: r.vencido ? 'rojo' : null }, pesos(r.vencido))),
      kpi(`Vencen en ${r.dias_por_vencer} días · ${numero(r.n_por_vencer)}`, pesos(r.por_vencer)),
      kpi('Pagado este mes', conSigno(r.pagado_mes)));
    pintarBarra();
    pintarProveedores();
    await cargarFacturas();
  }

  function pintarBarra() {
    const proveedor = h('select', { 'aria-label': 'Proveedor', style: { width: 'auto' }, onchange: (e) => { filtro.proveedor_id = e.target.value; cargarFacturas(); } },
      h('option', { value: '' }, 'Todos los proveedores'),
      datos.proveedores.map((p) => h('option', { value: p.id, selected: String(p.id) === String(filtro.proveedor_id) }, p.nombre)));
    const buscar = h('input', { type: 'search', placeholder: 'Buscar N° o proveedor', value: filtro.q, style: { maxWidth: '240px' } });
    buscar.addEventListener('input', debounce(() => { filtro.q = buscar.value.trim(); cargarFacturas(); }, 250));
    vaciar(barra,
      pestanas([['por_pagar', 'Por pagar'], ['pagada', 'Pagadas'], ['todas', 'Todas']], filtro.estado, (e) => { filtro.estado = e; pintarBarra(); cargarFacturas(); }),
      h('div.fila', { style: { margin: '.6rem 0' } }, proveedor, buscar));
  }

  async function cargarFacturas() {
    let r;
    try {
      r = await api.get(`/api/proveedores/facturas${qs({ estado: filtro.estado, proveedor_id: filtro.proveedor_id, q: filtro.q })}`);
    } catch (e) {
      avisoError(e);
      return;
    }
    facturas = r.facturas;
    for (const id of [...seleccion]) if (!facturas.some((f) => f.id === id && !f.pagada)) seleccion.delete(id);
    pintarLista(r.total);
  }

  function estadoDe(f) {
    if (f.pagada) return h('span.etiqueta.ok', `${f.tipo === 'nota_credito' ? 'Descontada' : 'Pagada'} ${fechaCorta(f.pagada)}`);
    if (f.tipo === 'nota_credito') return h('span.etiqueta', 'Por descontar');
    if (f.vencida) return h('span.etiqueta.mal', 'Vencida');
    return h('span.etiqueta.aviso', 'Por pagar');
  }

  function pintarLista(total) {
    const porPagar = facturas.filter((f) => !f.pagada);
    const elegidas = () => facturas.filter((f) => seleccion.has(f.id));
    const sumaElegidas = h('b');
    const botonPagar = h('button.btn.primario', { type: 'button', onclick: () => pagarElegidas() }, 'Marcar como pagadas');
    const barraSeleccion = h('div.fila.entre.panel', { style: { margin: '.6rem 0', padding: '.6rem .9rem' } },
      h('span', 'Seleccionadas: ', sumaElegidas), botonPagar);
    const actualizarSeleccion = () => {
      const lista = elegidas();
      barraSeleccion.style.display = lista.length ? '' : 'none';
      vaciar(sumaElegidas, `${lista.length} · ${conSigno(lista.reduce((s, f) => s + f.con_signo, 0))}`);
      todas.checked = porPagar.length > 0 && porPagar.every((f) => seleccion.has(f.id));
    };
    const todas = h('input', { type: 'checkbox', 'aria-label': 'Seleccionar todas', disabled: !porPagar.length, onchange: (e) => {
      porPagar.forEach((f) => (e.target.checked ? seleccion.add(f.id) : seleccion.delete(f.id)));
      zonaLista.querySelectorAll('input[data-factura]').forEach((c) => { c.checked = e.target.checked; });
      actualizarSeleccion();
    } });
    const casilla = (f) => (f.pagada ? '' : h('input', { type: 'checkbox', 'data-factura': f.id, 'aria-label': `Seleccionar N° ${f.numero}`, checked: seleccion.has(f.id),
      onclick: (e) => e.stopPropagation(),
      onchange: (e) => { if (e.target.checked) seleccion.add(f.id); else seleccion.delete(f.id); actualizarSeleccion(); } }));
    const tituloTotal = { por_pagar: 'Total por pagar de la lista', pagada: 'Total pagado de la lista', todas: 'Total de la lista' }[filtro.estado];
    vaciar(zonaLista,
      barraSeleccion,
      tabla([
        { titulo: todas, valor: casilla },
        { titulo: 'Fecha', valor: (f) => fechaCorta(f.fecha) },
        { titulo: 'Proveedor', valor: (f) => f.proveedor },
        { titulo: 'N° factura', valor: (f) => [f.tipo === 'nota_credito' ? h('span.etiqueta', 'NC') : null, ' ', h('span.mono', f.numero)] },
        { titulo: 'Vence', valor: (f) => h('span', { class: f.vencida ? 'rojo' : null }, fechaCorta(f.vence)) },
        { titulo: 'Monto', valor: (f) => h('span', { class: f.tipo === 'nota_credito' ? 'verde' : null }, conSigno(f.con_signo)), clase: 'num' },
        { titulo: 'Estado', valor: estadoDe },
        { titulo: '', valor: (f) => h('div.fila.fin',
          f.pagada ? null : h('button.btn.chico', { type: 'button', onclick: (e) => { e.stopPropagation(); pagar([f]); } }, f.tipo === 'nota_credito' ? 'Descontar' : 'Pagar'),
          h('button.btn.chico', { type: 'button', onclick: (e) => { e.stopPropagation(); verFactura(f); } }, 'Ver')) },
      ], facturas, {
        vacio: filtro.estado === 'por_pagar' ? 'No hay facturas por pagar. Anótalas con «Anotar factura».' : 'No hay facturas.',
        alClic: (f) => verFactura(f),
        pie: [{ valor: tituloTotal, colspan: 5 }, { valor: h('b', conSigno(total)), clase: 'num' }, { valor: '', colspan: 2 }],
      }));
    actualizarSeleccion();
  }

  function pintarProveedores() {
    const conDeuda = datos.proveedores.filter((p) => p.por_pagar);
    vaciar(zonaProveedores, h('div.panel', { style: { marginTop: '1rem' } },
      h('h3', 'Cuánto se le debe a cada proveedor'),
      tabla([
        { titulo: 'Proveedor', valor: (p) => p.nombre },
        { titulo: 'Facturas por pagar', valor: (p) => numero(p.n_por_pagar), clase: 'num' },
        { titulo: 'Vencido', valor: (p) => h('span', { class: p.vencido ? 'rojo' : 'suave' }, pesos(p.vencido)), clase: 'num' },
        { titulo: 'Total por pagar', valor: (p) => h('b', conSigno(p.por_pagar)), clase: 'num' },
      ], conDeuda, {
        vacio: 'No se le debe nada a ningún proveedor.',
        alClic: (p) => { filtro = { ...filtro, estado: 'por_pagar', proveedor_id: String(p.id) }; pintarBarra(); cargarFacturas(); },
        pie: conDeuda.length ? [{ valor: 'Total', colspan: 3 }, { valor: h('b', conSigno(datos.resumen.por_pagar)), clase: 'num' }] : null,
      }),
      conDeuda.length ? h('p.ayuda', 'Haz clic en un proveedor para ver solo sus facturas.') : null));
  }

  async function nuevaFactura() {
    const r = await formFactura(datos);
    if (!r) return;
    aviso(r.proveedor_nuevo ? `Factura anotada. «${r.proveedor || 'El proveedor'}» quedó en la lista de proveedores.` : 'Factura anotada.', 'ok');
    cargarTodo();
  }

  async function pagar(lista) {
    const r = await formPago(datos, lista);
    if (!r) return;
    lista.forEach((f) => seleccion.delete(f.id));
    aviso(`${r.pagadas === 1 ? 'Marcada como pagada' : `${r.pagadas} marcadas como pagadas`}: ${conSigno(r.total)}.`, 'ok');
    cargarTodo();
  }

  function pagarElegidas() {
    const lista = facturas.filter((f) => seleccion.has(f.id));
    if (lista.length) pagar(lista);
  }

  function verFactura(f) {
    const nombre = f.tipo === 'nota_credito' ? 'Nota de crédito' : 'Factura';
    const fila = (t, v) => h('div.fila.entre', h('span.suave', t), h('span', v));
    modal({
      titulo: `${nombre} N° ${f.numero} · ${f.proveedor}`,
      cuerpo: [
        fila('Monto', h('b', pesos(f.monto))),
        fila('Fecha', fechaCorta(f.fecha)),
        f.vence ? fila('Vence', fechaCorta(f.vence)) : null,
        fila('Estado', estadoDe(f)),
        f.pagada && f.medio_pago ? fila('Cómo se pagó', datos.medios[f.medio_pago] || f.medio_pago) : null,
        f.nota ? h('p', f.nota) : null,
      ],
      botones: [
        { texto: 'Borrar', clase: 'peligro', accion: async (m) => {
          if (!(await confirmar(`Borrar ${nombre.toLowerCase()}`, `¿Borrar la ${nombre.toLowerCase()} N° ${f.numero} de ${f.proveedor} (${pesos(f.monto)})?`, { aceptar: 'Borrar', peligro: true }))) return;
          try { await api.del(`/api/proveedores/facturas/${f.id}`); m.cerrar(); aviso('Borrada.', 'ok'); cargarTodo(); } catch (e) { m.error(e.message); }
        } },
        f.pagada ? { texto: 'Volver a «por pagar»', accion: async (m) => {
          try { await api.post(`/api/proveedores/facturas/${f.id}/por-pagar`); m.cerrar(); cargarTodo(); } catch (e) { m.error(e.message); }
        } } : { texto: f.tipo === 'nota_credito' ? 'Descontar' : 'Pagar', accion: (m) => { m.cerrar(); pagar([f]); } },
        { texto: 'Editar', clase: 'primario', accion: async (m) => {
          m.cerrar();
          const r = await formFactura(datos, f);
          if (r) { aviso('Guardada.', 'ok'); cargarTodo(); }
        } },
      ].filter(Boolean),
    });
  }

  function administrarProveedores() {
    const cuerpo = h('div');
    const pintar = () => vaciar(cuerpo, tabla([
      { titulo: 'Proveedor', valor: (p) => p.nombre },
      { titulo: 'RUT', valor: (p) => p.rut || '' },
      { titulo: 'Contacto', valor: (p) => p.contacto || '' },
      { titulo: 'Por pagar', valor: (p) => conSigno(p.por_pagar), clase: 'num' },
      { titulo: '', valor: (p) => h('div.fila.fin',
        h('button.btn.chico', { type: 'button', onclick: async (e) => { e.stopPropagation(); if (await formProveedor(p)) { await cargarTodo(); pintar(); } } }, 'Editar'),
        h('button.btn.chico.peligro', { type: 'button', onclick: async (e) => {
          e.stopPropagation();
          if (!(await confirmar('Quitar proveedor', `¿Quitar a «${p.nombre}» de la lista? Sus facturas pagadas se conservan.`, { aceptar: 'Quitar', peligro: true }))) return;
          try { await api.del(`/api/proveedores/${p.id}`); await cargarTodo(); pintar(); } catch (err) { avisoError(err); }
        } }, 'Quitar')) },
    ], datos.proveedores, { vacio: 'Todavía no hay proveedores: se agregan solos al anotar su primera factura.' }));
    pintar();
    modal({
      titulo: 'Lista de proveedores',
      ancho: 'muy-ancho',
      cuerpo,
      botones: [
        { texto: 'Nuevo proveedor', accion: async () => { if (await formProveedor()) { await cargarTodo(); pintar(); } } },
        { texto: 'Cerrar', clase: 'primario', accion: (m) => m.cerrar() },
      ],
    });
  }

  await cargarTodo();
}
