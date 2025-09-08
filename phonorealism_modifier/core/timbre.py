import numpy as np
from scipy.fft import rfft
from scipy.signal import find_peaks

def get_harmonic_profile(waveform, num_harmonics=64):
    """
    Analyzes a waveform to find the relative amplitudes of its harmonics.

    Args:
        waveform (np.ndarray): The waveform to analyze (should be a 1D array).
        num_harmonics (int): The number of harmonics to return.

    Returns:
        np.ndarray: An array of harmonic amplitudes, normalized so the fundamental is 1.0.
    """
    if waveform is None or len(waveform) == 0:
        return np.zeros(num_harmonics)

    # Ensure waveform is suitable for FFT
    waveform = waveform.astype(np.float32)

    # Compute the real FFT
    fft_result = rfft(waveform)
    fft_magnitude = np.abs(fft_result)

    # Find the peak corresponding to the fundamental frequency
    # This is usually the largest peak, excluding DC offset (index 0)
    if len(fft_magnitude) > 1:
        fundamental_index = np.argmax(fft_magnitude[1:]) + 1
    else:
        return np.zeros(num_harmonics)
        
    fundamental_amplitude = fft_magnitude[fundamental_index]

    if fundamental_amplitude == 0:
        return np.zeros(num_harmonics)

    # Find amplitudes of the harmonics
    harmonic_amplitudes = []
    for n in range(1, num_harmonics + 1):
        harmonic_index = fundamental_index * n
        if harmonic_index < len(fft_magnitude):
            # Simple peak picking
            start = max(0, harmonic_index - 2)
            end = min(len(fft_magnitude), harmonic_index + 3)
            try:
                peak_amplitude = np.max(fft_magnitude[start:end])
                harmonic_amplitudes.append(peak_amplitude)
            except ValueError:
                 harmonic_amplitudes.append(0) # No peak found in range
        else:
            harmonic_amplitudes.append(0)

    harmonic_amplitudes = np.array(harmonic_amplitudes)
    
    # Normalize so the fundamental (first harmonic) is 1.0
    fundamental_true_amp = harmonic_amplitudes[0]
    if fundamental_true_amp > 0:
        normalized_amplitudes = harmonic_amplitudes / fundamental_true_amp
    else:
        normalized_amplitudes = np.zeros(num_harmonics)

    return normalized_amplitudes
