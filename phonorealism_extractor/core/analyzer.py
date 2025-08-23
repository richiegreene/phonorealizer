
import librosa
import numpy as np

def analyze_audio(file_path, num_harmonics=32, analysis_mode="Isolated Harmonics"):
    """
    Analyzes an audio file to extract harmonic partials.

    Args:
        file_path (str): Path to the audio file.
        num_harmonics (int): The number of harmonics to extract.
        analysis_mode (str): The analysis mode ("Isolated Harmonics", "Spectral Bleed Through", "Isolated Artifacts").

    Returns:
        A list of lists, where each inner list represents a harmonic and contains tuples of (time, frequency, amplitude).
    """
    try:
        y, sr = librosa.load(file_path, sr=None)
    except Exception as e:
        print(f"Error loading audio file: {e}")
        return None

    N_FFT = 2048
    HOP_LENGTH = 512

    # Estimate fundamental frequency (f0)
    f0, _, _ = librosa.pyin(y, sr=sr, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=N_FFT, hop_length=HOP_LENGTH)
    f0 *= 2  # Correct for octave error
    times = librosa.times_like(f0, sr=sr, hop_length=HOP_LENGTH)

    # Get spectrogram
    stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
    magnitudes, phases = librosa.magphase(stft)
    
    partials = [[] for _ in range(num_harmonics)]

    db_spectrogram = librosa.amplitude_to_db(magnitudes, ref=np.max)

    last_f0 = 0
    for i, time in enumerate(times):
        current_f0 = f0[i]
        f0_is_nan = np.isnan(current_f0)

        if not f0_is_nan:
            last_f0 = current_f0

        if analysis_mode == "Isolated Harmonics":
            if f0_is_nan:
                continue
            process_f0 = current_f0
        elif analysis_mode == "Spectral Bleed Through":
            process_f0 = current_f0 if not f0_is_nan else last_f0
        elif analysis_mode == "Isolated Artifacts":
            if not f0_is_nan:
                # Optionally, you could add silent frames here
                # for n in range(1, num_harmonics + 1):
                #     partials[n-1].append((time, 0, -100)) # 0 freq, min amplitude
                continue
            process_f0 = last_f0
        else: # Default to isolated harmonics
            if f0_is_nan:
                continue
            process_f0 = current_f0

        if process_f0 <= 0:
            continue

        for n in range(1, num_harmonics + 1):
            harmonic_freq = n * process_f0
            
            # Find the nearest frequency bin in the STFT
            freq_bin = int(round(harmonic_freq * stft.shape[0] / sr))

            if 0 <= freq_bin < db_spectrogram.shape[0]:
                amplitude = db_spectrogram[freq_bin, i]
                partials[n-1].append((time, harmonic_freq, amplitude))
            else:
                # Add a silent point if the harmonic is out of bounds
                partials[n-1].append((time, harmonic_freq, -100)) # or some other indicator of silence


    return partials
