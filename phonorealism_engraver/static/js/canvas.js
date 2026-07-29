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
 * The surface carries no grid, barlines or rules by default. The notation is
 * the ribbon; furniture is something to opt into, not to strip out later.
 */

import { fillRibbon } from '/shared/ribbon.js';
import { GLOBAL, KINDS, nudgeMany } from '/shared/annotations.js';
import {
  castOff, systemBands, orderedParts, layoutFor, pageGeometry,
  timeMarkers, markerLabel, pitchGrid, yForBand, centsForBand,
  annotationY, partLabelFor, tickRow,
} from '/shared/layout.js';

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

    /**
     * The selected marks. A set rather than one id because placing a line of
     * lyrics on a common baseline is an operation on all of them at once —
     * doing it one mark at a time is how they end up not quite aligned.
     */
    this.selection = new Set();
    this._primary = null;
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

  /**
   * The mark the panel describes: the last one touched. Assigning it replaces
   * the whole selection, which is what every single-mark caller means.
   */
  get selectedId() {
    return this._primary;
  }

  set selectedId(id) {
    this.selection = new Set(id ? [id] : []);
    this._primary = id || null;
  }

  /**
   * Change the selection and say so.
   *
   * @param {string|null} id
   * @param {boolean} additive shift-click: add or remove one, keeping the rest
   */
  select(id, additive = false) {
    if (!id) {
      if (additive) return; // shift on empty space is not "deselect everything"
      this.selection.clear();
      this._primary = null;
    } else if (!additive) {
      this.selection = new Set([id]);
      this._primary = id;
    } else if (this.selection.has(id)) {
      this.selection.delete(id);
      if (this._primary === id) this._primary = [...this.selection].pop() || null;
    } else {
      this.selection.add(id);
      this._primary = id;
    }
    this.dispatchEvent(
      new CustomEvent('select', {
        detail: { id: this._primary, ids: [...this.selection] },
      })
    );
  }

  /** Select many at once — what the panel's list and Select all need. */
  selectMany(ids) {
    this.selection = new Set(ids || []);
    this._primary = [...this.selection].pop() || null;
    this.dispatchEvent(
      new CustomEvent('select', {
        detail: { id: this._primary, ids: [...this.selection] },
      })
    );
    this.draw();
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
    const scale = opts.textScale || 1;
    const yFor = (cents) => yForBand(b, cents);

    this._drawRules(b, xFor, tA, tB, opts);

    if (layout.showPartLabels && opts.showLabel) {
      // Sized by the engraving setting alone, not by the zoom: a name that grew
      // and shrank with the view could not be judged against the page.
      const size = layout.partLabelSize || 10;
      g.fillStyle = ink === 'paper' ? '#111' : C.labelBright;
      g.font = `600 ${size}px system-ui, sans-serif`;
      // Centred on the part's contents rather than hung from the top of the
      // staff, so it stays against the music when normalised heights make every
      // system a different shape.
      g.fillText(
        partLabelFor(b.part, opts.systemIndex || 0),
        opts.labelX,
        b.coreTop + b.coreH / 2 + size * 0.35
      );
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
        if (y < b.coreTop - b.coreH || y > b.coreTop + b.coreH * 2) {
          flush();
          continue;
        }
        // Thickness follows the zoom, so the page on screen is the page that
        // prints rather than the same staves carrying heavier ink.
        run.push([xFor(t), y, 0.4 + (Math.max(0, s.a) / b.ampRef) * layout.ribbonScale * scale]);
      }
      flush();
    }

    // marks
    for (const a of this.project.annotations || []) {
      if (a.scope !== GLOBAL && a.scope !== b.part.id) continue;
      if (a.t < tA - 0.001 || a.t > tB + 0.001) continue;
      const def = KINDS[a.kind] || KINDS.text;
      const isGlobal = a.scope === GLOBAL;
      const selected = this.selection.has(a.id);
      const size = (a.style?.size || def.size || 13) * scale;

      let cents = null;
      let best = null;
      for (const p of b.partials) {
        const s = sampleAt(p, a.t, 0);
        if (s && s.f > 0 && (!best || s.a > best.a)) best = s;
      }
      if (best) cents = 1200 * Math.log2(best.f / 440);
      const base = cents == null ? b.coreTop + b.coreH / 2 : yFor(cents);
      const y = annotationY(b, a, size, base, scale);
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

  /**
   * The horizontal grid: pitch guidelines across the staff.
   *
   * Drawn first of everything, so the notation always reads on top of it.
   */
  _drawPitchGrid(b, opts) {
    const layout = this.layout;
    const mode = layout.pitchGrid || 'none';
    if (mode === 'none') return;

    const g = this.ctx;
    const paper = opts.ink === 'paper';
    const grid = pitchGrid(b.centre - b.span, b.centre + b.span, b.pxPerCent, mode);
    const yTopEdge = b.coreTop;
    const yBotEdge = b.coreTop + b.coreH;
    const alpha = Math.max(0, Math.min(1, layout.pitchGridOpacity ?? 0.1));

    if (grid.bands.length && alpha > 0.001) {
      // On paper the chromatic regions are literally darker. On the dark
      // surface, darkening the ground would show nothing, so they are tinted
      // instead — the same reading of which regions are the black notes.
      g.fillStyle = paper ? `rgba(0,0,0,${alpha})` : `rgba(190,208,230,${alpha})`;
      for (const band of grid.bands) {
        const top = Math.max(yTopEdge, yForBand(b, band.c1));
        const bottom = Math.min(yBotEdge, yForBand(b, band.c0));
        if (bottom - top > 0.15) g.fillRect(opts.x0, top, opts.x1 - opts.x0, bottom - top);
      }
    }

    for (const line of grid.lines) {
      const y = yForBand(b, line.cents);
      if (y < yTopEdge - 0.5 || y > yBotEdge + 0.5) continue;
      g.strokeStyle = paper
        ? line.strong ? 'rgba(0,0,0,0.32)' : 'rgba(0,0,0,0.13)'
        : line.strong ? 'rgba(190,208,230,0.42)' : 'rgba(150,168,190,0.18)';
      g.lineWidth = line.strong ? 1 : 0.7;
      g.beginPath();
      g.moveTo(opts.x0, y);
      g.lineTo(opts.x1, y);
      g.stroke();
    }
  }

  /**
   * The vertical grid: pseudo-barlines at a chosen rate, with optional
   * timestamps, and the pitch grid underneath them.
   *
   * Drawn behind the notation so the ribbon always reads on top of them.
   */
  _drawRules(b, xFor, tA, tB, opts) {
    const g = this.ctx;
    const layout = this.layout;
    const paper = opts.ink === 'paper';
    const scale = opts.textScale || 1;

    this._drawPitchGrid(b, opts);

    if (layout.showStaffOutline) {
      g.strokeStyle = paper ? '#c8c8c8' : 'rgba(150,168,190,0.55)';
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(opts.x0, b.coreTop + b.coreH + 0.5);
      g.lineTo(opts.x1, b.coreTop + b.coreH + 0.5);
      g.stroke();
    }

    const style = layout.rulesStyle || 'none';
    if (style === 'none' && (layout.rulesLabels || 'none') === 'none') return;

    const pxPerSecond = (opts.x1 - opts.x0) / Math.max(1e-6, tB - tA);
    const marks = timeMarkers(tA, tB, {
      rate: layout.rulesRate,
      group: layout.rulesGroup,
      pxPerSecond,
    });
    if (!marks.length) return;

    for (const m of marks) {
      const x = xFor(m.t);
      if (x < opts.x0 - 1 || x > opts.x1 + 1) continue;
      const strong = m.strong;

      if (style !== 'none') {
        g.strokeStyle = paper
          ? strong ? 'rgba(0,0,0,0.42)' : 'rgba(0,0,0,0.16)'
          : strong ? 'rgba(190,208,230,0.55)' : 'rgba(150,168,190,0.22)';
        g.lineWidth = strong ? 1.2 : 0.8;
        g.beginPath();
        if (style === 'ticks') {
          // One short row of marks: a time reference that stays out of the way
          // of the notation. Where the row sits is the engraver's choice, since
          // which edge is clear of the music depends on the music.
          const { top, len } = tickRow(b, layout, strong, scale);
          g.moveTo(x, top);
          g.lineTo(x, top + len);
        } else {
          // Barlines span the staff.
          g.moveTo(x, b.coreTop);
          g.lineTo(x, b.coreTop + b.coreH);
        }
        g.stroke();
      }

      // Labels only on the top staff of a system — repeating them on every
      // staff is clutter, not information.
      if (opts.isFirst && strong) {
        const label = markerLabel(m, layout.rulesLabels, layout.rulesRate);
        if (label) {
          g.font = `${9 * scale}px ui-monospace, Menlo, monospace`;
          g.fillStyle = paper ? '#777' : C.label;
          g.fillText(label, x + 2 * scale, b.top - 3 * scale);
        }
      }
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

    // Galley is one system running the whole work, so normalised heights crop
    // each staff to the part's own compass rather than to a passage of it.
    const bands = systemBands(
      { parts, tA: 0, tB: this.score?.duration ?? 0 },
      this.score,
      layout,
      RULER_H + 8 - this.scrollY,
      { project: this.project, pxPerSecond: layout.pxPerSecond }
    );
    this._contentH =
      RULER_H + 8 + bands.reduce((sum, b) => sum + b.height + layout.staffGap, 0);

    const xFor = (t) => this.xForGalley(t);
    for (const b of bands) {
      this._bands.push({
        band: b,
        x0: this.plotX,
        x1: this.w,
        tFor: (x) => this.tForGalley(x),
        xFor,
      });
      g.save();
      g.beginPath();
      // The clip takes in the name gutter as well, as Page view's does, so a
      // part name is not cut away by the box that keeps its notation in.
      g.rect(0, b.top, this.w, b.height);
      g.clip();
      this._drawBand(b, xFor, this.t0, this.t0 + this.tSpan, {
        ink: 'screen',
        x0: this.plotX,
        x1: this.w,
        labelX: 8,
        showLabel: true,
        isFirst: b === bands[0],
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

        const bands = systemBands(sys, this.score, layout, py + y, {
          scale: z,
          project: this.project,
        });
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
            isFirst: b === bands[0],
            systemIndex: sys.index,
            textScale: z,
            tFor,
          });
          g.restore();
        }
        y += sys.height * z + layout.systemGap * z;
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
        // Grabbing a mark already in the selection moves the whole selection.
        // Grabbing one outside it selects just that one first, so a drag never
        // silently carries marks the user had forgotten were selected.
        if (ev.shiftKey || !this.selection.has(hit.id)) {
          this.select(hit.id, ev.shiftKey);
        }
        if (this.selection.has(hit.id)) {
          const start = new Map();
          for (const id of this.selection) {
            const a = this.project.annotations.find((z) => z.id === id);
            if (a) start.set(id, { t: a.t, t2: a.t2, dy: a.dy || 0 });
          }
          this._drag = { start, x, y, band: hit.band, tFor: hit.tFor, moved: false };
          c.setPointerCapture(ev.pointerId);
        }
        this.draw();
        return;
      }
      const e = this._bandAt(x, y, this.mode === 'write');
      // Shift on empty space keeps the selection: it is the modifier for adding
      // to it, so treating it as "clear" would undo the gesture in progress.
      if (ev.shiftKey) {
        this.draw();
        return;
      }
      this.select(null);
      this.selectedBreakId = null;

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
        const cents = centsForBand(b, y);
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
      if (this._drag?.start) {
        const b = this._drag.band;
        // One delta for the whole selection, so marks keep their spacing from
        // each other. Converted through the band the drag started in: the
        // gesture is in pixels but the marks are stored in seconds and cents.
        let dt = this._drag.tFor(x) - this._drag.tFor(this._drag.x);
        for (const s of this._drag.start.values()) dt = Math.max(dt, -s.t);
        const dCents = -((y - this._drag.y) * 2 * b.span) / b.coreH;

        const moves = new Map();
        for (const [id, s] of this._drag.start) {
          moves.set(id, {
            t: s.t + dt,
            t2: s.t2 == null ? null : s.t2 + dt,
            dy: s.dy + dCents,
          });
        }
        nudgeMany(this.project, moves);
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
