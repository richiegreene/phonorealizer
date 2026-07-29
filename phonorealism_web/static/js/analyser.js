/*
 * analyser.js — live pitch and amplitude from the performer's microphone.
 *
 * Method follows the desktop Perform window: take an FFT, pick the strongest
 * bin, then refine it by fitting a parabola across the peak and its neighbours.
 * The refinement is what makes this usable — a raw bin index at fftSize 8192 /
 * 48 kHz is only accurate to ±5.9 Hz, which is ±16 cents at 608 Hz and far too
 * coarse to rehearse against. Interpolating gets it to well under a cent for a
 * clean sustained tone.
 *
 * Unlike the desktop version this interpolates on the *log* magnitudes, which
 * is what the browser hands us anyway. A windowed sinusoid's spectral peak is
 * near-Gaussian, so it is a parabola in dB — fitting there is both simpler and
 * more accurate than fitting linear magnitudes.
 */

/**
 * ~170 ms of signal at 48 kHz. Long enough to resolve closely spaced partials,
 * short enough to follow a glissando. Phonorealism parts are sustained, so the
 * trade sits further toward frequency resolution than a general pitch tracker.
 */
const FFT_SIZE = 8192;

/** Ignore anything below this — room rumble and handling noise live here. */
const MIN_TRACK_HZ = 50;

/**
 * Locate the dominant frequency in a dB magnitude spectrum.
 *
 * Split out from the analyser both because it is the part worth testing on
 * synthetic input and because it is the part with the interesting maths.
 *
 * @param {Float32Array} mags  magnitudes in dB, as getFloatFrequencyData gives
 * @param {number} binHz       sampleRate / fftSize
 * @param {number} lo          first bin to consider
 * @param {number} hi          last bin to consider
 * @returns {{hz:number, db:number, prominence:number}}
 */
export function peakFrequency(mags, binHz, lo, hi) {
  lo = Math.max(1, lo);
  hi = Math.min(mags.length - 2, hi);
  if (hi <= lo) return { hz: 0, db: -Infinity, prominence: 0 };

  let peak = lo;
  let peakDb = -Infinity;
  let sum = 0;
  let count = 0;
  for (let i = lo; i <= hi; i++) {
    const v = mags[i];
    if (v > peakDb) {
      peakDb = v;
      peak = i;
    }
    if (Number.isFinite(v)) {
      sum += v;
      count++;
    }
  }

  // Parabolic (quadratic) interpolation across the peak and its neighbours.
  // A windowed sinusoid's mainlobe is close to Gaussian, so in dB it is close
  // to a parabola — fitting here rather than on linear magnitudes is both
  // simpler and more accurate.
  let hz = peak * binHz;
  const l = mags[peak - 1];
  const c = mags[peak];
  const r = mags[peak + 1];
  if (Number.isFinite(l) && Number.isFinite(c) && Number.isFinite(r)) {
    const denom = l - 2 * c + r;
    if (denom !== 0) {
      const delta = (0.5 * (l - r)) / denom;
      if (Math.abs(delta) <= 1) hz = (peak + delta) * binHz;
    }
  }

  return { hz, db: peakDb, prominence: peakDb - (count ? sum / count : -100) };
}

export class MicAnalyser {
  constructor() {
    this.ctx = null;
    this.stream = null;
    this.analyser = null;
    this.source = null;
    this.freqData = null;
    this.timeData = null;

    /** Restrict the peak search to a band around the notated pitch. */
    this.targetHz = 0;
    this.bandSemitones = 7;
    this.bandLimited = true;

    /** Maps mic RMS onto the score's 0..1 amplitude scale. Set by calibrate(). */
    this.gain = 1;

    this._calibrating = null;
    this.lastError = null;
  }

  get sampleRate() {
    return this.ctx ? this.ctx.sampleRate : 48000;
  }

  get running() {
    return !!this.analyser;
  }

  /**
   * Open the microphone.
   *
   * Every piece of "helpful" phone DSP has to be switched off. Auto gain
   * control would make the amplitude readout meaningless — it is precisely the
   * dynamic contour we are asking the performer to match. Noise suppression is
   * trained on speech and treats a sustained high partial as noise to remove.
   * Echo cancellation would try to subtract the in-ear reference tone from the
   * very signal we are measuring.
   */
  async start({ deviceId } = {}) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error(
        'This browser will not expose the microphone. A secure origin ' +
          '(https:// or localhost) is required — plain http:// on a LAN address ' +
          'is blocked no matter the browser.'
      );
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1,
      },
    });

    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === 'suspended') await this.ctx.resume();

    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = FFT_SIZE;
    // Smoothing is a display convenience that would lag the pitch readout
    // behind the performer. Do our own smoothing downstream instead.
    this.analyser.smoothingTimeConstant = 0;
    this.source.connect(this.analyser);

    this.freqData = new Float32Array(this.analyser.frequencyBinCount);
    this.timeData = new Float32Array(this.analyser.fftSize);
    return this;
  }

  stop() {
    if (this.stream) for (const t of this.stream.getTracks()) t.stop();
    if (this.source) this.source.disconnect();
    this.stream = null;
    this.source = null;
    this.analyser = null;
  }

  /** Tell the tracker which pitch is currently notated, for band limiting. */
  setTarget(hz) {
    this.targetHz = hz > 0 ? hz : 0;
  }

  /**
   * Analyse the most recent frame.
   * @returns {{hz:number, rms:number, level:number, conf:number}|null}
   */
  read() {
    if (!this.analyser) return null;
    const a = this.analyser;
    a.getFloatFrequencyData(this.freqData);
    a.getFloatTimeDomainData(this.timeData);

    // --- amplitude ---
    let sum = 0;
    for (let i = 0; i < this.timeData.length; i++) sum += this.timeData[i] * this.timeData[i];
    const rms = Math.sqrt(sum / this.timeData.length);

    // --- pitch ---
    const bins = this.freqData;
    const n = bins.length;
    const binHz = this.sampleRate / a.fftSize;

    let lo = Math.max(1, Math.floor(MIN_TRACK_HZ / binHz));
    let hi = n - 2;
    if (this.bandLimited && this.targetHz > 0) {
      const r = Math.pow(2, this.bandSemitones / 12);
      lo = Math.max(lo, Math.floor(this.targetHz / r / binHz));
      hi = Math.min(hi, Math.ceil((this.targetHz * r) / binHz));
    }
    if (hi <= lo) return { hz: 0, rms, level: rms * this.gain, conf: 0 };

    const { hz, db, prominence } = peakFrequency(bins, binHz, lo, hi);

    // Confidence: how far the peak stands above the mean level of the search
    // band. A clean tone sits 25 dB+ clear; noise sits a few dB clear.
    let conf = Math.max(0, Math.min(1, (prominence - 6) / 24));
    // No usable signal at all — do not report a pitch dragged out of the noise.
    if (db < -95 || rms < 1e-4) conf = 0;

    if (this._calibrating) this._calibrating.peak = Math.max(this._calibrating.peak, rms);

    return { hz: conf > 0 ? hz : 0, rms, level: rms * this.gain, conf };
  }

  /**
   * Match this performer's mic level to the score's amplitude scale.
   *
   * The score's amplitude is a normalised spectral magnitude; the mic's RMS
   * depends on the instrument, the distance and the phone. They are not
   * comparable until anchored, so we ask the performer for their loudest
   * sustained tone and map that onto the loudest point of their part.
   *
   * @param {number} ms listening window
   * @param {number} targetPeak the part's peak amplitude to map onto
   */
  calibrate(ms = 3000, targetPeak = 1) {
    this._calibrating = { peak: 0 };
    return new Promise((resolve) => {
      setTimeout(() => {
        const peak = this._calibrating.peak;
        this._calibrating = null;
        if (peak > 1e-5) {
          this.gain = targetPeak / peak;
          resolve({ ok: true, peak, gain: this.gain });
        } else {
          resolve({ ok: false, peak, gain: this.gain });
        }
      }, ms);
    });
  }

  static async listInputs() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter((d) => d.kind === 'audioinput');
    } catch {
      return [];
    }
  }
}

/**
 * One-pole smoother for the displayed traces. Pitch and amplitude get separate
 * instances because they want different time constants — pitch wants to settle,
 * amplitude wants to stay responsive.
 */
export class Smoother {
  constructor(coeff = 0.3) {
    this.coeff = coeff;
    this.value = null;
  }

  push(v) {
    if (v === null || !Number.isFinite(v)) return this.value;
    this.value = this.value === null ? v : this.value + this.coeff * (v - this.value);
    return this.value;
  }

  reset() {
    this.value = null;
  }
}
