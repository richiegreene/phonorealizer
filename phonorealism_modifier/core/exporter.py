import os
import numpy as np
import pandas as pd
import soundfile as sf
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString
import librosa
import mido

class Exporter:
    def __init__(self, data):
        self.data = data

    def export(self, settings, output_path, wavetable=None):
        if settings['csv']['export']:
            self.export_csv(output_path)

        if settings['wav']['export']:
            self.export_wav(settings['wav'], output_path, wavetable=wavetable)

        if settings['midi']['export']:
            self.export_midi(settings['midi'], output_path)

        if settings['svg_pitch']['export']:
            self.export_svg_pitch(settings['svg_pitch'], output_path)

        if settings['svg_amplitude']['export']:
            self.export_svg_amplitude(settings['svg_amplitude'], output_path)

    def export_csv(self, output_path):
        self.data.export_csv(output_path + '.csv')

    def export_wav(self, wav_settings, output_path, wavetable=None):
        if wav_settings['full']:
            self._synthesize_and_save(self.data.get_harmonics(), output_path + '.wav', halve_frequencies=True, wavetable=wavetable)
        if wav_settings['parts']:
            output_dir = os.path.splitext(output_path)[0] + "_partials"
            os.makedirs(output_dir, exist_ok=True)
            for i, partial in enumerate(self.data.get_harmonics()):
                self._synthesize_and_save([partial], os.path.join(output_dir, f"partial_{i+1}.wav"), halve_frequencies=True, wavetable=wavetable)

    def _synthesize_and_save(self, harmonics, output_path, sr=44100, halve_frequencies=False, wavetable=None):
        if not harmonics:
            return

        duration = self.data.get_duration()
        waveform = np.zeros(int(sr * duration))

        for harmonic in harmonics:
            if not harmonic:
                continue
            time_array, freq_array, amp_array = zip(*harmonic)
            if halve_frequencies:
                freq_array = np.array(freq_array) / 2
            partial_wave = self._generate_partial_waveform(time_array, freq_array, amp_array, sr, duration, wavetable=wavetable)
            waveform[:len(partial_wave)] += partial_wave

        max_abs_amp = np.max(np.abs(waveform))
        if max_abs_amp > 0:
            waveform /= max_abs_amp
        
        sf.write(output_path, waveform, sr)

    def _generate_partial_waveform(self, time_array, freq_array, amp_array, sr, duration, wavetable=None):
        t = np.linspace(0, duration, int(sr * duration))
        
        freq_interp = np.interp(t, time_array, freq_array)
        amp_interp = np.interp(t, time_array, amp_array)

        phase = 2 * np.pi * np.cumsum(freq_interp) / sr
        
        if wavetable is None:
            waveform = self._db_to_linear(amp_interp) * np.sin(phase)
        else:
            wavetable_size = len(wavetable)
            lookup_indices = (phase % (2 * np.pi)) * (wavetable_size / (2 * np.pi))
            waveform = self._db_to_linear(amp_interp) * np.interp(lookup_indices, np.arange(wavetable_size), wavetable)

        return waveform

    def _db_to_linear(self, db):
        return 10 ** (db / 20)

    def export_svg_pitch(self, svg_settings, output_path):
        render_mode = 'line' if svg_settings['line'] else 'amplitude' # Determine render mode

        if svg_settings['full']:
            if svg_settings['lin']:
                self._save_full_svg(self.data.get_harmonics(), output_path + '_log.svg', scale='log', render_mode=render_mode, **svg_settings)
            if svg_settings['log']:
                self._save_full_svg(self.data.get_harmonics(), output_path + '_lin.svg', scale='lin', render_mode=render_mode, **svg_settings)
        if svg_settings['parts']:
            output_dir = os.path.splitext(output_path)[0] + "_pitch_partials"
            os.makedirs(output_dir, exist_ok=True)
            for i, partial in enumerate(self.data.get_harmonics()):
                if svg_settings['lin']:
                    self._save_partial_svg(partial, os.path.join(output_dir, f"partial_{i+1}_lin.svg"), scale='lin', render_mode=render_mode, **svg_settings)
                if svg_settings['log']:
                    self._save_partial_svg(partial, os.path.join(output_dir, f"partial_{i+1}_log.svg"), scale='log', render_mode=render_mode, **svg_settings)

    def export_svg_amplitude(self, svg_settings, output_path):
        import svgwrite

        if svg_settings['full']:
            amplitude_data = self._get_amplitude_data(self.data.get_harmonics())
            self._save_amplitude_svg(amplitude_data, output_path + '_amplitude.svg', **svg_settings)
        if svg_settings['parts']:
            output_dir = os.path.splitext(output_path)[0] + "_amplitude_partials"
            os.makedirs(output_dir, exist_ok=True)
            for i, partial in enumerate(self.data.get_harmonics()):
                amplitude_data = self._get_amplitude_data([partial])
                self._save_amplitude_svg(amplitude_data, os.path.join(output_dir, f"partial_{i+1}_amplitude.svg"), **svg_settings)

    def _get_amplitude_data(self, harmonics, sr=44100, hop_length=512):
        if not harmonics:
            return []

        duration = self.data.get_duration()
        waveform = np.zeros(int(sr * duration))

        for harmonic in harmonics:
            if not harmonic:
                continue
            time_array, freq_array, amp_array = zip(*harmonic)
            partial_wave = self._generate_partial_waveform(time_array, freq_array, amp_array, sr, duration)
            waveform[:len(partial_wave)] += partial_wave

        # Normalize waveform to -1 to 1
        max_abs_amp = np.max(np.abs(waveform))
        if max_abs_amp > 0:
            waveform /= max_abs_amp

        # Calculate RMS for each frame
        rms = librosa.feature.rms(y=waveform, frame_length=2048, hop_length=hop_length)[0] # [0] to get the 1D array
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

        # Normalize RMS to peak of 1.0
        max_rms = np.max(rms)
        if max_rms > 0:
            normalized_rms = rms / max_rms
        else:
            normalized_rms = rms # Avoid division by zero

        return list(zip(times, normalized_rms))

    def _save_amplitude_svg(self, amplitude_data, output_path, width=5000, height=500, max_points=5000, **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, width, height)

        if len(amplitude_data) > max_points:
            indices = np.linspace(0, len(amplitude_data) - 1, max_points, dtype=int)
            amplitude_data = [amplitude_data[i] for i in indices]

        if not amplitude_data:
            dwg.save()
            return

        times, amplitudes = zip(*amplitude_data)

        time_scale = width / (times[-1] if times else 1)
        center_y = height / 2.0

        top_path_coords = []
        bottom_path_coords = []

        for i in range(len(times)):
            x = times[i] * time_scale
            # Scale amplitude to half of height
            scaled_amplitude = amplitudes[i] * (height / 2.0)
            y_top = center_y - scaled_amplitude
            y_bottom = center_y + scaled_amplitude
            top_path_coords.append((x, y_top))
            bottom_path_coords.append((x, y_bottom))

        path_d = f"M {top_path_coords[0][0]},{top_path_coords[0][1]} "
        for p in top_path_coords[1:]:
            path_d += f"L {p[0]},{p[1]} "
        
        path_d += f"L {bottom_path_coords[-1][0]},{bottom_path_coords[-1][1]} "
        for p in reversed(bottom_path_coords[:-1]):
            path_d += f"L {p[0]},{p[1]} "
        path_d += "Z"

        dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()

    def _save_full_svg(self, partials, output_path, sr=44100, scale='log', svg_width=1000, svg_height=500, gain=1.0, render_mode='amplitude', **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)
        time_scale = svg_width / self.data.get_duration()
        freq_scale = svg_height / (sr / 2)
        min_freq_log = np.log10(20)
        max_freq_log = np.log10(sr/2)
        max_stroke_width = 5
        min_stroke_width = 0.1

        for harmonic in partials:
            if not harmonic or len(harmonic) < 2:
                continue

            times, freqs, amps_db = zip(*harmonic)
            points = []
            for i in range(len(times)):
                x = times[i] * time_scale
                if scale == 'log':
                    f = max(freqs[i], 20)
                    y = svg_height - ((np.log10(f) - min_freq_log) / (max_freq_log - min_freq_log)) * svg_height
                else:
                    y = svg_height - (freqs[i] * freq_scale)
                points.append(np.array([x, y]))

            if len(points) < 2:
                continue

            max_amp_db = np.max(amps_db)
            min_amp_db = np.min(amps_db)
            max_linear_amp = self._db_to_linear(max_amp_db)
            min_linear_amp = self._db_to_linear(min_amp_db)
        
            stroke_widths = []
            if render_mode == 'amplitude':
                for amp_db in amps_db:
                    linear_amp = self._db_to_linear(amp_db)
                    if max_linear_amp > min_linear_amp:
                        normalized_amp = (linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
                    else:
                        normalized_amp = 0
                    stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
                    stroke_width *= gain
                    stroke_widths.append(stroke_width)
            else:
                for _ in amps_db:
                    stroke_widths.append(min_stroke_width * gain)

            normals = []
            for i in range(len(points)):
                tangent = np.array([0.0, 0.0])
                if i == 0:
                    tangent = points[1] - points[0]
                elif i == len(points) - 1:
                    tangent = points[i] - points[i-1]
                else:
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
                    if i > 0:
                        tangent = points[i] - points[i-1]
                    else:
                        tangent = points[1] - points[0]
                    norm_tangent = np.linalg.norm(tangent)
                    if norm_tangent < 1e-6:
                        tangent = np.array([1.0, 0.0])

                normal = np.array([-tangent[1], tangent[0]])
                norm_normal = np.linalg.norm(normal)
                if norm_normal > 1e-6:
                    normal /= norm_normal
                else:
                    normal = np.array([0.0, 1.0])
                normals.append(normal)

            top_path = [p + n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]
            bottom_path = [p - n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]

            path_d = f"M {top_path[0][0]},{top_path[0][1]} "
            for p in top_path[1:]:
                path_d += f"L {p[0]},{p[1]} "
            
            path_d += f"L {bottom_path[-1][0]},{bottom_path[-1][1]} "
            for p in reversed(bottom_path[:-1]):
                path_d += f"L {p[0]},{p[1]} "
            path_d += "Z"

            dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()

    def _save_partial_svg(self, harmonic, output_path, sr=44100, scale='log', svg_width=1000, svg_height=500, gain=1.0, render_mode='amplitude', **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)
        time_scale = svg_width / self.data.get_duration()
        freq_scale = svg_height / (sr / 2)
        min_freq_log = np.log10(20)
        max_freq_log = np.log10(sr/2)

        if not harmonic or len(harmonic) < 2:
            dwg.save()
            return

        times, freqs, amps_db = zip(*harmonic)
        points = []
        for i in range(len(times)):
            x = times[i] * time_scale
            if scale == 'log':
                f = max(freqs[i], 20)
                y = svg_height - ((np.log10(f) - min_freq_log) / (max_freq_log - min_freq_log)) * svg_height
            else:
                y = svg_height - (freqs[i] * freq_scale)
            points.append(np.array([x, y]))

        if len(points) < 2:
            dwg.save()
            return

        max_amp_db = np.max(amps_db)
        min_amp_db = np.min(amps_db)
        max_linear_amp = self._db_to_linear(max_amp_db)
        min_linear_amp = self._db_to_linear(min_amp_db)
    
        max_stroke_width = 5
        min_stroke_width = 0.1
        
        stroke_widths = []
        if render_mode == 'amplitude':
            for amp_db in amps_db:
                linear_amp = self._db_to_linear(amp_db)
                if max_linear_amp > min_linear_amp:
                    normalized_amp = (linear_amp - min_linear_amp) / (max_linear_amp - min_linear_amp)
                else:
                    normalized_amp = 0
                stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
                stroke_width *= gain
                stroke_widths.append(stroke_width)
        else:
            for _ in amps_db:
                stroke_widths.append(min_stroke_width * gain)

        normals = []
        for i in range(len(points)):
            tangent = np.array([0.0, 0.0])
            if i == 0:
                tangent = points[1] - points[0]
            elif i == len(points) - 1:
                tangent = points[i] - points[i-1]
            else:
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
                if i > 0:
                    tangent = points[i] - points[i-1]
                else:
                    tangent = points[1] - points[0]
                norm_tangent = np.linalg.norm(tangent)
                if norm_tangent < 1e-6:
                    tangent = np.array([1.0, 0.0])

            normal = np.array([-tangent[1], tangent[0]])
            norm_normal = np.linalg.norm(normal)
            if norm_normal > 1e-6:
                normal /= norm_normal
            else:
                normal = np.array([0.0, 1.0])
            normals.append(normal)

        top_path = [p + n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]
        bottom_path = [p - n * (w / 2.0) for p, n, w in zip(points, normals, stroke_widths)]

        path_d = f"M {top_path[0][0]},{top_path[0][1]} "
        for p in top_path[1:]:
            path_d += f"L {p[0]},{p[1]} "
        
        path_d += f"L {bottom_path[-1][0]},{bottom_path[-1][1]} "
        for p in reversed(bottom_path[:-1]):
            path_d += f"L {p[0]},{p[1]} "
        path_d += "Z"

        dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()

    def export_midi(self, midi_settings, output_path):
        if midi_settings['full']:
            self._save_midi(self.data.get_harmonics(), output_path + '.mid')
        if midi_settings['parts']:
            output_dir = os.path.splitext(output_path)[0] + "_midi_partials"
            os.makedirs(output_dir, exist_ok=True)
            for i, partial in enumerate(self.data.get_harmonics()):
                self._save_midi([partial], os.path.join(output_dir, f"partial_{i+1}.mid"))

    def _freq_to_midi(self, freq):
        if freq <= 0:
            return 0
        return 69 + 12 * np.log2(freq / 440.0)

    def _db_to_velocity(self, db):
        linear = 10 ** (db / 20.0)
        return int(min(max(linear * 127, 0), 127))

    def _calculate_pitch_bend(self, current_freq, base_freq):
        if base_freq == 0 or current_freq == 0:
            return 0
        
        # Calculate the pitch difference in cents
        cents_deviation = 1200 * np.log2(current_freq / base_freq)
        
        # Assuming a pitch bend range of +/- 2 semitones (200 cents)
        # The pitch bend value is a 14-bit integer from -8192 to 8191
        # We map the cents deviation to this range.
        # A deviation of 200 cents maps to 8191.
        pitch_bend_range_cents = 200
        pitch_bend_value = int((cents_deviation / pitch_bend_range_cents) * 8191)
        
        return max(-8192, min(8191, pitch_bend_value))

    def _save_midi(self, harmonics, output_path, ticks_per_beat=480, tempo=120):
        mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat) # Type 1 for multiple tracks

        for harmonic in harmonics:
            if not harmonic:
                continue

            track = mido.MidiTrack()
            mid.tracks.append(track)

            # Set tempo only in the first track
            if len(mid.tracks) == 1:
                microseconds_per_beat = mido.bpm2tempo(tempo)
                track.append(mido.MetaMessage('set_tempo', tempo=microseconds_per_beat))

            last_time_ticks = 0
            active_note = None
            last_velocity = 0

            for i, (time, freq, amp_db) in enumerate(harmonic):
                velocity = self._db_to_velocity(amp_db)
                
                if velocity == 0 and active_note is not None:
                    # Note off
                    current_time_ticks = int(mido.second2tick(time, ticks_per_beat, mido.bpm2tempo(tempo)))
                    delta_ticks = max(0, current_time_ticks - last_time_ticks)
                    track.append(mido.Message('note_off', note=active_note['note'], velocity=0, time=delta_ticks))
                    last_time_ticks = current_time_ticks
                    active_note = None
                    continue

                if velocity > 0 and active_note is None:
                    # Note on
                    base_freq = freq
                    midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                    active_note = {'note': midi_note, 'base_freq': base_freq}
                    
                    current_time_ticks = int(mido.second2tick(time, ticks_per_beat, mido.bpm2tempo(tempo)))
                    delta_ticks = max(0, current_time_ticks - last_time_ticks)
                    track.append(mido.Message('note_on', note=midi_note, velocity=velocity, time=delta_ticks))
                    last_time_ticks = current_time_ticks
                    last_velocity = velocity

                if active_note is not None:
                    # Pitch bend or new note
                    cents_deviation = 1200 * np.log2(freq / active_note['base_freq']) if active_note['base_freq'] > 0 and freq > 0 else 0
                    
                    if abs(cents_deviation) > 100: # More than 100 cents deviation
                        # End previous note
                        current_time_ticks = int(mido.second2tick(time, ticks_per_beat, mido.bpm2tempo(tempo)))
                        delta_ticks = max(0, current_time_ticks - last_time_ticks)
                        track.append(mido.Message('note_off', note=active_note['note'], velocity=0, time=delta_ticks))
                        last_time_ticks = current_time_ticks

                        # Start a new note
                        base_freq = freq
                        midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                        active_note = {'note': midi_note, 'base_freq': base_freq}
                        track.append(mido.Message('note_on', note=midi_note, velocity=velocity, time=0))
                        last_velocity = velocity
                    else:
                        # Pitch bend
                        pitch_bend = self._calculate_pitch_bend(freq, active_note['base_freq'])
                        current_time_ticks = int(mido.second2tick(time, ticks_per_beat, mido.bpm2tempo(tempo)))
                        delta_ticks = max(0, current_time_ticks - last_time_ticks)
                        track.append(mido.Message('pitchwheel', pitch=pitch_bend, time=delta_ticks))
                        last_time_ticks = current_time_ticks

            if active_note is not None:
                # Turn off the last note at the end of the harmonic
                time = harmonic[-1][0]
                current_time_ticks = int(mido.second2tick(time, ticks_per_beat, mido.bpm2tempo(tempo)))
                delta_ticks = max(0, current_time_ticks - last_time_ticks)
                track.append(mido.Message('note_off', note=active_note['note'], velocity=0, time=delta_ticks))
                last_time_ticks = current_time_ticks

        mid.save(output_path)

    def _save_waveform_svg(self, audio_data, output_path, sr=44100, svg_width=1000, svg_height=500, gain=1.0, max_points=5000, **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)

        if len(audio_data) > max_points:
            indices = np.linspace(0, len(audio_data) - 1, max_points, dtype=int)
            audio_data = audio_data[indices]

        num_samples = len(audio_data)
        time_scale = svg_width / num_samples
        
        amps = np.abs(audio_data)
        max_amp = np.max(amps)
        min_amp = np.min(amps)

        max_stroke_width = svg_height / 2.0
        min_stroke_width = 0.1

        scaled_stroke_widths = []
        for amp in amps:
            if max_amp > min_amp:
                normalized_amp = (amp - min_amp) / (max_amp - min_amp)
            else:
                normalized_amp = 0
            stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
            scaled_stroke_widths.append(stroke_width * gain)

        top_path_coords = []
        bottom_path_coords = []
        center_y = svg_height / 2.0

        for i in range(num_samples):
            x = i * time_scale
            half_width = scaled_stroke_widths[i] / 2.0
            y_top = center_y - half_width
            y_bottom = center_y + half_width
            top_path_coords.append((x, y_top))
            bottom_path_coords.append((x, y_bottom))

        path_d = f"M {top_path_coords[0][0]},{top_path_coords[0][1]} "
        for p in top_path_coords[1:]:
            path_d += f"L {p[0]},{p[1]} "
        
        path_d += f"L {bottom_path_coords[-1][0]},{bottom_path_coords[-1][1]} "
        for p in reversed(bottom_path_coords[:-1]):
            path_d += f"L {p[0]},{p[1]} "
        path_d += "Z"

        dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()

    def _save_waveform_svg(self, audio_data, output_path, sr=44100, svg_width=1000, svg_height=500, gain=1.0, max_points=5000, **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)

        if len(audio_data) > max_points:
            indices = np.linspace(0, len(audio_data) - 1, max_points, dtype=int)
            audio_data = audio_data[indices]

        num_samples = len(audio_data)
        time_scale = svg_width / num_samples
        
        amps = np.abs(audio_data)
        max_amp = np.max(amps)
        min_amp = np.min(amps)

        max_stroke_width = svg_height / 2.0
        min_stroke_width = 0.1

        scaled_stroke_widths = []
        for amp in amps:
            if max_amp > min_amp:
                normalized_amp = (amp - min_amp) / (max_amp - min_amp)
            else:
                normalized_amp = 0
            stroke_width = min_stroke_width + normalized_amp * (max_stroke_width - min_stroke_width)
            scaled_stroke_widths.append(stroke_width * gain)

        top_path_coords = []
        bottom_path_coords = []
        center_y = svg_height / 2.0

        for i in range(num_samples):
            x = i * time_scale
            half_width = scaled_stroke_widths[i] / 2.0
            y_top = center_y - half_width
            y_bottom = center_y + half_width
            top_path_coords.append((x, y_top))
            bottom_path_coords.append((x, y_bottom))

        path_d = f"M {top_path_coords[0][0]},{top_path_coords[0][1]} "
        for p in top_path_coords[1:]:
            path_d += f"L {p[0]},{p[1]} "
        
        path_d += f"L {bottom_path_coords[-1][0]},{bottom_path_coords[-1][1]} "
        for p in reversed(bottom_path[:-1]):
            path_d += f"L {p[0]},{p[1]} "
        path_d += "Z"

        dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()
