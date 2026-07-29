/*
 * ribbon.js — justidraw-style notation geometry.
 *
 * A partial drawn as a shape whose vertical position is pitch and whose
 * thickness is amplitude, tapering away as the partial dies. This is the
 * notation these scores are composed in, so the performer app and the engraver
 * must draw it identically — hence one implementation, shared.
 *
 * The construction matches the modifier's SVG exporter: offset the centreline
 * perpendicularly by half the width at each point. At an interior point the
 * tangent is the sum of the normalised incoming and outgoing directions, which
 * bisects the corner — offsetting along that bisector keeps the two edges
 * parallel through a bend instead of pinching on the inside of it.
 */

/** Half-window for width smoothing; see smoothWidths(). */
const SMOOTH_RADIUS = 2;

/**
 * Average the width channel over a short window.
 *
 * Displays sample at roughly one point per two pixels, which at normal zoom
 * lands close to the score's own ~11.6 ms analysis frame. Sampling a noisy
 * per-frame amplitude at nearly its own rate aliases that noise into a coarse
 * sawtooth along the ribbon edge — an artefact of the analysis resolution, not
 * something the composer wrote.
 *
 * @param {Array<[number,number,number]>} pts [x, y, width] triples
 * @returns {Float64Array} smoothed widths
 */
export function smoothWidths(pts, radius = SMOOTH_RADIUS) {
  const n = pts.length;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let k = i - radius; k <= i + radius; k++) {
      if (k < 0 || k >= n) continue;
      sum += pts[k][2];
      count++;
    }
    out[i] = sum / count;
  }
  return out;
}

/**
 * Compute the two offset edges of a ribbon.
 * @param {Array<[number,number,number]>} pts [x, y, width] triples
 * @returns {{top: Array<[number,number]>, bottom: Array<[number,number]>}}
 */
export function ribbonEdges(pts, radius = SMOOTH_RADIUS) {
  const n = pts.length;
  const w = smoothWidths(pts, radius);
  const top = new Array(n);
  const bottom = new Array(n);

  for (let i = 0; i < n; i++) {
    let tx;
    let ty;
    if (i === 0) {
      tx = pts[1][0] - pts[0][0];
      ty = pts[1][1] - pts[0][1];
    } else if (i === n - 1) {
      tx = pts[i][0] - pts[i - 1][0];
      ty = pts[i][1] - pts[i - 1][1];
    } else {
      const ax = pts[i][0] - pts[i - 1][0];
      const ay = pts[i][1] - pts[i - 1][1];
      const bx = pts[i + 1][0] - pts[i][0];
      const by = pts[i + 1][1] - pts[i][1];
      const la = Math.hypot(ax, ay) || 1;
      const lb = Math.hypot(bx, by) || 1;
      tx = ax / la + bx / lb;
      ty = ay / la + by / lb;
    }
    let len = Math.hypot(tx, ty);
    if (len < 1e-6) {
      tx = 1;
      ty = 0;
      len = 1;
    }
    const nx = -ty / len;
    const ny = tx / len;
    const half = w[i] / 2;
    top[i] = [pts[i][0] + nx * half, pts[i][1] + ny * half];
    bottom[i] = [pts[i][0] - nx * half, pts[i][1] - ny * half];
  }
  return { top, bottom };
}

/**
 * Fill one ribbon onto a 2D canvas context.
 * @param {CanvasRenderingContext2D} g
 * @param {Array<[number,number,number]>} pts
 * @param {string} fill
 */
export function fillRibbon(g, pts, fill) {
  if (pts.length < 2) return;
  const { top, bottom } = ribbonEdges(pts);
  g.beginPath();
  g.moveTo(top[0][0], top[0][1]);
  for (let i = 1; i < top.length; i++) g.lineTo(top[i][0], top[i][1]);
  for (let i = bottom.length - 1; i >= 0; i--) g.lineTo(bottom[i][0], bottom[i][1]);
  g.closePath();
  g.fillStyle = fill;
  g.fill();
}

/**
 * The same shape as an SVG path string, for print and PDF output.
 * @returns {string} an SVG `d` attribute
 */
export function ribbonPath(pts) {
  if (pts.length < 2) return '';
  const { top, bottom } = ribbonEdges(pts);
  const r = (v) => Math.round(v * 100) / 100;
  let d = `M ${r(top[0][0])},${r(top[0][1])}`;
  for (let i = 1; i < top.length; i++) d += ` L ${r(top[i][0])},${r(top[i][1])}`;
  for (let i = bottom.length - 1; i >= 0; i--) {
    d += ` L ${r(bottom[i][0])},${r(bottom[i][1])}`;
  }
  return `${d} Z`;
}
