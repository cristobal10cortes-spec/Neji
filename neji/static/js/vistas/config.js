// Configuración: negocio, ticket, opciones, usuarios, cajas, esta terminal y respaldos.

import { api, descargar } from '../api.js';
import { recargarConfiguracion } from '../app.js';
import { esAdmin, esFarmacia, estado, fijarCaja, nombreCaja } from '../estado.js';
import {
  DATOS_NEGOCIO, PARTES_TICKET, bloquesTicket, columnasDe, configAutomatica, disenoPredeterminado, disenoTicket, esDe58, escritorio, guardarImpresora,
  impresoraSugerida, imprimir, imprimirConDialogo, leerImpresora, listarImpresoras, papelDe, ticketVenta, trabajoImpresion,
} from '../impresion.js';
import { aviso, avisoError, fecha, formulario, h, numero, pestanas, tabla, vaciar } from '../ui.js';
import { componerRenglones } from '../renglones.js';
import { importadorCsv } from './productos.js';

let pestanaActual = null;

function campo(etiqueta, control, ayuda) {
  return h('label.campo', etiqueta, control, ayuda ? h('span.ayuda', ayuda) : null);
}

function check(etiqueta, control, ayuda) {
  return h('div', h('label.check', control, etiqueta), ayuda ? h('div.ayuda', { style: { marginLeft: '1.6rem' } }, ayuda) : null);
}

function formularioConfig(claves, construir) {
  const c = estado.config;
  const controles = {};
  for (const [clave, tipo] of Object.entries(claves)) {
    controles[clave] = tipo === 'check'
      ? h('input', { type: 'checkbox', checked: c[clave] === '1' })
      : tipo === 'area' ? h('textarea', c[clave] || '') : h('input', { value: c[clave] || '' });
  }
  const error = h('div.error-modal.oculto', { role: 'alert' });
  const form = h('form.panel', error, construir(controles),
    h('div.fila.fin', { style: { marginTop: '1rem' } }, h('button.btn.primario', { type: 'submit' }, 'Guardar cambios')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const datos = Object.fromEntries(Object.entries(controles).map(([k, el]) => [k, el.type === 'checkbox' ? el.checked : el.value]));
    try {
      await api.put('/api/config', datos);
      aviso('Configuración guardada.', 'ok');
      await recargarConfiguracion({ pestana: pestanaActual });
    } catch (err) {
      error.textContent = err.message;
      error.classList.remove('oculto');
    }
  });
  return form;
}

function vistaNegocio() {
  return formularioConfig({
    negocio_nombre: 'texto', negocio_rut: 'texto', negocio_giro: 'texto', negocio_direccion: 'texto', negocio_telefono: 'texto', negocio_email: 'texto',
  }, (c) => [
    h('h3', 'Datos del negocio'),
    h('div.rejilla',
      campo('Nombre del negocio', c.negocio_nombre), campo('RUT', c.negocio_rut), campo('Giro', c.negocio_giro),
      campo('Dirección', c.negocio_direccion), campo('Teléfono', c.negocio_telefono), campo('Correo', c.negocio_email)),
    h('p.ayuda', { style: { marginTop: '.8rem' } }, 'Estos datos salen en el encabezado del ticket. Qué líneas salen y cómo se ven se elige en la pestaña «Ticket».'),
  ]);
}

const copiar = (x) => JSON.parse(JSON.stringify(x));

// Lo editado en la pestaña Ticket y todavía no guardado: se conserva al ir a otra pestaña o pantalla.
let borradorTicket = null;

/**
 * Ticket: ancho del papel (80 mm de fábrica), las líneas del encabezado y del pie, qué partes salen y
 * una vista previa que cambia mientras se edita.
 */
async function vistaTicket(zona) {
  const c = estado.config;
  const borrador = borradorTicket?.usuario === estado.usuario?.id ? borradorTicket : null;
  let diseno = copiar(borrador?.diseno || disenoTicket(c));
  const anchoInicial = borrador?.papel ?? (c.ticket_ancho === '58' ? '58' : '80');
  const papel = h('select', { 'aria-label': 'Ancho del papel' },
    h('option', { value: '80', selected: anchoInicial !== '58' }, '80 mm · 48 letras por línea (lo normal)'),
    h('option', { value: '58', selected: anchoInicial === '58' }, '58 mm · 32 letras por línea'));
  const automatico = h('input', { type: 'checkbox', checked: borrador ? borrador.automatico : c.imprimir_automatico === '1' });
  const directa = h('input', { type: 'checkbox', checked: borrador ? borrador.directa : c.impresion_directa === '1' });
  const error = h('div.error-modal.oculto', { role: 'alert' });
  const previa = h('div');
  const editores = h('div');
  const notaPapel = h('p.ayuda.nota-papel');
  const sinGuardar = h('span.sin-guardar', { class: borrador ? null : 'oculto' }, 'Hay cambios sin guardar');
  let ultimoCampo = null;   // la línea donde se insertan los datos del negocio
  let listo = false;
  // En NejiPOS.exe con impresora de tickets, la vista previa muestra los mismos renglones que el papel.
  const directo = Boolean(await escritorio()) && !leerImpresora()?.dialogo;

  const ejemplo = () => ({ ...ventaDeEjemplo(estado.usuario?.nombre_ticket || estado.usuario?.nombre || 'Cajero'), cliente: 'María González', cliente_rut: '12.345.678-5' });
  // El ancho con que imprime este computador: el de «Impresora de tickets» si lo fijó; si no, el de aquí.
  const papelEquipo = () => papelDe(leerImpresora(), papel.value);
  const pintarPrevia = () => {
    const pe = papelEquipo();
    const ticket = ticketVenta(ejemplo(), { diseno, papel: pe });
    notaPapel.textContent = pe !== papel.value
      ? `Este computador imprime en ${pe} mm (se eligió en «Impresora de tickets»): la vista previa y la prueba usan ese ancho.` : '';
    if (directo) {
      const impresora = leerImpresora();
      const columnas = columnasDe(impresora, papel.value);
      const renglones = componerRenglones(bloquesTicket(ticket), columnas, impresora?.codigo || 'cp850');
      vaciar(previa, h('div.papel-ticket',
        h('div.papel-termico', { 'aria-label': 'Vista previa del ticket', style: { width: `calc(${columnas}ch + 1.6rem)` } },
          renglones.map(([t, negrita, grande]) => h(`div.renglon${negrita ? '.g' : ''}${grande ? '.xl' : ''}`, t || '\u00a0')))));
    } else {
      vaciar(previa, h('div.papel-ticket', { 'aria-label': 'Vista previa del ticket' }, ticket));
    }
    if (listo) {
      borradorTicket = { usuario: estado.usuario?.id, diseno, papel: papel.value, automatico: automatico.checked, directa: directa.checked };
      sinGuardar.classList.remove('oculto');
    }
  };
  papel.addEventListener('change', pintarPrevia);
  automatico.addEventListener('change', pintarPrevia);
  directa.addEventListener('change', pintarPrevia);

  function editorLineas(seccion, titulo) {
    const cont = h('div.lineas-ticket');
    const pintar = (enfocar = null) => {
      const lista = diseno[seccion];
      vaciar(cont, lista.map((l, i) => {
        const texto = h('input', { value: l.texto, maxlength: 120, placeholder: 'Texto de la línea', 'aria-label': `${titulo}, línea ${i + 1}` });
        texto.addEventListener('input', () => { l.texto = texto.value; pintarPrevia(); });
        texto.addEventListener('focus', () => { ultimoCampo = { texto, linea: l }; });
        const alinear = h('select', { 'aria-label': `Alineación de la línea ${i + 1}` },
          h('option', { value: 'centro', selected: l.alinear !== 'izq' }, 'Centrada'),
          h('option', { value: 'izq', selected: l.alinear === 'izq' }, 'Izquierda'));
        alinear.addEventListener('change', () => { l.alinear = alinear.value; pintarPrevia(); });
        const alternar = (clave, etiqueta, nombre) => {
          const b = h('button.btn.chico.alternar', { type: 'button', title: nombre, 'aria-label': `${nombre} (línea ${i + 1})`, 'aria-pressed': String(Boolean(l[clave])) }, etiqueta);
          b.addEventListener('click', () => { l[clave] = !l[clave]; b.setAttribute('aria-pressed', String(l[clave])); pintarPrevia(); });
          return b;
        };
        const mover = (paso) => {
          const j = i + paso;
          [lista[i], lista[j]] = [lista[j], lista[i]];
          pintar(j);
          pintarPrevia();
        };
        return h('div.linea-ticket', texto, alinear,
          alternar('negrita', 'N', 'Negrita'), alternar('grande', 'A+', 'Letra grande'),
          h('button.btn.chico', { type: 'button', title: 'Subir', 'aria-label': `Subir la línea ${i + 1}`, disabled: i === 0, onclick: () => mover(-1) }, '↑'),
          h('button.btn.chico', { type: 'button', title: 'Bajar', 'aria-label': `Bajar la línea ${i + 1}`, disabled: i === lista.length - 1, onclick: () => mover(1) }, '↓'),
          h('button.btn.chico.peligro-suave', {
            type: 'button', title: 'Quitar la línea', 'aria-label': `Quitar la línea ${i + 1}`,
            onclick: () => {
              if (ultimoCampo?.linea === l) ultimoCampo = null;
              lista.splice(i, 1);
              pintar(Math.min(i, lista.length - 1));
              pintarPrevia();
            },
          }, '✕'));
      }), h('button.btn.chico', {
        type: 'button', disabled: lista.length >= 20,
        onclick: () => { lista.push({ texto: '', alinear: 'centro', negrita: false, grande: false }); pintar(lista.length - 1); },
      }, '+ Agregar línea'));
      if (enfocar !== null && enfocar >= 0) cont.querySelectorAll('.linea-ticket input')[enfocar]?.focus();
      else if (enfocar === -1) cont.querySelector(':scope > .btn')?.focus();   // sin líneas: «+ Agregar línea»
    };
    pintar();
    return h('section.seccion-ticket', h('h3', titulo),
      seccion === 'encabezado' ? h('p.ayuda', 'Lo que va entre llaves, como {nombre} o {rut}, se reemplaza por los datos de la pestaña «Negocio». Si todos los datos de una línea están vacíos, la línea no sale: por eso conviene poner cada dato en su propia línea. «N» es negrita y «A+» letra grande.') : null,
      cont);
  }

  // Botones para poner los datos del negocio en la línea que se está editando (sin perderla de vista).
  const insertar = h('div.fila.insertar-dato', h('span.ayuda', 'Insertar dato del negocio:'),
    DATOS_NEGOCIO.map(([clave, nombre]) => h('button.btn.chico', {
      type: 'button',
      onmousedown: (e) => e.preventDefault(),
      onclick: () => {
        if (!ultimoCampo?.texto.isConnected) return aviso('Primero haz clic en la línea donde va el dato.');
        const { texto, linea: l } = ultimoCampo;
        const desde = texto.selectionStart ?? texto.value.length;
        const hasta = texto.selectionEnd ?? desde;
        texto.value = `${texto.value.slice(0, desde)}{${clave}}${texto.value.slice(hasta)}`;
        l.texto = texto.value;
        texto.focus();
        texto.setSelectionRange(desde + clave.length + 2, desde + clave.length + 2);
        pintarPrevia();
        return null;
      },
    }, nombre)));

  const partes = Object.fromEntries(PARTES_TICKET.map(([k]) => [k, h('input', { type: 'checkbox', checked: diseno.mostrar[k] !== false })]));
  Object.entries(partes).forEach(([k, el]) => el.addEventListener('change', () => { diseno.mostrar[k] = el.checked; pintarPrevia(); }));

  const pintarEditores = () => vaciar(editores, editorLineas('encabezado', 'Encabezado'), insertar,
    h('section.seccion-ticket', h('h3', 'Qué más sale en el ticket'),
      h('div.partes-ticket', PARTES_TICKET.map(([k, nombre]) => h('label.check', partes[k], nombre))),
      h('p.ayuda', 'Siempre salen el folio y la fecha, los productos, el total y la forma de pago.')),
    editorLineas('pie', 'Pie (al final del ticket)'));

  const guardar = async () => {
    try {
      const limpio = { ...diseno, encabezado: diseno.encabezado.filter((l) => l.texto.trim()), pie: diseno.pie.filter((l) => l.texto.trim()) };
      await api.put('/api/config', { ticket_diseno: limpio, ticket_ancho: papel.value, imprimir_automatico: automatico.checked, impresion_directa: directa.checked });
      borradorTicket = null;
      aviso('Ticket guardado.', 'ok');
      await recargarConfiguracion({ pestana: pestanaActual });
    } catch (err) {
      // El botón está abajo: el error se ve en un aviso y arriba del panel, que se trae a la vista.
      error.textContent = err.message;
      error.classList.remove('oculto');
      avisoError(err);
      error.scrollIntoView({ block: 'center' });
    }
  };

  pintarEditores();
  pintarPrevia();
  listo = true;
  vaciar(zona, h('div.editor-ticket',
    h('div.panel',
      error,
      h('h3', 'Papel'),
      h('div.papel-general', campo('Ancho del papel', papel, 'Lo normal es 80 mm. Si tu impresora usa rollos de 58 mm, elige 58. Cada computador puede usar otro ancho en «Impresora de tickets».')),
      notaPapel,
      editores,
      h('h3', { style: { marginTop: '1rem' } }, 'Al cobrar'),
      check('Imprimir el ticket automáticamente al cobrar', automatico),
      check('Cuando se use el cuadro de impresión, imprimir sin mostrarlo (en la impresora predeterminada)', directa,
        'La impresora de tickets de cada caja se elige en la pestaña «Impresora de tickets» y ahí siempre se imprime directo. Esta opción es para lo demás (etiquetas, hojas) en NejiPOS.exe; se aplica al volver a abrir Neji POS.'),
      h('div.fila.entre', { style: { marginTop: '1rem' } },
        h('button.btn', {
          type: 'button',
          onclick: () => {
            diseno = copiar(disenoPredeterminado());
            Object.entries(partes).forEach(([k, el]) => { el.checked = diseno.mostrar[k] !== false; });
            papel.value = '80';
            ultimoCampo = null;
            pintarEditores();
            pintarPrevia();
            aviso('Se volvió al ticket de fábrica. Presiona «Guardar cambios» para quedarte con él.');
          },
        }, 'Volver al ticket de fábrica'),
        h('div.fila',
          sinGuardar,
          h('button.btn', { type: 'button', onclick: () => imprimir(ticketVenta(ejemplo(), { diseno, papel: papelEquipo() }), { papelGeneral: papel.value }) }, 'Imprimir prueba'),
          h('button.btn.primario', { type: 'button', onclick: guardar }, 'Guardar cambios')))),
    h('div.panel.previa-ticket', h('h3', 'Así sale el ticket'), previa)));
}

function vistaOpciones() {
  return formularioConfig({
    redondeo_efectivo: 'check', permitir_stock_negativo: 'check',
    iva_porcentaje: 'texto', respaldos_mantener: 'texto', modulo_farmacia: 'check',
  }, (c) => [
    h('h3', 'Tipo de negocio'),
    check('Farmacia: activar vademécum, principios activos y recetario magistral', c.modulo_farmacia,
      'Agrega las pantallas Vademécum y Recetario, el aviso clínico al vender y la búsqueda por componente con %.'),
    h('div', { style: { height: '.6rem' } }),
    h('h3', 'Ventas'),
    check('Redondear pagos en efectivo (Ley 20.956)', c.redondeo_efectivo, 'Si el total termina en 1 a 5 baja a la decena; si termina en 6 a 9 sube. La boleta se emite por el monto exacto.'),
    check('Permitir vender sin existencia (inventario negativo)', c.permitir_stock_negativo, 'Útil si todavía no cargas todo tu inventario.'),
    h('p.ayuda', { style: { marginTop: '1rem' } }, 'Los permisos de cada cajero (descuentos, devoluciones, corte, reportes…) se eligen en la pestaña Usuarios.'),
    h('h3', { style: { marginTop: '1.2rem' } }, 'Otros'),
    h('div.rejilla',
      campo('IVA (%)', c.iva_porcentaje),
      campo('Respaldos automáticos a guardar', c.respaldos_mantener, 'Se hace un respaldo diario de la base de datos.')),
  ]);
}

/** Venta de ejemplo para la vista previa del ticket. */
function ventaDeEjemplo(atendio) {
  const items = esFarmacia()
    ? [['PARACETAMOL 500MG X 16 COMP', 2, 990], ['LORATADINA 10MG X 10', 1, 1890]]
    : [['Bebida cola 1.5L', 2, 1590], ['Pan batido (kg)', 0.5, 2290]];
  const lineas = items.map(([descripcion, cantidad, precio]) => ({
    descripcion, cantidad, precio_unitario: precio, importe: Math.round(cantidad * precio), tipo_precio: 'normal',
  }));
  const total = lineas.reduce((t, l) => t + l.importe, 0);
  const iva = Math.round(total - total / 1.19);
  const recibido = Math.ceil(total / 1000) * 1000;
  const ahora = new Date();
  const local = new Date(ahora - ahora.getTimezoneOffset() * 60000);   // la hora de este equipo, como en los tickets
  return {
    folio: 1024, fecha: local.toISOString().slice(0, 19).replace('T', ' '), caja: nombreCaja(), atendio, usuario: atendio,
    items: lineas, subtotal: total, descuento: 0, total, neto: total - iva, iva, exento: 0,
    pagos: [{ metodo: 'efectivo', monto: total }], efectivo_recibido: recibido, cambio: recibido - total, redondeo: 0,
  };
}

/** Ticket de ejemplo en pantalla, con la línea «Atendió» destacada. */
export function previaTicket(atendio) {
  // Si la línea «Atendió» está apagada en Configuración → Ticket, se ve igual (para elegir el nombre) con un aviso.
  const apagada = disenoTicket().mostrar.atendio === false;
  return h('div',
    apagada ? h('p.aviso-suave', 'La línea «Atendió» está apagada en Configuración → Ticket: este nombre no sale en los tickets.') : null,
    h('div.papel-ticket', { 'aria-label': 'Vista previa del ticket' }, ticketVenta(ventaDeEjemplo(atendio), { destacarAtendio: true })));
}

async function vistaUsuarios(zona) {
  const catalogo = (await api.get('/api/permisos')).filter((p) => !p.farmacia || esFarmacia());
  let usuarios = [];
  let elegido = null;
  const lista = h('div');
  const previa = h('div');
  vaciar(zona, h('div.usuarios', lista, previa));

  async function cargar(id = elegido) {
    usuarios = await api.get('/api/usuarios');
    elegido = usuarios.some((u) => u.id === id) ? id : (usuarios.find((u) => u.id === estado.usuario.id) || usuarios[0])?.id;
    pintar();
  }

  function resumenPermisos(u) {
    if (u.rol === 'admin') return h('span.etiqueta.ok', 'Todos');
    const si = catalogo.filter((p) => u.permisos[p.clave]);
    return h('span', { title: si.map((p) => p.etiqueta).join('\n') || 'Solo vender' }, `${si.length} de ${catalogo.length}`);
  }

  const elegir = (u) => { elegido = u.id; pintar(); lista.querySelector(`tr[data-id="${u.id}"]`)?.focus(); };

  function pintar() {
    const tablaUsuarios = tabla([
        { titulo: 'Usuario', valor: (u) => h('b', u.usuario) },
        { titulo: 'Nombre', valor: (u) => u.nombre },
        { titulo: 'En el ticket', valor: (u) => u.nombre_ticket || h('span.suave', u.nombre) },
        { titulo: 'Rol', valor: (u) => (u.rol === 'admin' ? 'Administrador' : 'Cajero') },
        { titulo: 'Permisos', valor: resumenPermisos },
        { titulo: 'Estado', valor: (u) => h(`span.etiqueta.${u.activo ? 'ok' : 'mal'}`, u.activo ? 'Activo' : 'Inactivo') },
        {
          titulo: '',
          valor: (u) => h('button.btn.chico', {
            type: 'button', dataset: { editar: u.id }, 'aria-label': `Editar ${u.usuario}`,
            onclick: (e) => { e.stopPropagation(); elegido = u.id; pintarPrevia(); marcarElegido(); editar(u); },
          }, 'Editar'),
        },
      ], usuarios, {
        alClic: elegir,
        claseFila: (u) => (u.id === elegido ? 'sel' : ''),
      });
    // Las filas también se eligen con el teclado (Tab y Enter o Espacio).
    tablaUsuarios.querySelectorAll('tbody tr.clic').forEach((tr, i) => {
      const u = usuarios[i];
      tr.tabIndex = 0;
      tr.dataset.id = u.id;
      tr.setAttribute('aria-label', `Ver el ticket de ${u.usuario}`);
      tr.addEventListener('keydown', (e) => {
        if (e.target === tr && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); elegir(u); }
      });
    });
    vaciar(lista, h('div.panel',
      h('div.fila.entre', h('h3', 'Usuarios'), h('button.btn.primario', { type: 'button', dataset: { editar: 'nuevo' }, onclick: () => editar() }, 'Nuevo usuario')),
      tablaUsuarios,
      h('p.ayuda', 'El administrador puede todo, incluida esta configuración. A cada cajero se le eligen sus permisos con «Editar». Haz clic en un usuario para ver cómo sale en el ticket.')));
    pintarPrevia();
  }

  function marcarElegido() {
    lista.querySelectorAll('tbody tr').forEach((tr) => tr.classList.toggle('sel', Number(tr.dataset.id) === elegido));
  }

  function pintarPrevia() {
    const u = usuarios.find((x) => x.id === elegido);
    if (!u) {
      vaciar(previa);
      return;
    }
    const nombre = h('input', { value: u.nombre_ticket || '', placeholder: u.nombre, maxlength: 60, 'aria-label': 'Nombre en el ticket' });
    const papel = h('div');
    const refrescar = () => vaciar(papel, previaTicket(nombre.value.trim() || u.nombre));
    nombre.addEventListener('input', refrescar);
    const guardar = async () => {
      try {
        await api.put(`/api/usuarios/${u.id}`, { nombre_ticket: nombre.value.trim() });
        if (u.id === estado.usuario.id) estado.usuario.nombre_ticket = nombre.value.trim() || null;
        aviso('Nombre del ticket guardado.', 'ok');
        await cargar(u.id);
        previa.querySelector('input')?.focus();
      } catch (e) {
        avisoError(e);
      }
    };
    nombre.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); guardar(); } });
    refrescar();
    vaciar(previa, h('div.panel.previa-ticket',
      h('h3', 'Así sale en el ticket'),
      h('label.campo', `Atendió (${u.usuario})`, nombre,
        h('span.ayuda', 'Ej: «Cajero 1 · Cristóbal Araya Cortés». Vacío = su nombre.')),
      h('div.fila.fin', h('button.btn.primario', { type: 'button', onclick: guardar }, 'Guardar')),
      papel));
  }

  async function editar(u = null) {
    // Un administrador muestra lo que tendría como cajero: pasarlo a cajero restringe, no le da todo.
    const casillas = Object.fromEntries(catalogo.map((p) => [p.clave,
      h('input', { type: 'checkbox', checked: u ? (u.permisos_cajero || u.permisos)[p.clave] : p.por_defecto })]));
    const nota = h('p.ayuda.nota-admin');
    const permisos = h('fieldset.permisos',
      h('legend', 'Permisos del cajero'),
      nota,
      h('p.ayuda', 'Todos pueden vender, cobrar, abrir la caja y atender clientes.'),
      catalogo.map((p) => h('label.check', casillas[p.clave], p.etiqueta)));
    // Lo elegido para el cajero se guarda aparte mientras el rol es Administrador (que se ve con todo marcado).
    let deCajero = null;
    const valoresCajero = () => deCajero || Object.fromEntries(Object.entries(casillas).map(([k, el]) => [k, el.checked]));
    const r = await formulario({
      titulo: u ? `Editar ${u.usuario}` : 'Nuevo usuario',
      ancho: 'ancho',
      campos: [
        { nombre: 'usuario', etiqueta: 'Usuario (para entrar)', valor: u?.usuario, requerido: !u, deshabilitado: Boolean(u), autofocus: !u },
        { nombre: 'nombre', etiqueta: 'Nombre', valor: u?.nombre, autofocus: Boolean(u) },
        { nombre: 'nombre_ticket', etiqueta: 'Nombre en el ticket (Atendió)', valor: u?.nombre_ticket, placeholder: 'Vacío = su nombre', atributos: { maxlength: 60 } },
        { nombre: 'rol', etiqueta: 'Rol', tipo: 'select', valor: u?.rol || 'cajero', opciones: [['cajero', 'Cajero'], ['admin', 'Administrador']] },
        { nombre: 'password', etiqueta: u ? 'Nueva contraseña (vacío = no cambiar)' : 'Contraseña', tipo: 'password', requerido: !u },
        u ? { nombre: 'activo', etiqueta: 'Activo', tipo: 'check', valor: Boolean(u.activo) } : null,
      ].filter(Boolean),
      extra: permisos,
      alMostrar: (e) => {
        const segunRol = () => {
          const admin = e.rol.value === 'admin';
          if (admin && !deCajero) {
            deCajero = valoresCajero();
            Object.values(casillas).forEach((el) => { el.checked = true; });
          } else if (!admin && deCajero) {
            Object.entries(casillas).forEach(([k, el]) => { el.checked = deCajero[k]; });
            deCajero = null;
          }
          permisos.disabled = admin;
          permisos.classList.toggle('apagado', admin);
          nota.textContent = admin ? 'El administrador tiene todos los permisos, incluida la configuración, los usuarios y las cajas.' : '';
          nota.classList.toggle('oculto', !admin);
        };
        e.rol.addEventListener('change', segunRol);
        segunRol();
      },
      alEnviar: (v) => {
        v.permisos = valoresCajero();
        return u ? api.put(`/api/usuarios/${u.id}`, v) : api.post('/api/usuarios', v);
      },
    });
    if (r) {
      aviso('Usuario guardado.', 'ok');
      if (u?.id === estado.usuario.id) estado.usuario = { ...estado.usuario, nombre: r.nombre, nombre_ticket: r.nombre_ticket };
      await cargar(r.id);
    }
    // El foco vuelve al botón «Editar» de ese usuario (o a «Nuevo usuario»).
    const id = r?.id ?? u?.id;
    (lista.querySelector(`button[data-editar="${id}"]`) || lista.querySelector('button[data-editar="nuevo"]'))?.focus();
  }

  await cargar();
}

/** Varias cajas: las otras se conectan a este equipo por la red local. */
function panelRed(equipo) {
  const permitir = h('input', { type: 'checkbox', checked: estado.config.modo_red === '1' });
  const situacion = h('div');
  const pintar = () => {
    if (equipo?.red_activa && permitir.checked) {
      vaciar(situacion, h('p', 'Las otras cajas entran desde su navegador a ', h('b.mono', equipo.direccion_red),
        ' (o abren NejiPOS.exe con ', h('span.mono', `--conectar ${equipo.direccion_red.replace('http://', '')}`), ').'));
    } else if (permitir.checked !== Boolean(equipo?.red_activa)) {
      vaciar(situacion, h('p', h('b', 'El cambio se aplica la próxima vez que abras Neji POS en este equipo.')));
    } else {
      vaciar(situacion, h('p.suave', 'Ahora solo este equipo puede usar Neji POS.'));
    }
  };
  permitir.addEventListener('change', async () => {
    try {
      estado.config = await api.put('/api/config', { modo_red: permitir.checked });
      aviso('Listo. El cambio se aplica al volver a abrir Neji POS en este equipo.', 'ok', 6000);
    } catch (e) {
      permitir.checked = !permitir.checked;
      avisoError(e);
    }
    pintar();
  });
  pintar();
  return h('div', { style: { marginTop: '1.2rem' } },
    h('h3', 'Varias cajas en la red'),
    h('label.check', permitir, 'Permitir que otras cajas de la red se conecten a este equipo'),
    situacion,
    h('p.ayuda', 'Este equipo debe quedar encendido y con Neji POS abierto mientras las otras cajas vendan. La primera vez, Windows puede preguntar si permite el acceso a la red: acepta en «Redes privadas». Luego elige en cada equipo qué caja es, en la pestaña «Esta terminal».'));
}

async function vistaCajas(zona) {
  const cargar = async () => {
    const cajas = await api.get('/api/cajas');
    vaciar(zona, h('div.panel',
      h('div.fila.entre', h('h3', 'Cajas'), h('button.btn.primario', { type: 'button', onclick: () => editar() }, 'Nueva caja')),
      tabla([
        { titulo: 'N°', valor: (c) => c.id },
        { titulo: 'Nombre', valor: (c) => [c.nombre, c.principal ? [' ', h('span.etiqueta.ok', 'principal')] : null] },
        { titulo: 'Estado', valor: (c) => h(`span.etiqueta.${c.activa ? 'ok' : 'mal'}`, c.activa ? 'Activa' : 'Inactiva') },
      ], cajas, { alClic: (c) => editar(c) }),
      h('p.ayuda', 'Desde la caja principal se hace el corte general: cierra juntas todas las cajas y suma lo de todos los cajeros.'),
      panelRed(equipo)));
  };
  const equipo = await api.get('/api/equipo').catch(() => null);
  const editar = async (c = null) => {
    const r = await formulario({
      titulo: c ? `Editar ${c.nombre}` : 'Nueva caja',
      campos: [
        { nombre: 'nombre', etiqueta: 'Nombre', valor: c?.nombre, requerido: true },
        c ? { nombre: 'activa', etiqueta: 'Activa', tipo: 'check', valor: Boolean(c.activa) } : null,
        c && !c.principal ? { nombre: 'principal', etiqueta: 'Caja principal (aquí se hace el corte general)', tipo: 'check', valor: false } : null,
      ].filter(Boolean),
      alEnviar: (v) => (c ? api.put(`/api/cajas/${c.id}`, v) : api.post('/api/cajas', v)),
    });
    if (r) { await recargarConfiguracion({ pestana: pestanaActual }); }
  };
  await cargar();
}

function vistaTerminal() {
  const sel = h('select', estado.cajas.filter((c) => c.activa).map((c) => h('option', { value: c.id, selected: c.id === estado.cajaId }, c.nombre)));
  return h('div.panel',
    h('h3', 'Esta terminal'),
    h('p', 'Elige qué caja es este computador. Cada caja tiene su propio turno y su propio corte.'),
    h('div.fila', h('div', { style: { maxWidth: '300px', flex: 1 } }, sel),
      h('button.btn.primario', {
        type: 'button',
        onclick: async () => { fijarCaja(parseInt(sel.value, 10)); aviso('Caja de esta terminal actualizada.', 'ok'); await recargarConfiguracion({ pestana: pestanaActual }); },
      }, 'Usar esta caja')),
    h('h3', { style: { marginTop: '1.4rem' } }, 'Atajos de teclado'),
    tabla([{ titulo: 'Tecla', valor: (f) => h('kbd', f[0]) }, { titulo: 'Acción', valor: (f) => f[1] }], [
      ['F1 / F2 / F3 / F4', 'Ir a Ventas / Clientes / Productos / Inventario'],
      ['Enter', 'Agregar el código escrito o escaneado (acepta 3*código para varias unidades)'],
      ['F10', 'Buscar producto por descripción'],
      ['INS', 'Varios: cantidad + código'],
      ['Ctrl+P', 'Artículo común (no registrado)'],
      ['F11 o Ctrl+M', 'Precio de mayoreo en la línea seleccionada'],
      ['↑ ↓', 'Moverse por las líneas del ticket'],
      ['+ / − / *', 'Sumar, restar o escribir la cantidad de la línea'],
      ['Supr', 'Borrar la línea seleccionada'],
      ['Ctrl+D', 'Descuento al ticket'],
      ['F5', 'Asignar cliente'],
      ['F6', 'Nuevo ticket (deja el actual pendiente)'],
      ['RePág / AvPág', 'Cambiar de ticket'],
      ['F7 / F8', 'Entrada / salida de efectivo'],
      ['F9', 'Verificador de precios'],
      ['F12', 'Cobrar (en el cobro: F1 efectivo … F6 mixto)'],
    ]));
}

function vistaImportar() {
  const importador = importadorCsv();
  return h('div.panel',
    h('h3', 'Importar inventario desde CSV'),
    importador.el,
    h('div.fila.fin', { style: { marginTop: '1rem' } },
      h('button.btn.primario', {
        type: 'button',
        onclick: async (e) => {
          const boton = e.currentTarget;
          boton.disabled = true;
          try { await importador.importar(); } finally { boton.disabled = false; }
        },
      }, 'Importar')));
}

/** Ticket de prueba: tildes, eñes, columnas y letra grande. */
function ticketPrueba(papel) {
  const ln = (izq, der, clase = '') => h(`div.ln${clase ? '.' + clase : ''}`, h('span', izq), h('span', der));
  return h(`div.ticket${papel === '58' ? '.t58' : ''}`,
    h('div.c.xl', estado.config.negocio_nombre || 'Neji POS'),
    h('div.c', 'Prueba de impresión'),
    h('hr'),
    h('div', 'Tildes y eñes: áéíóú ÁÉÍÓÚ ñ Ñ ü ¿? ¡! °'),
    ln('Izquierda', 'Derecha'),
    ln('Producto con un nombre bastante largo para ver cómo se corta', '$1.990'),
    ln('TOTAL', '$12.345', 'xl'),
    h('hr'),
    h('div.c', 'Si ves esto bien, la impresora está lista.'),
    h('div', { style: { height: '8mm' } }));
}

// Marcas sin «modo chino» (a las genéricas POS-58/POS-80 se les apaga, igual que en neji/impresoras.py).
const SIN_MODO_CHINO = /epson|\bstar\b|\btsp|bixolon|\bsrp-|citizen|\bct-s|samsung|\btm-/i;

/** Impresora de tickets de este computador (se guarda en este equipo, no en el servidor). */
async function vistaImpresora(zona) {
  let detectadas = await listarImpresoras();
  const guardada = leerImpresora();
  let config = { modo: 'escpos', papel: '', cortar: true, cajon: true, codigo: 'cp850', copias: 1, ...(guardada || {}) };
  // Una encontrada sola solo fija el papel si su nombre lo dice; si no, manda el de Configuración → Ticket.
  if (config.automatica && config.papel !== '58') config.papel = '';
  if (!guardada && detectadas.ok) {
    // Sin elegir todavía: se propone la que Neji usaría sola.
    const sugerida = impresoraSugerida(detectadas.impresoras);
    if (sugerida) config = { ...config, ...configAutomatica(sugerida) };
  }

  function formularioActual(campos) {
    const nombre = campos.nombre();
    return {
      ...config,
      nombre,
      dialogo: !nombre,
      modo: campos.modo.value,
      papel: campos.papel.value,
      cortar: campos.cortar.checked,
      cajon: campos.cajon.checked,
      copias: Number(campos.copias.value) || 1,
      codigo: campos.codigo.value,
      sin_chino: campos.sinChino.checked,
      columnas: campos.columnas.value ? Math.max(16, Math.min(80, Number(campos.columnas.value) || 0)) || null : null,
      automatica: false,
    };
  }

  function pintar() {
    const impresoras = detectadas.impresoras || [];
    const actual = impresoras.some((i) => i.nombre === config.nombre) ? config.nombre : (config.dialogo ? '' : config.nombre || '');
    const radios = [];
    const opcion = (valor) => {
      const r = h('input.radio', {
        type: 'radio', name: 'impresora', value: valor, checked: valor === actual,
        'aria-label': valor ? `Usar ${valor}` : 'Ninguna: usar el cuadro de impresión',
        onchange: () => alElegir(valor),
      });
      radios.push(r);
      return r;
    };
    const chinoPorDefecto = (nombre) => Boolean(nombre) && !SIN_MODO_CHINO.test(nombre);
    let chinoTocado = typeof config.sin_chino === 'boolean';
    // Al elegir otra impresora se ajusta lo que depende de ella (si no se cambió a mano).
    const alElegir = (nombre) => {
      const i = impresoras.find((x) => x.nombre === nombre);
      if (i) {
        // Una que no parece de tickets va mejor con su controlador y sin pulso de cajón.
        campos.modo.value = i.termica ? 'escpos' : 'windows';
        campos.cajon.checked = Boolean(i.termica);
        if (esDe58(i)) campos.papel.value = '58';
      }
      if (!chinoTocado) campos.sinChino.checked = chinoPorDefecto(nombre);
    };
    const general = estado.config.ticket_ancho === '58' ? '58' : '80';
    const etiquetas = (i) => [
      i.termica ? h('span.etiqueta.ok', 'de tickets') : null,
      i.predeterminada ? h('span.etiqueta', 'predeterminada') : null,
      i.virtual ? h('span.etiqueta', 'virtual') : null,
      i.sin_conexion ? h('span.etiqueta.mal', 'sin conexión') : null,
      i.sin_papel ? h('span.etiqueta.mal', 'sin papel') : null,
    ];
    const campos = {
      nombre: () => radios.find((r) => r.checked)?.value || '',
      papel: h('select', { 'aria-label': 'Papel' },
        h('option', { value: '', selected: !['58', '80'].includes(config.papel) }, `General (${general} mm)`),
        h('option', { value: '80', selected: config.papel === '80' }, '80 mm (48 letras por línea)'),
        h('option', { value: '58', selected: config.papel === '58' }, '58 mm (32 letras por línea)')),
      modo: h('select', { 'aria-label': 'Forma de imprimir' },
        h('option', { value: 'escpos', selected: config.modo !== 'windows' }, 'Directa (ESC/POS)'),
        h('option', { value: 'windows', selected: config.modo === 'windows' }, 'Con el controlador de Windows')),
      cortar: h('input', { type: 'checkbox', checked: config.cortar !== false }),
      cajon: h('input', { type: 'checkbox', checked: config.cajon !== false }),
      copias: h('select', { 'aria-label': 'Copias' }, [1, 2, 3].map((n) => h('option', { value: n, selected: Number(config.copias || 1) === n }, String(n)))),
      codigo: h('select', { 'aria-label': 'Página de códigos' },
        [['cp850', 'PC850 Latino (recomendada)'], ['cp858', 'PC858 (con €)'], ['cp1252', 'Windows-1252'], ['cp437', 'PC437 (de fábrica)']]
          .map(([v, t]) => h('option', { value: v, selected: (config.codigo || 'cp850') === v }, t))),
      columnas: h('input', { inputmode: 'numeric', value: config.columnas || '', placeholder: 'Automático', style: { maxWidth: '140px' } }),
      sinChino: h('input', {
        type: 'checkbox', checked: typeof config.sin_chino === 'boolean' ? config.sin_chino : chinoPorDefecto(config.nombre),
        onchange: () => { chinoTocado = true; },
      }),
    };

    const estadoActual = config.nombre && !config.dialogo
      ? h('p', 'Los tickets se imprimen directo en ', h('b', config.nombre), config.automatica ? ' (Neji la encontró sola).' : '.')
      : h('p', 'Los tickets se imprimen con el cuadro de impresión de Windows.');

    const lista = !detectadas.escritorio
      ? h('div.aviso-suave',
        h('p', h('b', 'Estás usando Neji POS en el navegador. '), 'Aquí la impresora se elige en el cuadro de impresión.'),
        h('p.ayuda', 'Con el programa NejiPOS.exe, Neji encuentra solo las impresoras instaladas en este computador (USB, red o serie: POS-80, POS-58, SLK, Epson, Xprinter…) e imprime directo, sin preguntar.'))
      : !detectadas.ok
        ? h('div.error-modal', detectadas.error || 'No se pudieron leer las impresoras.')
        : tabla([
          { titulo: 'Usar', valor: (i) => opcion(i.nombre) },
          { titulo: 'Impresora', valor: (i) => [h('b', i.nombre), ' ', etiquetas(i)] },
          { titulo: 'Conexión', valor: (i) => i.conexion },
          { titulo: 'Controlador', valor: (i) => h('span.suave', i.controlador) },
        ], impresoras, { vacio: 'No hay impresoras instaladas en este computador.', alClic: (i) => { const r = radios.find((x) => x.value === i.nombre); if (r) r.checked = true; } });

    const probar = async () => {
      const prueba = formularioActual(campos);
      if (!prueba.nombre) return imprimirConDialogo(ticketPrueba(papelDe(prueba)));
      const api = await escritorio();
      const r = api ? await api.imprimir(trabajoImpresion(prueba, bloquesTicket(ticketPrueba(papelDe(prueba))))) : null;
      if (r?.ok) aviso(r.aviso || `Prueba enviada a «${prueba.nombre}».`, r.aviso ? 'error' : 'ok', r.aviso ? 8000 : 3500);
      else avisoError(new Error(r?.error || 'No se pudo imprimir.'));
      return null;
    };
    const guardar = h('button.btn.primario', {
      type: 'button',
      onclick: () => {
        config = formularioActual(campos);
        guardarImpresora(config);
        aviso('Impresora guardada en este computador.', 'ok');
        pintar();
      },
    }, 'Guardar');
    const ayudaPapel = h('span.ayuda', 'El general se elige en la pestaña Ticket y vale para todas las cajas. Cámbialo aquí solo si esta impresora usa otro papel.');

    if (!detectadas.escritorio) {
      // En el navegador manda el cuadro de impresión: aquí solo se elige el ancho del papel.
      vaciar(zona, h('div.panel.impresora',
        h('h3', 'Impresora de tickets de este computador'),
        lista,
        h('div.rejilla', { style: { marginTop: '1rem' } }, h('label.campo', 'Papel', campos.papel, ayudaPapel)),
        h('div.fila.fin', { style: { marginTop: '1rem' } }, h('button.btn', { type: 'button', onclick: probar }, 'Imprimir prueba'), guardar)));
      return;
    }

    vaciar(zona, h('div.panel.impresora',
      h('div.fila.entre', h('h3', 'Impresora de tickets de este computador'),
        detectadas.escritorio ? h('button.btn', { type: 'button', onclick: async () => { detectadas = await listarImpresoras({ refrescar: true }); pintar(); } }, 'Buscar de nuevo') : null),
      estadoActual,
      lista,
      detectadas.escritorio && detectadas.ok ? h('label.check', opcion(''), 'Ninguna: usar siempre el cuadro de impresión de Windows') : null,
      h('div.rejilla', { style: { marginTop: '1rem' } },
        h('label.campo', 'Papel', campos.papel, ayudaPapel),
        h('label.campo', 'Forma de imprimir', campos.modo, h('span.ayuda', 'La directa es para impresoras de tickets: más rápida, corta el papel y abre el cajón. La del controlador sirve con cualquier impresora; úsala si salen símbolos raros.')),
        h('label.campo', 'Copias', campos.copias)),
      h('label.check', campos.cortar, 'Cortar el papel al terminar el ticket'),
      h('label.check', campos.cajon, 'Abrir el cajón de dinero al cobrar en efectivo (cajón conectado a la impresora)'),
      h('details', { style: { marginTop: '.6rem' } },
        h('summary', 'Avanzado'),
        h('div.rejilla', { style: { marginTop: '.6rem' } },
          h('label.campo', 'Página de códigos (tildes y ñ)', campos.codigo, h('span.ayuda', 'Si las tildes salen mal, prueba otra.')),
          h('label.campo', 'Letras por línea', campos.columnas, h('span.ayuda', 'Vacío = según el papel. Algunas de 80 mm usan 42.'))),
        h('label.check', campos.sinChino, 'Apagar el modo chino (si las tildes o la ñ salen como letras chinas)')),
      h('div.fila.fin', { style: { marginTop: '1rem' } },
        h('button.btn', { type: 'button', onclick: probar }, 'Imprimir prueba'),
        guardar),
      h('p.ayuda', 'Esta elección es de este computador: cada caja usa su propia impresora. Las etiquetas de códigos de barras y las hojas se imprimen siempre con el cuadro de impresión.')));
  }
  pintar();
}

async function vistaRespaldos(zona) {
  const cargar = async () => {
    const [respaldos, equipo] = await Promise.all([api.get('/api/respaldos'), api.get('/api/equipo').catch(() => null)]);
    const carpeta = equipo?.carpeta_datos || 'datos';
    vaciar(zona, h('div.panel',
      h('div.fila.entre', h('h3', 'Respaldos'),
        h('button.btn.primario', { type: 'button', onclick: async () => { try { await api.post('/api/respaldos'); aviso('Respaldo creado.', 'ok'); cargar(); } catch (e) { avisoError(e); } } }, 'Respaldar ahora')),
      h('p', 'Neji hace un respaldo automático cada día y guarda los últimos. Descarga uno de vez en cuando y guárdalo en un pendrive o en la nube: si el computador falla, con ese archivo recuperas todo.'),
      tabla([
        { titulo: 'Archivo', valor: (r) => h('span.mono', r.nombre) },
        { titulo: 'Fecha', valor: (r) => fecha(r.fecha) },
        { titulo: 'Tamaño', valor: (r) => `${numero(Math.round(r.tamano / 1024))} KB`, clase: 'num' },
        { titulo: '', valor: (r) => h('button.btn.chico', { type: 'button', onclick: () => descargar(`/api/respaldos/${encodeURIComponent(r.nombre)}`) }, 'Descargar') },
      ], respaldos, { vacio: 'Aún no hay respaldos.' }),
      h('p', 'Tus datos están en ', h('b.mono', carpeta), '. Los respaldos automáticos quedan en la carpeta «respaldos» dentro de ella.'),
      h('p.ayuda', `Para restaurar: cierra Neji POS, reemplaza el archivo neji.db de esa carpeta por el respaldo (renómbralo a neji.db) y vuelve a abrir.`)));
  };
  await cargar();
}

export async function montar(contenedor, parametros = {}) {
  const admin = esAdmin();
  const opciones = admin
    ? [['negocio', 'Negocio'], ['ticket', 'Ticket'], ['opciones', 'Opciones'], ['usuarios', 'Usuarios'], ['cajas', 'Cajas'], ['terminal', 'Esta terminal'],
      ['impresora', 'Impresora de tickets'], ['respaldos', 'Respaldos'], ['importar', 'Importar inventario (CSV)']]
    : [['terminal', 'Esta terminal'], ['impresora', 'Impresora de tickets']];
  let actual = opciones.some(([k]) => k === parametros.pestana) ? parametros.pestana : opciones[0][0];
  const barra = h('div');
  const zona = h('div');
  // La versión, para saber cuál está abierta (por ejemplo, después de instalar una nueva).
  vaciar(contenedor, h('div.fila.entre', h('h2', 'Configuración'), h('span.version', `Neji POS versión ${estado.version || '—'}`)), barra, zona);

  async function mostrar(p) {
    actual = p;
    pestanaActual = p;
    vaciar(barra, pestanas(opciones, actual, mostrar));
    try {
      if (p === 'negocio') vaciar(zona, vistaNegocio());
      else if (p === 'ticket') await vistaTicket(zona);
      else if (p === 'opciones') vaciar(zona, vistaOpciones());
      else if (p === 'usuarios') await vistaUsuarios(zona);
      else if (p === 'cajas') await vistaCajas(zona);
      else if (p === 'respaldos') await vistaRespaldos(zona);
      else if (p === 'importar') vaciar(zona, vistaImportar());
      else if (p === 'impresora') await vistaImpresora(zona);
      else vaciar(zona, vistaTerminal());
    } catch (e) {
      avisoError(e);
    }
  }
  await mostrar(actual);
}
