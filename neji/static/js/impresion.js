// Impresión: ticket de venta, corte de caja, cotización y etiquetas con código de barras.

import { estado } from './estado.js';
import { partir } from './renglones.js';
import { aviso, fecha, h, numero, pesos, unidadPlural } from './ui.js';

const NOMBRE_METODO = {
  efectivo: 'Efectivo', debito: 'Débito', credito: 'Crédito', transferencia: 'Transferencia', fiado: 'Fiado (crédito cliente)',
};
export const nombreMetodo = (m) => NOMBRE_METODO[m] || m;

// --- Impresora de tickets de este computador -------------------------------------------------------
// En NejiPOS.exe los tickets van directo a la impresora elegida en Configuración → Impresora de tickets
// (o a la que se detecta sola), sin cuadro de impresión. En el navegador se usa el cuadro de siempre.

const CLAVE_IMPRESORA = 'neji.impresora';
const PAPEL_COLUMNAS = { 80: 48, 58: 32 };

/** Configuración de la impresora de esta terminal (o null). */
export function leerImpresora() {
  try {
    const c = JSON.parse(localStorage.getItem(CLAVE_IMPRESORA) || 'null');
    return c && typeof c === 'object' ? c : null;
  } catch {
    return null;
  }
}

export function guardarImpresora(config) {
  try {
    if (config) localStorage.setItem(CLAVE_IMPRESORA, JSON.stringify(config));
    else localStorage.removeItem(CLAVE_IMPRESORA);
  } catch { /* sin almacenamiento */ }
  impresorasDetectadas = null;
}

const apiEscritorio = () => (window.pywebview?.api?.impresoras ? window.pywebview.api : null);
// NejiPOS.exe deja lista su API (window.pywebview.api) poco después de cargar la página. Se espera una sola
// vez, al comienzo: en el navegador, después de eso imprimir no espera nada.
const escritorioListo = new Promise((resolver) => {
  const listo = () => resolver(apiEscritorio());
  window.addEventListener('pywebviewready', listo, { once: true });
  setTimeout(listo, 1500);
});

/** La API del programa de escritorio (window.pywebview.api), o null en el navegador. */
export function escritorio() {
  const api = apiEscritorio();
  return api ? Promise.resolve(api) : escritorioListo;
}

let impresorasDetectadas = null; // se leen una vez por sesión

/** Impresoras de este computador según NejiPOS.exe: { ok, impresoras, error }. */
export async function listarImpresoras({ refrescar = false } = {}) {
  const api = await escritorio();
  if (!api) return { ok: false, escritorio: false, impresoras: [] };
  if (refrescar || !impresorasDetectadas) impresorasDetectadas = api.impresoras();
  const r = await impresorasDetectadas;
  if (!r?.ok) impresorasDetectadas = null;
  return { escritorio: true, impresoras: [], ...r };
}

/**
 * Elige sola la impresora de tickets: primero las que están en línea (la predeterminada, después
 * cualquiera) y, solo si no hay, una sin conexión.
 */
export function impresoraSugerida(impresoras) {
  const termicas = impresoras.filter((i) => !i.virtual && i.termica);
  return termicas.find((i) => i.predeterminada && !i.sin_conexion) || termicas.find((i) => !i.sin_conexion)
    || termicas[0] || null;
}

/** ¿El nombre dice que es de 58 mm? (POS-58, POS58, XP-58IIH, «58mm Printer») */
export const esDe58 = (i) => /(^|\D)58(\D|$)/.test(`${i?.nombre || ''} ${i?.controlador || ''}`);

const papelGeneral = () => (estado.config.ticket_ancho === '58' ? '58' : '80');

/**
 * Ancho del papel con esa configuración: el elegido en este computador o, si no se eligió, el de
 * Configuración → Ticket. Una impresora encontrada sola solo lo fija si su nombre lo dice.
 */
export function papelDe(config, general = papelGeneral()) {
  if (config?.automatica) return config.papel === '58' ? '58' : general;
  return config?.papel === '58' || config?.papel === '80' ? config.papel : general;
}

/** Letras por línea con esa configuración (las de «Letras por línea» o las del papel). */
export const columnasDe = (config, general) => Number(config?.columnas) || PAPEL_COLUMNAS[papelDe(config, general)];

export const papelTicket = () => papelDe(leerImpresora());

/** Configuración para una impresora encontrada sola. */
export const configAutomatica = (i) => ({
  nombre: i.nombre, modo: 'escpos', papel: esDe58(i) ? '58' : '', cortar: true, cajon: true, codigo: 'cp850', copias: 1, automatica: true,
});

/**
 * Impresora para los tickets de esta terminal: la elegida o, si no hay, la que se detecta sola. Una
 * encontrada sola se vuelve a revisar si ya no está o quedó sin conexión y hay otra de tickets en línea
 * (por ejemplo, Windows crea «POS-80C (Copiar 1)» al enchufarla en otro puerto USB).
 */
async function impresoraParaTickets() {
  const elegida = leerImpresora();
  if (elegida?.dialogo) return null; // eligió usar siempre el cuadro de impresión
  if (elegida?.nombre && !elegida.automatica) return elegida;
  const { ok, impresoras } = await listarImpresoras();
  if (!ok) return elegida?.nombre ? elegida : null;
  if (elegida?.nombre) {
    const actual = impresoras.find((i) => i.nombre === elegida.nombre);
    if (actual && !actual.sin_conexion) return elegida;
  }
  const sugerida = impresoraSugerida(impresoras);
  if (!sugerida || (elegida?.nombre && sugerida.sin_conexion)) return elegida?.nombre ? elegida : null;
  const config = configAutomatica(sugerida);
  guardarImpresora(config);
  return config;
}

/** Trabajo para NejiPOS.exe a partir de la configuración de la impresora. */
export function trabajoImpresion(config, bloques, { abrirCajon = false, papelGeneral: general } = {}) {
  const papel = papelDe(config, general);
  return {
    impresora: config.nombre, modo: config.modo === 'windows' ? 'windows' : 'escpos',
    columnas: Number(config.columnas) || PAPEL_COLUMNAS[papel], papel, cortar: config.cortar !== false,
    cajon: Boolean(abrirCajon && config.cajon), codigo: config.codigo || 'cp850', copias: Number(config.copias) || 1,
    sin_chino: typeof config.sin_chino === 'boolean' ? config.sin_chino : undefined, usb_directo: config.usb_directo !== false, bloques,
  };
}

/**
 * Ticket en pantalla → bloques que entiende la impresora: texto (izquierda o centrado), par
 * (izquierda y derecha), línea, espacio y el timbre del SII. «.g» es negrita y «.xl» letra grande.
 */
export function bloquesTicket(raiz) {
  const bloques = [];
  const estilo = (el) => ({ negrita: el.matches('.g, .xl, b, strong') || Boolean(el.querySelector(':scope > b, :scope > strong')), grande: el.matches('.xl') });
  const visitar = (el) => {
    for (const hijo of el.children) {
      if (hijo.matches('.timbre')) bloques.push({ tipo: 'timbre', ted: hijo.dataset.ted || '' });
      else if (hijo.matches('hr')) bloques.push({ tipo: 'linea' });
      else if (hijo.matches('.ln')) {
        const [izq, der] = hijo.children;
        bloques.push({ tipo: 'par', izq: izq?.textContent || '', der: der?.textContent || '', ...estilo(hijo) });
      } else if (hijo.matches('table')) {
        for (const tr of hijo.querySelectorAll('tr')) {
          const celdas = [...tr.children].map((c) => c.textContent.trim());
          bloques.push(celdas.length > 1 ? { tipo: 'par', izq: celdas.slice(0, -1).join(' '), der: celdas.at(-1) } : { tipo: 'texto', texto: celdas[0] || '' });
        }
      } else if (hijo.children.length && [...hijo.children].some((c) => c.matches('div, hr, table'))) {
        visitar(hijo);
      } else if (hijo.textContent.trim()) {
        bloques.push({ tipo: 'texto', texto: hijo.textContent, alinear: hijo.matches('.c') ? 'centro' : 'izq', ...estilo(hijo) });
      } else if (hijo.style?.height) {
        bloques.push({ tipo: 'espacio', lineas: 2 });
      }
    }
  };
  visitar(raiz);
  return bloques;
}

export function imprimirConDialogo(contenido) {
  const zona = document.getElementById('impresion');
  zona.replaceChildren(contenido);
  const limpiar = () => { zona.replaceChildren(); window.removeEventListener('afterprint', limpiar); };
  window.addEventListener('afterprint', limpiar);
  setTimeout(() => window.print(), 50);
}

/**
 * Imprime un ticket (directo en la impresora de tickets si está NejiPOS.exe) o cualquier hoja (etiquetas,
 * compras sugeridas) con el cuadro de impresión. `abrirCajon`: venta en efectivo con cajón conectado.
 */
export async function imprimir(contenido, { abrirCajon = false, papelGeneral: general } = {}) {
  if (contenido?.classList?.contains('ticket')) {
    const config = await impresoraParaTickets();
    if (config) {
      const api = await escritorio();
      const r = api ? await api.imprimir(trabajoImpresion(config, bloquesTicket(contenido), { abrirCajon, papelGeneral: general })) : null;
      if (r?.ok) {
        if (r.aviso) aviso(r.aviso, 'error', 8000);   // salió el ticket, pero no se abrió el cajón
        return true;
      }
      const motivo = (r?.error || 'el programa no respondió').replace(/[.\s]+$/, '');
      aviso(`No se pudo imprimir en «${config.nombre}»: ${motivo}. Se abre el cuadro de impresión.`, 'error', 8000);
    }
  }
  imprimirConDialogo(contenido);
  return false;
}

/** Abre el cajón de dinero (conectado a la impresora de tickets) sin imprimir nada. */
export async function abrirCajon() {
  const config = await impresoraParaTickets();
  const api = config?.cajon ? await escritorio() : null;
  if (api) await api.imprimir(trabajoImpresion(config, [], { abrirCajon: true }));
}

const ln = (izq, der, clase = '') => h(`div.ln${clase ? '.' + clase : ''}`, h('span', izq), h('span', der));

// --- Diseño del ticket (Configuración → Ticket) ------------------------------------------------------
// El encabezado y el pie son líneas de texto. {nombre}, {rut}, {giro}, {direccion}, {telefono} y {correo}
// se reemplazan por los datos de Configuración → Negocio; si el dato está vacío, la línea no sale.

export const DATOS_NEGOCIO = [
  ['nombre', 'Nombre', 'negocio_nombre'], ['rut', 'RUT', 'negocio_rut'], ['giro', 'Giro', 'negocio_giro'],
  ['direccion', 'Dirección', 'negocio_direccion'], ['telefono', 'Teléfono', 'negocio_telefono'], ['correo', 'Correo', 'negocio_email'],
];
export const PARTES_TICKET = [
  ['atendio', 'Caja y «Atendió»'], ['cliente', 'Cliente'], ['neto_iva', 'Neto e IVA'], ['cambio', 'Recibido y cambio'],
];

const linea = (texto, extra = {}) => ({ texto, alinear: 'centro', negrita: false, grande: false, ...extra });
// Los textos de antes (hasta 500 letras) se parten por palabras en líneas de 120 como máximo.
const textoEnLineas = (t) => String(t || '').split('\n').map((x) => x.trim()).filter(Boolean)
  .flatMap((x) => partir(x.split(/\s+/).join(' '), 120));

/** Diseño de fábrica: el mismo ticket de siempre. */
export function disenoPredeterminado(c = {}) {
  return {
    encabezado: [
      linea('{nombre}', { negrita: true, grande: true }), linea('RUT: {rut}'), linea('{giro}'), linea('{direccion}'), linea('Tel: {telefono}'),
      ...textoEnLineas(c.ticket_encabezado).map((t) => linea(t)),
    ],
    pie: [...textoEnLineas(c.ticket_pie ?? '¡Gracias por su compra!'), ...textoEnLineas(c.ticket_leyenda ?? 'Comprobante interno de venta')].map((t) => linea(t)),
    mostrar: Object.fromEntries(PARTES_TICKET.map(([k]) => [k, true])),
  };
}

/** Diseño guardado (o el de fábrica, armado con los textos de antes). */
export function disenoTicket(c = estado.config) {
  const base = disenoPredeterminado(c);
  try {
    const d = JSON.parse(c.ticket_diseno || 'null');
    if (d && Array.isArray(d.encabezado) && Array.isArray(d.pie)) return { ...base, ...d, mostrar: { ...base.mostrar, ...(d.mostrar || {}) } };
  } catch { /* diseño dañado: el de fábrica */ }
  return base;
}

/** Texto de una línea con los datos del negocio, o null si sus datos están vacíos. */
export function textoLinea(texto, c = estado.config) {
  let hayDato = false;
  let lleno = false;
  const t = String(texto || '').replace(/\{(\w+)\}/g, (todo, clave) => {
    const dato = DATOS_NEGOCIO.find(([k]) => k === clave);
    if (!dato) return todo;
    hayDato = true;
    const valor = String(c[dato[2]] || '').trim();
    if (valor) lleno = true;
    return valor;
  });
  if (hayDato && !lleno) return null;
  return t.trim() ? t : null;
}

/** Líneas del diseño → elementos del ticket (.c centrado, .g negrita, .xl grande; los lee bloquesTicket). */
function lineasTicket(lineas, c) {
  return lineas.map((l) => {
    const t = textoLinea(l.texto, c);
    if (t === null) return null;
    return h(`div${l.alinear === 'izq' ? '' : '.c'}${l.grande ? '.xl' : l.negrita ? '.g' : ''}`, t);
  });
}

function encabezadoNegocio(diseno = disenoTicket()) {
  return lineasTicket(diseno.encabezado, estado.config);
}

const claseTicket = () => `div.ticket${papelTicket() === '58' ? '.t58' : ''}`;

// --- Boleta y factura electrónica (SII) -------------------------------------------------------------------
// Con la boleta electrónica activada, el ticket es la representación impresa del documento: el recuadro con
// el RUT, el tipo y el folio, los datos del emisor (y del cliente en la factura), el IVA y el timbre (PDF417).

const TIPOS_VENTA = [33, 34, 39, 41];
const FACTURAS = [33, 34];
const SIN_IVA = [34, 41];
const NOMBRE_CORTO = { 33: 'Factura electrónica', 34: 'Factura exenta electrónica', 39: 'Boleta electrónica', 41: 'Boleta exenta electrónica', 61: 'Nota de crédito electrónica' };
const RUT_CONSUMIDOR_FINAL = '66666666-6';

/** La boleta o factura electrónica de la venta (no cuentan las que rechazó el SII), o null. */
export const documentoDeVenta = (v) => [...(v?.documentos || [])].reverse()
  .find((d) => TIPOS_VENTA.includes(d.tipo) && d.estado !== 'rechazado') || null;

/** 76354771-K → 76.354.771-K */
export function rutConPuntos(rut) {
  const m = /^(\d+)-([\dkK])$/.exec(String(rut || '').replace(/\./g, '').trim());
  return m ? `${m[1].replace(/\B(?=(\d{3})+(?!\d))/g, '.')}-${m[2].toUpperCase()}` : String(rut || '');
}

/**
 * El timbre (PDF417) como imagen: `filas` de '0' y '1' que arma el servidor; cada fila mide `altoFila` módulos de
 * alto. `girado`: a lo largo del papel (en 58 mm no cabe derecho con módulos que la impresora alcance a marcar).
 */
export function svgPdf417(filas, altoFila = 3, girado = false) {
  const margen = 2;
  const ancho = filas[0]?.length || 0;
  const alto = filas.length * altoFila;
  let trazo = '';
  filas.forEach((fila, y) => {
    for (let x = 0; x < ancho;) {
      if (fila[x] !== '1') { x++; continue; }
      let w = 1;
      while (fila[x + w] === '1') w++;
      // Girado 90° a la derecha: las filas quedan de derecha a izquierda y el largo del código, hacia abajo.
      trazo += girado ? `M${margen + alto - (y + 1) * altoFila} ${x + margen}h${altoFila}v${w}h-${altoFila}z`
        : `M${x + margen} ${margen + y * altoFila}h${w}v${altoFila}h-${w}z`;
      x += w;
    }
  });
  const [vw, vh] = girado ? [alto, ancho] : [ancho, alto];
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vw + 2 * margen} ${vh + 2 * margen}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><path fill="#000" d="${trazo}"/></svg>`,
    'image/svg+xml').documentElement;
  return document.importNode(svg, true);
}

/** El recuadro del documento: RUT del emisor, tipo y número, y la oficina del SII. */
function recuadroDte(doc) {
  const e = doc.emisor || {};
  return h('div.recuadro-dte',
    h('div.c.g', `R.U.T.: ${rutConPuntos(e.rut)}`),
    h('div.c.g', doc.nombre),
    h('div.c.g', `N° ${doc.folio}`),
    e.oficina_sii ? h('div.c', `S.I.I. - ${e.oficina_sii.toUpperCase()}`) : null);
}

/** Razón social, giro y dirección del emisor que no salgan ya en el encabezado del ticket. */
function datosEmisor(doc, encabezado) {
  const e = doc.emisor || {};
  const textos = encabezado.filter(Boolean).map((el) => el.textContent.toLowerCase());
  const falta = (valor) => Boolean(valor) && !textos.some((t) => t.includes(String(valor).toLowerCase()));
  return [
    falta(e.razon_social) ? h('div.c.g', e.razon_social) : null,
    falta(e.giro) ? h('div.c', `Giro: ${e.giro}`) : null,
    falta(e.direccion) || falta(e.comuna) ? h('div.c', [e.direccion, e.comuna].filter(Boolean).join(', ')) : null,
  ];
}

/** Datos del cliente (en la factura y en la nota de crédito de una factura). */
function datosReceptor(doc) {
  const r = doc.receptor;
  if (!r?.rut || r.rut === RUT_CONSUMIDOR_FINAL) return null;
  return [
    h('div', `Señor(es): ${r.razon_social}`),
    h('div', `R.U.T.: ${rutConPuntos(r.rut)}`),
    r.giro ? h('div', `Giro: ${r.giro}`) : null,
    r.direccion || r.comuna ? h('div', `Dirección: ${[r.direccion, r.comuna].filter(Boolean).join(', ')}`) : null,
  ];
}

function totalesDte(doc) {
  const tasa = estado.config.iva_porcentaje || 19;
  return [
    doc.neto ? ln('Neto', pesos(doc.neto)) : null,
    doc.exento ? ln('Exento', pesos(doc.exento)) : null,
    SIN_IVA.includes(doc.tipo) ? null : ln(`IVA (${tasa}%)`, pesos(doc.iva)),
  ];
}

/** El timbre electrónico y las leyendas que pide el SII. */
function timbreDte(doc, papel) {
  const r = doc.resolucion || {};
  return [
    // Como en la impresión directa: en 80 mm, filas de 2,5 módulos (unos 6,6 x 3,5 cm); en 58 mm, girado (3,8 x 7,8 cm).
    h('div.timbre', { class: papel === '58' ? 'girado' : null, 'data-ted': doc.ted },
      papel === '58' ? svgPdf417(doc.pdf417_58 || doc.pdf417, 3, true) : svgPdf417(doc.pdf417, 2.5)),
    h('div.c', 'Timbre Electrónico SII'),
    h('div.c', `Res. N° ${r.numero ?? 0}${r.anio ? ' de ' + r.anio : ''}`),
    h('div.c', 'Verifique documento: www.sii.cl'),
  ];
}

// Con documento electrónico, el ticket ya no es un «comprobante interno».
const LEYENDA_INTERNA = /comprobante interno|no v[aá]lido como (boleta|factura|documento)/i;

/**
 * Ticket de venta. `diseno` y `papel` sirven para la vista previa de Configuración → Ticket (lo que
 * todavía no se guarda); si no, se usan los guardados. Si la venta tiene boleta o factura electrónica, el
 * ticket la lleva (recuadro, datos del emisor y del cliente, IVA y timbre).
 */
export function ticketVenta(v, { destacarAtendio = false, diseno = disenoTicket(), papel = null } = {}) {
  const c = estado.config;
  const ver = diseno.mostrar;
  const doc = documentoDeVenta(v);
  const factura = doc && FACTURAS.includes(doc.tipo);
  const pagos = v.pagos.map((p) => ln(nombreMetodo(p.metodo), pesos(p.monto)));
  const efectivo = v.pagos.find((p) => p.metodo === 'efectivo');
  const encabezado = encabezadoNegocio(diseno);
  const pie = doc ? diseno.pie.filter((l) => !LEYENDA_INTERNA.test(l.texto)) : diseno.pie;
  return h(papel ? `div.ticket${papel === '58' ? '.t58' : ''}` : claseTicket(),
    encabezado,
    doc ? [h('hr'), recuadroDte(doc), h('hr'), datosEmisor(doc, encabezado)] : null,
    h('hr'),
    doc ? ln(fecha(v.fecha), `Venta ${v.folio}`) : ln(`Folio: ${v.folio}`, fecha(v.fecha)),
    ver.atendio || destacarAtendio ? h('div', { class: destacarAtendio ? 'atendio' : null }, `${v.caja} · Atendió: ${v.atendio || v.usuario}`) : null,
    factura ? datosReceptor(doc)
      : v.cliente && ver.cliente ? h('div', `Cliente: ${v.cliente}${v.cliente_rut ? ' · ' + v.cliente_rut : ''}`) : null,
    h('hr'),
    v.items.map((i) => [
      h('div', i.descripcion),
      ln(`  ${numero(i.cantidad)} x ${pesos(i.precio_unitario)}${i.tipo_precio === 'mayoreo' ? ' (may.)' : ''}`, pesos(i.importe)),
    ]),
    h('hr'),
    v.descuento ? [ln('Subtotal', pesos(v.subtotal)), ln('Descuento', `-${pesos(v.descuento)}`)] : null,
    ln('TOTAL', pesos(v.total), 'xl'),
    doc ? totalesDte(doc) : ver.neto_iva ? [
      ln(`Neto`, pesos(v.neto)),
      ln(`IVA (${c.iva_porcentaje || 19}%)`, pesos(v.iva)),
      v.exento ? ln('Exento', pesos(v.exento)) : null,
    ] : null,
    h('hr'),
    pagos,
    efectivo && ver.cambio ? [
      v.redondeo ? ln('Redondeo (Ley 20.956)', pesos(v.redondeo)) : null,
      ln('Recibido', pesos(v.efectivo_recibido)),
      ln('Cambio', pesos(v.cambio), 'g'),
    ] : null,
    v.pagos.some((p) => p.metodo === 'fiado') && v.cliente_saldo != null ? ln('Saldo pendiente cliente', pesos(v.cliente_saldo)) : null,
    v.devuelto ? ln('Devuelto', `-${pesos(v.devuelto)}`) : null,
    doc ? [h('hr'), timbreDte(doc, papel || papelTicket())] : null,
    pie.length ? [h('hr'), lineasTicket(pie, c)] : null,
    h('div', { style: { height: '8mm' } }));
}

/** Nota de crédito electrónica de una devolución (`doc`: uno de `venta.documentos`). */
export function ticketNotaCredito(v, doc) {
  const encabezado = encabezadoNegocio();
  return h(claseTicket(),
    encabezado,
    h('hr'), recuadroDte(doc), h('hr'), datosEmisor(doc, encabezado),
    h('hr'),
    ln(fecha(doc.fecha, false), `Venta ${v.folio}`),
    datosReceptor(doc),
    (doc.referencias || []).map((r) => [
      h('div', `Referencia: ${NOMBRE_CORTO[r.tipo] || 'Documento'} N° ${r.folio} del ${fecha(r.fecha, false)}`),
      h('div', r.codigo === 1 ? 'Anula el documento de referencia' : 'Corrige montos (devolución parcial)'),
      r.razon ? h('div', `Motivo: ${r.razon}`) : null,
    ]),
    h('hr'),
    (doc.lineas || []).map((l) => [h('div', l.nombre), ln(`  ${numero(l.cantidad)} x ${pesos(l.precio)}`, pesos(l.monto))]),
    h('hr'),
    doc.descuento ? ln('Descuento', `-${pesos(doc.descuento)}`) : null,
    ln('TOTAL', pesos(doc.total), 'xl'),
    totalesDte(doc),
    h('hr'),
    timbreDte(doc, papelTicket()),
    h('div', { style: { height: '8mm' } }));
}

export function ticketCorte(t) {
  const m = t.por_metodo || {};
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', t.estado === 'cerrado' ? 'CORTE DE CAJA' : 'ESTADO DE CAJA (turno abierto)'),
    h('div', `${t.caja} · Turno #${t.id}`),
    h('div', `Abrió: ${t.usuario} ${fecha(t.abierto)}`),
    t.cerrado ? h('div', `Cerró: ${t.usuario_cierre || ''} ${fecha(t.cerrado)}`) : null,
    h('hr'),
    h('div.g', 'Dinero en caja'),
    ln('Fondo inicial', pesos(t.fondo_inicial)),
    ln('+ Ventas en efectivo', pesos(t.ventas_efectivo)),
    ln('+ Abonos en efectivo', pesos(t.abonos_efectivo)),
    ln('+ Entradas', pesos(t.entradas)),
    ln('- Salidas', pesos(t.salidas)),
    ln('- Devoluciones', pesos(t.devoluciones_efectivo)),
    ln('= Esperado en caja', pesos(t.efectivo_esperado), 'g'),
    t.estado === 'cerrado' ? [
      ln('Contado', pesos(t.efectivo_contado)),
      ln(t.diferencia < 0 ? 'FALTANTE' : t.diferencia > 0 ? 'SOBRANTE' : 'Diferencia', pesos(t.diferencia), 'g'),
    ] : null,
    h('hr'),
    h('div.g', `Ventas (${t.n_ventas})`),
    Object.entries(m).filter(([, v]) => v).map(([k, v]) => ln(nombreMetodo(k), pesos(v))),
    t.redondeo ? ln('Redondeo', pesos(t.redondeo)) : null,
    ln('Total ventas', pesos(t.total_ventas), 'g'),
    t.devoluciones ? ln('Devoluciones', pesos(t.devoluciones)) : null,
    t.abonos_otros ? ln('Abonos con tarjeta/transf.', pesos(t.abonos_otros)) : null,
    t.ganancia != null ? ln('Ganancia estimada', pesos(t.ganancia)) : null,
    t.departamentos?.length ? [h('hr'), h('div.g', 'Por departamento'), t.departamentos.map((d) => ln(d.departamento, pesos(d.total)))] : null,
    t.movimientos?.length ? [h('hr'), h('div.g', 'Entradas y salidas'), t.movimientos.map((mv) => ln(`${mv.tipo === 'entrada' ? '+' : '-'} ${mv.concepto}`, pesos(mv.monto)))] : null,
    t.nota ? [h('hr'), h('div', `Nota: ${t.nota}`)] : null,
    h('div', { style: { height: '8mm' } }));
}

/** Corte general: todas las cajas cerradas juntas desde la caja principal. */
export function ticketCorteGeneral(g) {
  const t = g.totales;
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', `CORTE GENERAL N° ${g.id}`),
    h('div', fecha(g.fecha)),
    h('div', `Hizo: ${g.usuario} · ${g.caja}`),
    h('hr'),
    g.turnos.map((x) => [
      h('div.g', `${x.caja} · Turno #${x.id}`),
      h('div', `Abrió: ${x.usuario} ${fecha(x.abierto)}`),
      ln('Ventas', `${x.n_ventas} · ${pesos(x.total_ventas)}`),
      ln('Esperado en caja', pesos(x.efectivo_esperado)),
      ln('Contado', pesos(x.efectivo_contado)),
      ln(x.diferencia < 0 ? 'FALTANTE' : x.diferencia > 0 ? 'SOBRANTE' : 'Diferencia', pesos(x.diferencia)),
      h('hr'),
    ]),
    h('div.g', 'TOTAL DE TODAS LAS CAJAS'),
    ln('Fondos iniciales', pesos(t.fondo_inicial)),
    ln('+ Ventas en efectivo', pesos(t.ventas_efectivo)),
    ln('+ Abonos en efectivo', pesos(t.abonos_efectivo)),
    ln('+ Entradas', pesos(t.entradas)),
    ln('- Salidas', pesos(t.salidas)),
    ln('- Devoluciones', pesos(t.devoluciones_efectivo)),
    ln('= Esperado', pesos(t.efectivo_esperado), 'g'),
    ln('Contado', pesos(t.efectivo_contado)),
    ln(t.diferencia < 0 ? 'FALTANTE' : t.diferencia > 0 ? 'SOBRANTE' : 'Diferencia', pesos(t.diferencia), 'g'),
    h('hr'),
    h('div.g', `Ventas (${t.n_ventas})`),
    Object.entries(t.por_metodo).filter(([, v]) => v).map(([k, v]) => ln(nombreMetodo(k), pesos(v))),
    t.redondeo ? ln('Redondeo', pesos(t.redondeo)) : null,
    ln('Total ventas', pesos(t.total_ventas), 'g'),
    t.devoluciones ? ln('Devoluciones', pesos(t.devoluciones)) : null,
    t.abonos_otros ? ln('Abonos con tarjeta/transf.', pesos(t.abonos_otros)) : null,
    t.ganancia != null ? ln('Ganancia estimada', pesos(t.ganancia)) : null,
    g.por_cajero.length ? [h('hr'), h('div.g', 'Por cajero'), g.por_cajero.map((c) => ln(`${c.cajero} (${c.n_ventas})`, pesos(c.total)))] : null,
    t.departamentos.length ? [h('hr'), h('div.g', 'Por departamento'), t.departamentos.map((d) => ln(d.departamento, pesos(d.total)))] : null,
    g.nota ? [h('hr'), h('div', `Nota: ${g.nota}`)] : null,
    h('div', { style: { height: '8mm' } }));
}

export function ticketCotizacion(q) {
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', `COTIZACIÓN N° ${q.folio}`),
    h('div', fecha(q.fecha)),
    q.cliente_nombre ? h('div', `Cliente: ${q.cliente_nombre}${q.cliente_rut ? ' · ' + q.cliente_rut : ''}`) : null,
    h('hr'),
    q.items.map((i) => [h('div', i.descripcion), ln(`  ${numero(i.cantidad)} x ${pesos(i.precio_unitario)}`, pesos(i.importe))]),
    h('hr'),
    q.descuento ? [ln('Subtotal', pesos(q.subtotal)), ln('Descuento', `-${pesos(q.descuento)}`)] : null,
    ln('TOTAL', pesos(q.total), 'xl'),
    h('hr'),
    h('div.c', 'Precios sujetos a cambio y a disponibilidad de stock.'),
    q.nota ? h('div', q.nota) : null,
    h('div', { style: { height: '8mm' } }));
}

/** Cantidad de principio activo en la unidad más legible: 15000 mg -> "15 g". */
export function cantidadLegible(valor, unidad) {
  let v = valor;
  let u = unidad;
  if (u === 'mcg' && Math.abs(v) >= 1000) { v /= 1000; u = 'mg'; }
  if (u === 'mg' && Math.abs(v) >= 1000) { v /= 1000; u = 'g'; }
  if (u === 'g' && Math.abs(v) > 0 && Math.abs(v) < 1) { v *= 1000; u = 'mg'; }
  if (u === 'mg' && Math.abs(v) > 0 && Math.abs(v) < 1) { v *= 1000; u = 'mcg'; }
  return `${numero(Math.round(v * 1000) / 1000)} ${u}`;
}

const ESTADO_RECETA = { pendiente: 'PENDIENTE DE PAGO', vendida: 'VENDIDA', anulada: 'ANULADA' };

/** Orden de preparación / presupuesto de una receta magistral. */
export function ticketReceta(r) {
  const c = estado.config;
  return h(claseTicket(),
    encabezadoNegocio(),
    h('hr'),
    h('div.c.g', `RECETA MAGISTRAL N° ${r.folio}`),
    ln(fecha(r.fecha), ESTADO_RECETA[r.estado] || ''),
    r.paciente ? h('div', `Paciente: ${r.paciente}${r.rut_paciente ? ' · ' + r.rut_paciente : ''}`) : null,
    r.medico ? h('div', `Médico: ${r.medico}`) : null,
    h('hr'),
    h('div.g', `${r.forma} × ${numero(r.cantidad)} ${unidadPlural(r.cantidad, r.unidad, r.nombre_unidad)}`),
    r.componentes.length ? [
      h('div', 'Composición por unidad:'),
      r.componentes.map((x) => ln(`  ${x.nombre}`, `${numero(x.dosis)} ${x.unidad}`)),
      h('hr'),
      h('div', 'Total a pesar:'),
      r.componentes.map((x) => ln(`  ${x.nombre}`, cantidadLegible(x.cantidad_total, x.unidad_precio))),
    ] : h('div', 'Sin principios activos (solo base).'),
    r.indicaciones ? [h('hr'), h('div', `Indicaciones: ${r.indicaciones}`)] : null,
    h('hr'),
    ln('Neto', pesos(r.neto)),
    ln(`IVA (${c.iva_porcentaje || 19}%)`, pesos(r.iva)),
    ln('TOTAL', pesos(r.total), 'xl'),
    r.venta_folio ? h('div', `Vendida en folio ${r.venta_folio}`) : null,
    h('hr'),
    h('div', `Preparó: ${r.usuario || ''}`),
    h('div', { style: { height: '8mm' } }));
}

export function hojaComprasSugeridas(productos) {
  return h('div.hoja',
    h('h2', `Compras sugeridas — ${estado.config.negocio_nombre}`),
    h('p', `Generado: ${new Date().toLocaleString('es-CL')}`),
    h('table', { border: '1', cellpadding: '4', style: { borderCollapse: 'collapse', width: '100%' } },
      h('thead', h('tr', ['Código', 'Producto', 'Existencia', 'Mínimo', 'Vendido 30 días', 'Comprar', 'Costo est.'].map((t) => h('th', t)))),
      h('tbody', productos.map((p) => h('tr',
        h('td', p.codigo), h('td', p.descripcion), h('td', numero(p.existencia)), h('td', numero(p.minimo)),
        h('td', numero(p.vendidos_30d)), h('td', h('b', numero(p.sugerido))), h('td', pesos(p.costo_estimado)))))),
    h('p', h('b', `Total estimado: ${pesos(productos.reduce((s, p) => s + p.costo_estimado, 0))}`)));
}

// --- Código de barras Code 128 ----------------------------------------------

const PATRONES = [
  '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
  '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
  '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
  '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
  '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
  '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
  '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
  '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
  '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
];
const INICIO_B = 104, INICIO_C = 105, CAMBIO_A_B = 100, PARADA = 106;

/** Valores Code 128 para un texto: usa el set C en códigos numéricos (más compacto) y B para el resto. */
export function valoresCode128(texto) {
  const valores = [];
  if (/^\d{4,}$/.test(texto)) {
    const pares = texto.length - (texto.length % 2);
    valores.push(INICIO_C);
    for (let i = 0; i < pares; i += 2) valores.push(parseInt(texto.slice(i, i + 2), 10));
    if (pares < texto.length) valores.push(CAMBIO_A_B, texto.charCodeAt(pares) - 32);
  } else {
    valores.push(INICIO_B);
    for (const ch of texto) {
      const cod = ch.charCodeAt(0);
      valores.push(cod >= 32 && cod <= 127 ? cod - 32 : 0);
    }
  }
  let suma = valores[0];
  for (let i = 1; i < valores.length; i++) suma += valores[i] * i;
  valores.push(suma % 103, PARADA);
  return valores;
}

export function svgCode128(texto) {
  const anchos = valoresCode128(texto).map((v) => PATRONES[v]).join('');
  const margen = 10;
  let x = margen;
  const rects = [];
  for (let i = 0; i < anchos.length; i++) {
    const w = parseInt(anchos[i], 10);
    if (i % 2 === 0) rects.push(`<rect x="${x}" y="0" width="${w}" height="50"/>`);
    x += w;
  }
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${x + margen} 50" preserveAspectRatio="none" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><g fill="#000">${rects.join('')}</g></svg>`,
    'image/svg+xml').documentElement;
  return document.importNode(svg, true);
}

/** items: [{ producto, copias }] */
export function hojaEtiquetas(items) {
  const etiquetas = [];
  for (const { producto, copias } of items) {
    for (let i = 0; i < copias; i++) {
      etiquetas.push(h('div.etiqueta-prod',
        h('div.d', producto.descripcion),
        h('div.p', pesos(producto.precio_venta) + (producto.tipo_venta === 'granel' ? ' /kg' : '')),
        svgCode128(producto.codigo),
        h('div.cod', producto.codigo)));
    }
  }
  return h('div.etiquetas', etiquetas);
}
