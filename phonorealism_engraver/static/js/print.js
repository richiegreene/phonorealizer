/*
 * print.js — paginated engraving output.
 *
 * Emits SVG rather than rasterising the editing canvas: the ribbon is already a
 * filled polygon, so vector output is both smaller and genuinely resolution
 * independent, and it stays editable in Illustrator or Inkscape afterwards.
 * The same document is what gets handed to the browser's print dialogue, so
 * "Save as PDF" and "export SVG" cannot disagree with each other.
 *
 * Pagination is by time: each page holds a fixed number of seconds, and every
 * part gets a system on every page — the layout a player reads down a page.
 */

import { ribbonPath } from '/shared/ribbon.js';
import { GLOBAL, KINDS } from '/shared/annotations.js';

/** A4 landscape at 96 dpi, with generous margins for a music stand. */
const PAGE = { w: 1123, h: 794, margin: 54 };
const LABEL_W = 96;
const SYSTEM_H = 104;
const SYSTEM_GAP = 26;

const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function sampleAt(p, t, cursor) {
  const n = p.t.length;
  if (n === 0 || t < p.t[0] || t > p.t[n - 1]) return null;
  let i = Math.min(Math.max(cursor, 0), n - 1);
  if (p.t[i] > t) i = 0;
  while (i + 1 < n && p.t[i + 1] <= t) i++;
  if (i + 1 >= n) return { f: p.f[n - 1], a: p.a[n - 1], i: n - 1 };
  const span = p.t[i + 1] - p.t[i];
  const u = span > 0 ? (t - p.t[i]) / span : 0;
  return {
    f: p.f[i] + u * (p.f[i + 1] - p.f[i]),
    a: p.a[i] + u * (p.a[i + 1] - p.a[i]),
    i,
  };
}

/** Per-part pitch window and amplitude reference, computed once for the run. */
function partMetrics(score, part) {
  const partials = (part.partials || []).map((i) => score.partials[i - 1]).filter(Boolean);
  let lo = Infinity;
  let hi = -Infinity;
  let aMax = 0;
  for (const p of partials) {
    lo = Math.min(lo, p.fMin);
    hi = Math.max(hi, p.fMax);
    aMax = Math.max(aMax, p.aMax);
  }
  if (!Number.isFinite(lo) || !(hi > 0)) {
    lo = 220;
    hi = 880;
  }
  return {
    partials,
    centre: 1200 * Math.log2(Math.sqrt(lo * hi) / 440),
    span: Math.max(180, 1200 * Math.log2(hi / lo) * 0.62),
    ampRef: aMax > 1e-6 ? aMax : 1,
  };
}

/**
 * Render the whole project as one SVG document containing every page.
 * @param {object} opts { secondsPerPage, ribbonScale, title }
 */
export function buildSVG(score, project, opts = {}) {
  const secondsPerPage = opts.secondsPerPage || 20;
  const ribbonScale = opts.ribbonScale ?? 15;
  const title = opts.title || project.score?.name || 'Untitled';
  const parts = project.parts || [];
  if (!parts.length) return { svg: '', pages: 0 };

  const duration = score.duration || 1;
  const pages = Math.max(1, Math.ceil(duration / secondsPerPage));
  const plotW = PAGE.w - PAGE.margin * 2 - LABEL_W;
  const metrics = new Map(parts.map((p) => [p.id, partMetrics(score, p)]));

  const docs = [];
  for (let page = 0; page < pages; page++) {
    const tA = page * secondsPerPage;
    const tB = Math.min(duration, tA + secondsPerPage);
    const xFor = (t) => PAGE.margin + LABEL_W + ((t - tA) / secondsPerPage) * plotW;

    const body = [];
    body.push(
      `<rect width="${PAGE.w}" height="${PAGE.h}" fill="#ffffff"/>`,
      `<text x="${PAGE.margin}" y="${PAGE.margin - 22}" font-family="Georgia, serif" font-size="16">${esc(title)}</text>`,
      `<text x="${PAGE.w - PAGE.margin}" y="${PAGE.margin - 22}" text-anchor="end" font-family="system-ui, sans-serif" font-size="10" fill="#666">page ${page + 1} of ${pages} · ${tA.toFixed(1)}–${tB.toFixed(1)} s</text>`
    );

    let y = PAGE.margin;
    for (const part of parts) {
      const m = metrics.get(part.id);
      const yFor = (cents) => y + SYSTEM_H / 2 - ((cents - m.centre) / m.span) * (SYSTEM_H / 2);

      body.push(
        `<text x="${PAGE.margin}" y="${y + 14}" font-family="system-ui, sans-serif" font-size="11" font-weight="600">${esc(part.name)}</text>`,
        `<line x1="${PAGE.margin + LABEL_W}" y1="${y + SYSTEM_H}" x2="${PAGE.w - PAGE.margin}" y2="${y + SYSTEM_H}" stroke="#e2e2e2" stroke-width="0.5"/>`
      );

      // Second ticks, faint, for orientation on the page.
      for (let t = Math.ceil(tA); t <= tB; t++) {
        const x = xFor(t);
        body.push(
          `<line x1="${x.toFixed(1)}" y1="${y}" x2="${x.toFixed(1)}" y2="${y + SYSTEM_H}" stroke="#f0f0f0" stroke-width="0.5"/>`
        );
      }

      const dt = Math.max(0.004, (tB - tA) / plotW);
      for (const p of m.partials) {
        let run = [];
        let cursor = 0;
        const flush = () => {
          if (run.length >= 2) {
            body.push(`<path d="${ribbonPath(run)}" fill="#111111"/>`);
          }
          run = [];
        };
        for (let t = Math.max(tA, p.t0); t <= Math.min(tB, p.t1); t += dt) {
          const s = sampleAt(p, t, cursor);
          if (!s) continue;
          cursor = s.i;
          if (!(s.f > 0)) {
            flush();
            continue;
          }
          const yy = yFor(1200 * Math.log2(s.f / 440));
          if (yy < y - SYSTEM_H || yy > y + SYSTEM_H * 2) {
            flush();
            continue;
          }
          run.push([xFor(t), yy, 0.4 + (Math.max(0, s.a) / m.ampRef) * ribbonScale]);
        }
        flush();
      }

      // Marks belonging to this part, plus every global one.
      for (const a of project.annotations || []) {
        if (a.scope !== GLOBAL && a.scope !== part.id) continue;
        if (a.t < tA || a.t > tB) continue;
        const def = KINDS[a.kind] || KINDS.text;
        let cents = null;
        let best = null;
        for (const p of m.partials) {
          const s = sampleAt(p, a.t, 0);
          if (s && s.f > 0 && (!best || s.a > best.a)) best = s;
        }
        if (best) cents = 1200 * Math.log2(best.f / 440);
        const baseY = cents == null ? y + SYSTEM_H / 2 : yFor(cents);
        const off = a.place === 'above' ? -14 : a.place === 'below' ? 22 : 3;
        const x = xFor(a.t);
        const size = (a.style?.size || def.size || 12) * 0.85;
        const font = a.kind === 'lyric' ? 'Georgia, serif' : 'system-ui, sans-serif';
        // Clamped into the system band for the same reason as on screen: a mark
        // that falls outside its system is simply lost from the page.
        const ty = Math.min(
          y + SYSTEM_H - 3,
          Math.max(y + size + 2, baseY + off - (a.dy / m.span) * (SYSTEM_H / 2))
        );
        // Knock the ink back behind the text so it reads over a thick ribbon.
        const wText = String(a.text).length * size * 0.55 + 6;
        body.push(
          `<rect x="${(x - 3).toFixed(1)}" y="${(ty - size).toFixed(1)}" width="${wText.toFixed(1)}" height="${(size + 4).toFixed(1)}" fill="#ffffff" fill-opacity="0.82"/>`
        );

        if (a.t2 != null && a.t2 > a.t) {
          const x2 = xFor(Math.min(a.t2, tB));
          body.push(
            `<line x1="${x.toFixed(1)}" y1="${(ty + 3).toFixed(1)}" x2="${x2.toFixed(1)}" y2="${(ty + 3).toFixed(1)}" stroke="#444" stroke-width="0.7"/>`
          );
        }
        if (def.boxed) {
          const w = String(a.text).length * size * 0.6 + 8;
          body.push(
            `<rect x="${(x - 4).toFixed(1)}" y="${(ty - size).toFixed(1)}" width="${w.toFixed(1)}" height="${(size + 6).toFixed(1)}" fill="none" stroke="#111" stroke-width="0.8"/>`
          );
        }
        body.push(
          `<text x="${x.toFixed(1)}" y="${ty.toFixed(1)}" font-family="${font}" font-size="${size.toFixed(1)}"` +
            `${a.style?.italic ? ' font-style="italic"' : ''}${a.style?.bold ? ' font-weight="600"' : ''}` +
            ` fill="#111">${esc(a.text)}</text>`
        );
      }

      y += SYSTEM_H + SYSTEM_GAP;
      // Parts beyond the page simply do not fit; a taller run needs fewer
      // seconds per page rather than a silently clipped system.
      if (y + SYSTEM_H > PAGE.h - PAGE.margin) break;
    }

    docs.push(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${PAGE.w}" height="${PAGE.h}" ` +
        `viewBox="0 0 ${PAGE.w} ${PAGE.h}" class="page">${body.join('')}</svg>`
    );
  }

  return { svg: docs, pages };
}

/** Open the pages in a new window, ready for Print / Save as PDF. */
export function openPrintView(score, project, opts = {}) {
  const { svg, pages } = buildSVG(score, project, opts);
  if (!pages) {
    alert('Define at least one part before printing.');
    return;
  }
  const w = window.open('', '_blank');
  if (!w) {
    alert('The print view was blocked. Allow pop-ups for this page and try again.');
    return;
  }
  const title = opts.title || project.score?.name || 'Engraving';
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>
  html,body{margin:0;background:#3a3a3a}
  .page{display:block;margin:16px auto;background:#fff;box-shadow:0 2px 14px rgba(0,0,0,.4)}
  @media print{
    html,body{background:#fff}
    .page{margin:0;box-shadow:none;page-break-after:always;break-after:page}
    @page{size:landscape;margin:0}
  }
</style></head><body>${svg.join('')}</body></html>`);
  w.document.close();
}

/** Download the pages as a single SVG file per page, zipped into one text blob. */
export function downloadSVG(score, project, opts = {}) {
  const { svg, pages } = buildSVG(score, project, opts);
  if (!pages) {
    alert('Define at least one part before exporting.');
    return;
  }
  const name = (opts.title || 'engraving').replace(/\s+/g, '_');
  svg.forEach((doc, i) => {
    const blob = new Blob([doc], { type: 'image/svg+xml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = pages > 1 ? `${name}_p${i + 1}.svg` : `${name}.svg`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}
