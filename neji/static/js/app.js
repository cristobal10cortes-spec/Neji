// Arranque, navegación entre pantallas y atajos de teclado globales.

import { api, cuandoSeCierreSesion } from './api.js';
import { cargarSesion, esFarmacia, estado, nombreCaja, puede } from './estado.js';
import { aviso, avisoError, cerrarModales, h, teclaEnModal, vaciar } from './ui.js';
import * as caja from './vistas/caja.js';
import * as clientes from './vistas/clientes.js';
import * as config from './vistas/config.js';
import * as cotizaciones from './vistas/cotizaciones.js';
import * as historial from './vistas/historial.js';
import * as inventario from './vistas/inventario.js';
import * as productos from './vistas/productos.js';
import * as recetario from './vistas/recetario.js';
import * as reportes from './vistas/reportes.js';
import * as vademecum from './vistas/vademecum.js';
import * as ventas from './vistas/ventas.js';

const VISTAS = [
  { clave: 'ventas', titulo: 'Ventas', tecla: 'F1', modulo: ventas },
  { clave: 'clientes', titulo: 'Clientes', tecla: 'F2', modulo: clientes },
  { clave: 'productos', titulo: 'Productos', tecla: 'F3', modulo: productos },
  { clave: 'inventario', titulo: 'Inventario', tecla: 'F4', modulo: inventario, permiso: 'inventario' },
  { clave: 'vademecum', titulo: 'Vademécum', modulo: vademecum, farmacia: true },
  { clave: 'recetario', titulo: 'Recetario', modulo: recetario, farmacia: true },
  { clave: 'caja', titulo: 'Caja', modulo: caja },
  { clave: 'historial', titulo: 'Historial', modulo: historial },
  { clave: 'cotizaciones', titulo: 'Cotizaciones', corto: 'Cotiz.', modulo: cotizaciones },
  { clave: 'reportes', titulo: 'Reportes', modulo: reportes, permiso: 'reportes' },
  { clave: 'config', titulo: 'Configuración', corto: 'Config.', modulo: config },
];

const raiz = document.getElementById('app');
let vistaActual = null;
let principal = null;
let nav = null;

export function ir(clave, parametros) {
  if (parametros) sessionStorage.setItem('neji.parametros', JSON.stringify(parametros));
  if (location.hash === `#${clave}`) mostrarVista();
  else location.hash = clave;
}

function tomarParametros() {
  const p = sessionStorage.getItem('neji.parametros');
  sessionStorage.removeItem('neji.parametros');
  return p ? JSON.parse(p) : {};
}

function vistasPermitidas() {
  return VISTAS.filter((v) => (!v.permiso || puede(v.permiso)) && (!v.farmacia || esFarmacia()));
}

/**
 * Vuelve a leer el usuario: el administrador puede cambiar sus permisos mientras la sesión está abierta.
 * Devuelve true si cambiaron (hay que rearmar el menú).
 */
async function refrescarUsuario() {
  try {
    const { usuario } = await api.get('/api/estado');
    if (!usuario) return false;
    const huella = (u) => JSON.stringify([u.rol, u.permisos]);
    const cambio = huella(usuario) !== huella(estado.usuario);
    estado.usuario = usuario;
    return cambio;
  } catch {
    return false; // sin conexión: se sigue con lo que había
  }
}

async function mostrarVista() {
  if (!estado.usuario) return;
  if (await refrescarUsuario()) {
    dibujarAplicacion(); // el menú cambia según los permisos; vuelve a llamar a mostrarVista
    return;
  }
  const clave = location.hash.slice(1) || 'ventas';
  const vista = vistasPermitidas().find((v) => v.clave === clave) || VISTAS[0];
  // Una ventana que queda abierta seguiría trabajando con la pantalla anterior (p. ej. «Vender» desde la ficha
  // de un principio abierta en F10): se cierran todas antes de montar la nueva.
  cerrarModales();
  vistaActual?.desmontar?.();
  vistaActual = null;
  for (const b of nav.querySelectorAll('button')) b.classList.toggle('activo', b.dataset.vista === vista.clave);
  const contenedor = h('div');
  vaciar(principal, contenedor);
  document.title = `${vista.titulo} · Neji POS`;
  try {
    vistaActual = (await vista.modulo.montar(contenedor, tomarParametros())) || null;
  } catch (e) {
    avisoError(e);
  }
}

function dibujarAplicacion() {
  // En pantallas angostas (Windows al 125 %) los nombres largos se abrevian para que el menú quepa entero.
  nav = h('nav.nav', vistasPermitidas().map((v) => h('button', { type: 'button', title: v.titulo, dataset: { vista: v.clave }, onclick: () => ir(v.clave) },
    v.tecla ? h('kbd', v.tecla) : null, h('span.nombre-largo', v.titulo), v.corto ? h('span.nombre-corto', v.corto) : null)));
  principal = h('main');
  vaciar(raiz,
    h('header.barra',
      h('div.marca', 'Neji', h('span', ' POS')),
      nav,
      h('div.sesion',
        h('span.caja', { title: 'Caja de esta terminal (se cambia en Configuración)' }, nombreCaja()),
        h('span.ocultar-movil.nombre-usuario', `${estado.usuario.nombre} (${estado.usuario.rol})`),
        h('button.btn.chico', { type: 'button', onclick: salir, title: `Cerrar la sesión de ${estado.usuario.nombre}` }, 'Salir'))),
    principal);
  mostrarVista();
}

async function salir() {
  await api.post('/api/logout').catch(() => {});
  estado.usuario = null;
  location.hash = '';
  iniciar();
}

function pantallaAcceso(configurado, negocio) {
  const error = h('div.error-modal.oculto', { role: 'alert' });
  const mostrarError = (msg) => { error.textContent = msg; error.classList.remove('oculto'); };

  if (!configurado) {
    const campos = {
      negocio_nombre: h('input', { required: true, autofocus: true, placeholder: 'Ej: Minimarket Don Pepe' }),
      negocio_rut: h('input', { placeholder: '76.123.456-7 (opcional)' }),
      nombre: h('input', { placeholder: 'Tu nombre' }),
      usuario: h('input', { required: true, value: 'admin', autocomplete: 'username' }),
      password: h('input', { type: 'password', required: true, autocomplete: 'new-password' }),
      modulo_farmacia: h('input', { type: 'checkbox' }),
    };
    const form = h('form.tarjeta-login',
      h('div.marca', 'Neji', h('span', ' POS')),
      h('p.suave', 'Bienvenido. Configura tu negocio y el usuario administrador para empezar.'),
      error,
      h('label.campo', 'Nombre del negocio', campos.negocio_nombre),
      h('label.campo', 'RUT del negocio', campos.negocio_rut),
      h('label.campo', 'Tu nombre', campos.nombre),
      h('label.campo', 'Usuario administrador', campos.usuario),
      h('label.campo', 'Contraseña (mínimo 4 caracteres)', campos.password),
      h('label.check', campos.modulo_farmacia, 'Es una farmacia (activar vademécum y recetario magistral)'),
      h('button.btn.primario.grande', { type: 'submit' }, 'Comenzar'));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const datos = Object.fromEntries(Object.entries(campos).map(([k, el]) => [k, el.type === 'checkbox' ? el.checked : el.value.trim()]));
      try {
        await api.post('/api/setup', datos);
        iniciar();
      } catch (err) {
        mostrarError(err.message);
      }
    });
    vaciar(raiz, h('div.centro', form));
    campos.negocio_nombre.focus();
    return;
  }

  const usuario = h('input', { required: true, autofocus: true, autocomplete: 'username' });
  const password = h('input', { type: 'password', required: true, autocomplete: 'current-password' });
  const form = h('form.tarjeta-login',
    h('div.marca', 'Neji', h('span', ' POS')),
    h('p.suave', negocio),
    error,
    h('label.campo', 'Usuario', usuario),
    h('label.campo', 'Contraseña', password),
    h('button.btn.primario.grande', { type: 'submit' }, 'Entrar'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api.post('/api/login', { usuario: usuario.value.trim(), password: password.value });
      iniciar();
    } catch (err) {
      mostrarError(err.message);
      password.select();
    }
  });
  vaciar(raiz, h('div.centro', form));
  usuario.focus();
}

async function iniciar() {
  try {
    const r = await api.get('/api/estado');
    estado.usuario = r.usuario;
    if (!r.usuario) {
      pantallaAcceso(r.configurado, r.negocio);
      return;
    }
    await cargarSesion();
    dibujarAplicacion();
  } catch (e) {
    vaciar(raiz, h('div.centro', h('div.tarjeta-login', h('h2', 'No se pudo conectar'), h('p', e.message),
      h('button.btn.primario', { onclick: iniciar }, 'Reintentar'))));
  }
}

export async function recargarConfiguracion(parametros) {
  if (parametros) sessionStorage.setItem('neji.parametros', JSON.stringify(parametros));
  await cargarSesion();
  dibujarAplicacion();
}

cuandoSeCierreSesion(() => {
  if (estado.usuario) {
    estado.usuario = null;
    aviso('La sesión expiró. Vuelve a entrar.', 'error');
    iniciar();
  }
});

document.addEventListener('keydown', (e) => {
  // Recargar la pantalla (en la ventana de escritorio no existe F5 del navegador).
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'r') {
    e.preventDefault();
    location.reload();
    return;
  }
  if (teclaEnModal(e)) return;
  if (!estado.usuario) return;
  const vista = vistasPermitidas().find((v) => v.tecla === e.key);
  if (vista) {
    e.preventDefault();
    ir(vista.clave);
    return;
  }
  vistaActual?.alTeclear?.(e);
});

window.addEventListener('hashchange', mostrarVista);

// Soltar un archivo fuera de un campo de archivo haría que la ventana lo abra y reemplace a Neji.
for (const tipo of ['dragover', 'drop']) {
  window.addEventListener(tipo, (e) => {
    if (!e.target.closest?.('input[type=file]')) e.preventDefault();
  });
}
iniciar();
