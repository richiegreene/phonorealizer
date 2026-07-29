/*
 * print.js — paginated engraving output.
 *
 * Uses the same casting-off engine as the canvas, so the pages that print are
 * the pages you laid out. Emits SVG rather than rasterising: the ribbon is
 * already a filled polygon, so vector output is smaller, resolution
 * independent, and still editable in Illustrator or Inkscape.
 *
 * Can render the full score (every part on each system) or an individual part
 * layout, each honouring the breaks scoped to it.
 *
 * Page furniture — titles, running heads, page numbers, staff rules — is off
 * unless the project asks for it. What comes out is the music.
 */

import { ribbonPath } from '/shared/ribbon.js';
import { GLOBAL, KINDS } from '/shared/annotations.js';
import { castOff, systemBands, timeMarkers, markerLabel } from '/shared/layout.js';

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

/**
 * @param {object} opts { target: 'score'|partId, title }
 * @returns {{svg: string[], pages: number, label: string}}
 */
export function buildSVG(score, project, opts = {}) {
  const target = opts.target || 'score';
  const cast = castOff(score, project, { target });
  if (!cast.pages.length) return { svg: [], pages: 0, label: '' };
  const { layout, page } = cast;
  const labelW = layout.showPartLabels ? layout.labelWidth : 0;

  const label =
    target === 'score'
      ? 'Full Score'
      : (project.parts.find((p) => p.id === target)?.name || 'Part');

  const docs = cast.pages.map((pg, pi) => {
    const body = [`<rect width="${page.w}" height="${page.h}" fill="#ffffff"/>`];

    if (layout.showTitle && pi === 0 && opts.title) {
      body.push(
        `<text x="${page.margin}" y="${page.margin - 20}" font-family="Georgia, serif" font-size="16">${esc(opts.title)}</text>`
      );
    }
    if (layout.showPageNumbers) {
      body.push(
        `<text x="${page.w - page.margin}" y="${page.h - page.margin / 2}" text-anchor="end" ` +
          `font-family="system-ui, sans-serif" font-size="9" fill="#666">${pi + 1}</text>`
      );
    }

    let y = page.margin;
    for (const sys of pg.systems) {
      const x0 = page.margin + labelW;
      const x1 = page.w - page.margin;
      const across = Math.max(1e-6, sys.tB - sys.tA);
      const xFor = (t) => x0 + ((t - sys.tA) / across) * (x1 - x0);
      const bands = systemBands(sys, score, layout, y);

      for (const b of bands) {
        const isFirstBand = b === bands[0];
        const yFor = (cents) =>
          b.top + b.height / 2 - ((cents - b.centre) / b.span) * (b.height / 2);

        if (layout.showPartLabels) {
          body.push(
            `<text x="${page.margin}" y="${(b.top + 12).toFixed(1)}" font-family="system-ui, sans-serif" ` +
              `font-size="10" font-weight="600">${esc(b.part.name)}</text>`
          );
        }
        if (layout.showStaffOutline) {
          body.push(
            `<line x1="${x0}" y1="${(b.top + b.height).toFixed(1)}" x2="${x1}" y2="${(b.top + b.height).toFixed(1)}" stroke="#c8c8c8" stroke-width="1"/>`
          );
        }

        // Time rules, drawn before the notation so the ribbon sits on top.
        const rulesStyle = layout.rulesStyle || 'none';
        if (rulesStyle !== 'none' || (layout.rulesLabels || 'none') !== 'none') {
          const pxPerSecond = (x1 - x0) / Math.max(1e-6, sys.tB - sys.tA);
          for (const mk of timeMarkers(sys.tA, sys.tB, {
            rate: layout.rulesRate,
            group: layout.rulesGroup,
            pxPerSecond,
          })) {
            const mx = xFor(mk.t);
            if (mx < x0 - 1 || mx > x1 + 1) continue;
            const stroke = mk.strong ? '#000000' : '#000000';
            const opacity = mk.strong ? 0.42 : 0.16;
            const width = mk.strong ? 0.9 : 0.6;
            if (rulesStyle === 'ticks') {
              const len = Math.min(10, b.height * 0.16) * (mk.strong ? 1.6 : 1);
              body.push(
                `<line x1="${mx.toFixed(1)}" y1="${b.top.toFixed(1)}" x2="${mx.toFixed(1)}" y2="${(b.top + len).toFixed(1)}" stroke="${stroke}" stroke-opacity="${opacity}" stroke-width="${width}"/>`,
                `<line x1="${mx.toFixed(1)}" y1="${(b.top + b.height - len).toFixed(1)}" x2="${mx.toFixed(1)}" y2="${(b.top + b.height).toFixed(1)}" stroke="${stroke}" stroke-opacity="${opacity}" stroke-width="${width}"/>`
              );
            } else if (rulesStyle !== 'none') {
              const extra = rulesStyle === 'grid' ? layout.staffGap : 0;
              body.push(
                `<line x1="${mx.toFixed(1)}" y1="${b.top.toFixed(1)}" x2="${mx.toFixed(1)}" y2="${(b.top + b.height + extra).toFixed(1)}" stroke="${stroke}" stroke-opacity="${opacity}" stroke-width="${width}"/>`
              );
            }
            if (isFirstBand && mk.strong) {
              const label = markerLabel(mk, layout.rulesLabels, layout.rulesRate);
              if (label) {
                body.push(
                  `<text x="${(mx + 2).toFixed(1)}" y="${(b.top - 3).toFixed(1)}" font-family="ui-monospace, Menlo, monospace" font-size="8" fill="#888">${esc(label)}</text>`
                );
              }
            }
          }
        }

        const dt = Math.max(0.004, across / (x1 - x0));
        for (const p of b.partials) {
          let run = [];
          let cursor = 0;
          const flush = () => {
            if (run.length >= 2) body.push(`<path d="${ribbonPath(run)}" fill="#111111"/>`);
            run = [];
          };
          for (let t = Math.max(sys.tA, p.t0); t <= Math.min(sys.tB, p.t1); t += dt) {
            const s = sampleAt(p, t, cursor);
            if (!s) continue;
            cursor = s.i;
            if (!(s.f > 0)) {
              flush();
              continue;
            }
            const yy = yFor(1200 * Math.log2(s.f / 440));
            if (yy < b.top - b.height || yy > b.top + b.height * 2) {
              flush();
              continue;
            }
            run.push([xFor(t), yy, 0.4 + (Math.max(0, s.a) / b.ampRef) * layout.ribbonScale]);
          }
          flush();
        }

        for (const a of project.annotations || []) {
          if (a.scope !== GLOBAL && a.scope !== b.part.id) continue;
          if (a.t < sys.tA - 0.001 || a.t > sys.tB + 0.001) continue;
          const def = KINDS[a.kind] || KINDS.text;
          let best = null;
          for (const p of b.partials) {
            const s = sampleAt(p, a.t, 0);
            if (s && s.f > 0 && (!best || s.a > best.a)) best = s;
          }
          const base = best ? yFor(1200 * Math.log2(best.f / 440)) : b.top + b.height / 2;
          const off = a.place === 'above' ? -14 : a.place === 'below' ? 20 : 3;
          const size = (a.style?.size || def.size || 12) * 0.85;
          const ty = Math.min(
            b.top + b.height - 3,
            Math.max(b.top + size + 2, base + off - (a.dy / b.span) * (b.height / 2))
          );
          const x = xFor(a.t);
          const font = a.kind === 'lyric' ? 'Georgia, serif' : 'system-ui, sans-serif';
          const wText = String(a.text).length * size * 0.55 + 6;

          body.push(
            `<rect x="${(x - 3).toFixed(1)}" y="${(ty - size).toFixed(1)}" width="${wText.toFixed(1)}" height="${(size + 4).toFixed(1)}" fill="#ffffff" fill-opacity="0.85"/>`
          );
          if (a.t2 != null && a.t2 > a.t) {
            body.push(
              `<line x1="${x.toFixed(1)}" y1="${(ty + 3).toFixed(1)}" x2="${xFor(Math.min(a.t2, sys.tB)).toFixed(1)}" y2="${(ty + 3).toFixed(1)}" stroke="#444" stroke-width="0.7"/>`
            );
          }
          if (def.boxed) {
            body.push(
              `<rect x="${(x - 4).toFixed(1)}" y="${(ty - size).toFixed(1)}" width="${(wText + 2).toFixed(1)}" height="${(size + 5).toFixed(1)}" fill="none" stroke="#111" stroke-width="0.8"/>`
            );
          }
          body.push(
            `<text x="${x.toFixed(1)}" y="${ty.toFixed(1)}" font-family="${font}" font-size="${size.toFixed(1)}"` +
              `${a.style?.italic ? ' font-style="italic"' : ''}${a.style?.bold ? ' font-weight="600"' : ''}` +
              ` fill="#111">${esc(a.text)}</text>`
          );
        }
      }

      const used =
        sys.parts.length * layout.staffHeight + (sys.parts.length - 1) * layout.staffGap;
      y += used + layout.systemGap;
    }

    return (
      `<svg xmlns="http://www.w3.org/2000/svg" width="${page.w}" height="${page.h}" ` +
      `viewBox="0 0 ${page.w} ${page.h}" class="page">${body.join('')}</svg>`
    );
  });

  return { svg: docs, pages: docs.length, label };
}

/**
 * Which layouts to render.
 * @param {'score'|'parts'|'both'} which
 */
export function buildLayouts(score, project, which = 'score', title = '') {
  const out = [];
  if (which === 'score' || which === 'both') {
    const r = buildSVG(score, project, { target: 'score', title });
    if (r.pages) out.push(r);
  }
  if (which === 'parts' || which === 'both') {
    for (const p of project.parts || []) {
      const r = buildSVG(score, project, { target: p.id, title });
      if (r.pages) out.push(r);
    }
  }
  return out;
}

export function openPrintView(score, project, which = 'score', title = '') {
  const layouts = buildLayouts(score, project, which, title);
  if (!layouts.length) {
    alert('Add at least one part before printing.');
    return;
  }
  const w = window.open('', '_blank');
  if (!w) {
    alert('The print view was blocked. Allow pop-ups for this page and try again.');
    return;
  }
  const pages = layouts.flatMap((l) => l.svg).join('');
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(title || 'Engraving')}</title>
<style>
  html,body{margin:0;background:#3a3a3a}
  .page{display:block;margin:16px auto;background:#fff;box-shadow:0 2px 14px rgba(0,0,0,.4)}
  @media print{
    html,body{background:#fff}
    .page{margin:0;box-shadow:none;page-break-after:always;break-after:page}
    @page{size:landscape;margin:0}
  }
</style></head><body>${pages}</body></html>`);
  w.document.close();
}

export function downloadSVG(score, project, which = 'score', title = '') {
  const layouts = buildLayouts(score, project, which, title);
  if (!layouts.length) {
    alert('Add at least one part before exporting.');
    return;
  }
  const base = (title || 'engraving').replace(/\s+/g, '_');
  for (const l of layouts) {
    const tag = l.label.replace(/\s+/g, '_');
    l.svg.forEach((doc, i) => {
      const blob = new Blob([doc], { type: 'image/svg+xml' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = l.svg.length > 1 ? `${base}_${tag}_p${i + 1}.svg` : `${base}_${tag}.svg`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }
}
