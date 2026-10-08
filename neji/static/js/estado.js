// Estado compartido de la sesión: usuario, configuración y caja de esta terminal.

import { api } from './api.js';

export const estado = {
  usuario: null,
  config: {},
  cajas: [],
  cajaId: leerCajaLocal(),
};

function leerCajaLocal() {
  try {
    return parseInt(localStorage.getItem('neji.caja') || '1', 10) || 1;
  } catch {
    return 1;
  }
}

export function fijarCaja(id) {
  estado.cajaId = id;
  try { localStorage.setItem('neji.caja', String(id)); } catch { /* sin almacenamiento */ }
}

export const esAdmin = () => estado.usuario?.rol === 'admin';
export const opcion = (clave) => estado.config[clave] === '1';
export const puede = (permiso) => esAdmin() || opcion(permiso);
export const esFarmacia = () => opcion('modulo_farmacia');

export function nombreCaja() {
  return estado.cajas.find((c) => c.id === estado.cajaId)?.nombre || `Caja ${estado.cajaId}`;
}

export async function cargarSesion() {
  const [config, cajas] = await Promise.all([api.get('/api/config'), api.get('/api/cajas')]);
  estado.config = config;
  estado.cajas = cajas;
  if (!cajas.some((c) => c.id === estado.cajaId && c.activa)) {
    const primera = cajas.find((c) => c.activa);
    if (primera) fijarCaja(primera.id);
  }
}

// Tickets abiertos de esta terminal (sobreviven a recargar la página).
const claveTickets = () => `neji.tickets.${estado.cajaId}`;

export function leerTickets() {
  try {
    const t = JSON.parse(localStorage.getItem(claveTickets()) || 'null');
    if (t && Array.isArray(t.lista) && t.lista.length) return t;
  } catch { /* datos dañados: se empieza de cero */ }
  return { lista: [nuevoTicket(1)], activo: 0 };
}

export function guardarTickets(tickets) {
  try { localStorage.setItem(claveTickets(), JSON.stringify(tickets)); } catch { /* sin almacenamiento */ }
}

export function nuevoTicket(numero) {
  return { numero, items: [], cliente: null, descuento: 0, cotizacionId: null, sel: -1 };
}
