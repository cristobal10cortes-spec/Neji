// Configuración: negocio, ticket, opciones, usuarios, cajas, esta terminal y respaldos.

import { api, descargar } from '../api.js';
import { ir, recargarConfiguracion } from '../app.js';
import { esAdmin, estado, fijarCaja } from '../estado.js';
import { aviso, avisoError, fecha, formulario, h, numero, pestanas, tabla, vaciar } from '../ui.js';

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
    ticket_encabezado: 'area', ticket_pie: 'area', ticket_leyenda: 'texto', ticket_ancho: 'texto', imprimir_automatico: 'check',
  }, (c) => {
    const ancho = h('select', h('option', { value: '80', selected: estado.config.ticket_ancho !== '58' }, '80 mm'), h('option', { value: '58', selected: estado.config.ticket_ancho === '58' }, '58 mm'));
    c.ticket_ancho = ancho;
    return [
      h('h3', 'Datos del negocio'),
      h('div.rejilla',
        campo('Nombre del negocio', c.negocio_nombre), campo('RUT', c.negocio_rut), campo('Giro', c.negocio_giro),
        campo('Dirección', c.negocio_direccion), campo('Teléfono', c.negocio_telefono), campo('Correo', c.negocio_email)),
      h('h3', { style: { marginTop: '1.2rem' } }, 'Ticket'),
      h('div.rejilla',
        campo('Ancho del papel', ancho),
        campo('Texto bajo el encabezado', c.ticket_encabezado, 'Ej: horario de atención o redes sociales'),
        campo('Mensaje al final', c.ticket_pie),
        campo('Leyenda legal', c.ticket_leyenda, 'Mientras no emitas boleta electrónica desde Neji, el ticket es un comprobante interno.')),
      check('Imprimir el ticket automáticamente al cobrar', c.imprimir_automatico),
    ];
  });
}

function vistaOpciones() {
  return formularioConfig({
    redondeo_efectivo: 'check', permitir_stock_negativo: 'check', cajero_puede_cambiar_precio: 'check', cajero_puede_devolver: 'check',
    iva_porcentaje: 'texto', respaldos_mantener: 'texto', modulo_farmacia: 'check',
  }, (c) => [
    h('h3', 'Tipo de negocio'),
    check('Farmacia: activar vademécum, principios activos y recetario magistral', c.modulo_farmacia,
      'Agrega las pantallas Vademécum y Recetario, el aviso clínico al vender y la búsqueda por componente con %.'),
    h('div', { style: { height: '.6rem' } }),
    h('h3', 'Ventas'),
    check('Redondear pagos en efectivo (Ley 20.956)', c.redondeo_efectivo, 'Si el total termina en 1 a 5 baja a la decena; si termina en 6 a 9 sube. La boleta se emite por el monto exacto.'),
    check('Permitir vender sin existencia (inventario negativo)', c.permitir_stock_negativo, 'Útil si todavía no cargas todo tu inventario.'),
    h('h3', { style: { marginTop: '1.2rem' } }, 'Permisos de cajeros'),
    check('Los cajeros pueden cambiar precios y aplicar descuentos', c.cajero_puede_cambiar_precio),
    check('Los cajeros pueden hacer devoluciones', c.cajero_puede_devolver),
    h('h3', { style: { marginTop: '1.2rem' } }, 'Otros'),
    h('div.rejilla',
      campo('IVA (%)', c.iva_porcentaje),
      campo('Respaldos automáticos a guardar', c.respaldos_mantener, 'Se hace un respaldo diario de la base de datos.')),
  ]);
}

async function vistaUsuarios(zona) {
  const cargar = async () => {
    const usuarios = await api.get('/api/usuarios');
    vaciar(zona, h('div.panel',
      h('div.fila.entre', h('h3', 'Usuarios'), h('button.btn.primario', { type: 'button', onclick: () => editar() }, 'Nuevo usuario')),
      tabla([
        { titulo: 'Usuario', valor: (u) => h('b', u.usuario) },
        { titulo: 'Nombre', valor: (u) => u.nombre },
        { titulo: 'Rol', valor: (u) => (u.rol === 'admin' ? 'Administrador' : 'Cajero') },
        { titulo: 'Estado', valor: (u) => h(`span.etiqueta.${u.activo ? 'ok' : 'mal'}`, u.activo ? 'Activo' : 'Inactivo') },
      ], usuarios, { alClic: (u) => editar(u) }),
      h('p.ayuda', 'El administrador ve reportes, costos e inventario y cambia la configuración. El cajero vende, cobra, atiende clientes y hace cortes.')));
  };
  const editar = async (u = null) => {
    const r = await formulario({
      titulo: u ? `Editar ${u.usuario}` : 'Nuevo usuario',
      campos: [
        { nombre: 'usuario', etiqueta: 'Usuario', valor: u?.usuario, requerido: !u, deshabilitado: Boolean(u), autofocus: !u },
        { nombre: 'nombre', etiqueta: 'Nombre', valor: u?.nombre, autofocus: Boolean(u) },
        { nombre: 'rol', etiqueta: 'Rol', tipo: 'select', valor: u?.rol || 'cajero', opciones: [['cajero', 'Cajero'], ['admin', 'Administrador']] },
        { nombre: 'password', etiqueta: u ? 'Nueva contraseña (vacío = no cambiar)' : 'Contraseña', tipo: 'password', requerido: !u },
        u ? { nombre: 'activo', etiqueta: 'Activo', tipo: 'check', valor: Boolean(u.activo) } : null,
      ].filter(Boolean),
      alEnviar: (v) => (u ? api.put(`/api/usuarios/${u.id}`, v) : api.post('/api/usuarios', v)),
    });
    if (r) { aviso('Usuario guardado.', 'ok'); cargar(); }
  };
  await cargar();
}

async function vistaCajas(zona) {
  const cargar = async () => {
    const cajas = await api.get('/api/cajas');
    vaciar(zona, h('div.panel',
      h('div.fila.entre', h('h3', 'Cajas'), h('button.btn.primario', { type: 'button', onclick: () => editar() }, 'Nueva caja')),
      tabla([
        { titulo: 'N°', valor: (c) => c.id },
        { titulo: 'Nombre', valor: (c) => c.nombre },
        { titulo: 'Estado', valor: (c) => h(`span.etiqueta.${c.activa ? 'ok' : 'mal'}`, c.activa ? 'Activa' : 'Inactiva') },
      ], cajas, { alClic: (c) => editar(c) }),
      h('p.ayuda', 'Para usar varias cajas, inicia Neji con «iniciar-red» en el computador principal y entra desde los otros equipos con la dirección que aparece en la ventana. Luego elige en cada equipo qué caja es en la pestaña «Esta terminal».')));
  };
  const editar = async (c = null) => {
    const r = await formulario({
      titulo: c ? `Editar ${c.nombre}` : 'Nueva caja',
      campos: [
        { nombre: 'nombre', etiqueta: 'Nombre', valor: c?.nombre, requerido: true },
        c ? { nombre: 'activa', etiqueta: 'Activa', tipo: 'check', valor: Boolean(c.activa) } : null,
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

const OPCIONES_IMPORTAR = [
  ['productos', 'Productos (código, nombre, costo, precio, departamento, distribuidor, vencimiento y principio activo)'],
  ['existencias', 'Existencias (stock) de los productos'],
  ['vademecum', 'Vademécum (uso terapéutico y efectos adversos)'],
  ['recetario', 'Recetario: precios de principios activos y fórmulas magistrales'],
  ['negocio', 'Datos del negocio para el ticket (nombre, dirección, teléfono, correo)'],
];

function vistaImportar() {
  const archivo = h('input', { type: 'file', accept: '.db,.sqlite,.sqlite3' });
  const opciones = Object.fromEntries(OPCIONES_IMPORTAR.map(([k]) => [k, h('input', { type: 'checkbox', checked: true })]));
  const resultado = h('div');
  const error = h('div.error-modal.oculto', { role: 'alert' });
  const boton = h('button.btn.primario', { type: 'button' }, 'Importar');
  boton.addEventListener('click', async () => {
    error.classList.add('oculto');
    if (!archivo.files[0]) {
      error.textContent = 'Elige el archivo corand_erp_pro.db.';
      error.classList.remove('oculto');
      return;
    }
    const datos = new FormData();
    datos.append('archivo', archivo.files[0]);
    for (const [k, el] of Object.entries(opciones)) datos.append(k, el.checked ? '1' : '0');
    boton.disabled = true;
    boton.textContent = 'Importando...';
    try {
      const r = await api.subir('/api/importar/corand', datos);
      vaciar(resultado, h('div.panel', { style: { marginTop: '1rem' } },
        h('h3', 'Importación terminada'),
        h('ul',
          h('li', `Productos nuevos: ${r.productos_creados} · actualizados: ${r.productos_actualizados} · con principio activo: ${r.productos_con_principio}`),
          h('li', `Fichas de vademécum: ${r.fichas_vademecum}`),
          h('li', `Principios activos con precio de recetario: ${r.precios_recetario} · fórmulas magistrales: ${r.formas}`),
          h('li', `Datos del negocio actualizados: ${r.datos_negocio}`)),
        r.advertencias.length ? [h('p.rojo', `${r.advertencias.length} advertencias:`), h('ul', r.advertencias.map((a) => h('li', a)))] : null,
        h('button.btn', { type: 'button', onclick: async () => { await recargarConfiguracion(); ir('vademecum'); } }, 'Ir al vademécum')));
      aviso('Importación terminada. Se hizo un respaldo antes de empezar.', 'ok', 6000);
    } catch (e) {
      error.textContent = e.message;
      error.classList.remove('oculto');
    } finally {
      boton.disabled = false;
      boton.textContent = 'Importar';
    }
  });
  return h('div.panel',
    h('h3', 'Importar desde CORAND.ERP / Easy Pharma'),
    h('p', 'Trae tus datos del programa anterior: elige el archivo ', h('b', 'corand_erp_pro.db'), ' (está en la misma carpeta que el programa).'),
    h('ol.ayuda',
      h('li', 'Cierra CORAND.ERP antes de copiar el archivo.'),
      h('li', 'Neji hace un respaldo de su base antes de importar y no modifica tu archivo original.'),
      h('li', 'Si un producto o principio activo ya existe, se actualiza (no se duplica). Puedes importar de nuevo cuando quieras.'),
      h('li', 'Los usuarios no se importan: en CORAND las contraseñas están sin cifrar. Créalos en la pestaña Usuarios.')),
    error,
    h('div.fila', archivo),
    h('div', { style: { margin: '.75rem 0' } }, OPCIONES_IMPORTAR.map(([k, t]) => h('label.check', opciones[k], t))),
    boton,
    resultado);
}

async function vistaRespaldos(zona) {
  const cargar = async () => {
    const respaldos = await api.get('/api/respaldos');
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
      h('p.ayuda', 'Para restaurar: cierra Neji, reemplaza el archivo datos/neji.db por el respaldo (renómbralo a neji.db) y vuelve a abrir.')));
  };
  await cargar();
}

export async function montar(contenedor, parametros = {}) {
  const admin = esAdmin();
  const opciones = admin
    ? [['negocio', 'Negocio y ticket'], ['opciones', 'Opciones'], ['usuarios', 'Usuarios'], ['cajas', 'Cajas'], ['terminal', 'Esta terminal'], ['respaldos', 'Respaldos'], ['importar', 'Importar']]
    : [['terminal', 'Esta terminal']];
  let actual = opciones.some(([k]) => k === parametros.pestana) ? parametros.pestana : opciones[0][0];
  const barra = h('div');
  const zona = h('div');
  vaciar(contenedor, h('h2', 'Configuración'), barra, zona);

  async function mostrar(p) {
    actual = p;
    pestanaActual = p;
    vaciar(barra, pestanas(opciones, actual, mostrar));
    try {
      if (p === 'negocio') vaciar(zona, vistaNegocio());
      else if (p === 'opciones') vaciar(zona, vistaOpciones());
      else if (p === 'usuarios') await vistaUsuarios(zona);
      else if (p === 'cajas') await vistaCajas(zona);
      else if (p === 'respaldos') await vistaRespaldos(zona);
      else if (p === 'importar') vaciar(zona, vistaImportar());
      else vaciar(zona, vistaTerminal());
    } catch (e) {
      avisoError(e);
    }
  }
  await mostrar(actual);
}
