import os
import numpy as np
import pandas as pd
import soundfile as sf
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString
import librosa
import mido
import pyqtgraph as pg

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
            
        if settings['tessera']['export']:
            self.export_tessera(output_path)

    def export_csv(self, output_path):
        self.data.export_csv(output_path + '.csv')
    
    def _db_to_tessera_velocity(self, db, min_audible_db=-60.0, min_vel=0.01):
        if db < min_audible_db:
            return 0.0
        # Map dB from min_audible_db to 0dB to a 0-1 linear velocity scale
        # Assuming 0dB is max velocity (1.0)
        # linear scale: (db - min_audible_db) / (0 - min_audible_db)
        vel = (db - min_audible_db) / (0.0 - min_audible_db)
        return max(min_vel, min(vel, 1.0)) # Clip between min_vel and 1.0

    def export_tessera(self, output_path):
        all_harmonics = self.data.get_harmonics()
        if not all_harmonics:
            print("No harmonic data to export to Tessera.")
            return

        notes_lua_table = []
        midi_c4 = 60 # MIDI note number for C4
        min_note_duration = 0.01 # Minimum duration for a note in seconds

        # Iterate through ALL harmonics
        for harmonic_data in all_harmonics:
            if not harmonic_data or len(harmonic_data) < 2: # Need at least two points to form an envelope
                continue

            # First point of the harmonic defines the base time, frequency, and amplitude
            first_time, first_freq, first_amp_db = harmonic_data[0]

            # Convert first frequency to base MIDI note
            midi_base_note = self._freq_to_midi(first_freq)
            
            # Convert base MIDI note to Tessera interval {x, y}
            semitones_from_c4 = round(midi_base_note - midi_c4)
            interval_y = int(semitones_from_c4)
            interval_x = int(-np.floor(semitones_from_c4 / 2.0))

            # Convert base amplitude to Tessera velocity (0.0 to 1.0)
            vel = self._db_to_tessera_velocity(first_amp_db)

            verts_lua_table = []
            
            # Populate verts for pitch and pressure envelopes
            for current_time, current_freq, current_amp_db in harmonic_data:
                relative_time = current_time - first_time
                
                current_midi = self._freq_to_midi(current_freq)
                pitch_offset = current_midi - midi_base_note # Pitch offset in semitones
                
                pressure_value = self._db_to_tessera_velocity(current_amp_db) # Pressure 0-1

                verts_lua_table.append(f"""\
						{{
							{relative_time},
							{pitch_offset},
							{pressure_value},
						}},""")
            
            # Ensure the note has a minimum duration if it's too short
            note_duration = relative_time if harmonic_data else 0.0 # 'relative_time' will be from the last point
            if note_duration < min_note_duration:
                # Add a final vert point to ensure minimum duration if needed
                last_vert = harmonic_data[-1]
                last_relative_time = last_vert[0] - first_time
                if last_relative_time < min_note_duration:
                    pitch_offset_last = self._freq_to_midi(last_vert[1]) - midi_base_note
                    pressure_last = self._db_to_tessera_velocity(last_vert[2])
                    verts_lua_table.append(f"""\
						{{
							{min_note_duration},
							{pitch_offset_last},
							{pressure_last},
						}},""")
            
            note_lua = f"""
				{{
					verts = {{
{os.linesep.join(verts_lua_table)}
					}},
					interval = {{
						{interval_x},
						{interval_y},
					}},
					time = {first_time},
					vel = {vel},
				}},"""
            notes_lua_table.append(note_lua)

        # Basic Lua project structure, similar to tessera_output_test.sav
        # All notes will be added to a single channel named "Simple Poly"
        project_lua_template = """local project = {{
	settings = {{
		follow = true,
		chase = false,
		preview_notes = true,
	}},
	VERSION = {{
		MINOR = 1,
		PATCH = 1,
		MAJOR = 0,
	}},
	channels = {{
		{{
			notes = {{
{notes_content}
			}},
			armed = true,
			effects = {{
			}},
			control = {{
			}},
			solo = false,
			instrument = {{
				state = {{
					1.5354823,
					639.3616,
					250,
				}},
				name = "polysine",
				mute = false,
				display_name = "Simple Poly",
			}},
			visible = true,
			mute = false,
			lock = false,
			name = "Simple Poly",
			gain = 1,
			hue = 89.422045,
		}},
	}},
	name = "Phonorealism Export",
	transport = {{
		start_time = 0.0,
		recording = false,
	}},
}}
return project"""

        full_lua_content = project_lua_template.format(notes_content="\n".join(notes_lua_table))
        
        output_filepath = output_path + '.sav'
        with open(output_filepath, 'w') as f:
            f.write(full_lua_content)
        print(f"Tessera file exported to {output_filepath}")

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

    def _hz_to_cents(self, freq, reference_freq=440.0):
        """Converts frequency (Hz) to cents relative to a reference frequency."""
        if freq <= 0:
            return -np.inf # Or some other suitable value for invalid frequencies
        return 1200 * np.log2(freq / reference_freq)

    def _cents_to_hz(self, cents, reference_freq=440.0):
        """Converts cents to frequency (Hz) relative to a reference frequency."""
        return reference_freq * (2 ** (cents / 1200.0))

    def _freq_to_note_name(self, freq, reference_freq=440.0):
        """Converts frequency (Hz) to a musical note name (e.g., C4, A#3)."""
        if freq <= 0:
            return ""

        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        
        # Calculate the number of semitones from A4 (440 Hz)
        semitones = 12 * np.log2(freq / reference_freq)
        
        # A4 is MIDI note 69.
        midi_note = int(round(semitones)) + 69
        
        # Calculate octave and note index
        octave = (midi_note // 12) - 1 # MIDI C0 is octave -1 in some systems, C4 is 60, A4 is 69
        note_index = midi_note % 12
        
        return f"{note_names[note_index]}{octave}"

    def _get_note_names(self, min_freq, max_freq, reference_freq=440.0):
        """Generates a list of note frequencies and their names within a given range."""
        notes = []
        midi_min = int(np.floor(12 * np.log2(min_freq / reference_freq) + 69)) if min_freq > 0 else 0
        midi_max = int(np.ceil(12 * np.log2(max_freq / reference_freq) + 69)) if max_freq > 0 else 127

        for midi_note in range(midi_min, midi_max + 1):
            freq = reference_freq * (2 ** ((midi_note - 69) / 12.0))
            # Ensure frequency is within a reasonable range (e.g., human hearing)
            if 20 <= freq <= 20000:
                 notes.append((freq, self._freq_to_note_name(freq, reference_freq)))
        
        # Sort by frequency to ensure correct order
        notes.sort(key=lambda x: x[0])
        return notes

    def export_svg_pitch(self, svg_settings, output_path):
        render_mode = 'line' if svg_settings['line'] else 'amplitude' # Determine render mode
        
        # Create a copy of svg_settings to avoid modifying the original dictionary
        # and remove 'colormap' key to prevent it from being passed twice via **svg_settings
        kwargs_settings = svg_settings.copy()
        colormap_enabled = kwargs_settings.pop('colormap', False)
        colormap_name = kwargs_settings.pop('colormap_name', 'viridis')
        background_grid_enabled = kwargs_settings.pop('background_grid', False)
        line_width = kwargs_settings.pop('line_width', 1.0) # New parameter for line width
        
        if svg_settings['full']:
            if svg_settings['lin']:
                self._save_full_svg(self.data.get_harmonics(), output_path + '_log.svg', scale='log', render_mode=render_mode, colormap=colormap_enabled, colormap_name=colormap_name, background_grid=background_grid_enabled, line_width=line_width, **kwargs_settings)
            if svg_settings['log']:
                self._save_full_svg(self.data.get_harmonics(), output_path + '_lin.svg', scale='lin', render_mode=render_mode, colormap=colormap_enabled, colormap_name=colormap_name, background_grid=background_grid_enabled, line_width=line_width, **kwargs_settings)
        if svg_settings['parts']:
            output_dir = os.path.splitext(output_path)[0] + "_pitch_partials"
            os.makedirs(output_dir, exist_ok=True)
            for i, partial in enumerate(self.data.get_harmonics()):
                if svg_settings['lin']:
                    self._save_partial_svg(partial, os.path.join(output_dir, f"partial_{i+1}_lin.svg"), scale='lin', render_mode=render_mode, colormap=colormap_enabled, colormap_name=colormap_name, background_grid=background_grid_enabled, line_width=line_width, **kwargs_settings)
                if svg_settings['log']:
                    self._save_partial_svg(partial, os.path.join(output_dir, f"partial_{i+1}_log.svg"), scale='log', render_mode=render_mode, colormap=colormap_enabled, colormap_name=colormap_name, background_grid=background_grid_enabled, line_width=line_width, **kwargs_settings)

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

    def _save_full_svg(self, partials, output_path, sr=44100, scale='log', svg_width=1000, svg_height=500, gain=1.0, render_mode='amplitude', colormap=False, colormap_name='viridis', background_grid=False, line_width=1.0, **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)

        # Initialize these based on overall data if background_grid is true, otherwise use previous logic
        current_time_scale = svg_width / self.data.get_duration()
        current_freq_scale = svg_height / (sr / 2) # Only for linear scale
        
        # These are used consistently regardless of grid for actual harmonic plotting
        min_freq_log_plot = np.log10(20)
        max_freq_log_plot = np.log10(sr/2)

        if background_grid:
            all_times = []
            all_freqs = []
            for harmonic_group in partials: # Renamed variable to avoid conflict with method parameter
                if harmonic_group:
                    times, freqs, _ = zip(*harmonic_group)
                    all_times.extend(times)
                    all_freqs.extend(freqs)
            
            if not all_times or not all_freqs: # No data to draw grid for, but still want to create an empty SVG
                dwg.save()
                return

            min_data_time = min(all_times)
            max_data_time = max(all_times)
            min_data_freq = min(f for f in all_freqs if f > 0) # Ensure positive frequency
            max_data_freq = max(all_freqs)

            # Add padding to data ranges
            time_padding = (max_data_time - min_data_time) * 0.05 if (max_data_time - min_data_time) > 0 else 0.5
            min_time_padded = max(0.0, min_data_time - time_padding)
            max_time_padded = max_data_time + time_padding

            # Frequency padding for linear mode (in Hz)
            freq_padding_lin = (max_data_freq - min_data_freq) * 0.05 if (max_data_freq - min_data_freq) > 0 else min_data_freq * 0.1
            min_freq_lin_padded = max(20.0, min_data_freq - freq_padding_lin)
            max_freq_lin_padded = max_data_freq + freq_padding_lin
            
            # Recalculate time_scale based on padded range for grid drawing
            current_time_scale = svg_width / (max_time_padded - min_time_padded) if (max_time_padded - min_time_padded) > 0 else svg_width
            # Calculate x_offset to shift the data to fit the padded range within the SVG width
            x_offset_for_grid = -min_time_padded * current_time_scale

            # Determine the y-coordinate of the topmost horizontal grid line
            topmost_grid_y = svg_height # Default to bottom of SVG (or height of SVG)

            if scale == 'log':
                f_mapped_top = max(max_data_freq, 20)
                # Calculate the y_pos for the maximum data frequency, which will be the highest point on the grid.
                # Note: `y` increases downwards, so a higher frequency (smaller y_pos) is "topmost".
                calculated_top_y = svg_height - ((np.log10(f_mapped_top) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                topmost_grid_y = max(0, calculated_top_y) # Ensure it's not above the SVG bounds
            else: # Linear Hz mode
                # For linear scale, topmost grid line corresponds to max_freq_lin_padded
                # y_pos for max_freq_lin_padded, accounting for y_offset_for_grid
                calculated_top_y = svg_height - (max_freq_lin_padded * current_freq_scale + y_offset_for_grid)
                topmost_grid_y = max(0, calculated_top_y) # Ensure it's not above the SVG bounds
            
            # --- Draw Time Grid ---
            time_major_interval = 1.0 # 1 second
            
            current_time_tick = np.floor(min_time_padded / time_major_interval) * time_major_interval
            while current_time_tick <= max_time_padded:
                x_pos = current_time_tick * current_time_scale + x_offset_for_grid
                if 0 <= x_pos <= svg_width:
                    dwg.add(dwg.line((x_pos, topmost_grid_y), (x_pos, svg_height), stroke='grey', stroke_width=0.5, opacity=0.7))
                    dwg.add(dwg.text(f"{current_time_tick:.0f}s", insert=(x_pos + 3, svg_height - 5), fill='grey', font_size='2pt', text_anchor='start'))
                
                current_time_tick += time_major_interval

            # --- Draw Frequency Grid ---
            if scale == 'log': # Cents mode
                reference_freq_for_cents = 440.0
                cents_padding = 100.0 # Pad by 100 cents (semitone) on each side

                min_cents_data = self._hz_to_cents(min_data_freq, reference_freq_for_cents)
                max_cents_data = self._hz_to_cents(max_data_freq, reference_freq_for_cents)

                min_cents_padded = min_cents_data - cents_padding
                max_cents_padded = max_cents_data + cents_padding

                # Use min_freq_log_plot and max_freq_log_plot for vertical mapping
                # These define the total frequency range mapped to svg_height
                
                # Generate note names for major frequency ticks
                note_frequencies = self._get_note_names(
                    self._cents_to_hz(min_cents_padded, reference_freq_for_cents),
                    self._cents_to_hz(max_cents_padded, reference_freq_for_cents),
                    reference_freq_for_cents
                )
                
                for freq, note_name in note_frequencies:
                    f_mapped = max(freq, 20)
                    y_pos = svg_height - ((np.log10(f_mapped) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                    
                    if 0 <= y_pos <= svg_height:
                        dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='grey', stroke_width=0.5, opacity=0.7))
                        dwg.add(dwg.text(note_name, insert=(3, y_pos - 3), fill='grey', font_size='2pt', text_anchor='start'))

                # Minor ticks: 100 cents (semitones)
                current_cents = np.floor(min_cents_padded / 100.0) * 100.0
                while current_cents <= max_cents_padded:
                    freq = self._cents_to_hz(current_cents, reference_freq_for_cents)
                    is_major_note = False
                    for nf, _ in note_frequencies:
                        if np.isclose(freq, nf, atol=0.1):
                            is_major_note = True
                            break
                    
                    if not is_major_note and 20 <= freq <= 20000:
                        f_mapped = max(freq, 20)
                        y_pos = svg_height - ((np.log10(f_mapped) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                        if 0 <= y_pos <= svg_height:
                            dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='lightgrey', stroke_width=0.2, opacity=0.5))
                            dwg.add(dwg.text(f"{int(current_cents)}", insert=(svg_width - 3, y_pos - 3), fill='lightgrey', font_size='1.5pt', text_anchor='end'))

                    current_cents += 100.0
                # Restore original time_scale for harmonic plotting
                time_scale = svg_width / self.data.get_duration()
            else: # Linear Hz mode
                # Recalculate freq_scale_lin_effective based on padded range for grid drawing
                current_freq_scale = svg_height / (max_freq_lin_padded - min_freq_lin_padded) if (max_freq_lin_padded - min_freq_lin_padded) > 0 else svg_height
                y_offset_for_grid = -min_freq_lin_padded * current_freq_scale
                
                freq_major_interval = 100.0 # 100 Hz
                freq_minor_interval = 10.0 # 10 Hz

                current_freq_tick = np.floor(min_freq_lin_padded / freq_major_interval) * freq_major_interval
                while current_freq_tick <= max_freq_lin_padded:
                    y_pos = svg_height - (current_freq_tick * current_freq_scale + y_offset_for_grid)
                    if 0 <= y_pos <= svg_height:
                        dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='grey', stroke_width=0.5, opacity=0.7))
                        dwg.add(dwg.text(f"{current_freq_tick:.0f}Hz", insert=(3, y_pos - 3), fill='grey', font_size='2pt', text_anchor='start'))

                    minor_freq = current_freq_tick + freq_minor_interval
                    while minor_freq < current_freq_tick + freq_major_interval and minor_freq <= max_freq_lin_padded:
                        y_minor_pos = svg_height - (minor_freq * current_freq_scale + y_offset_for_grid)
                        if 0 <= y_minor_pos <= svg_height:
                            dwg.add(dwg.line((0, y_minor_pos), (svg_width, y_minor_pos), stroke='lightgrey', stroke_width=0.2, opacity=0.5))
                        minor_freq += freq_minor_interval
                    current_freq_tick += freq_major_interval
            
            # These variables need to be reset to the original interpretation for harmonic plotting
            # if background_grid was active, because the current_time_scale and current_freq_scale were adjusted for grid.
            time_scale = svg_width / self.data.get_duration()
            freq_scale = svg_height / (sr / 2) # Used for linear frequency mapping of harmonics
            min_freq_log = np.log10(20) # Used for log frequency mapping of harmonics
            max_freq_log = np.log10(sr/2) # Used for log frequency mapping of harmonics
        else: # background_grid is False, use original mapping
            time_scale = svg_width / self.data.get_duration()
            freq_scale = svg_height / (sr / 2)
            min_freq_log = np.log10(20)
            max_freq_log = np.log10(sr/2)

        amplitude_render_max_stroke_width = 5
        amplitude_render_min_stroke_width = 0.1

        cmap = None
        if colormap:
            if colormap_name == 'Greys (hueless)':
                # Create a simple grayscale colormap (black to white)
                # Map 0 (min amplitude) to black (0,0,0) and 1 (max amplitude) to white (255,255,255)
                # This needs to be a function that returns a QColor for a given normalized value
                class GreysColormap:
                    def map(self, val, mode):
                        gray_val = int(val * 255)
                        return pg.mkColor((gray_val, gray_val, gray_val))
                cmap = GreysColormap()
            elif colormap_name == 'Greys (hueless, inverted)':
                # Create an inverted grayscale colormap (white to black)
                # Map 0 (min amplitude) to white (255,255,255) and 1 (max amplitude) to black (0,0,0)
                class InvertedGreysColormap:
                    def map(self, val, mode):
                        # Apply a power function to make it ramp quicker to black (gamma correction)
                        # val is typically from 0 (min amplitude) to 1 (max amplitude)
                        # We want 0 to be white, and 1 to be black.
                        # (1 - val) gives us 1 for min amplitude, 0 for max amplitude.
                        # Raising (1 - val) to a power > 1 will make it decrease faster (darken quicker)
                        # Let's try a power of 2.0
                        adjusted_val = (1 - val)**1.0
                        gray_val = int(adjusted_val * 75) # Scale to a lighter gray instead of pure white
                        return pg.mkColor((gray_val, gray_val, gray_val))
                cmap = InvertedGreysColormap()
            else:
                cmap = pg.colormap.get(colormap_name)

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
            
            # Use all amplitudes from the current harmonic for normalization
            amps_linear = self._db_to_linear(np.array(amps_db))
            max_linear_amp_segment = np.max(amps_linear)
            min_linear_amp_segment = np.min(amps_linear)
            
            stroke_widths = []
            normalized_amps_for_color = [] # Store normalized amplitudes for color mapping

            if render_mode == 'amplitude':
                for amp_linear in amps_linear:
                    if max_linear_amp_segment > min_linear_amp_segment:
                        normalized_amp = (amp_linear - min_linear_amp_segment) / (max_linear_amp_segment - min_linear_amp_segment)
                    else:
                        normalized_amp = 0
                    stroke_width = amplitude_render_min_stroke_width + normalized_amp * (amplitude_render_max_stroke_width - amplitude_render_min_stroke_width)
                    stroke_width *= gain
                    stroke_widths.append(stroke_width)
                    normalized_amps_for_color.append(normalized_amp) # Use for color mapping
            else: # render_mode == 'line'
                # If colormap is enabled, the user's requested line_width should determine the polygon thickness.
                # Otherwise (no colormap, just a plain line), use a default thin line.
                for amp_linear in amps_linear:
                    if colormap:
                        stroke_widths.append(line_width * gain) 
                    else:
                        stroke_widths.append(amplitude_render_min_stroke_width * gain) # Default thin line

                    if max_linear_amp_segment > min_linear_amp_segment:
                        normalized_amp = (amp_linear - min_linear_amp_segment) / (max_linear_amp_segment - min_linear_amp_segment)
                    else:
                        normalized_amp = 0
                    normalized_amps_for_color.append(normalized_amp) # Use for color mapping

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
            
            top_path = []
            bottom_path = []
            
            # Interpolate normalized_amps_for_color to match resolution of points
            # Ensure normalized_amps_for_color is not empty
            if not normalized_amps_for_color:
                normalized_amps_for_color = [0] * len(points)
            elif len(normalized_amps_for_color) != len(points):
                # If lengths don't match (e.g., due to max_points), interpolate
                x_orig = np.linspace(0, 1, len(normalized_amps_for_color))
                x_new = np.linspace(0, 1, len(points))
                normalized_amps_for_color = np.interp(x_new, x_orig, normalized_amps_for_color)


            for j in range(len(points)):
                top_path.append(points[j] + normals[j] * (stroke_widths[j] / 2.0))
                bottom_path.append(points[j] - normals[j] * (stroke_widths[j] / 2.0))

            if colormap:
                # Draw as a series of colored polygons
                for j in range(len(points) - 1):
                    # Average amplitude for this segment
                    avg_normalized_amp = (normalized_amps_for_color[j] + normalized_amps_for_color[j+1]) / 2
                    color_q = cmap.map(avg_normalized_amp, mode='qcolor')
                    fill_color = svgwrite.rgb(color_q.red(), color_q.green(), color_q.blue(), '%')

                    # Create a polygon for each segment
                    segment_points = [
                        top_path[j], top_path[j+1],
                        bottom_path[j+1], bottom_path[j]
                    ]
                    dwg.add(dwg.polygon(points=segment_points, stroke='none', fill=fill_color))
            else:
                # Original behavior: single path with black fill
                path_d = f"M {top_path[0][0]},{top_path[0][1]} "
                for p in top_path[1:]:
                    path_d += f"L {p[0]},{p[1]} "
                
                path_d += f"L {bottom_path[-1][0]},{bottom_path[-1][1]} "
                for p in reversed(bottom_path[:-1]):
                    path_d += f"L {p[0]},{p[1]} "
                path_d += "Z"
                dwg.add(dwg.path(d=path_d, stroke='none', fill=svgwrite.rgb(0, 0, 0, '%')))

        dwg.save()

    def _save_partial_svg(self, harmonic, output_path, sr=44100, scale='log', svg_width=1000, svg_height=500, gain=1.0, render_mode='amplitude', colormap=False, colormap_name='viridis', background_grid=False, line_width=1.0, **kwargs):
        import svgwrite
        dwg = svgwrite.Drawing(output_path, profile='tiny')
        dwg.viewbox(0, 0, svg_width, svg_height)

        # Initialize these based on overall data if background_grid is true, otherwise use previous logic
        current_time_scale = svg_width / self.data.get_duration()
        current_freq_scale = svg_height / (sr / 2) # Only for linear scale
        
        # These are used consistently regardless of grid for actual harmonic plotting
        min_freq_log_plot = np.log10(20)
        max_freq_log_plot = np.log10(sr/2)

        if background_grid:
            all_times = []
            all_freqs = []
            if harmonic: # harmonic is already a single list of tuples
                times, freqs, _ = zip(*harmonic)
                all_times.extend(times)
                all_freqs.extend(freqs)
            
            if not all_times or not all_freqs: # No data to draw grid for, but still want to create an empty SVG
                dwg.save()
                return

            min_data_time = min(all_times)
            max_data_time = max(all_times)
            min_data_freq = min(f for f in all_freqs if f > 0) # Ensure positive frequency
            max_data_freq = max(all_freqs)

            # Add padding to data ranges
            time_padding = (max_data_time - min_data_time) * 0.05 if (max_data_time - min_data_time) > 0 else 0.5
            min_time_padded = max(0.0, min_data_time - time_padding)
            max_time_padded = max_data_time + time_padding

            # Frequency padding for linear mode (in Hz)
            freq_padding_lin = (max_data_freq - min_data_freq) * 0.05 if (max_data_freq - min_data_freq) > 0 else min_data_freq * 0.1
            min_freq_lin_padded = max(20.0, min_data_freq - freq_padding_lin)
            max_freq_lin_padded = max_data_freq + freq_padding_lin
            
            # Recalculate time_scale based on padded range for grid drawing
            current_time_scale = svg_width / (max_time_padded - min_time_padded) if (max_time_padded - min_time_padded) > 0 else svg_width
            # Calculate x_offset to shift the data to fit the padded range within the SVG width
            x_offset_for_grid = -min_time_padded * current_time_scale

            # Determine the y-coordinate of the topmost horizontal grid line
            topmost_grid_y = svg_height # Default to bottom of SVG (or height of SVG)

            if scale == 'log':
                f_mapped_top = max(max_data_freq, 20)
                # Calculate the y_pos for the maximum data frequency, which will be the highest point on the grid.
                # Note: `y` increases downwards, so a higher frequency (smaller y_pos) is "topmost".
                calculated_top_y = svg_height - ((np.log10(f_mapped_top) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                topmost_grid_y = max(0, calculated_top_y) # Ensure it's not above the SVG bounds
            else: # Linear Hz mode
                # For linear scale, topmost grid line corresponds to max_freq_lin_padded
                # y_pos for max_freq_lin_padded, accounting for y_offset_for_grid
                calculated_top_y = svg_height - (max_freq_lin_padded * current_freq_scale + y_offset_for_grid)
                topmost_grid_y = max(0, calculated_top_y) # Ensure it's not above the SVG bounds
            
            # --- Draw Time Grid ---
            time_major_interval = 1.0 # 1 second
            
            current_time_tick = np.floor(min_time_padded / time_major_interval) * time_major_interval
            while current_time_tick <= max_time_padded:
                x_pos = current_time_tick * current_time_scale + x_offset_for_grid
                if 0 <= x_pos <= svg_width:
                    dwg.add(dwg.line((x_pos, topmost_grid_y), (x_pos, svg_height), stroke='grey', stroke_width=0.5, opacity=0.7))
                    dwg.add(dwg.text(f"{current_time_tick:.0f}s", insert=(x_pos + 3, svg_height - 5), fill='grey', font_size='2pt', text_anchor='start'))
                
                current_time_tick += time_major_interval

            # --- Draw Frequency Grid ---
            if scale == 'log': # Cents mode
                reference_freq_for_cents = 440.0
                cents_padding = 100.0 # Pad by 100 cents (semitone) on each side

                min_cents_data = self._hz_to_cents(min_data_freq, reference_freq_for_cents)
                max_cents_data = self._hz_to_cents(max_data_freq, reference_freq_for_cents)

                min_cents_padded = min_cents_data - cents_padding
                max_cents_padded = max_cents_data + cents_padding

                # Use min_freq_log_plot and max_freq_log_plot for vertical mapping
                # These define the total frequency range mapped to svg_height
                
                # Generate note names for major frequency ticks
                note_frequencies = self._get_note_names(
                    self._cents_to_hz(min_cents_padded, reference_freq_for_cents),
                    self._cents_to_hz(max_cents_padded, reference_freq_for_cents),
                    reference_freq_for_cents
                )
                
                for freq, note_name in note_frequencies:
                    f_mapped = max(freq, 20)
                    y_pos = svg_height - ((np.log10(f_mapped) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                    
                    if 0 <= y_pos <= svg_height:
                        dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='grey', stroke_width=0.5, opacity=0.7))
                        dwg.add(dwg.text(note_name, insert=(3, y_pos - 3), fill='grey', font_size='2pt', text_anchor='start'))

                # Minor ticks: 100 cents (semitones)
                current_cents = np.floor(min_cents_padded / 100.0) * 100.0
                while current_cents <= max_cents_padded:
                    freq = self._cents_to_hz(current_cents, reference_freq_for_cents)
                    is_major_note = False
                    for nf, _ in note_frequencies:
                        if np.isclose(freq, nf, atol=0.1):
                            is_major_note = True
                            break
                    
                    if not is_major_note and 20 <= freq <= 20000:
                        f_mapped = max(freq, 20)
                        y_pos = svg_height - ((np.log10(f_mapped) - min_freq_log_plot) / (max_freq_log_plot - min_freq_log_plot)) * svg_height
                        if 0 <= y_pos <= svg_height:
                            dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='lightgrey', stroke_width=0.2, opacity=0.5))
                            dwg.add(dwg.text(f"{int(current_cents)}", insert=(svg_width - 3, y_pos - 3), fill='lightgrey', font_size='1.5pt', text_anchor='end'))

                    current_cents += 100.0
                # Restore original time_scale for harmonic plotting
                time_scale = svg_width / self.data.get_duration()
            else: # Linear Hz mode
                # Recalculate freq_scale_lin_effective based on padded range for grid drawing
                current_freq_scale = svg_height / (max_freq_lin_padded - min_freq_lin_padded) if (max_freq_lin_padded - min_freq_lin_padded) > 0 else svg_height
                y_offset_for_grid = -min_freq_lin_padded * current_freq_scale
                
                freq_major_interval = 100.0 # 100 Hz
                freq_minor_interval = 10.0 # 10 Hz

                current_freq_tick = np.floor(min_freq_lin_padded / freq_major_interval) * freq_major_interval
                while current_freq_tick <= max_freq_lin_padded:
                    y_pos = svg_height - (current_freq_tick * current_freq_scale + y_offset_for_grid)
                    if 0 <= y_pos <= svg_height:
                        dwg.add(dwg.line((0, y_pos), (svg_width, y_pos), stroke='grey', stroke_width=0.5, opacity=0.7))
                        dwg.add(dwg.text(f"{current_freq_tick:.0f}Hz", insert=(3, y_pos - 3), fill='grey', font_size='2pt', text_anchor='start'))

                    minor_freq = current_freq_tick + freq_minor_interval
                    while minor_freq < current_freq_tick + freq_major_interval and minor_freq <= max_freq_lin_padded:
                        y_minor_pos = svg_height - (minor_freq * current_freq_scale + y_offset_for_grid)
                        if 0 <= y_minor_pos <= svg_height:
                            dwg.add(dwg.line((0, y_minor_pos), (svg_width, y_minor_pos), stroke='lightgrey', stroke_width=0.2, opacity=0.5))
                        minor_freq += freq_minor_interval
                    current_freq_tick += freq_major_interval
            
            # These variables need to be reset to the original interpretation for harmonic plotting
            # if background_grid was active, because the current_time_scale and current_freq_scale were adjusted for grid.
            time_scale = svg_width / self.data.get_duration()
            freq_scale = svg_height / (sr / 2) # Used for linear frequency mapping of harmonics
            min_freq_log = np.log10(20) # Used for log frequency mapping of harmonics
            max_freq_log = np.log10(sr/2) # Used for log frequency mapping of harmonics
        else: # background_grid is False, use original mapping
            time_scale = svg_width / self.data.get_duration()
            freq_scale = svg_height / (sr / 2)
            min_freq_log = np.log10(20)
            max_freq_log = np.log10(sr/2)

        amplitude_render_max_stroke_width = 5
        amplitude_render_min_stroke_width = 0.1

        if not harmonic or len(harmonic) < 2:
            dwg.save()
            return

        amplitude_render_max_stroke_width = 5
        amplitude_render_min_stroke_width = 0.1

        cmap = None
        if colormap:
            if colormap_name == 'Greys (hueless)':
                # Create a simple grayscale colormap (black to white)
                class GreysColormap:
                    def map(self, val, mode):
                        gray_val = int(val * 255)
                        return pg.mkColor((gray_val, gray_val, gray_val))
                cmap = GreysColormap()
            elif colormap_name == 'Greys (hueless, inverted)':
                # Create an inverted grayscale colormap (white to black)
                class InvertedGreysColormap:
                    def map(self, val, mode):
                        # Apply a power function to make it ramp quicker to black (gamma correction)
                        # val is typically from 0 (min amplitude) to 1 (max amplitude)
                        # We want 0 to be white, and 1 to be black.
                        # (1 - val) gives us 1 for min amplitude, 0 for max amplitude.
                        # Raising (1 - val) to a power > 1 will make it decrease faster (darken quicker)
                        # Let's try a power of 2.0
                        adjusted_val = (1 - val)**1.0
                        gray_val = int(adjusted_val * 75) # Scale to a lighter gray instead of pure white
                        return pg.mkColor((gray_val, gray_val, gray_val))
                cmap = InvertedGreysColormap()
            else:
                cmap = pg.colormap.get(colormap_name)

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
        
        # Use all amplitudes from the current harmonic for normalization
        amps_linear = self._db_to_linear(np.array(amps_db))
        max_linear_amp_segment = np.max(amps_linear)
        min_linear_amp_segment = np.min(amps_linear)
    
        stroke_widths = []
        normalized_amps_for_color = [] # Store normalized amplitudes for color mapping
        
        if render_mode == 'amplitude':
            for amp_linear in amps_linear:
                if max_linear_amp_segment > min_linear_amp_segment:
                    normalized_amp = (amp_linear - min_linear_amp_segment) / (max_linear_amp_segment - min_linear_amp_segment)
                else:
                    normalized_amp = 0
                stroke_width = amplitude_render_min_stroke_width + normalized_amp * (amplitude_render_max_stroke_width - amplitude_render_min_stroke_width)
                stroke_width *= gain
                stroke_widths.append(stroke_width)
                normalized_amps_for_color.append(normalized_amp) # Use for color mapping
        else: # render_mode == 'line'
            # If colormap is enabled, the user's requested line_width should determine the polygon thickness.
            # Otherwise (no colormap, just a plain line), use a default thin line.
            for amp_linear in amps_linear:
                if colormap:
                    stroke_widths.append(line_width * gain) 
                else:
                    stroke_widths.append(amplitude_render_min_stroke_width * gain) # Default thin line

                if max_linear_amp_segment > min_linear_amp_segment:
                    normalized_amp = (amp_linear - min_linear_amp_segment) / (max_linear_amp_segment - min_linear_amp_segment)
                else:
                    normalized_amp = 0
                normalized_amps_for_color.append(normalized_amp) # Use for color mapping

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

        top_path = []
        bottom_path = []
        
        # Interpolate normalized_amps_for_color to match resolution of points
        if not normalized_amps_for_color:
            normalized_amps_for_color = [0] * len(points)
        elif len(normalized_amps_for_color) != len(points):
            x_orig = np.linspace(0, 1, len(normalized_amps_for_color))
            x_new = np.linspace(0, 1, len(points))
            normalized_amps_for_color = np.interp(x_new, x_orig, normalized_amps_for_color)

        for j in range(len(points)):
            top_path.append(points[j] + normals[j] * (stroke_widths[j] / 2.0))
            bottom_path.append(points[j] - normals[j] * (stroke_widths[j] / 2.0))

        if colormap:
            # Draw as a series of colored polygons
            for j in range(len(points) - 1):
                # Average amplitude for this segment
                avg_normalized_amp = (normalized_amps_for_color[j] + normalized_amps_for_color[j+1]) / 2
                color_q = cmap.map(avg_normalized_amp, mode='qcolor')
                fill_color = svgwrite.rgb(color_q.red(), color_q.green(), color_q.blue(), '%')

                # Create a polygon for each segment
                segment_points = [
                    top_path[j], top_path[j+1],
                    bottom_path[j+1], bottom_path[j]
                ]
                dwg.add(dwg.polygon(points=segment_points, stroke='none', fill=fill_color))
        else:
            # Original behavior: single path with black fill
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
        if midi_settings['compile'] and midi_settings['full']:
            self._export_compiled_mpe_midi_files(self.data.get_harmonics(), output_path)
        else:
            if midi_settings['full']:
                self._save_midi(self.data.get_harmonics(), output_path + '.mid', compile_mpe=False)
            if midi_settings['parts']:
                output_dir = os.path.splitext(output_path)[0] + "_midi_partials"
                os.makedirs(output_dir, exist_ok=True)
                for i, partial in enumerate(self.data.get_harmonics()):
                    self._save_midi([partial], os.path.join(output_dir, f"partial_{i+1}.mid"), compile_mpe=False)

    def _export_compiled_mpe_midi_files(self, all_harmonics, base_output_path, max_voices_per_file=8):
        if not all_harmonics:
            return

        total_harmonics = len(all_harmonics)
        base_name, ext = os.path.splitext(base_output_path)
        
        # Split all_harmonics into chunks, ensuring "bottom to top" prioritization
        # This implicitly groups harmonics 0-14 into file 1, 15-29 into file 2, etc.
        for i in range(0, total_harmonics, max_voices_per_file):
            harmonic_chunk = all_harmonics[i : i + max_voices_per_file]
            
            # Generate a unique filename for each compiled MIDI file
            file_suffix = f"_compiled_{i // max_voices_per_file + 1:02d}.mid"
            output_file_path = base_name + file_suffix

            # Ensure the output directory exists
            output_dir = os.path.dirname(output_file_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            self._save_midi(harmonic_chunk, output_file_path, compile_mpe=True, max_channels_mpe=max_voices_per_file)


    def _freq_to_midi(self, freq):
        if freq <= 0:
            return 0
        return 69 + 12 * np.log2(freq / 440.0)

    def _db_to_velocity(self, db, min_audible_db=-60.0, min_midi_velocity=1):
        if db < min_audible_db:
            return 0
        linear = 10 ** (db / 20.0)
        # Ensure minimum velocity is applied if linear is above 0, and clip to 127
        return int(min(max(linear * 127, min_midi_velocity), 127))

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

    def _save_midi(self, harmonics, output_path, ticks_per_beat=480, tempo=120, compile_mpe=False, max_channels_mpe=15):
        mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
        microseconds_per_beat = mido.bpm2tempo(tempo)

        if compile_mpe:
            main_track = mido.MidiTrack()
            mid.tracks.append(main_track)
            
            # Set tempo only once in the main track
            main_track.append(mido.MetaMessage('set_tempo', tempo=microseconds_per_beat))

            all_events = [] # Stores (absolute_time_seconds, mido_message_object, harmonic_index)

            # Map harmonic index to MIDI channel (1 to max_channels_mpe)
            harmonic_channels = {h_idx: (h_idx % max_channels_mpe) + 1 for h_idx in range(len(harmonics))}

            for h_idx, harmonic in enumerate(harmonics):
                if not harmonic:
                    continue

                channel = harmonic_channels[h_idx]
                
                last_time_for_harmonic = 0.0 # Keep track of last time for pitch bend messages
                active_note = None
                last_velocity = 0

                for i, (time, freq, amp_db) in enumerate(harmonic):
                    velocity = self._db_to_velocity(amp_db)
                    
                    # Store absolute time in seconds, message, and original harmonic index
                    
                    if velocity == 0 and active_note is not None:
                        # Note off
                        all_events.append((time, mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=0), h_idx))
                        active_note = None
                    
                    elif velocity > 0 and active_note is None:
                        # Note on
                        base_freq = freq
                        midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                        active_note = {'note': midi_note, 'base_freq': base_freq}
                        all_events.append((time, mido.Message('note_on', channel=channel, note=midi_note, velocity=velocity, time=0), h_idx))
                        last_velocity = velocity

                    if active_note is not None:
                        # Pitch bend or new note
                        cents_deviation = 1200 * np.log2(freq / active_note['base_freq']) if active_note['base_freq'] > 0 and freq > 0 else 0
                        
                        if abs(cents_deviation) > 100: # If large frequency jump, treat as new note
                            # End previous note
                            all_events.append((time, mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=0), h_idx))

                            # Start a new note
                            base_freq = freq
                            midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                            active_note = {'note': midi_note, 'base_freq': base_freq}
                            all_events.append((time, mido.Message('note_on', channel=channel, note=midi_note, velocity=velocity, time=0), h_idx))
                            last_velocity = velocity
                        else:
                            # Pitch bend
                            pitch_bend = self._calculate_pitch_bend(freq, active_note['base_freq'])
                            all_events.append((time, mido.Message('pitchwheel', channel=channel, pitch=pitch_bend, time=0), h_idx))
                            
                            if velocity != last_velocity:
                                all_events.append((time, mido.Message('polytouch', channel=channel, note=active_note['note'], value=velocity, time=0), h_idx))
                                last_velocity = velocity
                    
                    last_time_for_harmonic = time

                if active_note is not None:
                    # Turn off the last note at the end of the harmonic
                    final_time = harmonic[-1][0] if harmonic else last_time_for_harmonic # Use last known time or current time
                    all_events.append((final_time, mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=0), h_idx))

            # Sort all events globally by absolute time
            all_events.sort(key=lambda x: x[0])

            last_abs_time = 0.0
            for abs_time, msg, _ in all_events:
                delta_seconds = abs_time - last_abs_time
                delta_ticks = mido.second2tick(delta_seconds, ticks_per_beat, microseconds_per_beat)
                
                msg.time = max(0, int(round(delta_ticks))) # Ensure delta_ticks is non-negative
                main_track.append(msg)
                last_abs_time = abs_time

        else: # Existing logic for non-compile mode (multiple tracks)
            for h_idx, harmonic in enumerate(harmonics):
                if not harmonic:
                    continue

                track = mido.MidiTrack()
                mid.tracks.append(track)

                # Set tempo only in the first track
                if len(mid.tracks) == 1:
                    track.append(mido.MetaMessage('set_tempo', tempo=microseconds_per_beat))
                
                # Assign a unique channel to each harmonic/track
                channel = h_idx % 16

                last_time_ticks = 0
                active_note = None
                last_velocity = 0

                for i, (time, freq, amp_db) in enumerate(harmonic):
                    velocity = self._db_to_velocity(amp_db)
                    
                    if velocity == 0 and active_note is not None:
                        # Note off
                        current_time_ticks = int(mido.second2tick(time, ticks_per_beat, microseconds_per_beat))
                        delta_ticks = max(0, current_time_ticks - last_time_ticks)
                        track.append(mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=delta_ticks))
                        last_time_ticks = current_time_ticks
                        active_note = None
                        continue

                    if velocity > 0 and active_note is None:
                        # Note on
                        base_freq = freq
                        midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                        active_note = {'note': midi_note, 'base_freq': base_freq}
                        
                        current_time_ticks = int(mido.second2tick(time, ticks_per_beat, microseconds_per_beat))
                        delta_ticks = max(0, current_time_ticks - last_time_ticks)
                        track.append(mido.Message('note_on', channel=channel, note=midi_note, velocity=velocity, time=delta_ticks))
                        last_time_ticks = current_time_ticks
                        last_velocity = velocity

                    if active_note is not None:
                        # Pitch bend or new note
                        cents_deviation = 1200 * np.log2(freq / active_note['base_freq']) if active_note['base_freq'] > 0 and freq > 0 else 0
                        
                        if abs(cents_deviation) > 100: # More than 100 cents deviation
                            # End previous note
                            current_time_ticks = int(mido.second2tick(time, ticks_per_beat, microseconds_per_beat))
                            delta_ticks = max(0, current_time_ticks - last_time_ticks)
                            track.append(mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=delta_ticks))
                            last_time_ticks = current_time_ticks

                            # Start a new note
                            base_freq = freq
                            midi_note = max(0, min(127, int(round(self._freq_to_midi(base_freq))) - 12))
                            active_note = {'note': midi_note, 'base_freq': base_freq}
                            track.append(mido.Message('note_on', channel=channel, note=midi_note, velocity=velocity, time=0))
                            last_velocity = velocity
                        else:
                            # Pitch bend
                            pitch_bend = self._calculate_pitch_bend(freq, active_note['base_freq'])
                            current_time_ticks = int(mido.second2tick(time, ticks_per_beat, microseconds_per_beat))
                            delta_ticks = max(0, current_time_ticks - last_time_ticks)
                            track.append(mido.Message('pitchwheel', channel=channel, pitch=pitch_bend, time=delta_ticks))
                            last_time_ticks = current_time_ticks

                            if velocity != last_velocity:
                                track.append(mido.Message('polytouch', channel=channel, note=active_note['note'], value=velocity, time=0))
                                last_velocity = velocity

                if active_note is not None:
                    # Turn off the last note at the end of the harmonic
                    time = harmonic[-1][0]
                    current_time_ticks = int(mido.second2tick(time, ticks_per_beat, microseconds_per_beat))
                    delta_ticks = max(0, current_time_ticks - last_time_ticks)
                    track.append(mido.Message('note_off', channel=channel, note=active_note['note'], velocity=0, time=delta_ticks))
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


