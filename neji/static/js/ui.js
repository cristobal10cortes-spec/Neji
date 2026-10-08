// Utilidades de interfaz: creación de elementos, formatos chilenos, modales y avisos.

export function h(etiqueta, attrs, ...hijos) {
  const [nombre, ...clases] = etiqueta.split('.');
  const el = document.createElement(nombre || 'div');
  if (clases.length) el.className = clases.join(' ');
  if (attrs != null && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    hijos.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') el.className = [el.className, v].filter(Boolean).join(' ');
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked') el.checked = Boolean(v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  agregar(el, hijos);
  return el;
}

export function agregar(el, hijos) {
  for (const hijo of [hijos].flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

export function vaciar(el, ...hijos) {
  el.replaceChildren();
  return agregar(el, hijos);
}

// --- Formatos ----------------------------------------------------------------

const formatoPesos = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP' });
const formatoNumero = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 3 });

export const pesos = (n) => formatoPesos.format(Math.round(n || 0));
export const numero = (n) => formatoNumero.format(n || 0);

export function fecha(texto, conHora = true) {
  if (!texto) return '';
  const [d, t = ''] = texto.split(' ');
  const [a, m, dia] = d.split('-');
  return `${dia}-${m}-${a}` + (conHora && t ? ` ${t.slice(0, 5)}` : '');
}

export function hoy(desplazamientoDias = 0) {
  const d = new Date();
  d.setDate(d.getDate() + desplazamientoDias);
  const dos = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
}

/**
 * Monto en pesos, igual que el servidor (validar.entero): '1.990', '$1990', '20,000' -> 20000.
 * Solo una coma o un punto con 1 o 2 cifras al final son decimales y se redondean: '1.990,50' -> 1991.
 */
export function leerMonto(valor) {
  if (typeof valor === 'number') return Math.round(valor);
  const s = String(valor ?? '').replace(/[\s$]/g, '');
  if (/^-?\d+\.\d{1,2}$/.test(s)) return Math.round(Number(s));
  if (/^-?(\d{1,3}(\.\d{3})+|\d+),\d{1,2}$/.test(s)) return Math.round(Number(s.replace(/\./g, '').replace(',', '.')));
  const limpio = s.replace(/[^\d-]/g, '');
  return limpio ? parseInt(limpio, 10) : 0;
}

/**
 * Cantidad con hasta 3 decimales, igual que el servidor (validar.texto_a_numero): la coma es decimal y
 * el punto separa miles cuando va en grupos de tres ('5.000' son cinco mil, '0,755' y '1.5' llevan decimales).
 */
export function leerCantidad(valor) {
  if (typeof valor === 'number') return valor;
  let s = String(valor ?? '').trim().replace(/[\s$]/g, '');
  if (s.includes(',') || /^-?[1-9]\d{0,2}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '').replace(/,/g, '.');
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return NaN;
  return Math.round(Number(s) * 1000) / 1000;
}

/** Número para escribir en un campo: 2.125 -> '2,125' (así leerCantidad lo vuelve a leer igual). */
export const decimalTexto = (n) => (n == null ? '' : String(n).replace('.', ','));

const PREPOSICIONES = new Set(['a', 'al', 'con', 'de', 'del', 'en', 'para', 'por', 'sin']);
const SIN_TILDE = { á: 'a', é: 'e', í: 'i', ó: 'o', ú: 'u' };

/** Igual que el servidor (servicios/recetario.py: _plural_palabra). */
function pluralPalabra(p) {
  if (p.length <= 2 || !/[aeiouáéíóú]/.test(p) || /[sx]$/.test(p)) return p; // g, ml, de, ya en plural
  if (/[lnrdzj]$/.test(p)) {
    const base = p.endsWith('z') ? `${p.slice(0, -1)}c` : p;
    return `${base.slice(0, -2)}${base.slice(-2).replace(/[áéíóú]/g, (c) => SIN_TILDE[c])}es`; // jabón -> jabones
  }
  return `${p}s`;
}

/** 'cápsula blanda' -> 'cápsulas blandas', 'cápsula de gelatina' -> 'cápsulas de gelatina', 'ml' -> 'ml'. */
export function unidadPlural(cantidad, unidad, nombre) {
  if (unidad === 'ml' || Number(cantidad) === 1) return nombre;
  const palabras = nombre.split(' ');
  let corte = palabras.findIndex((p) => PREPOSICIONES.has(p.toLowerCase()));
  if (corte < 0) corte = palabras.length;
  return [...palabras.slice(0, corte).map(pluralPalabra), ...palabras.slice(corte)].join(' ');
}

/** Importe de una línea igual que el servidor: cantidad (3 decimales) x precio, redondeo 0,5 hacia arriba. */
export function importe(cantidad, precio) {
  const milesimas = Math.round(cantidad * 1000) * precio;
  return Math.floor((milesimas + 500) / 1000);
}

/** Ley 20.956: termina en 1-5 baja, en 6-9 sube. */
export function redondeoEfectivo(monto) {
  const resto = ((monto % 10) + 10) % 10;
  if (resto === 0) return monto;
  return resto <= 5 ? monto - resto : monto + (10 - resto);
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

let audio;
export function pitido() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const osc = audio.createOscillator();
    const vol = audio.createGain();
    osc.frequency.value = 330;
    vol.gain.value = 0.08;
    osc.connect(vol).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.18);
  } catch { /* sin audio */ }
}

// --- Avisos ------------------------------------------------------------------

export function aviso(mensaje, tipo = '', ms = 3500) {
  const el = h(`div.toast${tipo ? '.' + tipo : ''}`, { role: tipo === 'error' ? 'alert' : 'status' }, mensaje);
  document.getElementById('avisos').append(el);
  setTimeout(() => el.remove(), ms);
}

export function avisoError(error) {
  aviso(error?.message || String(error), 'error', 5000);
}

// --- Modales -----------------------------------------------------------------

const pila = [];

export function modalAbierto() {
  return pila.length > 0;
}

/** Abre un modal. `alTeclear(e)` recibe las teclas mientras es el modal de arriba. */
export function modal({ titulo, cuerpo, botones = [], ancho = '', alCerrar, alTeclear }) {
  const errorEl = h('div.error-modal.oculto', { role: 'alert' });
  const pie = h('footer');
  const caja = h(`div.modal${ancho ? '.' + ancho : ''}`, { role: 'dialog', 'aria-modal': 'true', 'aria-label': titulo, tabindex: '-1' },
    h('header', h('h3', titulo), h('button.cerrar', { type: 'button', title: 'Cerrar (Esc)', 'aria-label': 'Cerrar', onclick: () => obj.cerrar() }, '×')),
    h('div.cuerpo', errorEl, cuerpo),
    pie);
  const fondo = h('div.fondo-modal', caja);
  const enfocadoAntes = document.activeElement;
  let cerrado = false;

  const obj = {
    el: caja,
    alTeclear,
    cerrar(valor) {
      if (cerrado) return;
      cerrado = true;
      fondo.remove();
      pila.splice(pila.indexOf(obj), 1);
      alCerrar?.(valor);
      if (enfocadoAntes && document.contains(enfocadoAntes)) enfocadoAntes.focus();
    },
    error(mensaje) {
      errorEl.textContent = mensaje || '';
      errorEl.classList.toggle('oculto', !mensaje);
    },
  };

  if (botones.length === 0) pie.remove();
  for (const b of botones) {
    pie.append(h(`button.btn${b.clase ? '.' + b.clase : ''}`, { type: b.submit ? 'submit' : 'button', form: b.form, onclick: b.accion ? () => b.accion(obj) : null },
      b.tecla ? h('kbd', b.tecla) : null, b.texto));
  }

  document.getElementById('modales').append(fondo);
  pila.push(obj);
  setTimeout(() => {
    // Sin campos ni botón principal, el foco queda en la ventana: así las teclas no siguen escribiendo en la pantalla de atrás.
    const foco = caja.querySelector('[autofocus]') || caja.querySelector('.cuerpo input, .cuerpo select, .cuerpo textarea') || caja.querySelector('footer .btn.primario') || caja;
    foco.focus();
    if (foco?.select && foco.tagName === 'INPUT') foco.select();
  }, 0);
  return obj;
}

/** Maneja una tecla si hay un modal abierto. Devuelve true si la tecla le pertenecía al modal. */
export function teclaEnModal(e) {
  const arriba = pila[pila.length - 1];
  if (!arriba) return false;
  if (e.key === 'Escape') {
    e.preventDefault();
    arriba.cerrar();
    return true;
  }
  arriba.alTeclear?.(e);
  if (/^F\d+$/.test(e.key)) e.preventDefault();
  return true;
}

export function confirmar(titulo, mensaje, { aceptar = 'Aceptar', peligro = false } = {}) {
  return new Promise((resolver) => {
    let respuesta = false;
    modal({
      titulo,
      cuerpo: h('p', mensaje),
      alCerrar: () => resolver(respuesta),
      botones: [
        { texto: 'Cancelar', accion: (m) => m.cerrar() },
        { texto: aceptar, clase: peligro ? 'peligro' : 'primario', accion: (m) => { respuesta = true; m.cerrar(); } },
      ],
    });
  });
}

let contadorFormularios = 0;

/**
 * Formulario en un modal. Devuelve una promesa con el resultado de `alEnviar`
 * (o los valores si no hay `alEnviar`), o null si se cancela.
 * Tipos de campo: texto, password, email, monto, cantidad, fecha, area, select, check.
 */
export function formulario({ titulo, campos, aceptar = 'Guardar', ancho = '', alEnviar, intro, extra, alMostrar }) {
  return new Promise((resolver) => {
    const id = `form-${++contadorFormularios}`;
    const entradas = {};
    let resultado = null;
    const rejilla = h('div.rejilla');
    for (const c of campos) {
      let control;
      const comunes = { name: c.nombre, required: c.requerido, autofocus: c.autofocus, placeholder: c.placeholder, disabled: c.deshabilitado, ...(c.atributos || {}) };
      if (c.tipo === 'select') {
        control = h('select', comunes, c.opciones.map(([v, t]) => h('option', { value: v, selected: String(v) === String(c.valor ?? '') }, t)));
      } else if (c.tipo === 'check') {
        control = h('input', { ...comunes, type: 'checkbox', checked: c.valor });
      } else if (c.tipo === 'area') {
        control = h('textarea', comunes, c.valor ?? '');
      } else {
        const tipos = { password: 'password', email: 'email', fecha: 'date' };
        const modo = { monto: 'numeric', cantidad: 'decimal' }[c.tipo];
        // Una cantidad numérica se muestra con coma decimal: con punto, '2.125' se leería como 2125.
        const valor = c.tipo === 'cantidad' && typeof c.valor === 'number' ? decimalTexto(c.valor) : (c.valor ?? '');
        control = h('input', { ...comunes, type: tipos[c.tipo] || 'text', inputmode: modo, value: valor, autocomplete: c.tipo === 'password' ? 'new-password' : 'off' });
      }
      entradas[c.nombre] = control;
      if (c.tipo === 'check') {
        rejilla.append(h('label.check', { class: c.ancho ? 'ancho' : '' }, control, c.etiqueta));
      } else {
        rejilla.append(h('label.campo', { class: c.ancho ? 'ancho' : '' }, c.etiqueta, control, c.ayuda ? h('span.ayuda', c.ayuda) : null));
      }
    }
    const form = h('form', { id, novalidate: true }, intro || null, rejilla, extra || null);
    alMostrar?.(entradas);

    const m = modal({
      titulo,
      ancho,
      cuerpo: form,
      alCerrar: () => resolver(resultado),
      botones: [
        { texto: 'Cancelar', accion: (mm) => mm.cerrar() },
        { texto: aceptar, clase: 'primario', submit: true, form: id },
      ],
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const valores = {};
      for (const c of campos) {
        const ctl = entradas[c.nombre];
        if (c.tipo === 'check') valores[c.nombre] = ctl.checked;
        else if (c.tipo === 'monto') valores[c.nombre] = ctl.value.trim() === '' ? null : leerMonto(ctl.value);
        else if (c.tipo === 'cantidad') valores[c.nombre] = ctl.value.trim() === '' ? null : leerCantidad(ctl.value);
        else valores[c.nombre] = ctl.value.trim();
        if (c.requerido && (valores[c.nombre] === '' || valores[c.nombre] === null)) {
          m.error(`Completa: ${c.etiqueta}.`);
          ctl.focus();
          return;
        }
        if (c.tipo === 'cantidad' && Number.isNaN(valores[c.nombre])) {
          m.error(`${c.etiqueta}: número no válido.`);
          ctl.focus();
          return;
        }
      }
      const boton = m.el.querySelector('footer .btn.primario');
      boton.disabled = true;
      try {
        resultado = alEnviar ? (await alEnviar(valores)) ?? valores : valores;
        m.cerrar();
      } catch (err) {
        m.error(err.message);
      } finally {
        boton.disabled = false;
      }
    });
  });
}

/**
 * Tabla simple. columnas: [{ titulo, valor: (fila) => texto|Node, clase }]
 */
export function tabla(columnas, filas, { vacio = 'Sin datos.', alClic, pie, claseFila } = {}) {
  const cuerpo = h('tbody');
  if (!filas.length) {
    cuerpo.append(h('tr', h('td.vacio', { colspan: columnas.length }, vacio)));
  }
  for (const f of filas) {
    const tr = h('tr', { class: [alClic ? 'clic' : '', claseFila?.(f) || ''].join(' ').trim() || null, onclick: alClic ? () => alClic(f) : null },
      columnas.map((c) => h('td', { class: c.clase }, c.valor(f))));
    cuerpo.append(tr);
  }
  return h('div.tabla-caja', h('table',
    h('thead', h('tr', columnas.map((c) => h('th', { class: c.clase }, c.titulo)))),
    cuerpo,
    pie ? h('tfoot', h('tr', pie.map((p) => h('td', { class: p.clase, colspan: p.colspan }, p.valor)))) : null));
}

export function kpi(titulo, valor, destacado = false) {
  return h(`div.kpi${destacado ? '.destacado' : ''}`, h('div.titulo', titulo), h('div.valor', valor));
}

export function pestanas(opciones, activa, alCambiar) {
  const cont = h('div.pestanas', { role: 'tablist' });
  for (const [clave, texto] of opciones) {
    cont.append(h('button', { type: 'button', role: 'tab', class: clave === activa ? 'activo' : null, onclick: () => alCambiar(clave) }, texto));
  }
  return cont;
}

/** Selector de rango de fechas con atajos (hoy, ayer, semana, mes). */
export function selectorFechas(inicial, alCambiar) {
  const desde = h('input', { type: 'date', value: inicial.desde, style: { width: 'auto' } });
  const hasta = h('input', { type: 'date', value: inicial.hasta, style: { width: 'auto' } });
  const avisar = () => alCambiar({ desde: desde.value, hasta: hasta.value });
  desde.addEventListener('change', avisar);
  hasta.addEventListener('change', avisar);
  const fijar = (d, ha) => { desde.value = d; hasta.value = ha; avisar(); };
  const ahora = new Date();
  const dos = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
  const lunes = new Date(ahora);
  lunes.setDate(ahora.getDate() - ((ahora.getDay() + 6) % 7));
  const inicioMes = new Date(ahora.getFullYear(), ahora.getMonth(), 1);
  const inicioMesAnt = new Date(ahora.getFullYear(), ahora.getMonth() - 1, 1);
  const finMesAnt = new Date(ahora.getFullYear(), ahora.getMonth(), 0);
  return h('div.fila',
    h('span.suave', 'Desde'), desde, h('span.suave', 'hasta'), hasta,
    h('button.btn.chico', { type: 'button', onclick: () => fijar(hoy(), hoy()) }, 'Hoy'),
    h('button.btn.chico', { type: 'button', onclick: () => fijar(hoy(-1), hoy(-1)) }, 'Ayer'),
    h('button.btn.chico', { type: 'button', onclick: () => fijar(iso(lunes), hoy()) }, 'Semana'),
    h('button.btn.chico', { type: 'button', onclick: () => fijar(iso(inicioMes), hoy()) }, 'Mes'),
    h('button.btn.chico', { type: 'button', onclick: () => fijar(iso(inicioMesAnt), iso(finMesAnt)) }, 'Mes anterior'));
}
