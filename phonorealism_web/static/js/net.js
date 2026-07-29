/*
 * net.js — WebSocket link to the hub, plus the clock synchronisation that the
 * whole system rests on.
 *
 * Nothing streams between devices. Once the downbeat lands, every phone plays
 * its part from its own local clock and no further packets matter. So the only
 * thing the network has to deliver accurately is a shared notion of *when*.
 *
 * The estimator is the usual round-trip one (NTP, Ableton Link):
 *
 *     offset = tServer - (t0 + t1) / 2        rtt = t1 - t0
 *
 * The halving assumes the two legs of the round trip are symmetric. That is
 * false in general, and the error is bounded by half the asymmetry — which is
 * why we keep the sample with the *lowest* observed RTT rather than averaging.
 * A fast round trip is one that got queued behind nothing in either direction,
 * so it is also the most symmetric one available. Averaging would fold every
 * congested outlier straight into the downbeat.
 */

/** Probe fast while acquiring a lock, then settle into a slow keepalive. */
const FAST_PROBE_MS = 120;
const SLOW_PROBE_MS = 3000;
const FAST_PROBE_COUNT = 24;

/** Best-sample lifetime. Long enough to be stable, short enough to track drift. */
const SAMPLE_TTL_MS = 60000;

export class Net extends EventTarget {
  constructor({ role, name } = {}) {
    super();
    this.role = role || 'performer';
    this.name = name || '';
    this.id = null;
    this.ws = null;
    this.session = null;
    this.connected = false;

    /** Best (lowest-RTT) sync sample seen inside the TTL window. */
    this.best = null;
    /** Recent samples, for the quality readout. */
    this.samples = [];
    this._probes = 0;
    this._timer = null;
    this._reconnectDelay = 500;
  }

  /* ---------------- clock ---------------- */

  /** Local monotonic reference, in ms. */
  static now() {
    return performance.now();
  }

  /** Our best estimate of the hub's clock, in ms, right now. */
  serverNow() {
    return Net.now() + (this.best ? this.best.offset : 0);
  }

  /** Convert a hub timestamp into our local `performance.now()` frame. */
  toLocal(serverMs) {
    return serverMs - (this.best ? this.best.offset : 0);
  }

  /**
   * Sync quality. `spread` is the half-RTT of the best sample — a conservative
   * bound on how far our downbeat could sit from everyone else's.
   */
  get quality() {
    if (!this.best) return { locked: false, rtt: null, spread: null, grade: 'none' };
    const rtt = this.best.rtt;
    const spread = rtt / 2;
    let grade = 'poor';
    if (spread <= 8) grade = 'good';
    else if (spread <= 25) grade = 'fair';
    return { locked: true, rtt, spread, grade, samples: this.samples.length };
  }

  _probe() {
    if (!this.connected) return;
    this._send({ type: 'ping', t0: Net.now() });
    this._probes++;
    const delay = this._probes < FAST_PROBE_COUNT ? FAST_PROBE_MS : SLOW_PROBE_MS;
    this._timer = setTimeout(() => this._probe(), delay);
  }

  _onPong(msg) {
    const t1 = Net.now();
    const rtt = t1 - msg.t0;
    const sample = {
      rtt,
      offset: msg.ts - (msg.t0 + t1) / 2,
      at: t1,
    };
    this.samples.push(sample);
    if (this.samples.length > 64) this.samples.shift();

    // Retire the current best once it ages out, so slow clock drift between
    // this device and the hub gets picked up instead of being locked in.
    const fresh = this.best && t1 - this.best.at < SAMPLE_TTL_MS;
    if (!fresh || rtt < this.best.rtt) this.best = sample;

    this.dispatchEvent(new CustomEvent('sync', { detail: this.quality }));
  }

  /* ---------------- transport ---------------- */

  connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws = ws;

    ws.onopen = () => {
      this.connected = true;
      this._reconnectDelay = 500;
      this._probes = 0;
      this._send({ type: 'hello', role: this.role, name: this.name });
      this._probe();
      this.dispatchEvent(new Event('open'));
    };

    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'pong') return this._onPong(msg);
      if (msg.type === 'welcome') {
        this.id = msg.id;
        this.dispatchEvent(new CustomEvent('welcome', { detail: msg }));
        return;
      }
      if (msg.type === 'state') {
        this.session = msg.session;
        this.dispatchEvent(new CustomEvent('state', { detail: msg.session }));
        return;
      }
      this.dispatchEvent(new CustomEvent(msg.type, { detail: msg }));
    };

    ws.onclose = () => {
      this.connected = false;
      clearTimeout(this._timer);
      this.dispatchEvent(new Event('close'));
      // Keep the clock estimate across a blip; the hub's clock did not move.
      setTimeout(() => this.connect(), this._reconnectDelay);
      this._reconnectDelay = Math.min(this._reconnectDelay * 1.8, 8000);
    };

    ws.onerror = () => ws.close();
  }

  _send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  send(obj) {
    this._send(obj);
  }

  /* ---------------- convenience ---------------- */

  setName(name) {
    this.name = name;
    this._send({ type: 'rename', name });
  }

  claim(partId) {
    this._send({ type: 'claim', partId });
  }

  release() {
    this._send({ type: 'release' });
  }

  status(patch) {
    this._send({ type: 'status', ...patch });
  }

  meter(cents, amp, conf) {
    this._send({ type: 'meter', cents, amp, conf });
  }

  /** Conductor: schedule the downbeat `leadIn` ms from now, on the hub's clock. */
  start(leadIn = 2500) {
    this._send({ type: 'start', leadIn });
  }

  stop() {
    this._send({ type: 'stop' });
  }

  setParts(parts) {
    this._send({ type: 'parts', parts });
  }

  announceScore(meta) {
    this._send({ type: 'scoreReady', meta });
  }
}

/* ------------------------------------------------------------------ *
 * Score transfer over HTTP (too big for the socket, and cacheable)
 * ------------------------------------------------------------------ */

export async function uploadScore(scoreJSON) {
  const res = await fetch('/api/score', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scoreJSON),
  });
  if (!res.ok) throw new Error(`Score upload failed: ${res.status}`);
  return res.json();
}

export async function fetchScore() {
  const res = await fetch('/api/score', { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Score fetch failed: ${res.status}`);
  return res.json();
}
