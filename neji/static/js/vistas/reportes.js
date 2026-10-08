// Reportes de ventas: indicadores, ventas por día y hora, formas de pago, departamentos y productos.

import { api, descargar, qs } from '../api.js';
import { nombreMetodo } from '../impresion.js';
import { avisoError, fecha, h, hoy, kpi, numero, pesos, selectorFechas, tabla, vaciar } from '../ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const COLOR_SERIE = '#0f766e';
const COLOR_REJILLA = '#e6eaee';
const COLOR_EJE = '#5f6b77';

function s(etiqueta, attrs = {}) {
  const el = document.createElementNS(SVG, etiqueta);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function pasoLimpio(maximo) {
  if (maximo <= 0) return 1;
  const bruto = maximo / 4;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  return [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto);
}

const compacto = (n) => (n >= 1e6 ? `$${numero(Math.round(n / 1e5) / 10)}M` : n >= 1e3 ? `$${numero(Math.round(n / 100) / 10)}k` : pesos(n));

/**
 * Gráfico de columnas de una sola serie. datos: [{ etiqueta, valor, detalle }]
 * Columnas de hasta 24px con punta redondeada, rejilla tenue y tooltip al pasar o enfocar.
 */
function graficoColumnas(datos, { alto = 220 } = {}) {
  const ancho = 900;
  const margen = { izq: 56, der: 12, arr: 18, aba: 28 };
  const maximo = Math.max(...datos.map((d) => d.valor), 0);
  const paso = pasoLimpio(maximo);
  const tope = Math.max(paso * Math.ceil(maximo / paso), paso);
  const areaAlto = alto - margen.arr - margen.aba;
  const banda = (ancho - margen.izq - margen.der) / Math.max(datos.length, 1);
  const grosor = Math.min(24, banda - 2);
  const y = (v) => margen.arr + areaAlto * (1 - v / tope);

  const svg = s('svg', { viewBox: `0 0 ${ancho} ${alto}`, width: '100%', role: 'img', 'aria-label': 'Gráfico de columnas' });
  for (let v = 0; v <= tope + 0.5; v += paso) {
    svg.append(s('line', { x1: margen.izq, x2: ancho - margen.der, y1: y(v), y2: y(v), stroke: COLOR_REJILLA, 'stroke-width': 1 }));
    const t = s('text', { x: margen.izq - 8, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: COLOR_EJE });
    t.textContent = compacto(v);
    svg.append(t);
  }

  const contenedor = h('div', { style: { position: 'relative' } });
  const tip = h('div', { style: { position: 'absolute', pointerEvents: 'none', background: '#12343b', color: '#fff', padding: '.35rem .55rem', borderRadius: '6px', fontSize: '.85rem', display: 'none', whiteSpace: 'nowrap', zIndex: 2 } });

  const cadaEtiqueta = Math.ceil(datos.length / 16);
  const iMax = datos.findIndex((d) => d.valor === maximo);
  datos.forEach((d, i) => {
    const cx = margen.izq + banda * i + banda / 2;
    const alturaBarra = Math.max(areaAlto * (d.valor / tope), d.valor > 0 ? 2 : 0);
    const x = cx - grosor / 2;
    const yTop = margen.arr + areaAlto - alturaBarra;
    const r = Math.min(4, alturaBarra, grosor / 2);
    const camino = alturaBarra > 0
      ? `M${x},${margen.arr + areaAlto} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + grosor - r} Q${x + grosor},${yTop} ${x + grosor},${yTop + r} V${margen.arr + areaAlto} Z`
      : '';
    const grupo = s('g', { tabindex: 0, 'aria-label': `${d.etiqueta}: ${pesos(d.valor)}` });
    grupo.append(s('rect', { x: margen.izq + banda * i, y: margen.arr, width: banda, height: areaAlto, fill: 'transparent' }));
    const barra = s('path', { d: camino, fill: COLOR_SERIE });
    grupo.append(barra);
    const mostrar = () => {
      barra.setAttribute('fill-opacity', '0.75');
      tip.replaceChildren(h('b', d.etiqueta), h('br'), pesos(d.valor), d.detalle ? h('span', ` · ${d.detalle}`) : null);
      tip.style.display = 'block';
      const caja = contenedor.getBoundingClientRect();
      const escala = caja.width / ancho;
      tip.style.left = `${Math.min(Math.max(cx * escala - tip.offsetWidth / 2, 0), caja.width - tip.offsetWidth)}px`;
      tip.style.top = `${Math.max(yTop * escala - tip.offsetHeight - 6, 0)}px`;
    };
    const ocultar = () => { barra.removeAttribute('fill-opacity'); tip.style.display = 'none'; };
    grupo.addEventListener('pointerenter', mostrar);
    grupo.addEventListener('pointerleave', ocultar);
    grupo.addEventListener('focus', mostrar);
    grupo.addEventListener('blur', ocultar);
    svg.append(grupo);

    if (i % cadaEtiqueta === 0) {
      const t = s('text', { x: cx, y: alto - 9, 'text-anchor': 'middle', 'font-size': 11, fill: COLOR_EJE });
      t.textContent = d.corta || d.etiqueta;
      svg.append(t);
    }
    if (i === iMax && maximo > 0) {
      const t = s('text', { x: cx, y: yTop - 5, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 600, fill: '#1d2329' });
      t.textContent = compacto(d.valor);
      svg.append(t);
    }
  });
  svg.append(s('line', { x1: margen.izq, x2: ancho - margen.der, y1: margen.arr + areaAlto, y2: margen.arr + areaAlto, stroke: '#c9d0d7', 'stroke-width': 1 }));
  contenedor.append(svg, tip);
  return contenedor;
}

/** Celda con barra horizontal proporcional (una sola serie, el texto queda en color de texto). */
function barraRelativa(valor, maximo) {
  const ancho = maximo > 0 ? Math.max((valor / maximo) * 100, 1) : 0;
  return h('div', { style: { minWidth: '90px' } }, h('div.barrita', { style: { width: `${ancho}%` } }));
}

function diasDelRango(desde, hasta, porDia) {
  const mapa = new Map(porDia.map((d) => [d.dia, d]));
  const dias = [];
  const d = new Date(`${desde}T12:00:00`);
  const fin = new Date(`${hasta}T12:00:00`);
  while (d <= fin && dias.length < 400) {
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const fila = mapa.get(iso);
    dias.push({ etiqueta: fecha(iso, false), corta: iso.slice(8, 10) + '/' + iso.slice(5, 7), valor: fila?.total || 0, detalle: `${fila?.n_ventas || 0} ventas` });
    d.setDate(d.getDate() + 1);
  }
  return dias;
}

export async function montar(contenedor) {
  let filtro = { desde: hoy().slice(0, 8) + '01', hasta: hoy() };
  const cuerpo = h('div');
  vaciar(contenedor,
    h('div.fila.entre', h('h2', 'Reportes de ventas'),
      h('button.btn', { type: 'button', onclick: () => descargar(`/api/reportes/ventas.csv${qs(filtro)}`) }, 'Exportar detalle CSV')),
    selectorFechas(filtro, (f) => { filtro = f; cargar(); }),
    h('div', { style: { height: '1rem' } }),
    cuerpo);

  async function cargar() {
    let r;
    try {
      r = await api.get(`/api/reportes/ventas${qs(filtro)}`);
    } catch (e) {
      avisoError(e);
      return;
    }
    const x = r.resumen;
    const maxMetodo = Math.max(...r.por_metodo.map((m) => m.total), 0);
    const maxDep = Math.max(...r.por_departamento.map((d) => d.total), 0);
    const maxProd = Math.max(...r.top_productos.map((p) => p.total), 0);
    const maxCajero = Math.max(...r.por_cajero.map((c) => c.total), 0);
    const horas = Array.from({ length: 24 }, (_, hh) => {
      const f = r.por_hora.find((p) => p.hora === hh);
      return { etiqueta: `${hh}:00 – ${hh}:59`, corta: `${hh}h`, valor: f?.total || 0, detalle: `${f?.n_ventas || 0} ventas` };
    });
    const primeraHora = horas.findIndex((d) => d.valor > 0);
    const ultimaHora = 23 - [...horas].reverse().findIndex((d) => d.valor > 0);
    const horasVisibles = primeraHora >= 0 ? horas.slice(Math.max(primeraHora - 1, 0), Math.min(ultimaHora + 2, 24)) : horas.slice(8, 22);

    vaciar(cuerpo,
      h('div.kpis',
        kpi('Ventas netas', pesos(x.total), true),
        kpi('Tickets', numero(x.n_ventas)),
        kpi('Ticket promedio', pesos(x.ticket_promedio)),
        kpi('Ganancia estimada', `${pesos(x.ganancia)} · ${numero(x.margen)}%`),
        kpi('IVA débito', pesos(x.iva)),
        kpi('Devoluciones', pesos(x.devuelto)),
        kpi('Descuentos', pesos(x.descuentos))),
      h('div.panel', h('h3', 'Ventas por día'), r.por_dia.length ? graficoColumnas(diasDelRango(r.desde, r.hasta, r.por_dia)) : h('p.vacio', 'Sin ventas en el período.')),
      h('div.panel', h('h3', 'Ventas por hora del día'), h('p.ayuda', 'Sirve para decidir turnos y horarios de reposición.'),
        graficoColumnas(horasVisibles, { alto: 180 })),
      h('div.columnas',
        h('div.panel',
          h('h3', 'Formas de pago'),
          tabla([
            { titulo: 'Forma', valor: (m) => nombreMetodo(m.metodo) },
            { titulo: 'Ventas', valor: (m) => numero(m.n_ventas), clase: 'num' },
            { titulo: 'Monto', valor: (m) => pesos(m.total), clase: 'num' },
            { titulo: '', valor: (m) => barraRelativa(m.total, maxMetodo) },
          ], r.por_metodo, { vacio: 'Sin ventas.' })),
        h('div.panel',
          h('h3', 'Por cajero'),
          tabla([
            { titulo: 'Cajero', valor: (c) => c.cajero },
            { titulo: 'Ventas', valor: (c) => numero(c.n_ventas), clase: 'num' },
            { titulo: 'Monto', valor: (c) => pesos(c.total), clase: 'num' },
            { titulo: '', valor: (c) => barraRelativa(c.total, maxCajero) },
          ], r.por_cajero, { vacio: 'Sin ventas.' }))),
      h('div.panel',
        h('h3', 'Por departamento'),
        tabla([
          { titulo: 'Departamento', valor: (d) => d.departamento },
          { titulo: 'Venta', valor: (d) => pesos(d.total), clase: 'num' },
          { titulo: 'Ganancia', valor: (d) => pesos(d.ganancia), clase: 'num' },
          { titulo: '', valor: (d) => barraRelativa(d.total, maxDep) },
        ], r.por_departamento, { vacio: 'Sin ventas.' })),
      h('div.panel',
        h('h3', 'Productos más vendidos'),
        tabla([
          { titulo: '#', valor: (p) => r.top_productos.indexOf(p) + 1 },
          { titulo: 'Producto', valor: (p) => p.descripcion },
          { titulo: 'Cantidad', valor: (p) => numero(p.cantidad), clase: 'num' },
          { titulo: 'Venta', valor: (p) => pesos(p.total), clase: 'num' },
          { titulo: 'Ganancia', valor: (p) => pesos(p.ganancia), clase: 'num' },
          { titulo: '', valor: (p) => barraRelativa(p.total, maxProd) },
        ], r.top_productos, { vacio: 'Sin ventas.' })),
      h('p.ayuda', `Neto ${pesos(x.neto)} · IVA ${pesos(x.iva)} · Exento ${pesos(x.exento)} · Redondeo efectivo ${pesos(x.redondeo)}. La ganancia usa el costo registrado en cada producto al momento de la venta.`));
  }

  await cargar();
}
