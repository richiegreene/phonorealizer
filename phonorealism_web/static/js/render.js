/*
 * render.js — the scrolling performance display.
 *
 * Two stacked panes sharing one time axis, scrolling right-to-left past a fixed
 * "now" line: pitch above, amplitude below. Notated material and the
 * performer's live trace are drawn *in the same space*, overlaid, rather than
 * side by side — the whole point is to read the gap between them at a glance,
 * and side-by-side panes make the eye do the comparison instead of the display.
 *
 * The now line sits a third of the way across, not at the edge, so there is
 * room to see what is coming while still seeing what just happened.
 */

const NOW_X = 0.34;

/** Pitch pane takes the larger share; intonation needs the resolution more. */
const PITCH_FRACTION = 0.58;

const COLORS = {
  bg: '#0b0d10',
  paneEdge: '#1c2128',
  grid: '#171c22',
  gridStrong: '#252c35',
  score: '#4da3ff',
  scoreFill: 'rgba(77, 163, 255, 0.16)',
  // The notated ribbon reads as the printed part: near-white and solid, as in
  // justidraw and the SVG exports. The live ribbon sits over it, translucent
  // so both remain legible where they overlap.
  scoreRibbon: '#dbe7f3',
  ensemble: 'rgba(120, 140, 165, 0.30)',
  live: '#ffb648',
  liveFill: 'rgba(255, 168, 40, 0.62)',
  liveWeak: 'rgba(255, 182, 72, 0.28)',
  now: '#ff4d6d',
  text: '#8b98a8',
  textBright: '#e6edf5',
  dim: '#5a6674',
  good: '#3ddc84',
  near: '#ffd23f',
  off: '#ff6b6b',
};

export class PerformanceView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.dpr = 1;
    this.w = 0;
    this.h = 0;

    this.score = null;
    this.partials = []; // the performer's own
    this.others = [];

    /** Seconds of score visible across the full width. */
    this.window = 6;
    /** Half-height of the pitch pane, in cents, when following. */
    this.pitchSpan = 150;
    /**
     * 'range' fits the part's whole contour; 'follow' centres on the notated
     * pitch for fine intonation work. Range is the default because it is
     * legible the instant playback starts — a performer needs to find their
     * place before they need cents.
     */
    this.pitchMode = 'range';
    this.showEnsemble = false;

    /**
     * 'ribbon' draws the part the way justidraw and the modifier's SVG export
     * draw it: one shape whose vertical position is pitch and whose *thickness*
     * is amplitude, tapering to nothing as a partial dies away. 'panes' keeps
     * pitch and amplitude in separate stacked plots.
     *
     * Ribbon is the default because it is the notation these parts were
     * composed in — a player already reading justidraw sees the same object.
     */
    this.notation = 'ribbon';
    /** Ribbon thickness in pixels at the part's loudest point. */
    this.ribbonScale = 46;

    this.time = 0;
    this.live = []; // {t, cents, amp, conf}
    this.liveLimit = 4000;

    this.notated = null; // {hz, cents, amp} at `time`
    this.deviation = null; // cents, live minus notated
    this.countdown = null;

    this._cursors = new Map();
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(canvas);
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
  }

  setScore(score, partials, others = []) {
    this.score = score;
    this.partials = partials || [];
    this.others = others;
    this.live.length = 0;
    this._cursors.clear();
    if (this.partials.length) {
      // A sensible default zoom: enough cents to see the part's whole contour,
      // clamped so a static part is not magnified into noise.
      const lo = Math.min(...this.partials.map((p) => p.fMin));
      const hi = Math.max(...this.partials.map((p) => p.fMax));
      if (lo > 0 && hi > lo) {
        const spread = 1200 * Math.log2(hi / lo);
        this.rangeSpan = Math.max(200, spread * 0.6);
        this.rangeCentre = 1200 * Math.log2(Math.sqrt(lo * hi) / 440);
      }
    }
  }

  clearLive() {
    this.live.length = 0;
  }

  /** Record a live reading, stamped with the score time it belongs to. */
  pushLive(t, hz, amp, conf) {
    const cents = hz > 0 ? 1200 * Math.log2(hz / 440) : null;
    this.live.push({ t, cents, amp, conf });
    if (this.live.length > this.liveLimit) this.live.splice(0, this.live.length - this.liveLimit);
  }

  /* ---------------- geometry ---------------- */

  xFor(t) {
    return (t - this.time) * (this.w / this.window) + this.w * NOW_X;
  }

  get pitchTop() {
    return 0;
  }

  get pitchHeight() {
    // A ribbon carries amplitude in its own thickness, so there is no second
    // pane to leave room for — the pitch axis gets the whole screen, and with
    // it a good deal more vertical resolution.
    return this.notation === 'ribbon' ? this.h : this.h * PITCH_FRACTION;
  }

  /**
   * The amplitude that maps to full ribbon thickness: the loudest point of the
   * performer's own part. Scaling to the part rather than to an absolute 1.0
   * matters because a high partial's normalised magnitude may peak around 0.1,
   * which would otherwise render as a permanently invisible thread.
   */
  _ampRef() {
    let m = 0;
    for (const p of this.partials) m = Math.max(m, p.aMax);
    return m > 1e-6 ? m : 1;
  }

  get ampTop() {
    return this.pitchHeight + 1;
  }

  get ampHeight() {
    return this.h - this.ampTop;
  }

  _centreCents() {
    if (this.pitchMode === 'range' && this.rangeCentre != null) return this.rangeCentre;
    if (this.notated && this.notated.cents != null) return this.notated.cents;
    if (this.rangeCentre != null) return this.rangeCentre;
    return 0;
  }

  /**
   * Half-height of the pitch pane in cents.
   *
   * In follow mode this is the performer's chosen zoom, but widened when
   * necessary to keep *all* of their own partials on screen. A part can span an
   * octave or more — the flute doubling partials 1 and 2, say — and a fixed
   * ±150 cents would push the second line off the pane, where it degenerates
   * into a vertical streak at the clip edge instead of showing as music.
   */
  _span() {
    if (this.pitchMode === 'range' && this.rangeSpan) return this.rangeSpan;
    return Math.max(this.pitchSpan, this._neededSpan || 0);
  }

  yForCents(cents) {
    const span = this._span();
    const centre = this._smoothCentre != null ? this._smoothCentre : this._centreCents();
    const u = (cents - centre) / span; // -1..1 across the pane
    return this.pitchHeight / 2 - (u * this.pitchHeight) / 2;
  }

  yForAmp(a, mirror) {
    const mid = this.ampTop + this.ampHeight / 2;
    const half = (this.ampHeight / 2) * 0.92;
    return mirror ? mid + a * half : mid - a * half;
  }

  /* ---------------- state update ---------------- */

  /** Advance to a new score time and recompute what is notated right now. */
  setTime(t) {
    this.time = t;
    let best = null;
    const cents = [];
    for (const p of this.partials) {
      const c = this._cursors.get(p.index) || 0;
      const s = sampleForRender(p, t, c);
      if (!s) continue;
      this._cursors.set(p.index, s.i);
      if (s.f > 0) cents.push(1200 * Math.log2(s.f / 440));
      if (!best || s.a > best.a) best = s;
    }
    this.notated = best
      ? { hz: best.f, cents: best.f > 0 ? 1200 * Math.log2(best.f / 440) : null, amp: best.a }
      : null;

    // Ease the vertical centre so that a leap in the notated line does not
    // snap the whole display and cost the performer their place.
    const target = this._centreCents();
    if (this._smoothCentre == null) this._smoothCentre = target;
    else this._smoothCentre += (target - this._smoothCentre) * 0.18;

    // How wide the pane must be to hold every line the performer is reading.
    let needed = 0;
    for (const c of cents) needed = Math.max(needed, Math.abs(c - this._smoothCentre));
    const want = needed > 0 ? needed * 1.15 + 30 : 0;
    this._neededSpan =
      this._neededSpan == null ? want : this._neededSpan + (want - this._neededSpan) * 0.12;

    const last = this.live[this.live.length - 1];
    this.deviation =
      last && last.cents != null && this.notated && this.notated.cents != null && last.conf > 0.15
        ? last.cents - this.notated.cents
        : null;
  }

  /* ---------------- drawing ---------------- */

  draw() {
    const g = this.ctx;
    g.fillStyle = COLORS.bg;
    g.fillRect(0, 0, this.w, this.h);

    this._drawGrid();

    // Each pane is clipped to its own rectangle. Without this a pitch line that
    // leaves the visible cent range is still stroked to its true coordinate,
    // painting a full-height streak straight through the amplitude pane below.
    g.save();
    g.beginPath();
    g.rect(0, 0, this.w, this.pitchHeight);
    g.clip();
    if (this.notation === 'ribbon') {
      const ampRef = this._ampRef();
      if (this.showEnsemble) {
        this._drawPartialsRibbon(this.others, COLORS.ensemble, ampRef, false);
      }
      this._drawPartialsRibbon(this.partials, COLORS.scoreRibbon, ampRef, true);
      this._drawLiveRibbon(ampRef);
    } else {
      if (this.showEnsemble) this._drawPartials(this.others, COLORS.ensemble, 1, false);
      this._drawPartials(this.partials, COLORS.score, 2.2, true);
      this._drawLivePitch();
    }
    g.restore();

    if (this.notation !== 'ribbon') {
      g.save();
      g.beginPath();
      g.rect(0, this.ampTop, this.w, this.ampHeight);
      g.clip();
      this._drawAmplitudeScore();
      this._drawLiveAmplitude();
      g.restore();
    }

    this._drawNowLine();
    this._drawReadout();
    if (this.countdown != null) this._drawCountdown();
  }

  _drawGrid() {
    const g = this.ctx;

    if (this.notation !== 'ribbon') {
      g.strokeStyle = COLORS.paneEdge;
      g.lineWidth = 1;
      g.beginPath();
      g.moveTo(0, this.ampTop - 0.5);
      g.lineTo(this.w, this.ampTop - 0.5);
      g.stroke();
    }

    // Semitone lines in the pitch pane — the reference a performer actually
    // reads intonation against.
    const centre = this._smoothCentre != null ? this._smoothCentre : this._centreCents();
    const span = this._span();
    const step = span > 600 ? 1200 : span > 250 ? 100 : 50;
    const from = Math.ceil((centre - span) / step) * step;
    g.lineWidth = 1;
    for (let c = from; c <= centre + span; c += step) {
      const y = this.yForCents(c);
      if (y < 0 || y > this.pitchHeight) continue;
      const isOctave = Math.abs(c % 1200) < 1e-6;
      g.strokeStyle = isOctave ? COLORS.gridStrong : COLORS.grid;
      g.beginPath();
      g.moveTo(0, y + 0.5);
      g.lineTo(this.w, y + 0.5);
      g.stroke();
    }

    // One-second time rules.
    const t0 = Math.ceil(this.time - this.window * NOW_X);
    const t1 = this.time + this.window * (1 - NOW_X);
    g.strokeStyle = COLORS.grid;
    for (let t = t0; t <= t1; t += 1) {
      const x = Math.round(this.xFor(t)) + 0.5;
      g.beginPath();
      g.moveTo(x, 0);
      g.lineTo(x, this.h);
      g.stroke();
    }

    if (this.notation !== 'ribbon') {
      // Amplitude centre line.
      g.strokeStyle = COLORS.grid;
      const mid = Math.round(this.ampTop + this.ampHeight / 2) + 0.5;
      g.beginPath();
      g.moveTo(0, mid);
      g.lineTo(this.w, mid);
      g.stroke();
    }
  }

  /** Visible time bounds, with a margin so lines enter cleanly. */
  _bounds() {
    return [
      this.time - this.window * NOW_X - 0.05,
      this.time + this.window * (1 - NOW_X) + 0.05,
    ];
  }

  _drawPartials(partials, color, width, glow) {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    const px = this.w / this.window;
    // One sample every ~2 device pixels is plenty; beyond that we are drawing
    // detail no phone screen can show, on a thread that must hit 60 fps.
    const dt = Math.max(0.002, 2 / px);

    g.lineJoin = 'round';
    g.lineCap = 'round';
    for (const p of partials) {
      if (p.t1 < tA || p.t0 > tB) continue;
      g.strokeStyle = color;
      g.lineWidth = width;
      if (glow) {
        g.shadowColor = color;
        g.shadowBlur = 8;
      }
      g.beginPath();
      let pen = false;
      let cursor = 0;
      // Break the path well outside the pane rather than carrying it there.
      // Clipping alone would hide the excursion but still join the points
      // across it, leaving a vertical chord where the line exits and re-enters.
      const limit = this.pitchHeight * 3;
      for (let t = Math.max(tA, p.t0); t <= Math.min(tB, p.t1); t += dt) {
        const s = sampleForRender(p, t, cursor);
        if (!s) continue;
        cursor = s.i;
        if (!(s.f > 0)) continue;
        const y = this.yForCents(1200 * Math.log2(s.f / 440));
        if (y < -limit || y > limit) {
          pen = false;
          continue;
        }
        const x = this.xFor(t);
        if (!pen) {
          g.moveTo(x, y);
          pen = true;
        } else {
          g.lineTo(x, y);
        }
      }
      g.stroke();
      g.shadowBlur = 0;
    }
  }

  /**
   * Fill one ribbon: a centreline offset perpendicularly by half its width at
   * each point.
   *
   * This is the same construction the modifier's SVG exporter uses for its
   * pitch plots. The tangent at an interior point is the sum of the normalised
   * incoming and outgoing directions, which bisects the corner — offsetting
   * along that bisector keeps the two edges parallel through a bend instead of
   * pinching on the inside of it.
   *
   * @param {Array<[number,number,number]>} pts [x, y, width] triples
   */
  _fillRibbon(pts, fill) {
    const n = pts.length;
    if (n < 2) return;
    const g = this.ctx;

    // Smooth the width channel before offsetting.
    //
    // The display samples at roughly one point per two pixels, which at normal
    // zoom lands close to the score's own 11.6 ms analysis frame. Sampling a
    // noisy per-frame amplitude at nearly its own rate aliases that noise into
    // a coarse sawtooth along the ribbon edge — an artefact of the analysis
    // resolution, not something the composer wrote. A short moving average
    // removes it while leaving the envelope's actual shape intact.
    const R = 2; // half-window, i.e. 5 samples
    const wSm = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      let sum = 0;
      let count = 0;
      for (let k = i - R; k <= i + R; k++) {
        if (k < 0 || k >= n) continue;
        sum += pts[k][2];
        count++;
      }
      wSm[i] = sum / count;
    }

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
      // Perpendicular to the tangent.
      const nx = -ty / len;
      const ny = tx / len;
      const half = wSm[i] / 2;
      top[i] = [pts[i][0] + nx * half, pts[i][1] + ny * half];
      bottom[i] = [pts[i][0] - nx * half, pts[i][1] - ny * half];
    }

    g.beginPath();
    g.moveTo(top[0][0], top[0][1]);
    for (let i = 1; i < n; i++) g.lineTo(top[i][0], top[i][1]);
    for (let i = n - 1; i >= 0; i--) g.lineTo(bottom[i][0], bottom[i][1]);
    g.closePath();
    g.fillStyle = fill;
    g.fill();
  }

  /** Draw notated partials as justidraw-style ribbons. */
  _drawPartialsRibbon(partials, fill, ampRef, glow) {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    const px = this.w / this.window;
    const dt = Math.max(0.002, 2 / px);
    const limit = this.h * 3;

    if (glow) {
      g.shadowColor = fill;
      g.shadowBlur = 10;
    }
    for (const p of partials) {
      if (p.t1 < tA || p.t0 > tB) continue;
      let run = [];
      let cursor = 0;
      const flush = () => {
        if (run.length >= 2) this._fillRibbon(run, fill);
        run = [];
      };
      for (let t = Math.max(tA, p.t0); t <= Math.min(tB, p.t1); t += dt) {
        const s = sampleForRender(p, t, cursor);
        if (!s) continue;
        cursor = s.i;
        if (!(s.f > 0)) {
          flush();
          continue;
        }
        const y = this.yForCents(1200 * Math.log2(s.f / 440));
        if (y < -limit || y > limit) {
          flush();
          continue;
        }
        // A silent point tapers to a hairline rather than vanishing, so the
        // line stays followable through a rest.
        const w = 0.6 + (Math.max(0, s.a) / ampRef) * this.ribbonScale;
        run.push([this.xFor(t), y, w]);
      }
      flush();
    }
    g.shadowBlur = 0;
  }

  /**
   * The performer's own sound, drawn in the same language as the notation so
   * that matching is a matter of overlaying one shape on another — both the
   * contour and the thickness have to agree.
   */
  _drawLiveRibbon(ampRef) {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    const limit = this.h * 3;
    let run = [];
    const flush = () => {
      if (run.length >= 2) this._fillRibbon(run, COLORS.liveFill);
      run = [];
    };

    g.shadowColor = COLORS.live;
    g.shadowBlur = 6;
    for (const s of this.live) {
      if (s.t < tA || s.t > tB) continue;
      if (s.cents == null || s.conf < 0.15) {
        flush();
        continue;
      }
      const y = this.yForCents(s.cents);
      if (y < -limit || y > limit) {
        flush();
        continue;
      }
      const w = 0.6 + (Math.max(0, s.amp) / ampRef) * this.ribbonScale;
      run.push([this.xFor(s.t), y, w]);
    }
    flush();
    g.shadowBlur = 0;
  }

  /** The notated dynamic, as the mirrored envelope used across this project. */
  _drawAmplitudeScore() {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    const px = this.w / this.window;
    const dt = Math.max(0.002, 2 / px);
    if (!this.partials.length) return;

    const top = [];
    const bottom = [];
    // Per-partial cursors: without them each column rescans the whole envelope
    // from zero, turning the pane into O(columns x breakpoints) every frame.
    const cursors = new Array(this.partials.length).fill(0);
    for (let t = tA; t <= tB; t += dt) {
      let a = 0;
      for (let pi = 0; pi < this.partials.length; pi++) {
        const s = sampleForRender(this.partials[pi], t, cursors[pi]);
        if (!s) continue;
        cursors[pi] = s.i;
        if (s.a > a) a = s.a;
      }
      const x = this.xFor(t);
      top.push([x, this.yForAmp(a, false)]);
      bottom.push([x, this.yForAmp(a, true)]);
    }
    if (top.length < 2) return;

    g.beginPath();
    g.moveTo(top[0][0], top[0][1]);
    for (const [x, y] of top) g.lineTo(x, y);
    for (let i = bottom.length - 1; i >= 0; i--) g.lineTo(bottom[i][0], bottom[i][1]);
    g.closePath();
    g.fillStyle = COLORS.scoreFill;
    g.fill();
    g.strokeStyle = COLORS.score;
    g.lineWidth = 1.4;
    g.stroke();
  }

  /**
   * Pitch trace. Confidence gates the line so that rests and background noise
   * do not draw a wandering thread across the display — a performer glancing
   * down must be able to trust that a drawn line means a sounding note.
   */
  _drawLivePitch() {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    const limit = this.pitchHeight * 3;

    g.lineWidth = 2.2;
    g.lineJoin = 'round';
    g.lineCap = 'round';
    g.strokeStyle = COLORS.live;
    g.shadowColor = COLORS.live;
    g.shadowBlur = 6;
    g.beginPath();
    let pen = false;
    for (const s of this.live) {
      if (s.t < tA || s.t > tB) continue;
      if (s.cents == null || s.conf < 0.15) {
        pen = false;
        continue;
      }
      const y = this.yForCents(s.cents);
      if (y < -limit || y > limit) {
        pen = false;
        continue;
      }
      const x = this.xFor(s.t);
      if (!pen) {
        g.moveTo(x, y);
        pen = true;
      } else {
        g.lineTo(x, y);
      }
    }
    g.stroke();
    g.shadowBlur = 0;
  }

  /** Live amplitude, mirrored to sit against the notated envelope. */
  _drawLiveAmplitude() {
    const g = this.ctx;
    const [tA, tB] = this._bounds();
    g.strokeStyle = COLORS.liveWeak;
    g.lineWidth = 1.4;
    for (const mirror of [false, true]) {
      g.beginPath();
      let started = false;
      for (const s of this.live) {
        if (s.t < tA || s.t > tB) continue;
        const x = this.xFor(s.t);
        const y = this.yForAmp(Math.min(1.2, s.amp), mirror);
        if (!started) {
          g.moveTo(x, y);
          started = true;
        } else {
          g.lineTo(x, y);
        }
      }
      g.stroke();
    }
  }

  _drawNowLine() {
    const g = this.ctx;
    const x = Math.round(this.w * NOW_X) + 0.5;
    g.strokeStyle = COLORS.now;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(x, 0);
    g.lineTo(x, this.h);
    g.stroke();

    // Where the performer actually is, right now.
    const last = this.live[this.live.length - 1];
    if (last && last.cents != null && last.conf > 0.15) {
      g.fillStyle = COLORS.live;
      g.beginPath();
      g.arc(x, this.yForCents(last.cents), 4.5, 0, Math.PI * 2);
      g.fill();
    }
    if (this.notated && this.notated.cents != null) {
      g.strokeStyle = COLORS.score;
      g.lineWidth = 2;
      g.beginPath();
      g.arc(x, this.yForCents(this.notated.cents), 6.5, 0, Math.PI * 2);
      g.stroke();
    }
  }

  _drawReadout() {
    const g = this.ctx;
    g.textBaseline = 'top';

    const d = this.deviation;
    const label = d == null ? '—' : `${d > 0 ? '+' : ''}${d.toFixed(0)}`;
    // No reading is not the same as a bad reading. Colouring silence red would
    // tell a resting player they are wildly out of tune.
    const color =
      d == null
        ? COLORS.dim
        : Math.abs(d) <= 10
          ? COLORS.good
          : Math.abs(d) <= 30
            ? COLORS.near
            : COLORS.off;

    g.fillStyle = color;
    g.font = '600 34px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.textAlign = 'right';
    g.fillText(label, this.w - 14, 10);
    g.fillStyle = COLORS.text;
    g.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillText('cents', this.w - 14, 48);

    g.textAlign = 'left';
    if (this.notated) {
      g.fillStyle = COLORS.textBright;
      g.font = '13px ui-monospace, SFMono-Regular, Menlo, monospace';
      g.fillText(`${this.notated.hz.toFixed(1)} Hz`, 12, 10);
    }
    g.fillStyle = COLORS.text;
    g.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillText(`${this.time.toFixed(2)} s`, 12, 28);
  }

  _drawCountdown() {
    const g = this.ctx;
    const n = this.countdown;
    g.fillStyle = 'rgba(11, 13, 16, 0.72)';
    g.fillRect(0, 0, this.w, this.h);
    g.fillStyle = COLORS.textBright;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.font = '600 96px ui-monospace, SFMono-Regular, Menlo, monospace';
    g.fillText(n > 0 ? String(n) : '—', this.w / 2, this.h / 2);
    g.font = '14px system-ui, sans-serif';
    g.fillStyle = COLORS.text;
    g.fillText('stand by', this.w / 2, this.h / 2 + 70);
  }
}

/**
 * Local copy of the envelope sampler, kept here so the renderer has no import
 * cycle with score.js and can be handed plain partial objects.
 */
function sampleForRender(p, t, cursor) {
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
