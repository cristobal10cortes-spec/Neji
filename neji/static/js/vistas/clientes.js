// Clientes, crédito (fiado), abonos y estado de cuenta.

import { api, qs } from '../api.js';
import { estado, puede } from '../estado.js';
import { imprimir, nombreMetodo } from '../impresion.js';
import { aviso, avisoError, confirmar, debounce, fecha, formulario, h, modal, pesos, tabla, vaciar } from '../ui.js';

const textoLimite = (c) => (c.limite_credito == null ? 'Sin límite' : c.limite_credito === 0 ? 'Sin crédito' : pesos(c.limite_credito));

/** Formulario de alta/edición. Devuelve el cliente guardado o null. */
export function formCliente(cliente = null) {
  const campos = [
    { nombre: 'nombre', etiqueta: 'Nombre o razón social', valor: cliente?.nombre, requerido: true, autofocus: true },
    { nombre: 'rut', etiqueta: 'RUT', valor: cliente?.rut, placeholder: '12.345.678-5' },
    { nombre: 'telefono', etiqueta: 'Teléfono', valor: cliente?.telefono },
    { nombre: 'email', etiqueta: 'Correo', tipo: 'email', valor: cliente?.email },
    { nombre: 'direccion', etiqueta: 'Dirección', valor: cliente?.direccion },
    { nombre: 'giro', etiqueta: 'Giro', valor: cliente?.giro },
  ];
  if (puede('clientes_credito')) {
    campos.push(
      { nombre: 'limite_credito', etiqueta: 'Límite de crédito (fiado)', tipo: 'monto', valor: cliente?.limite_credito ?? 0, ayuda: '0 = no se le fía' },
      { nombre: 'sin_limite', etiqueta: 'Crédito sin límite', tipo: 'check', valor: cliente ? cliente.limite_credito == null : false },
    );
  }
  campos.push({ nombre: 'notas', etiqueta: 'Notas', tipo: 'area', valor: cliente?.notas, ancho: true });
  return formulario({
    titulo: cliente ? 'Editar cliente' : 'Nuevo cliente',
    ancho: 'ancho',
    campos,
    alEnviar: (v) => (cliente ? api.put(`/api/clientes/${cliente.id}`, v) : api.post('/api/clientes', v)),
  });
}

/** Buscador de clientes para asignar al ticket. Devuelve el cliente o null. */
export function elegirCliente() {
  return new Promise((resolver) => {
    const entrada = h('input', { placeholder: 'Nombre, RUT o teléfono', autocomplete: 'off', autofocus: true });
    const lista = h('div.lista-busqueda');
    let resultados = [];
    let sel = 0;
    let elegido = null;

    const pintar = () => {
      vaciar(lista, tabla([
        { titulo: 'Nombre', valor: (c) => c.nombre },
        { titulo: 'RUT', valor: (c) => c.rut || '' },
        { titulo: 'Debe', valor: (c) => pesos(c.saldo), clase: 'num' },
        { titulo: 'Disponible', valor: (c) => (c.credito_disponible == null ? 'Sin límite' : pesos(c.credito_disponible)), clase: 'num' },
      ], resultados, { vacio: 'Sin clientes.', alClic: (c) => { elegido = c; m.cerrar(); }, claseFila: (c) => (resultados[sel] === c ? 'sel' : '') }));
    };
    const cargar = debounce(async () => {
      resultados = await api.get(`/api/clientes${qs({ q: entrada.value.trim() })}`).catch(() => []);
      sel = 0;
      pintar();
    }, 180);
    entrada.addEventListener('input', cargar);

    const m = modal({
      titulo: 'Elegir cliente',
      ancho: 'ancho',
      cuerpo: [entrada, lista],
      botones: [
        { texto: 'Nuevo cliente', accion: async () => { const c = await formCliente(); if (c) { elegido = c; m.cerrar(); } } },
        { texto: 'Cancelar', accion: () => m.cerrar() },
      ],
      alCerrar: () => resolver(elegido),
      alTeclear: (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, resultados.length - 1); pintar(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); pintar(); }
        else if (e.key === 'Enter' && resultados[sel]) { e.preventDefault(); elegido = resultados[sel]; m.cerrar(); }
      },
    });
    cargar();
  });
}

async function abonar(cliente) {
  return formulario({
    titulo: `Abono de ${cliente.nombre}`,
    aceptar: 'Registrar abono',
    intro: h('p', `Deuda actual: `, h('b', pesos(cliente.saldo))),
    campos: [
      { nombre: 'monto', etiqueta: 'Monto', tipo: 'monto', valor: cliente.saldo, requerido: true, autofocus: true },
      { nombre: 'metodo', etiqueta: 'Forma de pago', tipo: 'select', valor: 'efectivo', opciones: ['efectivo', 'debito', 'credito', 'transferencia'].map((m) => [m, nombreMetodo(m)]) },
      { nombre: 'nota', etiqueta: 'Nota', ancho: true },
    ],
    alEnviar: (v) => api.post(`/api/clientes/${cliente.id}/abono`, { ...v, caja_id: estado.cajaId }),
  });
}

const describirMovimiento = (m) => (m.tipo === 'cargo' ? `Compra folio ${m.folio}`
  : m.tipo === 'abono' ? `Abono (${nombreMetodo(m.metodo)})` : `Devolución folio ${m.folio}`);

function imprimirEstadoCuenta(c) {
  imprimir(h('div.hoja',
    h('h2', `Estado de cuenta — ${c.nombre}`),
    h('p', c.rut ? `RUT ${c.rut} · ` : '', 'Deuda actual: ', h('b', pesos(c.saldo))),
    h('table', { border: '1', cellpadding: '4', style: { borderCollapse: 'collapse', width: '100%' } },
      h('thead', h('tr', ['Fecha', 'Movimiento', 'Monto', 'Saldo'].map((t) => h('th', t)))),
      h('tbody', c.movimientos.map((m) => h('tr', h('td', fecha(m.fecha)), h('td', describirMovimiento(m)),
        h('td', (m.tipo === 'cargo' ? '+' : '-') + pesos(m.monto)), h('td', pesos(m.saldo_nuevo))))))));
}

async function verCliente(id, alCambiar) {
  let c;
  try {
    c = await api.get(`/api/clientes/${id}`);
  } catch (e) {
    avisoError(e);
    return;
  }
  const m = modal({
    titulo: c.nombre,
    ancho: 'muy-ancho',
    cuerpo: [
      h('div.kpis',
        h('div.kpi.destacado', h('div.titulo', 'Debe'), h('div.valor', pesos(c.saldo))),
        h('div.kpi', h('div.titulo', 'Límite'), h('div.valor', textoLimite(c))),
        h('div.kpi', h('div.titulo', 'Disponible'), h('div.valor', c.credito_disponible == null ? '—' : pesos(c.credito_disponible)))),
      h('p.suave', [c.rut, c.telefono, c.email, c.direccion].filter(Boolean).join(' · ')),
      h('h3', 'Estado de cuenta'),
      tabla([
        { titulo: 'Fecha', valor: (x) => fecha(x.fecha) },
        { titulo: 'Movimiento', valor: describirMovimiento },
        { titulo: 'Usuario', valor: (x) => x.usuario || '' },
        { titulo: 'Cargo', valor: (x) => (x.tipo === 'cargo' ? pesos(x.monto) : ''), clase: 'num' },
        { titulo: 'Abono', valor: (x) => (x.tipo !== 'cargo' ? pesos(x.monto) : ''), clase: 'num' },
        { titulo: 'Saldo', valor: (x) => pesos(x.saldo_nuevo), clase: 'num' },
      ], c.movimientos, { vacio: 'Sin movimientos.' }),
    ],
    botones: [
      { texto: 'Imprimir', accion: () => imprimirEstadoCuenta(c) },
      { texto: 'Editar', accion: async () => { if (await formCliente(c)) { m.cerrar(); alCambiar(); verCliente(id, alCambiar); } } },
      c.saldo > 0 ? { texto: 'Abonar', clase: 'primario', accion: async () => { if (await abonar(c)) { aviso('Abono registrado.', 'ok'); m.cerrar(); alCambiar(); verCliente(id, alCambiar); } } } : null,
    ].filter(Boolean),
  });
}

export async function montar(contenedor) {
  const buscar = h('input', { type: 'search', placeholder: 'Buscar por nombre, RUT o teléfono', autofocus: true, style: { maxWidth: '420px' } });
  const conDeuda = h('input', { type: 'checkbox' });
  const lista = h('div');
  const totalDeuda = h('span.suave');

  vaciar(contenedor,
    h('div.fila.entre',
      h('h2', 'Clientes'),
      h('button.btn.primario', { type: 'button', onclick: async () => { if (await formCliente()) cargar(); } }, 'Nuevo cliente')),
    h('div.fila', buscar, h('label.check', conDeuda, 'Solo con deuda'), h('span.espacio'), totalDeuda),
    h('div', { style: { height: '.75rem' } }),
    lista);

  async function cargar() {
    let clientes = [];
    try {
      clientes = await api.get(`/api/clientes${qs({ q: buscar.value.trim(), con_deuda: conDeuda.checked ? 1 : '' })}`);
    } catch (e) {
      avisoError(e);
    }
    totalDeuda.textContent = `Por cobrar: ${pesos(clientes.reduce((s, c) => s + c.saldo, 0))}`;
    vaciar(lista, tabla([
      { titulo: 'Nombre', valor: (c) => c.nombre },
      { titulo: 'RUT', valor: (c) => c.rut || '' },
      { titulo: 'Teléfono', valor: (c) => c.telefono || '' },
      { titulo: 'Límite', valor: textoLimite, clase: 'num' },
      { titulo: 'Debe', valor: (c) => h('span', { class: c.saldo > 0 ? 'rojo negrita' : '' }, pesos(c.saldo)), clase: 'num' },
      {
        titulo: '',
        valor: (c) => h('div.fila.fin',
          c.saldo > 0 ? h('button.btn.chico', { type: 'button', onclick: async (e) => { e.stopPropagation(); if (await abonar(c)) { aviso('Abono registrado.', 'ok'); cargar(); } } }, 'Abonar') : null,
          puede('clientes_credito') ? h('button.btn.chico.peligro', {
            type: 'button',
            onclick: async (e) => {
              e.stopPropagation();
              if (!(await confirmar('Eliminar cliente', `¿Eliminar a ${c.nombre}?`, { aceptar: 'Eliminar', peligro: true }))) return;
              try { await api.del(`/api/clientes/${c.id}`); cargar(); } catch (err) { avisoError(err); }
            },
          }, 'Eliminar') : null),
      },
    ], clientes, { vacio: 'No hay clientes.', alClic: (c) => verCliente(c.id, cargar) }));
  }

  buscar.addEventListener('input', debounce(cargar));
  conDeuda.addEventListener('change', cargar);
  await cargar();
  buscar.focus();
}
