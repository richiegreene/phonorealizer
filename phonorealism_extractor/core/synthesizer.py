
import numpy as np
import soundfile as sf
from scipy.interpolate import interp1d

def db_to_linear(db):
    return 10 ** (db / 20)

def generate_partial_waveform(time_array, freq_array, amp_array, sr, duration):
    t = np.linspace(0, duration, int(sr * duration))
    freq_interp = interp1d(time_array, freq_array, kind='linear', bounds_error=False, fill_value=0)
    amp_interp = interp1d(time_array, amp_array, kind='linear', bounds_error=False, fill_value=-120)

    freq_t = freq_interp(t)
    amp_t = db_to_linear(amp_interp(t))

    phase = 2 * np.pi * np.cumsum(freq_t) / sr
    waveform = amp_t * np.sin(phase)

    return waveform

def synthesize_from_partials(partials, sr, output_wav_path, duration):
    if not partials:
        return

    waveform = np.zeros(int(sr * duration))

    for harmonic in partials:
        if not harmonic:
            continue
        time_array, freq_array, amp_array = zip(*harmonic)
        # octave transpose frequency for synthesis
        freq_array_halved = [f * 0.5 for f in freq_array]
        partial_wave = generate_partial_waveform(time_array, freq_array_halved, amp_array, sr, duration)
        waveform[:len(partial_wave)] += partial_wave

    # Normalize and write to file
    waveform /= np.max(np.abs(waveform))
    sf.write(output_wav_path, waveform, sr)
