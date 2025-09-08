from fractions import Fraction
import numpy as np
import pandas as pd
from PySide6.QtGui import QImage

def db_to_linear(db):
    return 10 ** (db / 20.0)

def linear_to_db(linear):
    if linear <= 1e-7: return -140.0
    return 20 * np.log10(linear)

class HarmonicEditor:
    def __init__(self, harmonic_data):
        self.data = harmonic_data

    def revert_to_original(self):
        if self.data.original_df is not None:
            self.data.df = self.data.original_df.copy()
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.data._modified = True

    def apply_batch_edits(self, selected_points, edits):
        if not selected_points:
            return

        selected_indices = self.get_indices_from_points(selected_points)
        trace = False

        if trace:
            print("\n--- Batch Edit Trace Report ---")
            print(f"Processing {len(selected_indices)} selected partials.")

        temp_df = self.data.df.loc[selected_indices].copy()

        # --- Superimpose: Calculate image-based transformations ---
        image_path = edits.get('superimpose_image_path')
        if image_path:
            try:
                # Get options from edits dict
                apply_amp = edits.get('superimpose_amplitude', False)
                apply_pitch = edits.get('superimpose_pitch', False)
                min_db = float(edits.get('superimpose_min_db', -80.0))
                max_db = float(edits.get('superimpose_max_db', 0.0))
                min_cents = float(edits.get('superimpose_min_cents', -100.0))
                max_cents = float(edits.get('superimpose_max_cents', 100.0))
                invert = edits.get('superimpose_invert', False)
                mix = float(edits.get('superimpose_mix', '100').strip() or 100) / 100.0
                y_axis_mode = edits.get("y_axis_mode", "Linear")

                image = QImage(image_path)
                if not image.isNull() and (apply_amp or apply_pitch):
                    image_amps = pd.Series(np.nan, index=selected_indices)
                    image_cents = pd.Series(np.nan, index=selected_indices)

                    min_time, max_time = temp_df['time'].min(), temp_df['time'].max()
                    min_freq, max_freq = temp_df['frequency'].min(), temp_df['frequency'].max()
                    time_range = max_time - min_time if max_time > min_time else 1
                    
                    is_log_scale = (y_axis_mode != "Linear")
                    if is_log_scale:
                        min_freq_log = np.log2(min_freq) if min_freq > 0 else 0
                        max_freq_log = np.log2(max_freq) if max_freq > 0 else 0
                        freq_range_log = max_freq_log - min_freq_log if max_freq_log > min_freq_log else 1
                    else:
                        freq_range = max_freq - min_freq if max_freq > min_freq else 1

                    for idx, partial in temp_df.iterrows():
                        norm_time = (partial['time'] - min_time) / time_range
                        if is_log_scale:
                            partial_freq_log = np.log2(partial['frequency']) if partial['frequency'] > 0 else 0
                            norm_freq = (partial_freq_log - min_freq_log) / freq_range_log if freq_range_log != 0 else 0
                        else:
                            norm_freq = (partial['frequency'] - min_freq) / freq_range
                        
                        img_x = int(norm_time * (image.width() - 1))
                        img_y = int((1 - norm_freq) * (image.height() - 1))
                        brightness = image.pixelColor(img_x, img_y).lightnessF()
                        
                        if invert:
                            brightness = 1.0 - brightness
                        
                        if apply_amp:
                            image_amps[idx] = min_db + (brightness * (max_db - min_db))
                        if apply_pitch:
                            image_cents[idx] = min_cents + (brightness * (max_cents - min_cents))

                    # Apply transformations with mix
                    if apply_amp:
                        temp_df['amplitude'] = (temp_df['amplitude'] * (1 - mix)) + (image_amps * mix)
                        if trace: print(f"- Applied Superimpose (Amplitude) with mix: {mix*100:.0f}%")
                    
                    if apply_pitch:
                        pitch_multiplier = 2 ** (image_cents / 1200.0)
                        temp_df['frequency'] = temp_df['frequency'] * (1 - mix) + (temp_df['frequency'] * pitch_multiplier * mix)
                        if trace: print(f"- Applied Superimpose (Pitch) with mix: {mix*100:.0f}%")

            except Exception as e:
                print(f"Error processing superimpose image: {e}")

        # --- Slope Calculation ---
        apply_slope = edits.get('apply_slope', False)
        slope_factors = pd.Series(1.0, index=selected_indices)
        if apply_slope:
            if trace: print("- Calculating Slope factors...")
            is_fixed_slope = edits.get('fixed_slope', False)
            is_variable_slope = edits.get('variable_slope', True)

            if is_variable_slope:
                y_rate = edits.get('y_rate', 100) / 100.0
                x_rate = edits.get('x_rate', 100) / 100.0
                if y_rate > 0 or x_rate > 0:
                    min_freq, max_freq = temp_df['frequency'].min(), temp_df['frequency'].max()
                    min_time, max_time = temp_df['time'].min(), temp_df['time'].max()
                    norm_freq = (temp_df['frequency'] - min_freq) / ((max_freq - min_freq) or 1)
                    norm_time = (temp_df['time'] - min_time) / ((max_time - min_time) or 1)
                    distances = np.sqrt(((norm_time - 0.5) * x_rate * 2)**2 + ((norm_freq - 0.5) * y_rate * 2)**2)
                    max_dist = distances.max()
                    if max_dist > 0:
                        slope_factors = 1 - (distances / max_dist)
            
            elif is_fixed_slope:
                slope_sec = float(edits.get('slope_sec', 2.0))
                slope_cents = float(edits.get('slope_cents', 702.0))
                min_time, max_time = temp_df['time'].min(), temp_df['time'].max()
                min_freq, max_freq = temp_df['frequency'].min(), temp_df['frequency'].max()

                def to_cents(f, ref=20.0):
                    return 1200 * np.log2(f / ref) if f > 0 else 0

                min_freq_cents = to_cents(min_freq)
                max_freq_cents = to_cents(max_freq)

                def get_fixed_slope(row):
                    dist_t = min(row['time'] - min_time, max_time - row['time'])
                    dist_f_cents = min(to_cents(row['frequency']) - min_freq_cents, max_freq_cents - to_cents(row['frequency']))
                    factor_t = min(1.0, dist_t / slope_sec if slope_sec > 0 else 1.0)
                    factor_f = min(1.0, dist_f_cents / slope_cents if slope_cents > 0 else 1.0)
                    return factor_t * factor_f

                slope_factors = temp_df.apply(get_fixed_slope, axis=1)
            if trace: print(f"  Slope factors calculated (min: {slope_factors.min():.2f}, max: {slope_factors.max():.2f})")

        # --- Apply all other edits to the temporary DataFrame ---
        original_df = temp_df.copy()

        # Shifting
        for key, col in [('Sec', 'time'), ('dB', 'amplitude'), ('Hz', 'frequency')]:
            val_str = edits[key].strip()
            if val_str:
                val = float(val_str)
                if val_str.startswith(('+', '-')):
                    temp_df[col] += val
                else:
                    temp_df[col] = val
                if trace: print(f"- Applied Shift for {key}: {val_str}")
        
        cents_str = edits['Cents'].strip()
        if cents_str:
            cents = float(cents_str)
            temp_df['frequency'] *= (2 ** (cents / 1200.0))
            if trace: print(f"- Applied Cents Shift: {cents}")

        # Scaling
        time_scale_str = edits.get('time_scale', '').strip()
        if time_scale_str:
            try:
                scale_factor = float(time_scale_str)
                if scale_factor > 0:
                    min_time = temp_df['time'].min()
                    temp_df['time'] = min_time + (temp_df['time'] - min_time) * scale_factor
                    if trace: print(f"- Applied Time Scale: {scale_factor}")
            except ValueError:
                if trace: print(f"- Skipped Time Scale: Could not parse '{time_scale_str}'")

        pitch_scale_factor_str = edits.get('pitch_scale_factor', '').strip()
        if pitch_scale_factor_str:
            try:
                pitch_scale_factor = float(Fraction(pitch_scale_factor_str))
                fixed_partial = int(edits.get('pitch_scale_fixed_partial', '1').strip())
                
                def scale_pitch(row):
                    if row['harmonic_index'] > fixed_partial:
                        return row['frequency'] * pitch_scale_factor
                    elif row['harmonic_index'] < fixed_partial:
                        return row['frequency'] / pitch_scale_factor
                    return row['frequency']
                
                temp_df['frequency'] = temp_df.apply(scale_pitch, axis=1)
                if trace: print(f"- Applied Pitch Scaling: factor={pitch_scale_factor}, fixed partial={fixed_partial}")
            except (ValueError, ZeroDivisionError) as e:
                if trace: print(f"- Skipped Pitch Scaling: {e}")

        amplitude_scale_factor_str = edits.get('amplitude_scale_factor', '').strip()
        if amplitude_scale_factor_str:
            try:
                amplitude_scale_factor = float(Fraction(amplitude_scale_factor_str))
                fixed_partial = int(edits.get('amplitude_scale_fixed_partial', '1').strip())

                def scale_amp(row):
                    distance = abs(row['harmonic_index'] - fixed_partial)
                    if distance > 0:
                        return row['amplitude'] + (20 * np.log10(amplitude_scale_factor) * distance) # operate in dB
                    return row['amplitude']

                temp_df['amplitude'] = temp_df.apply(scale_amp, axis=1)
                if trace: print(f"- Applied Dynamic Scaling: factor={amplitude_scale_factor}, fixed partial={fixed_partial}")
            except (ValueError, ZeroDivisionError) as e:
                if trace: print(f"- Skipped Dynamic Scaling: {e}")

        # Smoothing
        use_smoothstep = edits.get('smoothstep', False)
        def smoothstep(x): return x * x * (3 - 2 * x)
        smoothing_hz = edits.get('smoothing_hz', 0)
        if smoothing_hz > 0:
            p = smoothing_hz / 100.0
            if use_smoothstep: p = smoothstep(p)
            avg_freqs = temp_df.groupby('harmonic_index')['frequency'].transform('mean')
            temp_df['frequency'] = temp_df['frequency'] * (1 - p) + avg_freqs * p
            if trace: print(f"- Applied Pitch Smoothing: {smoothing_hz}%")

        smoothing_db = edits.get('smoothing_db', 0)
        if smoothing_db > 0:
            p = smoothing_db / 100.0
            if use_smoothstep: p = smoothstep(p)
            avg_amps = temp_df.groupby('harmonic_index')['amplitude'].transform('mean')
            temp_df['amplitude'] = temp_df['amplitude'] * (1 - p) + avg_amps * p
            if trace: print(f"- Applied Dynamic Smoothing: {smoothing_db}%")

        # Sliding
        sliding_percentage = edits.get('sliding_percentage', 0)
        if sliding_percentage > 0:
            p = sliding_percentage / 100.0
            if trace: print(f"- Applying Pitch Slide: {sliding_percentage}%")
            for h_idx, group in temp_df.groupby('harmonic_index'):
                group = group.sort_values(by='time')
                if len(group) >= 2:
                    start_freq, end_freq = group['frequency'].iloc[0], group['frequency'].iloc[-1]
                    start_time, end_time = group['time'].iloc[0], group['time'].iloc[-1]
                    time_range = end_time - start_time
                    if time_range > 0:
                        time_ratios = (group['time'] - start_time) / time_range
                        interpolated_freqs = start_freq + time_ratios * (end_freq - start_freq)
                        temp_df.loc[group.index, 'frequency'] = group['frequency'] * (1 - p) + interpolated_freqs * p

        dynamic_percentage = edits.get('dynamic_percentage', 0)
        if dynamic_percentage > 0:
            p = dynamic_percentage / 100.0
            if trace: print(f"- Applying Dynamic Slide: {dynamic_percentage}%")
            for h_idx, group in temp_df.groupby('harmonic_index'):
                group = group.sort_values(by='time')
                if len(group) >= 2:
                    start_amp, end_amp = group['amplitude'].iloc[0], group['amplitude'].iloc[-1]
                    start_time, end_time = group['time'].iloc[0], group['time'].iloc[-1]
                    time_range = end_time - start_time
                    if time_range > 0:
                        time_ratios = (group['time'] - start_time) / time_range
                        interpolated_amps = start_amp + time_ratios * (end_amp - start_amp)
                        temp_df.loc[group.index, 'amplitude'] = group['amplitude'] * (1 - p) + interpolated_amps * p

        # Snapping
        try:
            f_ref = float(edits['ref_pitch'])
        except (ValueError, TypeError):
            f_ref = 261.6256

        edo_str = edits['edo'].strip()
        if edo_str:
            try:
                edo = int(edo_str)
                if trace: print(f"- Applying Snap to EDO: {edo} with ref pitch {f_ref:.2f} Hz")
                
                def snap_to_edo(freq):
                    if freq > 0:
                        n = edo * np.log2(freq / f_ref)
                        n_nearest = round(n)
                        return f_ref * (2 ** (n_nearest / edo))
                    return freq
                
                temp_df['frequency'] = temp_df['frequency'].apply(snap_to_edo)
            except (ValueError, TypeError):
                if trace: print(f"- Skipped EDO Snap: Invalid EDO value '{edo_str}'")

        ratio_str = edits['ratios'].strip()
        if ratio_str:
            try:
                ratios = [float(Fraction(r.strip())) for r in ratio_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']
                if trace: print(f"- Applying Snap to Ratios: {ratios} (Octave Repeat: {octave_repeat})")

                def snap_to_ratios(freq):
                    if freq <= 0: return freq
                    target_freqs = []
                    for ratio in ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(freq / (f_ref * ratio))
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    if not target_freqs: return freq
                    return min(target_freqs, key=lambda f: abs(f - freq))

                temp_df['frequency'] = temp_df['frequency'].apply(snap_to_ratios)
            except Exception as e:
                if trace: print(f"- Skipped Ratio Snap: {e}")

        scale_str = edits['scale'].strip()
        if scale_str:
            try:
                base_scale_ratios = [float(Fraction(r.strip())) for r in scale_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']
                if trace: print(f"- Applying Snap to Scale: {base_scale_ratios} (Octave Repeat: {octave_repeat})")

                def snap_to_scale(row):
                    freq = row['frequency']
                    if freq <= 0: return freq
                    harmonic_index = row['harmonic_index']
                    scaled_target_ratios = [r * harmonic_index for r in base_scale_ratios]
                    target_freqs = []
                    for ratio in scaled_target_ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(freq / (f_ref * ratio))
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    if not target_freqs: return freq
                    return min(target_freqs, key=lambda f: abs(f - freq))

                temp_df['frequency'] = temp_df.apply(snap_to_scale, axis=1)
            except Exception as e:
                if trace: print(f"- Skipped Scale Snap: {e}")

        # --- Final Application with Slope ---
        final_df = original_df.add((temp_df - original_df).mul(slope_factors, axis=0))
        self.data.df.loc[selected_indices] = final_df

        self.data._modified = True
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}

    def get_indices_from_points(self, selected_points):
        if not selected_points: return []
        try:
            return [spot.data()['index'] for spot in selected_points]
        except KeyError:
            point_masks = []
            for spot in selected_points:
                data = spot.data()
                point_masks.append(
                    (self.data.df['time'] == float(data['time'])) &
                    (self.data.df['frequency'] == float(data['frequency'])) &
                    (self.data.df['amplitude'] == float(data['amplitude'])) &
                    (self.data.df['harmonic_index'] == int(data['harmonic_index']))
                )
            return self.data.df[np.logical_or.reduce(point_masks)].index

    def select_all(self):
        if self.data.df is None: return []
        return list(self.data.df.index)