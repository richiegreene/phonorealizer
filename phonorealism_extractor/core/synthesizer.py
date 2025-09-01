
import numpy as np
import soundfile as sf
from scipy.interpolate import interp1d

def db_to_linear(db):
    return 10 ** (db / 20)

def generate_partial_waveform(time_array, freq_array, amp_array, sr, duration, playback_speed, wavetable=None):
    t = np.linspace(0, duration, int(sr * duration))
    
    # Scale the time_array for interpolation to change playback speed
    scaled_time_array = [t_val / playback_speed for t_val in time_array]

    freq_interp = interp1d(scaled_time_array, freq_array, kind='linear', bounds_error=False, fill_value=0)
    amp_interp = interp1d(scaled_time_array, amp_array, kind='linear', bounds_error=False, fill_value=-120)

    freq_t = freq_interp(t)
    amp_t = db_to_linear(amp_interp(t))

    phase = 2 * np.pi * np.cumsum(freq_t) / sr
    
    if wavetable is None:
        waveform = amp_t * np.sin(phase)
    else:
        wavetable_size = len(wavetable)
        lookup_indices = (phase % (2 * np.pi)) * (wavetable_size / (2 * np.pi))
        waveform = amp_t * np.interp(lookup_indices, np.arange(wavetable_size), wavetable)

    return waveform

def synthesize_from_partials(partials, sr, output_wav_path, duration, playback_speed=1.0, wavetable=None):
    if not partials:
        return

    adjusted_duration = duration / playback_speed
    waveform = np.zeros(int(sr * adjusted_duration))

    for harmonic in partials:
        if not harmonic:
            continue
        time_array, freq_array, amp_array = zip(*harmonic)
        # octave transpose frequency for synthesis
        freq_array_halved = [f * 0.5 for f in freq_array]
        partial_wave = generate_partial_waveform(time_array, freq_array_halved, amp_array, sr, adjusted_duration, playback_speed, wavetable=wavetable)
        waveform[:len(partial_wave)] += partial_wave

    # Normalize and write to file
    max_abs_amp = np.max(np.abs(waveform))
    if max_abs_amp > 0:
        waveform /= max_abs_amp
    
    sf.write(output_wav_path, waveform, sr)
