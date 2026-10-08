// Llamadas a la API del servidor. Los errores traen el mensaje listo para mostrar.

import { avisoError } from './ui.js';

export class ErrorApi extends Error {
  constructor(mensaje, status, codigo) {
    super(mensaje);
    this.status = status;
    this.codigo = codigo;
  }
}

let alPerderSesion = () => {};
export function cuandoSeCierreSesion(fn) { alPerderSesion = fn; }

async function pedir(metodo, url, datos, esFormulario = false) {
  const opciones = { method: metodo, headers: {}, credentials: 'same-origin' };
  if (datos !== undefined) {
    if (esFormulario) {
      opciones.body = datos;
    } else {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.body = JSON.stringify(datos);
    }
  }
  let resp;
  try {
    resp = await fetch(url, opciones);
  } catch {
    throw new ErrorApi('No hay conexión con el servidor de Neji. ¿Está abierto el programa?', 0);
  }
  const cuerpo = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 401 && cuerpo.codigo === 'sin_sesion') alPerderSesion();
    throw new ErrorApi(cuerpo.error || `Error ${resp.status}`, resp.status, cuerpo.codigo);
  }
  return cuerpo;
}

export const api = {
  get: (url) => pedir('GET', url),
  post: (url, datos = {}) => pedir('POST', url, datos),
  put: (url, datos = {}) => pedir('PUT', url, datos),
  del: (url) => pedir('DELETE', url),
  subir: (url, formData) => pedir('POST', url, formData, true),
};

export function qs(parametros) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(parametros)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

/**
 * Descarga un archivo del servidor (CSV, respaldos). Primero revisa que el servidor responda bien:
 * si hay un error se muestra el mensaje, en vez de bajar un archivo vacío o abrir el diálogo Guardar
 * para nada (en la ventana de escritorio cada descarga pregunta dónde guardar).
 */
export async function descargar(url) {
  try {
    const r = await fetch(url, { method: 'HEAD', credentials: 'same-origin' });
    if (!r.ok) {
      const cuerpo = await fetch(url, { credentials: 'same-origin' }).then((x) => x.json()).catch(() => ({}));
      throw new ErrorApi(cuerpo.error || `No se pudo descargar el archivo (error ${r.status}).`, r.status);
    }
  } catch (e) {
    avisoError(e instanceof ErrorApi ? e : new ErrorApi('No hay conexión con el servidor de Neji.', 0));
    return;
  }
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.append(a);
  a.click();
  a.remove();
}
