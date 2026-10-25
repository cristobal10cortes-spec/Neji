// Lector de códigos de barras: lo que escanea va siempre a la venta.
//
// Un lector USB «de teclado» escribe el código muy rápido (unas pocas milésimas entre letra y letra) y
// termina con Enter. Aquí se reconoce esa ráfaga: si el foco no está en el campo de la venta ni en otro campo
// para códigos (está en un buscador de clientes, en un botón o en otra pantalla), lo escrito se quita de donde
// cayó y el código se agrega al ticket.
// Los lectores que se conectan como puerto COM USB los lee NejiPOS.exe (neji/lector_serie.py) y sus
// códigos llegan por recibir().

import { estado } from './estado.js';
import { escritorio } from './impresion.js';
import { aviso, cerrarModales, modalAbierto } from './ui.js';

const CLAVE = 'neji.lector';
const RAPIDO = 50;   // ms entre teclas: nadie escribe así de rápido; un lector, siempre
const MINIMO = 4;    // letras de un código
const SIN_FIN = 150; // ms sin teclas: un lector que no manda Enter al final ya terminó
const MINIMO_SIN_FIN = 6; // sin Enter al final se pide un código más largo (nadie escribe 6 letras así)

/** Configuración del lector en esta terminal: { forzar } (de fábrica, todo va a la venta). */
export function leerLector() {
  try {
    return { forzar: true, ...JSON.parse(localStorage.getItem(CLAVE) || '{}') };
  } catch {
    return { forzar: true };
  }
}

export function guardarLector(cambios) {
  try {
    localStorage.setItem(CLAVE, JSON.stringify({ ...leerLector(), ...cambios }));
  } catch { /* sin almacenamiento: queda lo de fábrica */ }
}

let llevar = null;   // (codigo) => lo agrega a la venta (lo da app.js)
let prueba = null; // «Probar el lector» (Configuración → Esta terminal): muestra la lectura en vez de vender

/**
 * Mientras `elemento` esté en pantalla, cada lectura va a `alLeer(codigo, origen)` en vez de a la venta
 * (al salir de esa pantalla, el lector vuelve solo a la venta).
 */
export function probarLector(elemento, alLeer) {
  prueba = { elemento, alLeer };
}

/** La prueba en curso, si su pantalla sigue abierta. */
function probando() {
  if (prueba && !prueba.elemento.isConnected) prueba = null;
  return prueba?.alLeer || null;
}

const editable = (el) => Boolean(el) && (el.isContentEditable
  || (el.matches?.('input, textarea') && !el.disabled && !el.readOnly
    && !['checkbox', 'radio', 'button', 'submit', 'reset', 'file', 'range', 'color'].includes(el.type)));
const modalArriba = () => [...document.querySelectorAll('#modales .modal')].at(-1) || null;
const enLaVenta = () => (location.hash.slice(1) || 'ventas') === 'ventas';

/** Palabras de un campo hecho para escanear: el código de un producto, el verificador, buscar en inventario... */
const PARA_CODIGOS = /c[oó]digo|barras|escane|\bean\b|\bsku\b/i;

/** Si `campo` es para escribir o escanear un código (data-lector="aqui" lo fuerza, "venta" lo niega). */
function quiereCodigo(campo) {
  if (!editable(campo)) return false;
  if (campo.dataset.lector) return campo.dataset.lector === 'aqui';
  return PARA_CODIGOS.test([campo.name, campo.id, campo.getAttribute('aria-label'), campo.placeholder].filter(Boolean).join(' '));
}

/**
 * Qué hacer con una lectura según dónde está el foco:
 * - 'normal': se deja como está (el campo de la venta, o un campo para códigos, como el del producto nuevo,
 *   el verificador de precios o el buscador del inventario);
 * - 'venta': se lleva al ticket (desde cualquier otro campo, un botón u otra pantalla);
 * - 'avisar': hay una ventana abierta (cobro, cantidad, un formulario...): no se escribe ahí y se avisa.
 */
function destino(campo) {
  const modal = modalAbierto() ? modalArriba() : null;
  if (enLaVenta() && !modal) return campo?.id === 'codigo-producto' ? 'normal' : 'venta';
  if (quiereCodigo(campo) && (!modal || modal.contains(campo))) return 'normal';
  if (modal) return modal.dataset.lector === 'cerrar' ? 'venta' : 'avisar';
  return 'venta';
}

function llevarAVenta(codigo) {
  // Solo llega aquí con la ventana «Venta registrada» abierta (o ninguna): se cierra y sigue la venta.
  if (modalAbierto()) cerrarModales();
  llevar?.(codigo);
}

const AVISO_VENTANA = 'Hay una ventana abierta: termínala o ciérrala (Esc) y vuelve a escanear.';

// --- Lectores de teclado -------------------------------------------------------------------------------

let rafaga = null;
let temporizador = null;

const esLectura = (r, ahora, limite, minimo = MINIMO) => Boolean(r) && r.letras.length >= minimo
  && r.rapidas === r.letras.length - 1 && ahora - r.ultimo <= limite;

/**
 * No era el lector (alguien que escribe muy rápido): las letras que se retuvieron mientras parecía una lectura
 * se escriben en el campo, donde iban.
 */
function soltar(r) {
  // Sin campo al empezar (p. ej. un botón de la venta), las primeras letras las llevó la venta a su buscador.
  const c = r?.campo?.isConnected ? r.campo : editable(document.activeElement) ? document.activeElement : null;
  if (!r?.tragadas || !c) return;
  const desde = c.selectionStart ?? c.value.length;
  const hasta = c.selectionEnd ?? desde;
  c.value = c.value.slice(0, desde) + r.tragadas + c.value.slice(hasta);
  try { c.setSelectionRange(desde + r.tragadas.length, desde + r.tragadas.length); } catch { /* campos sin selección */ }
  r.tragadas = '';
  c.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Lo que alcanzó a escribirse antes de saber que era el lector se quita del campo. */
function restaurar(r) {
  if (!r.campo || r.valor === null || r.campo.value === r.valor) return;
  r.campo.value = r.valor;
  try { r.campo.setSelectionRange(r.desde, r.hasta); } catch { /* campos sin selección */ }
  r.campo.dispatchEvent(new Event('input', { bubbles: true }));
}

function terminar(r, e) {
  const codigo = r.letras.trim();
  const alProbar = probando();
  const accion = alProbar ? 'probar' : r.accion ?? (leerLector().forzar ? destino(r.campo) : 'normal');
  if (accion === 'normal') return; // el Enter sigue su camino (p. ej. el campo de la venta lo agrega)
  if (e) {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
  restaurar(r);
  if (accion === 'probar') alProbar(codigo, 'lector USB (teclado)');
  else if (accion === 'avisar') aviso(AVISO_VENTANA, 'error', 5000);
  else llevarAVenta(codigo);
}

function teclear(e) {
  if (!estado.usuario || e.key === 'Shift') return; // un código con mayúsculas trae Mayús entre letra y letra
  const ahora = e.timeStamp;
  if (e.ctrlKey || e.altKey || e.metaKey || ((e.key.length !== 1 || e.repeat) && e.key !== 'Enter' && e.key !== 'Tab')) {
    // Un atajo, otra tecla o una tecla mantenida: no es el lector.
    clearTimeout(temporizador);
    soltar(rafaga);
    rafaga = null;
    return;
  }
  if (e.key === 'Enter' || e.key === 'Tab') {
    clearTimeout(temporizador);
    const r = rafaga;
    rafaga = null;
    if (esLectura(r, ahora, 100)) terminar(r, e);
    else soltar(r); // antes de que el Enter haga lo suyo con el campo
    return;
  }
  if (!rafaga || ahora - rafaga.ultimo > RAPIDO) {
    if (rafaga) {
      // La ráfaga anterior terminó sin Enter: era un lector que no lo manda, o alguien escribiendo rápido.
      clearTimeout(temporizador);
      if (esLectura(rafaga, ahora, Infinity, MINIMO_SIN_FIN)) terminar(rafaga, null);
      else soltar(rafaga);
    }
    // Puede empezar una lectura: se anota cómo estaba el campo para poder dejarlo igual.
    const campo = editable(e.target) ? e.target : null;
    rafaga = {
      letras: '', rapidas: 0, ultimo: ahora, campo, accion: null, tragadas: '',
      valor: campo ? campo.value : null, desde: campo?.selectionStart ?? null, hasta: campo?.selectionEnd ?? null,
    };
  } else {
    rafaga.rapidas += 1;
  }
  rafaga.letras += e.key;
  rafaga.ultimo = ahora;
  if (rafaga.rapidas >= 2) {
    // Tres letras seguidas así de rápido: es el lector. Lo que sigue no se escribe donde está el foco.
    rafaga.accion ??= probando() ? 'probar' : leerLector().forzar ? destino(rafaga.campo) : 'normal';
    if (rafaga.accion !== 'normal') {
      e.preventDefault();
      rafaga.tragadas += e.key;
    }
  }
  clearTimeout(temporizador);
  const r = rafaga;
  temporizador = setTimeout(() => {
    if (rafaga !== r) return;
    rafaga = null;
    if (esLectura(r, performance.now(), SIN_FIN + 100, MINIMO_SIN_FIN)) terminar(r, null);
    else soltar(r);
  }, SIN_FIN);
}

// --- Lectores por puerto COM (NejiPOS.exe) -------------------------------------------------------------

/** Un código leído por NejiPOS.exe desde un lector COM USB. */
export function recibir(codigo) {
  codigo = String(codigo || '').trim();
  if (!estado.usuario || !codigo) return;
  const alProbar = probando();
  if (alProbar) {
    alProbar(codigo, 'lector USB (puerto COM)');
    return;
  }
  const campo = editable(document.activeElement) ? document.activeElement : null;
  const accion = leerLector().forzar ? destino(campo) : 'normal';
  if (accion === 'venta' || (enLaVenta() && !modalAbierto() && (!campo || campo.id === 'codigo-producto'))) {
    llevarAVenta(codigo);
  } else if (accion === 'avisar') {
    aviso(AVISO_VENTANA, 'error', 5000);
  } else if (campo) {
    escribirEn(campo, codigo);
  } else {
    aviso(`El lector leyó «${codigo}», pero no hay dónde ponerlo.`, 'error', 5000);
  }
}

/** Como si el lector hubiera escrito el código en el campo con el foco; en un campo para códigos, también el Enter. */
function escribirEn(campo, codigo) {
  const desde = campo.selectionStart ?? campo.value.length;
  const hasta = campo.selectionEnd ?? desde;
  campo.value = campo.value.slice(0, desde) + codigo + campo.value.slice(hasta);
  campo.dispatchEvent(new Event('input', { bubbles: true }));
  if (!quiereCodigo(campo)) return;
  const enter = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true });
  if (campo.dispatchEvent(enter) && campo.form && campo.tagName !== 'TEXTAREA') campo.form.requestSubmit();
}

async function escucharLectoresCom() {
  const api = await escritorio();
  if (!api?.lecturas) return; // en el navegador no hay acceso a los puertos COM
  for (;;) {
    let r = null;
    try {
      r = await api.lecturas(20);
    } catch { /* el programa se está cerrando o se reinició: se reintenta */ }
    if (!r?.ok) {
      await new Promise((listo) => { setTimeout(listo, 5000); });
      continue;
    }
    for (const c of r.codigos || []) recibir(c);
  }
}

/** Se llama una vez al cargar Neji. `llevarCodigo(codigo)` agrega el código a la venta. */
export function iniciarLector({ llevarCodigo }) {
  llevar = llevarCodigo;
  // En la fase de captura: antes que cualquier otra tecla de Neji, para poder quitarle la lectura al campo.
  document.addEventListener('keydown', teclear, true);
  escucharLectoresCom();
}
