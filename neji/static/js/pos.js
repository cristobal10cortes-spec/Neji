// Cobro con la máquina POS integrada (ver neji/pos.py): manda el monto a la máquina de la caja, muestra
// «Pase la tarjeta…» y espera la respuesta. Lo usan el cobro de la venta y la prueba de Configuración → Máquina POS.

import { api } from './api.js';
import { h, pesos, vaciar } from './ui.js';

const CADA = 1000;    // cada cuánto se pregunta por el cobro (ms)

/**
 * Cobra `monto` con `metodo` (debito | credito) en la máquina de la caja `cajaId`, mostrando la espera en
 * `contenedor`. Devuelve {estado: 'aprobado', cobro} | {estado: 'manual'} (se cobra a mano) |
 * {estado: 'rechazado' | 'cancelado' | 'error', mensaje}. Con `detener.ahora = true` (por ejemplo, al cerrar la
 * ventana del cobro) se cancela el cobro en la máquina.
 */
export function cobrarEnMaquina(contenedor, { cajaId, monto, metodo, nombre = 'la máquina POS', permitirManual = true, detener = null }) {
  return new Promise((resolver) => {
    let cobro = null;
    let terminado = false;
    let temporizador = null;
    const texto = h('div', 'Enviando el monto a la máquina…');

    const terminar = (resultado) => {
      if (terminado) return;
      terminado = true;
      clearTimeout(temporizador);
      vaciar(contenedor);
      resolver(resultado);
    };
    const cancelar = async (siguiente) => {
      try {
        if (cobro) cobro = await api.post(`/api/pos/cobros/${cobro.id}/cancelar`);
      } catch {
        // si no se pudo cancelar, el cobro sigue esperando en la máquina: se avisa igual
      }
      terminar(siguiente);
    };

    vaciar(contenedor, h('div.cobro-maquina',
      h('div.monto', pesos(monto)),
      h('b', `Pase la tarjeta en ${nombre}`),
      texto,
      h('div.fila', { style: { justifyContent: 'center', marginTop: '.6rem' } },
        h('button.btn', { type: 'button', onclick: () => cancelar({ estado: 'cancelado', mensaje: 'Cobro cancelado.' }) }, 'Cancelar cobro'),
        permitirManual
          ? h('button.btn', { type: 'button', title: 'Si la máquina no responde: cobra a mano en la máquina y registra la venta igual', onclick: () => cancelar({ estado: 'manual' }) }, 'Cobrar a mano')
          : null)));

    const revisar = (c) => {
      cobro = c;
      if (c.estado === 'aprobado') return terminar({ estado: 'aprobado', cobro: c });
      if (c.estado !== 'esperando') return terminar({ estado: c.estado, mensaje: c.mensaje || `Pago ${c.estado_texto.toLowerCase()}.` });
      if (detener?.ahora) return cancelar({ estado: 'cancelado', mensaje: 'Cobro cancelado.' });
      texto.textContent = 'Esperando la tarjeta…';
      temporizador = setTimeout(async () => {
        try {
          revisar(await api.get(`/api/pos/cobros/${c.id}`));
        } catch (e) {
          terminar({ estado: 'error', mensaje: e.message });
        }
      }, CADA);
      return null;
    };

    api.post('/api/pos/cobros', { caja_id: cajaId, monto, metodo })
      .then(revisar)
      .catch((e) => terminar({ estado: 'error', mensaje: e.message }));
  });
}
