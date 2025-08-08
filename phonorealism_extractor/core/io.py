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

def save_full_svg(partials, output_path, sr, duration, scale='log'):
    dwg = svgwrite.Drawing(output_path, profile='tiny')

    # Define SVG dimensions and scaling
    svg_width = 1000
    svg_height = 500
    dwg.viewbox(0, 0, svg_width, svg_height)

    # Scaling factors
    time_scale = svg_width / duration
    freq_scale = svg_height / (sr / 2) # Max frequency is Nyquist
    min_freq_log = np.log10(20) # min audible frequency
    max_freq_log = np.log10(sr/2)

    max_stroke_width = 5 # Max line thickness in SVG
    min_stroke_width = 0.1 # Min line thickness in SVG

    for harmonic_index, harmonic in enumerate(partials):
        if not harmonic or len(harmonic) < 2:
            continue

        times, freqs, amps_db = zip(*harmonic)

        # --- Filter out consecutive duplicate points ---
        filtered_points = [harmonic[0]]
        for i in range(1, len(harmonic)):
            # Compare time and frequency, ignoring amplitude for duplication check
            if (harmonic[i][0] != harmonic[i-1][0] or 
                harmonic[i][1] != harmonic[i-1][1]):
                filtered_points.append(harmonic[i])
        
        if len(filtered_points) < 2:
            continue
        times, freqs, amps_db = zip(*filtered_points)
        # --- 1. Calculate centerline coordinates ---
        points = []
        for i in range(len(times)):
            x = times[i] * time_scale
            if scale == 'log':
                f = max(freqs[i], 20)
                y = svg_height - ((np.log10(f) - min_freq_log) / (max_freq_log - min_freq_log)) * svg_height
            else:  # linear
                y = svg_height - (freqs[i] * freq_scale)
            points.append(np.array([x, y]))

        # --- Filter points based on SVG coordinates ---
        filtered_points_coords = [points[0]]
        filtered_amps_db = [amps_db[0]]
        for i in range(1, len(points)):
            if np.linalg.norm(points[i] - points[i-1]) > 1e-6:
                filtered_points_coords.append(points[i])
                filtered_amps_db.append(amps_db[i])

        if len(filtered_points_coords) < 2:
            continue
        points = filtered_points_coords
        amps_db = filtered_amps_db

        # --- 2. Calculate stroke widths from amplitude ---
        max_amp_db = np.max(amps_db)
        min_amp_db = np.min(amps_db)
        max_linear_amp = db_to_linear(max_amp_db)
        min_linear_amp = db_to_linear(min_amp_db)
    
        stroke_widths = []
        for amp_db in amps_db:
            linear_amp = db_to_linear(amp_db)
            if max_linear_amp > min_linear_amp:
                normalized_amp = (linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
            else:
                normalized_amp = 0
            stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
            stroke_widths.append(stroke_width)

        # --- 3. Calculate normals at each point ---
        normals = []
        for i in range(len(points)):
            tangent = np.array([0.0, 0.0])
            if i == 0:
                # First point
                tangent = points[1] - points[0]
            elif i == len(points) - 1:
                # Last point
                tangent = points[i] - points[i-1]
            else:
                # Middle points
                v_in = points[i] - points[i-1]
                v_out = points[i+1] - points[i]
                
                norm_v_in = np.linalg.norm(v_in)
                norm_v_out = np.linalg.norm(v_out)

                if norm_v_in > 1e-6:
                    tangent += v_in / norm_v_in
                if norm_v_out > 1e-6:
                    tangent += v_out / norm_v_out
            
            norm_tangent = np.linalg.norm(tangent)
            if norm_tangent < 1e-6:
                # Tangent is zero, try to use one of the segments
                if i > 0:
                    tangent = points[i] - points[i-1]
                else:
                    tangent = points[1] - points[0]
                
                norm_tangent = np.linalg.norm(tangent)
                if norm_tangent < 1e-6:
                    # Still zero, use a default
                    tangent = np.array([1.0, 0.0])

            normal = np.array([-tangent[1], tangent[0]])
            norm_normal = np.linalg.norm(normal)
            if norm_normal > 1e-6:
                normal /= norm_normal
            else:
                normal = np.array([0.0, 1.0]) # Default up
            normals.append(normal)

        # --- 4. Calculate top and bottom path points ---
        top_path = [p + n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]
        bottom_path = [p - n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]

        # --- 5. Create the SVG path string ---
        path_d = f"M {top_path[0][0]},{top_path[0][1]} "
        for p in top_path[1:]:
            path_d += f"L {p[0]},{p[1]} "
        
        path_d += f"L {bottom_path[-1][0]},{bottom_path[-1][1]} "
        for p in reversed(bottom_path[:-1]):
            path_d += f"L {p[0]},{p[1]} "
        path_d += "Z"

        # --- 6. Add path to drawing ---
        dwg.add(dwg.path(d=path_d,
                         stroke='none',
                         fill=svgwrite.rgb(0, 0, 0, '%')))

    dwg.save()

def save_partial_svg(harmonic, output_path, sr, duration, scale='log'):
    dwg = svgwrite.Drawing(output_path, profile='tiny')

    # Define SVG dimensions and scaling
    svg_width = 1000
    svg_height = 500
    dwg.viewbox(0, 0, svg_width, svg_height)

    # Scaling factors
    time_scale = svg_width / duration
    freq_scale = svg_height / (sr / 2) # Max frequency is Nyquist
    min_freq_log = np.log10(20) # min audible frequency
    max_freq_log = np.log10(sr/2)

    if not harmonic or len(harmonic) < 2:
        dwg.save()
        return

    # --- Filter out consecutive duplicate points ---
    filtered_points = [harmonic[0]]
    for i in range(1, len(harmonic)):
        # Compare time and frequency, ignoring amplitude for duplication check
        if (harmonic[i][0] != harmonic[i-1][0] or 
            harmonic[i][1] != harmonic[i-1][1]):
            filtered_points.append(harmonic[i])
    
    if len(filtered_points) < 2:
        dwg.save()
        return
    times, freqs, amps_db = zip(*filtered_points)
    # --- 1. Calculate centerline coordinates ---
    points = []
    for i in range(len(times)):
        x = times[i] * time_scale
        if scale == 'log':
            f = max(freqs[i], 20)
            y = svg_height - ((np.log10(f) - min_freq_log) / (max_freq_log - min_freq_log)) * svg_height
        else:  # linear
            y = svg_height - (freqs[i] * freq_scale)
        points.append(np.array([x, y]))

    # --- Filter points based on SVG coordinates ---
    filtered_points_coords = [points[0]]
    filtered_amps_db = [amps_db[0]]
    for i in range(1, len(points)):
        if np.linalg.norm(points[i] - points[i-1]) > 1e-6:
            filtered_points_coords.append(points[i])
            filtered_amps_db.append(amps_db[i])

    if len(filtered_points_coords) < 2:
        dwg.save()
        return
    points = filtered_points_coords
    amps_db = filtered_amps_db

    # --- 2. Calculate stroke widths from amplitude ---
    max_amp_db = np.max(amps_db)
    min_amp_db = np.min(amps_db)
    max_linear_amp = db_to_linear(max_amp_db)
    min_linear_amp = db_to_linear(min_amp_db)

    max_stroke_width = 5 # Max line thickness in SVG
    min_stroke_width = 0.1 # Min line thickness in SVG
    
    stroke_widths = []
    for amp_db in amps_db:
        linear_amp = db_to_linear(amp_db)
        if max_linear_amp > min_linear_amp:
            normalized_amp = (linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
        else:
            normalized_amp = 0
        stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
        stroke_widths.append(stroke_width)

    # --- 3. Calculate normals at each point ---
    normals = []
    for i in range(len(points)):
        tangent = np.array([0.0, 0.0])
        if i == 0:
            # First point
            tangent = points[1] - points[0]
        elif i == len(points) - 1:
            # Last point
            tangent = points[i] - points[i-1]
        else:
            # Middle points
            v_in = points[i] - points[i-1]
            v_out = points[i+1] - points[i]
            
            norm_v_in = np.linalg.norm(v_in)
            norm_v_out = np.linalg.norm(v_out)

            if norm_v_in > 1e-6:
                tangent += v_in / norm_v_in
            if norm_v_out > 1e-6:
                tangent += v_out / norm_v_out
        
        norm_tangent = np.linalg.norm(tangent)
        if norm_tangent < 1e-6:
            # Tangent is zero, try to use one of the segments
            if i > 0:
                tangent = points[i] - points[i-1]
            else:
                tangent = points[1] - points[0]
            
            norm_tangent = np.linalg.norm(tangent)
            if norm_tangent < 1e-6:
                # Still zero, use a default
                tangent = np.array([1.0, 0.0])

        normal = np.array([-tangent[1], tangent[0]])
        norm_normal = np.linalg.norm(normal)
        if norm_normal > 1e-6:
            normal /= norm_normal
        else:
            normal = np.array([0.0, 1.0]) # Default up
        normals.append(normal)

    # --- 4. Calculate top and bottom path points ---
    top_path = [p + n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]
    bottom_path = [p - n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]

    # --- 5. Create the SVG path string ---
    path_d = f"M {top_path[0][0]},{top_path[0][1]} "
    for p in top_path[1:]:
        path_d += f"L {p[0]},{p[1]} "
    
    path_d += f"L {bottom_path[-1][0]},{bottom_path[-1][1]} "
    for p in reversed(bottom_path[:-1]):
        path_d += f"L {p[0]},{p[1]} "
    path_d += "Z"

    # --- 6. Add path to drawing ---
    dwg.add(dwg.path(d=path_d,
                     stroke='none',
                     fill=svgwrite.rgb(0, 0, 0, '%')))

    dwg.save()

def save_waveform_svg(audio_data, output_path, sr):
    """
    Saves an audio waveform to an SVG file.

    Args:
        audio_data (np.ndarray): The audio data.
        output_path (str): The path to the output SVG file.
        sr (int): The sample rate.
    """
    dwg = svgwrite.Drawing(output_path, profile='tiny')

    # Define SVG dimensions
    svg_width = 1000
    svg_height = 500
    dwg.viewbox(0, 0, svg_width, svg_height)

    # --- 1. Prepare data for SVG ---
    num_samples = len(audio_data)
    time_scale = svg_width / num_samples
    amp_scale = svg_height / 2.0

    # --- 2. Create the path string ---
    path_d = f"M 0,{svg_height / 2} "
    for i, sample in enumerate(audio_data):
        x = i * time_scale
        y = (svg_height / 2) - (sample * amp_scale)
        path_d += f"L {x},{y} "

    # --- 3. Add path to drawing ---
    dwg.add(dwg.path(d=path_d,
                     stroke=svgwrite.rgb(0, 0, 0, '%'),
                     fill='none',
                     stroke_width=1))

    dwg.save()