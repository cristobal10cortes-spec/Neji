// Renglones del ticket tal como los arma la impresora de tickets (ESC/POS): el mismo corte de líneas y
// los mismos reemplazos que neji/impresoras.py (componer y _codificar). Sirve para que la vista previa de
// Configuración → Ticket muestre exactamente lo que sale en el papel. No usa la página: se prueba con node.

// Letras de 128 a 255 de cada página de códigos (generado desde Python: bytes(range(128, 256)).decode(...)).
const PAGINAS = {
  cp850: "\u00c7\u00fc\u00e9\u00e2\u00e4\u00e0\u00e5\u00e7\u00ea\u00eb\u00e8\u00ef\u00ee\u00ec\u00c4\u00c5\u00c9\u00e6\u00c6\u00f4\u00f6\u00f2\u00fb\u00f9\u00ff\u00d6\u00dc\u00f8\u00a3\u00d8\u00d7\u0192\u00e1\u00ed\u00f3\u00fa\u00f1\u00d1\u00aa\u00ba\u00bf\u00ae\u00ac\u00bd\u00bc\u00a1\u00ab\u00bb\u2591\u2592\u2593\u2502\u2524\u00c1\u00c2\u00c0\u00a9\u2563\u2551\u2557\u255d\u00a2\u00a5\u2510\u2514\u2534\u252c\u251c\u2500\u253c\u00e3\u00c3\u255a\u2554\u2569\u2566\u2560\u2550\u256c\u00a4\u00f0\u00d0\u00ca\u00cb\u00c8\u0131\u00cd\u00ce\u00cf\u2518\u250c\u2588\u2584\u00a6\u00cc\u2580\u00d3\u00df\u00d4\u00d2\u00f5\u00d5\u00b5\u00fe\u00de\u00da\u00db\u00d9\u00fd\u00dd\u00af\u00b4\u00ad\u00b1\u2017\u00be\u00b6\u00a7\u00f7\u00b8\u00b0\u00a8\u00b7\u00b9\u00b3\u00b2\u25a0\u00a0",
  cp858: "\u00c7\u00fc\u00e9\u00e2\u00e4\u00e0\u00e5\u00e7\u00ea\u00eb\u00e8\u00ef\u00ee\u00ec\u00c4\u00c5\u00c9\u00e6\u00c6\u00f4\u00f6\u00f2\u00fb\u00f9\u00ff\u00d6\u00dc\u00f8\u00a3\u00d8\u00d7\u0192\u00e1\u00ed\u00f3\u00fa\u00f1\u00d1\u00aa\u00ba\u00bf\u00ae\u00ac\u00bd\u00bc\u00a1\u00ab\u00bb\u2591\u2592\u2593\u2502\u2524\u00c1\u00c2\u00c0\u00a9\u2563\u2551\u2557\u255d\u00a2\u00a5\u2510\u2514\u2534\u252c\u251c\u2500\u253c\u00e3\u00c3\u255a\u2554\u2569\u2566\u2560\u2550\u256c\u00a4\u00f0\u00d0\u00ca\u00cb\u00c8\u20ac\u00cd\u00ce\u00cf\u2518\u250c\u2588\u2584\u00a6\u00cc\u2580\u00d3\u00df\u00d4\u00d2\u00f5\u00d5\u00b5\u00fe\u00de\u00da\u00db\u00d9\u00fd\u00dd\u00af\u00b4\u00ad\u00b1\u2017\u00be\u00b6\u00a7\u00f7\u00b8\u00b0\u00a8\u00b7\u00b9\u00b3\u00b2\u25a0\u00a0",
  cp1252: "\u20ac\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\u017d\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\u017e\u0178\u00a0\u00a1\u00a2\u00a3\u00a4\u00a5\u00a6\u00a7\u00a8\u00a9\u00aa\u00ab\u00ac\u00ad\u00ae\u00af\u00b0\u00b1\u00b2\u00b3\u00b4\u00b5\u00b6\u00b7\u00b8\u00b9\u00ba\u00bb\u00bc\u00bd\u00be\u00bf\u00c0\u00c1\u00c2\u00c3\u00c4\u00c5\u00c6\u00c7\u00c8\u00c9\u00ca\u00cb\u00cc\u00cd\u00ce\u00cf\u00d0\u00d1\u00d2\u00d3\u00d4\u00d5\u00d6\u00d7\u00d8\u00d9\u00da\u00db\u00dc\u00dd\u00de\u00df\u00e0\u00e1\u00e2\u00e3\u00e4\u00e5\u00e6\u00e7\u00e8\u00e9\u00ea\u00eb\u00ec\u00ed\u00ee\u00ef\u00f0\u00f1\u00f2\u00f3\u00f4\u00f5\u00f6\u00f7\u00f8\u00f9\u00fa\u00fb\u00fc\u00fd\u00fe\u00ff",
  cp437: "\u00c7\u00fc\u00e9\u00e2\u00e4\u00e0\u00e5\u00e7\u00ea\u00eb\u00e8\u00ef\u00ee\u00ec\u00c4\u00c5\u00c9\u00e6\u00c6\u00f4\u00f6\u00f2\u00fb\u00f9\u00ff\u00d6\u00dc\u00a2\u00a3\u00a5\u20a7\u0192\u00e1\u00ed\u00f3\u00fa\u00f1\u00d1\u00aa\u00ba\u00bf\u2310\u00ac\u00bd\u00bc\u00a1\u00ab\u00bb\u2591\u2592\u2593\u2502\u2524\u2561\u2562\u2556\u2555\u2563\u2551\u2557\u255d\u255c\u255b\u2510\u2514\u2534\u252c\u251c\u2500\u253c\u255e\u255f\u255a\u2554\u2569\u2566\u2560\u2550\u256c\u2567\u2568\u2564\u2565\u2559\u2558\u2552\u2553\u256b\u256a\u2518\u250c\u2588\u2584\u258c\u2590\u2580\u03b1\u00df\u0393\u03c0\u03a3\u03c3\u00b5\u03c4\u03a6\u0398\u03a9\u03b4\u221e\u03c6\u03b5\u2229\u2261\u00b1\u2265\u2264\u2320\u2321\u00f7\u2248\u00b0\u2219\u00b7\u221a\u207f\u00b2\u25a0\u00a0",
};

// Lo que no existe en la página de códigos (igual que REEMPLAZOS en neji/impresoras.py).
const REEMPLAZOS = {"—": "-", "–": "-", "…": "...", "“": "\"", "”": "\"", "‘": "'", "’": "'", "€": "EUR", "·": "-", "•": "-", "☎": "Tel", "✆": "Tel", "📞": "Tel", "✚": "+", "✓": "v", "✔": "v", "→": "->", "←": "<-", "★": "*", "☆": "*"};

const texto = (valor) => String(valor ?? '').split(/\s+/).filter(Boolean).join(' ');
// Largo y cortes por letra (como Python), no por unidades UTF-16: un emoji cuenta como una letra.
const largo = (valor) => [...valor].length;
const cortar = (valor, desde, hasta) => [...valor].slice(desde, hasta).join('');

const existe = (letra, codigo) => letra.codePointAt(0) < 128 || (PAGINAS[codigo] || PAGINAS.cp850).includes(letra);

/** Texto -> como lo imprime la impresora con esa página de códigos (lo que no existe se aproxima o es «?»). */
export function comoImprime(valor, codigo = 'cp850') {
  let salida = '';
  for (const letra of String(valor ?? '')) {
    if (existe(letra, codigo)) {
      salida += letra;
      continue;
    }
    let reemplazo = REEMPLAZOS[letra];
    if (reemplazo === undefined) reemplazo = letra.normalize('NFKD').replace(/[^\x00-\x7f]/g, '') || '?';
    for (const x of reemplazo) salida += existe(x, codigo) ? x : '?';
  }
  return salida;
}

/** textwrap.wrap(texto, ancho, break_long_words=True, break_on_hyphens=False) de Python, sin espacios al final. */
export function partir(valor, ancho) {
  const pila = valor.split(/(\s+)/).filter((x) => x !== '').reverse();
  const lineas = [];
  while (pila.length) {
    const actual = [];
    let usado = 0;
    if (lineas.length && pila.at(-1).trim() === '') pila.pop();
    while (pila.length && usado + largo(pila.at(-1)) <= ancho) {
      usado += largo(pila.at(-1));
      actual.push(pila.pop());
    }
    if (pila.length && largo(pila.at(-1)) > ancho) {
      // Palabra más larga que el renglón: se corta para llenar lo que queda.
      const trozo = pila.pop();
      const libre = ancho < 1 ? 1 : ancho - usado;
      actual.push(cortar(trozo, 0, libre));
      if (largo(trozo) > libre) pila.push(cortar(trozo, libre));
    }
    if (actual.length && actual.at(-1).trim() === '') actual.pop();
    if (actual.length) lineas.push(actual.join('').trimEnd());   // sin espacios al final, como _partir
  }
  return lineas.length ? lineas : [''];
}

/** str.center(ancho) de Python: el espacio que sobra queda del mismo lado que en Python. */
function centrar(valor, ancho) {
  const margen = ancho - largo(valor);
  if (margen <= 0) return valor;
  const izquierda = Math.floor(margen / 2) + (margen & ancho & 1);
  return ' '.repeat(izquierda) + valor + ' '.repeat(margen - izquierda);
}

/**
 * Bloques del ticket (bloquesTicket) -> renglones [texto, negrita, grande] con el ancho del papel, como
 * neji/impresoras.componer. Un renglón grande usa letra de doble ancho: le caben la mitad de columnas.
 */
export function componerRenglones(bloques, columnas, codigo = 'cp850') {
  const renglones = [];
  for (const b of bloques || []) {
    const negrita = Boolean(b.negrita);
    const grande = Boolean(b.grande);
    const ancho = Math.max(grande ? Math.floor(columnas / 2) : columnas, 8);
    if (b.tipo === 'linea') {
      renglones.push(['-'.repeat(columnas), false, false]);
    } else if (b.tipo === 'espacio') {
      const n = Math.max(1, Math.min(Number.parseInt(b.lineas, 10) || 1, 10));
      for (let i = 0; i < n; i++) renglones.push(['', false, false]);
    } else if (b.tipo === 'par') {
      const izq = texto(b.izq);
      const der = cortar(texto(b.der), 0, ancho);
      if (largo(izq) + largo(der) + 1 <= ancho) {
        renglones.push([izq + ' '.repeat(ancho - largo(izq) - largo(der)) + der, negrita, grande]);
      } else {
        const partes = partir(izq, ancho);
        const ultima = partes.pop();
        for (const p of partes) renglones.push([p, negrita, grande]);
        if (largo(ultima) + largo(der) + 1 <= ancho) {
          renglones.push([ultima + ' '.repeat(ancho - largo(ultima) - largo(der)) + der, negrita, grande]);
        } else {
          renglones.push([ultima, negrita, grande], [' '.repeat(Math.max(ancho - largo(der), 0)) + der, negrita, grande]);
        }
      }
    } else {
      const centro = b.alinear === 'centro';
      for (const parte of partir(texto(b.texto), ancho)) {
        renglones.push([centro ? centrar(parte, ancho).trimEnd() : parte, negrita, grande]);
      }
    }
  }
  return renglones.map(([t, negrita, grande]) => [comoImprime(t, codigo), negrita, grande]);
}
