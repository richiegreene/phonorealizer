/*
 * canvas.js — the engraving surface.
 *
 * A full-score view rather than the performer app's scrolling one: the whole
 * duration laid out left to right, one horizontal band ("system") per part,
 * each drawn in the same ribbon notation the players read. Annotations sit on
 * the systems where they were placed.
 *
 * Each system scales its pitch axis to its own part's range. A phonorealism
 * score can span partial 1 at 400 Hz and partial 32 at 19 kHz — over five
 * octaves — and a single shared axis would compress every individual line into
 * a flat thread. Per-system scaling costs cross-part pitch comparison, which
 * the overlay view exists to provide.
 */

import { fillRibbon } from '/shared/ribbon.js';
import { GLOBAL, KINDS } from '/shared/annotations.js';

const C = {
  bg: '#0f1216',
  system: '#141920',
  systemEdge: '#222a34',
  grid: '#1b222b',
  ribbon: '#e4ecf4',
  ribbonMuted: 'rgba(160, 178, 198, 0.35)',
  label: '#8b98a8',
  labelBright: '#e6edf5',
  text: '#f2f6fa',
  global: '#7ee0c0',
  selected: '#ffb648',
  hover: 'rgba(255, 182, 72, 0.5)',
  cursor: '#ff4d6d',
};

const SYSTEM_GAP = 14;
const LABEL_W = 116;
const RULER_H = 26;

export class EngraveCanvas extends EventTarget {
  constructor(canvas) {
    super();
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.score = null;
    this.project = null;

    /** Seconds per pixel is derived from these two. */
    this.t0 = 0;
    this.tSpan = 20;

    this.systemHeight = 150;
    this.ribbonScale = 34;
    this.selectedId = null;
    this.hoverId = null;
    this.soloPart = null; // part id, or null for all systems

    this._systems = [];
    this._hit = [];
    this._drag = null;

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

  /** Parts currently drawn, honouring solo. */
  get visibleParts() {
    if (!this.project) return [];
    const parts = this.project.parts || [];
    return this.soloPart ? parts.filter((p) => p.id === this.soloPart) : parts;
  }

  /* ---------------- geometry ---------------- */

  get plotW() {
    return Math.max(10, this.w - LABEL_W);
  }

  xFor(t) {
    return LABEL_W + ((t - this.t0) / this.tSpan) * this.plotW;
  }

  tFor(x) {
    return this.t0 + ((x - LABEL_W) / this.plotW) * this.tSpan;
  }

  /** Lay out one band per visible part; recomputed each draw. */
  _layout() {
    const parts = this.visibleParts;
    this._systems = [];
    let y = RULER_H;
    for (const part of parts) {
      const partials = (part.partials || [])
        .map((i) => this.score?.partials[i - 1])
        .filter(Boolean);
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
      // A little headroom so ribbons do not graze the band edges.
      const centre = 1200 * Math.log2(Math.sqrt(lo * hi) / 440);
      const span = Math.max(180, 1200 * Math.log2(hi / lo) * 0.62);
      this._systems.push({
        part,
        partials,
        top: y,
        height: this.systemHeight,
        centre,
        span,
        ampRef: aMax > 1e-6 ? aMax : 1,
      });
      y += this.systemHeight + SYSTEM_GAP;
    }
    this.contentHeight = y;
    return this._systems;
  }

  systemAt(y) {
    return this._systems.find((s) => y >= s.top && y < s.top + s.height) || null;
  }

  yInSystem(sys, cents) {
    const u = (cents - sys.centre) / sys.span;
    return sys.top + sys.height / 2 - (u * sys.height) / 2;
  }

  centsInSystem(sys, y) {
    const u = ((sys.top + sys.height / 2 - y) * 2) / sys.height;
    return sys.centre + u * sys.span;
  }

  /* ---------------- drawing ---------------- */

  draw() {
    const g = this.ctx;
    g.fillStyle = C.bg;
    g.fillRect(0, 0, this.w, this.h);
    if (!this.score || !this.project) {
      this._placeholder();
      return;
    }

    this._layout();
    this._hit = [];
    this._drawRuler();

    for (const sys of this._systems) {
      this._drawSystem(sys);
    }
  }

  _placeholder() {
    const g = this.ctx;
    g.fillStyle = C.label;
    g.font = '13px system-ui, sans-serif';
    g.textAlign = 'center';
    g.fillText('Load a justidraw .sav or a phonorealizer CSV to begin.', this.w / 2, this.h / 2);
    g.textAlign = 'left';
  }

  _drawRuler() {
    const g = this.ctx;
    g.fillStyle = C.system;
    g.fillRect(0, 0, this.w, RULER_H);
    g.strokeStyle = C.systemEdge;
    g.beginPath();
    g.moveTo(0, RULER_H - 0.5);
    g.lineTo(this.w, RULER_H - 0.5);
    g.stroke();

    // Choose a tick interval that keeps labels from colliding at any zoom.
    const pxPerSec = this.plotW / this.tSpan;
    const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60];
    const step = steps.find((s) => s * pxPerSec > 54) || 60;

    g.font = '10px ui-monospace, Menlo, monospace';
    g.fillStyle = C.label;
    g.strokeStyle = C.grid;
    const from = Math.ceil(this.t0 / step) * step;
    for (let t = from; t <= this.t0 + this.tSpan; t += step) {
      const x = Math.round(this.xFor(t)) + 0.5;
      if (x < LABEL_W) continue;
      g.beginPath();
      g.moveTo(x, RULER_H - 6);
      g.lineTo(x, this.h);
      g.stroke();
      g.fillText(`${t.toFixed(step < 1 ? 1 : 0)}s`, x + 3, 12);
    }
  }

  _drawSystem(sys) {
    const g = this.ctx;

    g.fillStyle = C.system;
    g.fillRect(LABEL_W, sys.top, this.w - LABEL_W, sys.height);
    g.strokeStyle = C.systemEdge;
    g.lineWidth = 1;
    g.strokeRect(LABEL_W + 0.5, sys.top + 0.5, this.w - LABEL_W - 1, sys.height - 1);

    // Part name and register, in the gutter.
    g.fillStyle = C.labelBright;
    g.font = '600 12px system-ui, sans-serif';
    g.fillText(sys.part.name, 10, sys.top + 16);
    g.fillStyle = C.label;
    g.font = '10px ui-monospace, Menlo, monospace';
    g.fillText(`partials ${(sys.part.partials || []).join(', ')}`, 10, sys.top + 32);

    g.save();
    g.beginPath();
    g.rect(LABEL_W, sys.top, this.w - LABEL_W, sys.height);
    g.clip();
    this._drawRibbons(sys);
    this._drawAnnotations(sys);
    g.restore();
  }

  _drawRibbons(sys) {
    const g = this.ctx;
    const tA = this.t0;
    const tB = this.t0 + this.tSpan;
    const dt = Math.max(0.002, (2 * this.tSpan) / this.plotW);

    for (const p of sys.partials) {
      let run = [];
      let cursor = 0;
      const flush = () => {
        if (run.length >= 2) fillRibbon(g, run, C.ribbon);
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
        const y = this.yInSystem(sys, 1200 * Math.log2(s.f / 440));
        if (y < sys.top - sys.height || y > sys.top + sys.height * 2) {
          flush();
          continue;
        }
        run.push([this.xFor(t), y, 0.6 + (Math.max(0, s.a) / sys.ampRef) * this.ribbonScale]);
      }
      flush();
    }
  }

  /**
   * Annotations for this system: its own, plus every global mark. Globals are
   * drawn on every system in a distinct colour, which is what makes "set on all
   * parts at once" legible rather than invisible.
   */
  _drawAnnotations(sys) {
    const g = this.ctx;
    const marks = (this.project.annotations || []).filter(
      (a) => a.scope === GLOBAL || a.scope === sys.part.id
    );

    for (const a of marks) {
      const x = this.xFor(a.t);
      if (x < LABEL_W - 200 || x > this.w + 200) continue;

      const def = KINDS[a.kind] || KINDS.text;
      const isGlobal = a.scope === GLOBAL;
      const selected = a.id === this.selectedId;
      const hovered = a.id === this.hoverId;

      // Anchor to the sounding line where there is one, so a lyric sits under
      // the note it belongs to even as the part leaps.
      const cents = this._centsAt(sys, a.t);
      const baseY = cents == null ? sys.top + sys.height / 2 : this.yInSystem(sys, cents);
      const off = a.place === 'above' ? -26 : a.place === 'below' ? 30 : 4;
      const size = a.style?.size || def.size || 13;

      // Keep the mark inside its own band. A line sitting near the bottom of a
      // system would otherwise push a "below" lyric past the clip and out of
      // existence — an annotation that cannot be seen is worse than one that is
      // slightly crowded, so the band edge wins.
      const y = Math.min(
        sys.top + sys.height - 6,
        Math.max(sys.top + size + 4, baseY + off - (a.dy / sys.span) * (sys.height / 2))
      );
      g.font = `${a.style?.bold ? '600 ' : ''}${a.style?.italic ? 'italic ' : ''}${size}px ${
        a.kind === 'lyric' ? 'Georgia, serif' : 'system-ui, sans-serif'
      }`;
      const label = a.text || '(empty)';
      const wText = g.measureText(label).width;

      // Span marks get a line from t to t2.
      if (a.t2 != null && a.t2 > a.t) {
        const x2 = this.xFor(a.t2);
        g.strokeStyle = isGlobal ? C.global : C.ribbonMuted;
        g.lineWidth = selected ? 2 : 1;
        g.beginPath();
        g.moveTo(x, y + 3);
        g.lineTo(x2, y + 3);
        g.stroke();
        g.beginPath();
        g.moveTo(x2, y);
        g.lineTo(x2, y + 6);
        g.stroke();
      }

      // Text frequently lands on top of a near-white ribbon, where neither the
      // mark nor the notation underneath would be readable. A small scrim keeps
      // both legible without hiding the shape.
      g.fillStyle = 'rgba(15, 18, 22, 0.78)';
      g.fillRect(x - 4, y - size, wText + 8, size + 7);

      if (selected || hovered) {
        g.fillStyle = selected ? 'rgba(255,182,72,0.28)' : 'rgba(255,182,72,0.14)';
        g.fillRect(x - 4, y - size, wText + 8, size + 8);
      }
      if (def.boxed) {
        g.strokeStyle = isGlobal ? C.global : C.text;
        g.lineWidth = 1.2;
        g.strokeRect(x - 4, y - size, wText + 8, size + 7);
      }

      g.fillStyle = selected ? C.selected : isGlobal ? C.global : C.text;
      g.fillText(label, x, y);

      this._hit.push({
        id: a.id,
        x: x - 6,
        y: y - size - 2,
        w: wText + 12,
        h: size + 10,
        system: sys,
      });
    }
  }

  /** Loudest partial's pitch at time t, in cents, or null if nothing sounds. */
  _centsAt(sys, t) {
    let best = null;
    for (const p of sys.partials) {
      const s = sampleAt(p, t, 0);
      if (s && s.f > 0 && (!best || s.a > best.a)) best = s;
    }
    return best ? 1200 * Math.log2(best.f / 440) : null;
  }

  /* ---------------- interaction ---------------- */

  _at(x, y) {
    // Last drawn wins, so the topmost mark is the one you grab.
    for (let i = this._hit.length - 1; i >= 0; i--) {
      const h = this._hit[i];
      if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
    }
    return null;
  }

  _bindPointer() {
    const c = this.canvas;
    const pos = (ev) => {
      const r = c.getBoundingClientRect();
      return [ev.clientX - r.left, ev.clientY - r.top];
    };

    c.addEventListener('pointerdown', (ev) => {
      const [x, y] = pos(ev);
      const hit = this._at(x, y);
      if (hit) {
        this.selectedId = hit.id;
        const a = this.project.annotations.find((z) => z.id === hit.id);
        this._drag = { id: hit.id, x, y, t0: a.t, dy0: a.dy, sys: hit.system, moved: false };
        c.setPointerCapture(ev.pointerId);
        this.dispatchEvent(new CustomEvent('select', { detail: hit.id }));
      } else {
        const sys = this.systemAt(y);
        this.selectedId = null;
        this.dispatchEvent(new CustomEvent('select', { detail: null }));
        if (sys && x > LABEL_W) {
          this.dispatchEvent(
            new CustomEvent('place', {
              detail: { partId: sys.part.id, t: this.tFor(x), cents: this.centsInSystem(sys, y) },
            })
          );
        }
      }
      this.draw();
    });

    c.addEventListener('pointermove', (ev) => {
      const [x, y] = pos(ev);
      if (this._drag) {
        const a = this.project.annotations.find((z) => z.id === this._drag.id);
        if (!a) return;
        const dxT = ((x - this._drag.x) / this.plotW) * this.tSpan;
        a.t = Math.max(0, this._drag.t0 + dxT);
        // Vertical drag nudges in cents so the mark keeps its relationship to
        // the line when the view is later rescaled.
        a.dy = this._drag.dy0 - ((y - this._drag.y) * 2 * this._drag.sys.span) / this._drag.sys.height;
        this._drag.moved = true;
        this.draw();
        return;
      }
      const hit = this._at(x, y);
      const id = hit ? hit.id : null;
      if (id !== this.hoverId) {
        this.hoverId = id;
        c.style.cursor = id ? 'grab' : 'crosshair';
        this.draw();
      }
    });

    const end = (ev) => {
      if (this._drag) {
        if (this._drag.moved) this.dispatchEvent(new Event('edited'));
        this._drag = null;
        try {
          c.releasePointerCapture(ev.pointerId);
        } catch {
          /* pointer already gone */
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

    // Wheel zooms the time axis about the pointer; shift-wheel pans.
    c.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        const [x] = pos(ev);
        if (ev.shiftKey) {
          this.t0 += (ev.deltaY / this.plotW) * this.tSpan;
        } else {
          const anchor = this.tFor(x);
          const factor = Math.exp(ev.deltaY * 0.0015);
          const span = Math.min(
            Math.max(this.tSpan * factor, 0.25),
            (this.score?.duration || 60) * 4
          );
          this.t0 = anchor - ((anchor - this.t0) * span) / this.tSpan;
          this.tSpan = span;
        }
        this.t0 = Math.max(-1, this.t0);
        this.draw();
      },
      { passive: false }
    );
  }

  fitAll() {
    if (!this.score) return;
    this.t0 = 0;
    this.tSpan = this.score.duration || 20;
    this.draw();
  }
}

/** Envelope sampler; kept local so the canvas needs no import cycle. */
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
