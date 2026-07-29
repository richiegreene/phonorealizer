/*
 * canvas.js — the engraving surface.
 *
 * Two views, following Dorico's distinction:
 *
 *   Galley  one continuous strip per part, no pagination. What you write in:
 *           nothing reflows while you are placing marks.
 *   Page    the actual cast-off pages, laid out exactly as they will print.
 *           What you engrave in: breaks and spacing show their real effect.
 *
 * Both share the casting-off engine and the band geometry in shared/layout.js,
 * so a page break placed here lands in the same place on paper.
 *
 * The surface carries no rules, barlines or grid by default. The notation is
 * the ribbon; furniture is something to opt into, not to strip out later.
 */

import { fillRibbon } from '/shared/ribbon.js';
import { GLOBAL, KINDS } from '/shared/annotations.js';
import { castOff, systemBands, orderedParts, layoutFor, pageGeometry } from '/shared/layout.js';

const C = {
  bg: '#0f1216',
  sheet: '#ffffff',
  sheetInk: '#111111',
  band: 'rgba(255,255,255,0.015)',
  rule: '#222a34',
  ribbon: '#e4ecf4',
  ribbonMuted: 'rgba(160, 178, 198, 0.35)',
  label: '#8b98a8',
  labelBright: '#e6edf5',
  text: '#f2f6fa',
  global: '#7ee0c0',
  selected: '#ffb648',
  breakSystem: '#4da3ff',
  breakPage: '#ff7bd0',
};

const RULER_H = 24;
const PAGE_GAP = 26;

export class EngraveCanvas extends EventTarget {
  constructor(canvas) {
    super();
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.score = null;
    this.project = null;

    this.view = 'galley';
    this.target = 'score'; // 'score' or a part id

    /* galley horizontal window */
    this.t0 = 0;
    this.tSpan = 20;
    /* page view vertical scroll and zoom */
    this.scrollY = 0;
    this.pageZoom = 0.8;

    this.selectedId = null;
    this.hoverId = null;

    /**
     * Which mode the application is in. Clicking the surface means different
     * things in each — a mark in Write, a break in Engrave — so the surface has
     * to know, or the two would compete for the same gesture.
     */
    this.mode = 'setup';
    this.selectedBreakId = null;
    this._cursor = null;

    this._hit = [];
    this._breakHits = [];
    this._frames = [];
    this._bands = []; // {band, xFor, tFor, x0, x1, top, height}
    this._drag = null;
    this._contentH = 0;

    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(canvas);
    this._bindPointer();
    this.resize();
  }

  destroy() {
    this._ro.disconnect();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = Math.max(1, Math.round(rect.width));
    this.h = Math.max(1, Math.round(rect.height));
    this.canvas.width = this.w * this.dpr;
    this.canvas.height = this.h * this.dpr;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.draw();
  }

  setScore(score) {
    this.score = score;
    if (score) {
      this.t0 = 0;
      this.tSpan = score.duration || 20;
    }
    this.draw();
  }

  setProject(project) {
    this.project = project;
    this.draw();
  }

  /** The engraving profile for whatever layout is on screen. */
  get layout() {
    return layoutFor(this.project, this.target);
  }

  /* ---------------- shared drawing ---------------- */

  /**
   * Draw one part's band: its ribbons and the marks that belong to it.
   * `ink` selects the on-screen or on-paper palette so galley and page views
   * share this code without either looking wrong.
   */
  _drawBand(b, xFor, tA, tB, opts) {
    const g = this.ctx;
    const layout = this.layout;
    const ink = opts.ink;
    const yFor = (cents) => b.top + b.height / 2 - ((cents - b.centre) / b.span) * (b.height / 2);

    if (layout.showStaffLines) {
      g.strokeStyle = ink === 'paper' ? '#dddddd' : C.rule;
      g.lineWidth = 0.5;
      g.beginPath();
      g.moveTo(opts.x0, b.top + b.height);
      g.lineTo(opts.x1, b.top + b.height);
      g.stroke();
    }

    if (layout.showPartLabels && opts.showLabel) {
      g.fillStyle = ink === 'paper' ? '#111' : C.labelBright;
      g.font = '600 11px system-ui, sans-serif';
      g.fillText(b.part.name, opts.labelX, b.top + 13);
    }

    // ribbons
    const dt = Math.max(0.002, (tB - tA) / Math.max(20, opts.x1 - opts.x0));
    for (const p of b.partials) {
      let run = [];
      const flush = () => {
        if (run.length >= 2) fillRibbon(g, run, ink === 'paper' ? C.sheetInk : C.ribbon);
        run = [];
      };
      let cursor = 0;
      for (let t = Math.max(tA, p.t0); t <= Math.min(tB, p.t1); t += dt) {
        const s = sampleAt(p, t, cursor);
        if (!s) continue;
        cursor = s.i;
        if (!(s.f > 0)) {
          flush();
          continue;
        }
        const y = yFor(1200 * Math.log2(s.f / 440));
        if (y < b.top - b.height || y > b.top + b.height * 2) {
          flush();
          continue;
        }
        run.push([xFor(t), y, 0.4 + (Math.max(0, s.a) / b.ampRef) * layout.ribbonScale]);
      }
      flush();
    }

    // marks
    for (const a of this.project.annotations || []) {
      if (a.scope !== GLOBAL && a.scope !== b.part.id) continue;
      if (a.t < tA - 0.001 || a.t > tB + 0.001) continue;
      const def = KINDS[a.kind] || KINDS.text;
      const isGlobal = a.scope === GLOBAL;
      const selected = a.id === this.selectedId;
      const size = (a.style?.size || def.size || 13) * (opts.textScale || 1);

      let cents = null;
      let best = null;
      for (const p of b.partials) {
        const s = sampleAt(p, a.t, 0);
        if (s && s.f > 0 && (!best || s.a > best.a)) best = s;
      }
      if (best) cents = 1200 * Math.log2(best.f / 440);
      const base = cents == null ? b.top + b.height / 2 : yFor(cents);
      const off = a.place === 'above' ? -18 : a.place === 'below' ? 22 : 3;
      const y = Math.min(
        b.top + b.height - 4,
        Math.max(b.top + size + 2, base + off - (a.dy / b.span) * (b.height / 2))
      );
      const x = xFor(a.t);

      g.font =
        `${a.style?.bold ? '600 ' : ''}${a.style?.italic ? 'italic ' : ''}` +
        `${size}px ${a.kind === 'lyric' ? 'Georgia, serif' : 'system-ui, sans-serif'}`;
      const label = a.text || '(empty)';
      const wText = g.measureText(label).width;

      if (a.t2 != null && a.t2 > a.t) {
        g.strokeStyle = ink === 'paper' ? '#444' : isGlobal ? C.global : C.ribbonMuted;
        g.lineWidth = selected ? 1.6 : 0.9;
        g.beginPath();
        g.moveTo(x, y + 3);
        g.lineTo(xFor(Math.min(a.t2, tB)), y + 3);
        g.stroke();
      }

      // Scrim: text often crosses a thick ribbon, and neither would read.
      g.fillStyle = ink === 'paper' ? 'rgba(255,255,255,0.85)' : 'rgba(15,18,22,0.78)';
      g.fillRect(x - 3, y - size, wText + 6, size + 5);
      if (selected) {
        g.fillStyle = 'rgba(255,182,72,0.28)';
        g.fillRect(x - 3, y - size, wText + 6, size + 5);
      }
      if (def.boxed) {
        g.strokeStyle = ink === 'paper' ? '#111' : isGlobal ? C.global : C.text;
        g.lineWidth = 1;
        g.strokeRect(x - 3, y - size, wText + 6, size + 5);
      }
      g.fillStyle = ink === 'paper' ? '#111' : selected ? C.selected : isGlobal ? C.global : C.text;
      g.fillText(label, x, y);

      this._hit.push({ id: a.id, x: x - 5, y: y - size - 2, w: wText + 10, h: size + 9, band: b, tFor: opts.tFor });
    }
  }

  /* ---------------- galley ---------------- */

  get plotW() {
    const l = this.layout;
    return Math.max(10, this.w - (l.showPartLabels ? l.labelWidth : 0));
  }

  get plotX() {
    const l = this.layout;
    return l.showPartLabels ? l.labelWidth : 0;
  }

  xForGalley(t) {
    return this.plotX + ((t - this.t0) / this.tSpan) * this.plotW;
  }

  tForGalley(x) {
    return this.t0 + ((x - this.plotX) / this.plotW) * this.tSpan;
  }

  _drawGalley() {
    const g = this.ctx;
    const layout = this.layout;
    const parts =
      this.target === 'score'
        ? orderedParts(this.project.parts, layout)
        : (this.project.parts || []).filter((p) => p.id === this.target);
    if (!parts.length) return;

    this._drawRuler();

    const bands = systemBands({ parts }, this.score, layout, RULER_H + 8);
    this._contentH = RULER_H + 8 + parts.length * (layout.staffHeight + layout.staffGap);

    const xFor = (t) => this.xForGalley(t);
    for (const b of bands) {
      b.top -= this.scrollY;
      this._bands.push({
        band: b,
        x0: this.plotX,
        x1: this.w,
        tFor: (x) => this.tForGalley(x),
        xFor,
      });
      g.save();
      g.beginPath();
      g.rect(this.plotX, b.top, this.w - this.plotX, b.height);
      g.clip();
      this._drawBand(b, xFor, this.t0, this.t0 + this.tSpan, {
        ink: 'screen',
        x0: this.plotX,
        x1: this.w,
        labelX: 8,
        showLabel: true,
        tFor: (x) => this.tForGalley(x),
      });
      g.restore();
    }

    const bottom = bands.length ? bands[bands.length - 1].top + bands[bands.length - 1].height : this.h;
    this._frames.push({
      tA: this.t0,
      tB: this.t0 + this.tSpan,
      xFor,
      tFor: (x) => this.tForGalley(x),
      x0: this.plotX,
      x1: this.w,
      top: RULER_H,
      bottom,
    });
    this._drawBreakFlags();
  }

  _drawRuler() {
    const g = this.ctx;
    const pxPerSec = this.plotW / this.tSpan;
    const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60];
    const step = steps.find((s) => s * pxPerSec > 56) || 60;
    g.font = '10px ui-monospace, Menlo, monospace';
    g.fillStyle = C.label;
    const from = Math.ceil(this.t0 / step) * step;
    for (let t = from; t <= this.t0 + this.tSpan; t += step) {
      const x = this.xForGalley(t);
      if (x < this.plotX) continue;
      g.fillText(`${t.toFixed(step < 1 ? 1 : 0)}s`, x + 3, 13);
    }
  }

  /**
   * Break flags.
   *
   * Drawn in both views and hit-tested, so a break can be grabbed and dragged
   * rather than deleted and re-made. In Page view a break sits at the edge of
   * the system it created, which is where its effect actually is.
   */
  _drawBreakFlags() {
    const g = this.ctx;
    for (const b of this.project.breaks || []) {
      if (b.scope !== GLOBAL && b.scope !== this.target) continue;
      // The frame whose span contains this break; ties go to the one that ends
      // on it, which is the system the break brought to a close.
      const frame =
        this._frames.find((f) => b.t > f.tA - 1e-6 && b.t <= f.tB + 1e-6) ||
        this._frames.find((f) => b.t >= f.tA && b.t <= f.tB);
      if (!frame) continue;
      const x = frame.xFor(b.t);
      if (x < frame.x0 - 30 || x > frame.x1 + 30) continue;

      const selected = b.id === this.selectedBreakId;
      const colour = b.kind === 'page' ? C.breakPage : C.breakSystem;
      g.strokeStyle = colour;
      g.lineWidth = selected ? 2.5 : 1.5;
      g.setLineDash(selected ? [] : [5, 4]);
      g.beginPath();
      g.moveTo(x, frame.top);
      g.lineTo(x, frame.bottom);
      g.stroke();
      g.setLineDash([]);

      // Grab handle at the top of the flag.
      const label = b.kind === 'page' ? 'PAGE' : 'SYS';
      g.font = '9px ui-monospace, Menlo, monospace';
      const w = g.measureText(label).width + 10;
      g.fillStyle = colour;
      g.fillRect(x, frame.top, w, 14);
      g.fillStyle = '#0f1216';
      g.fillText(label, x + 5, frame.top + 10);

      this._breakHits.push({
        id: b.id,
        x: x - 6,
        y: frame.top,
        w: w + 10,
        h: Math.max(20, frame.bottom - frame.top),
      });
    }
  }

  /* ---------------- page ---------------- */

  _drawPages() {
    const g = this.ctx;
    const cast = castOff(this.score, this.project, { target: this.target });
    if (!cast.pages.length) return;
    const { layout, page } = cast;
    const z = this.pageZoom;
    const pw = page.w * z;
    const ph = page.h * z;
    const x0 = Math.max(10, (this.w - pw) / 2);

    this._contentH = cast.pages.length * (ph + PAGE_GAP) + PAGE_GAP;

    cast.pages.forEach((pg, pi) => {
      const py = PAGE_GAP + pi * (ph + PAGE_GAP) - this.scrollY;
      if (py > this.h || py + ph < 0) return;

      g.fillStyle = C.sheet;
      g.fillRect(x0, py, pw, ph);

      let y = page.margin * z;
      pg.systems.forEach((sys, si) => {
        const labelW = layout.showPartLabels ? layout.labelWidth : 0;
        const sx0 = x0 + (page.margin + labelW) * z;
        const sx1 = x0 + (page.w - page.margin) * z;
        const secondsAcross = Math.max(1e-6, sys.tB - sys.tA);
        // Each system is justified to the full measure width, which is what
        // makes a short final system read as deliberate rather than truncated.
        const xFor = (t) => sx0 + ((t - sys.tA) / secondsAcross) * (sx1 - sx0);
        const tFor = (x) => sys.tA + ((x - sx0) / (sx1 - sx0)) * secondsAcross;

        const bands = systemBands(sys, this.score, { ...layout, staffHeight: layout.staffHeight * z, staffGap: layout.staffGap * z }, py + y);
        this._frames.push({
          tA: sys.tA,
          tB: sys.tB,
          xFor,
          tFor,
          x0: sx0,
          x1: sx1,
          top: bands.length ? bands[0].top : py + y,
          bottom: bands.length ? bands[bands.length - 1].top + bands[bands.length - 1].height : py + y,
        });
        for (const b of bands) {
          this._bands.push({ band: b, x0: sx0, x1: sx1, tFor, xFor });
          g.save();
          g.beginPath();
          g.rect(sx0 - labelW * z, b.top, sx1 - sx0 + labelW * z, b.height);
          g.clip();
          this._drawBand(b, xFor, sys.tA, sys.tB, {
            ink: 'paper',
            x0: sx0,
            x1: sx1,
            labelX: x0 + page.margin * z,
            showLabel: true,
            textScale: z,
            tFor,
          });
          g.restore();
        }
        const used =
          sys.parts.length * layout.staffHeight * z +
          (sys.parts.length - 1) * layout.staffGap * z;
        y += used + layout.systemGap * z;
      });

      if (layout.showPageNumbers) {
        g.fillStyle = '#666';
        g.font = `${10 * z}px system-ui, sans-serif`;
        g.textAlign = 'right';
        g.fillText(`${pi + 1}`, x0 + (page.w - page.margin) * z, py + (page.h - page.margin / 2) * z);
        g.textAlign = 'left';
      }
    });
  }

  /* ---------------- entry ---------------- */

  draw() {
    const g = this.ctx;
    g.fillStyle = C.bg;
    g.fillRect(0, 0, this.w, this.h);
    this._hit = [];
    this._bands = [];
    this._breakHits = [];
    this._frames = [];
    if (!this.score || !this.project?.parts?.length) {
      g.fillStyle = C.label;
      g.font = '13px system-ui, sans-serif';
      g.textAlign = 'center';
      g.fillText(
        this.score ? 'Add a part in Setup to begin.' : 'Load a justidraw .sav or a phonorealizer CSV.',
        this.w / 2,
        this.h / 2
      );
      g.textAlign = 'left';
      return;
    }
    if (this.view === 'page') {
      this._drawPages();
      this._drawBreakFlags();
    } else {
      this._drawGalley();
    }
  }

  /* ---------------- interaction ---------------- */

  /**
   * The staff at a point, or failing that the nearest one.
   *
   * Exact hit-testing would make the gaps between staves dead to clicks, which
   * is needlessly unforgiving when placing a mark — the intent is unambiguous,
   * so snap to the closest staff rather than ignoring the gesture.
   */
  _bandAt(x, y, nearest = false) {
    let best = null;
    let bestDist = Infinity;
    for (const e of this._bands) {
      const b = e.band;
      if (x < e.x0 - 90 || x > e.x1) continue;
      if (y >= b.top && y < b.top + b.height) return e;
      if (!nearest) continue;
      const d = y < b.top ? b.top - y : y - (b.top + b.height);
      if (d < bestDist) {
        bestDist = d;
        best = e;
      }
    }
    // Only snap across a plausible gap, not from the far end of the sheet.
    return best && bestDist < 60 ? best : null;
  }

  _at(x, y) {
    for (let i = this._hit.length - 1; i >= 0; i--) {
      const h = this._hit[i];
      if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
    }
    return null;
  }

  _breakAt(x, y) {
    for (let i = this._breakHits.length - 1; i >= 0; i--) {
      const h = this._breakHits[i];
      if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
    }
    return null;
  }

  /** The system frame under a point, used to convert x back into time. */
  _frameAt(x, y) {
    return (
      this._frames.find((f) => x >= f.x0 - 40 && x <= f.x1 + 40 && y >= f.top - 20 && y <= f.bottom + 20) ||
      this._frames[0] ||
      null
    );
  }

  _bindPointer() {
    const c = this.canvas;
    const pos = (ev) => {
      const r = c.getBoundingClientRect();
      return [ev.clientX - r.left, ev.clientY - r.top];
    };

    c.addEventListener('pointerdown', (ev) => {
      const [x, y] = pos(ev);

      // Breaks take the gesture first in Engrave mode, so their flags stay
      // grabbable even where they cross a mark.
      if (this.mode === 'engrave') {
        const bh = this._breakAt(x, y);
        if (bh) {
          this.selectedBreakId = bh.id;
          const b = this.project.breaks.find((z) => z.id === bh.id);
          this._drag = { breakId: bh.id, x, t0: b.t, moved: false };
          c.setPointerCapture(ev.pointerId);
          this.dispatchEvent(new CustomEvent('selectBreak', { detail: bh.id }));
          this.draw();
          return;
        }
      }

      const hit = this._at(x, y);
      if (hit) {
        this.selectedId = hit.id;
        const a = this.project.annotations.find((z) => z.id === hit.id);
        this._drag = { id: hit.id, x, y, t0: a.t, dy0: a.dy, band: hit.band, tFor: hit.tFor, moved: false };
        c.setPointerCapture(ev.pointerId);
        this.dispatchEvent(new CustomEvent('select', { detail: hit.id }));
        this.draw();
        return;
      }
      const e = this._bandAt(x, y, this.mode === 'write');
      this.selectedId = null;
      this.selectedBreakId = null;
      this.dispatchEvent(new CustomEvent('select', { detail: null }));

      // Clicking empty space places something, and which thing depends on the
      // mode. Setup places nothing — it is about naming parts, and a stray
      // click there should not alter the music.
      if (this.mode === 'engrave') {
        const f = this._frameAt(x, y);
        if (f && x >= f.x0) {
          this.dispatchEvent(
            new CustomEvent('placeBreak', {
              detail: { t: Math.max(0, f.tFor(x)), partId: e ? e.band.part.id : null },
            })
          );
        }
        this.draw();
        return;
      }
      if (this.mode !== 'write') {
        this.draw();
        return;
      }
      if (e && x >= e.x0) {
        const b = e.band;
        // Report the exact spot clicked, in cents relative to the band centre,
        // so a new mark lands where the user put it rather than snapping.
        const cents = b.centre + (((b.top + b.height / 2 - y) * 2) / b.height) * b.span;
        this.dispatchEvent(
          new CustomEvent('place', {
            detail: { partId: b.part.id, t: e.tFor(x), cents, y },
          })
        );
      }
      this.draw();
    });

    c.addEventListener('pointermove', (ev) => {
      const [x, y] = pos(ev);
      if (this._drag?.breakId) {
        const b = this.project.breaks.find((z) => z.id === this._drag.breakId);
        if (!b) return;
        // Convert through whichever frame the pointer is over. In Page view the
        // layout recasts as the break moves, so re-reading the frame each time
        // keeps the flag under the cursor instead of chasing a stale mapping.
        const f = this._frameAt(x, y);
        if (f) b.t = Math.max(0, f.tFor(x));
        this._drag.moved = true;
        this.draw();
        // Live, so the Breaks list and the flag never disagree mid-gesture.
        this.dispatchEvent(new Event('breakEdited'));
        return;
      }
      if (this._drag) {
        const a = this.project.annotations.find((z) => z.id === this._drag.id);
        if (!a) return;
        const b = this._drag.band;
        a.t = Math.max(0, this._drag.tFor(x) - (this._drag.tFor(this._drag.x) - this._drag.t0));
        a.dy = this._drag.dy0 - ((y - this._drag.y) * 2 * b.span) / b.height;
        this._drag.moved = true;
        this.draw();
        return;
      }
      const overBreak = this.mode === 'engrave' ? this._breakAt(x, y) : null;
      const hit = overBreak ? null : this._at(x, y);
      const id = hit ? hit.id : null;
      const want = overBreak ? 'ew-resize' : id ? 'grab' : 'crosshair';
      // Compare against the cursor actually in effect. Comparing hover ids alone
      // left the cursor stuck on whatever it was last set to, because "nothing
      // hovered now" and "nothing hovered before" look identical.
      if (want !== this._cursor) {
        this._cursor = want;
        c.style.cursor = want;
      }
      this.hoverId = id;
    });

    const end = (ev) => {
      if (this._drag) {
        if (this._drag.moved) {
          this.dispatchEvent(new Event(this._drag.breakId ? 'breakEdited' : 'edited'));
        }
        this._drag = null;
        try {
          c.releasePointerCapture(ev.pointerId);
        } catch {
          /* pointer already released */
        }
      }
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);

    c.addEventListener('dblclick', (ev) => {
      const [x, y] = pos(ev);
      const hit = this._at(x, y);
      if (hit) this.dispatchEvent(new CustomEvent('edit', { detail: hit.id }));
    });

    c.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        const [x] = pos(ev);
        if (this.view === 'page') {
          if (ev.metaKey || ev.ctrlKey) {
            this.pageZoom = Math.min(2, Math.max(0.25, this.pageZoom * Math.exp(-ev.deltaY * 0.002)));
          } else {
            this.scrollY = Math.max(0, Math.min(this._contentH - this.h * 0.4, this.scrollY + ev.deltaY));
          }
        } else if (ev.shiftKey) {
          this.t0 += (ev.deltaY / this.plotW) * this.tSpan;
        } else if (ev.metaKey || ev.ctrlKey) {
          this.scrollY = Math.max(0, this.scrollY + ev.deltaY);
        } else {
          const anchor = this.tForGalley(x);
          const f = Math.exp(ev.deltaY * 0.0015);
          const span = Math.min(Math.max(this.tSpan * f, 0.25), (this.score?.duration || 60) * 4);
          this.t0 = anchor - ((anchor - this.t0) * span) / this.tSpan;
          this.tSpan = span;
        }
        this.t0 = Math.max(-1, this.t0);
        this.draw();
      },
      { passive: false }
    );
  }

  /** Time at the centre of the view — where a break lands when created. */
  cursorTime() {
    if (this.view === 'galley') return this.t0 + this.tSpan / 2;
    const cast = castOff(this.score, this.project, { target: this.target });
    const flat = cast.pages.flatMap((p) => p.systems);
    return flat.length ? flat[Math.floor(flat.length / 2)].tA : 0;
  }

  fitAll() {
    if (this.view === 'page') {
      this.scrollY = 0;
      this.pageZoom = Math.min(0.95, (this.h - 60) / pageGeometry(this.layout).h);
    } else if (this.score) {
      this.t0 = 0;
      this.tSpan = this.score.duration || 20;
      this.scrollY = 0;
    }
    this.draw();
  }
}

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
