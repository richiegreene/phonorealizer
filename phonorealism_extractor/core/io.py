
import csv
import soundfile as sf
import numpy as np
import librosa
import svgwrite
from scipy.interpolate import interp1d

def db_to_linear(db):
    return 10 ** (db / 20)

def save_partials_to_csv(partials, output_path):
    """
    Saves the extracted partials to a CSV file.

    Args:
        partials (list): A list of lists of partial data.
        output_path (str): The path to the output CSV file.
    """
    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['time', 'harmonic_index', 'frequency', 'amplitude'])

        for harmonic_index, harmonic in enumerate(partials):
            for time, frequency, amplitude in harmonic:
                writer.writerow([time, harmonic_index + 1, frequency, amplitude])

def save_harmonic_to_wav(harmonic, sr, output_path):
    """
    Saves a single harmonic to a WAV file.

    Args:
        harmonic (list): A list of (time, frequency, amplitude) tuples.
        sr (int): The sample rate.
        output_path (str): The path to the output WAV file.
    """
    if not harmonic:
        return

    times, freqs, amps_db = zip(*harmonic)
    duration = times[-1]
    t = np.linspace(0., duration, int(sr * duration))
    
    interp_freqs = np.interp(t, times, freqs)
    interp_amps_db = np.interp(t, times, amps_db)
    interp_amps = librosa.db_to_amplitude(interp_amps_db)

    harmonic_wave = interp_amps * np.sin(2 * np.pi * interp_freqs * t)
    harmonic_wave /= np.max(np.abs(harmonic_wave))
    sf.write(output_path, harmonic_wave, sr)

def save_full_svg(partials, output_path, sr, duration):
    dwg = svgwrite.Drawing(output_path, profile='tiny')

    # Define SVG dimensions and scaling
    svg_width = 1000
    svg_height = 500
    dwg.viewbox(0, 0, svg_width, svg_height)

    # Scaling factors
    time_scale = svg_width / duration
    freq_scale = svg_height / (sr / 2) # Max frequency is Nyquist

    # Max amplitude for normalization (adjust as needed based on expected range)
    max_amp_db = 0 # Assuming 0dB is max
    min_amp_db = -120 # Assuming -120dB is min
    max_linear_amp = db_to_linear(max_amp_db)
    min_linear_amp = db_to_linear(min_amp_db)

    max_stroke_width = 5 # Max line thickness in SVG
    min_stroke_width = 0.1 # Min line thickness in SVG

    for harmonic_index, harmonic in enumerate(partials):
        if not harmonic:
            continue

        times, freqs, amps_db = zip(*harmonic)

        # Iterate through segments to create tapered lines
        for i in range(len(times) - 1):
            t1, f1, a1_db = times[i], freqs[i], amps_db[i]
            t2, f2, a2_db = times[i+1], freqs[i+1], amps_db[i+1]

            # Convert to SVG coordinates
            x1 = t1 * time_scale
            y1 = svg_height - (f1 * freq_scale) # SVG Y-axis is inverted

            x2 = t2 * time_scale
            y2 = svg_height - (f2 * freq_scale)

            # Interpolate amplitude for stroke width
            # Simple average for segment, or more complex interpolation if needed
            avg_amp_db = (a1_db + a2_db) / 2
            avg_linear_amp = db_to_linear(avg_amp_db)

            # Normalize linear amplitude to stroke width range
            normalized_amp = (avg_linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
            stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
            stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width)) # Clamp values

            dwg.add(dwg.line((x1, y1), (x2, y2),
                             stroke=svgwrite.rgb(0, 0, 0, '%'), # Black color
                             stroke_width=stroke_width,
                             fill='none')) # No fill for lines

    dwg.save()

def save_partial_svg(harmonic, output_path, sr, duration):
    dwg = svgwrite.Drawing(output_path, profile='tiny')

    # Define SVG dimensions and scaling
    svg_width = 1000
    svg_height = 500
    dwg.viewbox(0, 0, svg_width, svg_height)

    # Scaling factors
    time_scale = svg_width / duration
    freq_scale = svg_height / (sr / 2) # Max frequency is Nyquist

    if not harmonic:
        dwg.save()
        return

    times, freqs, amps_db = zip(*harmonic)

    # Normalize amplitude for this partial specifically
    max_amp_db = np.max(amps_db)
    min_amp_db = np.min(amps_db)
    max_linear_amp = db_to_linear(max_amp_db)
    min_linear_amp = db_to_linear(min_amp_db)

    max_stroke_width = 5 # Max line thickness in SVG
    min_stroke_width = 0.1 # Min line thickness in SVG

    for i in range(len(times) - 1):
        t1, f1, a1_db = times[i], freqs[i], amps_db[i]
        t2, f2, a2_db = times[i+1], freqs[i+1], amps_db[i+1]

        # Convert to SVG coordinates
        x1 = t1 * time_scale
        y1 = svg_height - (f1 * freq_scale) # SVG Y-axis is inverted

        x2 = t2 * time_scale
        y2 = svg_height - (f2 * freq_scale)

        avg_amp_db = (a1_db + a2_db) / 2
        avg_linear_amp = db_to_linear(avg_amp_db)

        # Normalize linear amplitude to stroke width range
        if max_linear_amp - min_linear_amp > 0:
            normalized_amp = (avg_linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
        else:
            normalized_amp = 0
        stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
        stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width)) # Clamp values

        dwg.add(dwg.line((x1, y1), (x2, y2),
                         stroke=svgwrite.rgb(0, 0, 0, '%'), # Black color
                         stroke_width=stroke_width,
                         fill='none'))

    dwg.save()
