from fractions import Fraction
import numpy as np
import pandas as pd # Added import

import numpy as np

class HarmonicEditor:
    def __init__(self, harmonic_data):
        self.data = harmonic_data

    def select_all(self):
        if self.data.df is None:
            return []
        return list(self.data.df.index)

    def invert_selection(self, selected_indices):
        if self.data.df is None:
            return []
        all_indices = set(self.data.df.index)
        selected_set = set(selected_indices)
        inverted_indices = list(all_indices - selected_set)
        return inverted_indices

    def select_by_criteria(self, partial_str, time_str, current_selection):
        if self.data.df is None:
            return []

        partial_indices = self._parse_partial_string(partial_str)
        time_indices = self._parse_time_string(time_str)

        if partial_indices is not None and time_indices is not None:
            selection = partial_indices.intersection(time_indices)
        elif partial_indices is not None:
            selection = partial_indices
        elif time_indices is not None:
            selection = time_indices
        else:
            selection = set(self.data.df.index)

        return list(selection)

    def _parse_partial_string(self, p_str):
        if not p_str:
            return None

        indices = set()
        parts = p_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.lower() == 'odd':
                indices.update(self.data.df[self.data.df['harmonic_index'] % 2 != 0].index)
            elif part.lower() == 'even':
                indices.update(self.data.df[self.data.df['harmonic_index'] % 2 == 0].index)
            elif '-' in part:
                start, end = part.split('-')
                try:
                    start = int(start.strip())
                    end = int(end.strip())
                    for i in range(start, end + 1):
                        indices.update(self.data.df[self.data.df['harmonic_index'] == i].index)
                except ValueError:
                    pass  # Ignore malformed ranges
            else:
                try:
                    val = int(part)
                    indices.update(self.data.df[self.data.df['harmonic_index'] == val].index)
                except ValueError:
                    pass  # Ignore malformed numbers
        return indices

    def _parse_time_string(self, t_str):
        if not t_str:
            return None

        final_indices = set()
        parts = t_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                start, end = part.split('-')
                try:
                    start_time = float(start.strip())
                    end_time = float(end.strip())
                    mask = (self.data.df['time'] >= start_time) & (self.data.df['time'] <= end_time)
                    final_indices.update(self.data.df[mask].index)
                except ValueError:
                    pass  # Ignore malformed ranges
        return final_indices

    def get_indices_from_points(self, selected_points):
        if not selected_points:
            return []
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
            selection_mask = np.logical_or.reduce(point_masks)
            return self.data.df[selection_mask].index

    def apply_batch_edits(self, selected_points, edits):
        if not selected_points:
            return

        selected_indices = self.get_indices_from_points(selected_points)
        selected_df = self.data.df.loc[selected_indices].copy()

        # --- Slope Calculation ---
        apply_slope = edits.get('apply_slope', False)
        slope_factors = pd.Series(1.0, index=selected_indices)
        if apply_slope:
            is_fixed_slope = edits.get('fixed_slope', False)
            is_variable_slope = edits.get('variable_slope', True)

            if is_variable_slope:
                y_rate = edits.get('y_rate', 100) / 100.0
                x_rate = edits.get('x_rate', 100) / 100.0
                if y_rate > 0 or x_rate > 0:
                    min_freq, max_freq = selected_df['frequency'].min(), selected_df['frequency'].max()
                    min_time, max_time = selected_df['time'].min(), selected_df['time'].max()
                    center_freq = (min_freq + max_freq) / 2
                    center_time = (min_time + max_time) / 2
                    norm_freq = (selected_df['frequency'] - min_freq) / ((max_freq - min_freq) or 1)
                    norm_time = (selected_df['time'] - min_time) / ((max_time - min_time) or 1)
                    distances = np.sqrt(((norm_time - 0.5) * x_rate * 2)**2 + ((norm_freq - 0.5) * y_rate * 2)**2)
                    max_dist = distances.max()
                    if max_dist > 0:
                        slope_factors = 1 - (distances / max_dist)
                    else:
                        slope_factors = pd.Series(1.0, index=selected_indices)
            
            elif is_fixed_slope:
                slope_sec = float(edits.get('slope_sec', 2.0))
                slope_cents = float(edits.get('slope_cents', 702.0))
                min_time, max_time = selected_df['time'].min(), selected_df['time'].max()
                min_freq, max_freq = selected_df['frequency'].min(), selected_df['frequency'].max()

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

                slope_factors = selected_df.apply(get_fixed_slope, axis=1)

        # --- Step 2: Apply standard relative/absolute edits ---
        key_map = {'Sec': 'time', 'dB': 'amplitude'}
        for key, col_name in key_map.items():
            val_str = edits[key].strip()
            if val_str:
                try:
                    val_float = float(val_str)
                    if val_str.startswith(('+', '-')):
                        self.data.df.loc[selected_indices, col_name] += val_float * slope_factors
                    else:
                        original_values = self.data.df.loc[selected_indices, col_name]
                        self.data.df.loc[selected_indices, col_name] = original_values * (1 - slope_factors) + val_float * slope_factors
                except ValueError:
                    print(f"Could not parse '{val_str}' for {key}. Skipping.")

        # Frequency edits (Hz and Cents)
        hz_str = edits['Hz'].strip()
        cents_str = edits['Cents'].strip()
        if hz_str or cents_str:
            for idx in selected_indices:
                slope_factor = slope_factors.get(idx, 1.0)
                if slope_factor == 0: continue

                original_freq = self.data.df.loc[idx, 'frequency']
                current_freq = original_freq
                
                if hz_str:
                    try:
                        hz_float = float(hz_str)
                        if hz_str.startswith(('+', '-')):
                            current_freq += hz_float * slope_factor
                        else:
                            current_freq = original_freq * (1 - slope_factor) + hz_float * slope_factor
                    except ValueError:
                        print(f"Could not parse '{hz_str}' for Hz. Skipping.")
                
                if cents_str:
                    try:
                        cents_float = float(cents_str)
                        target_freq = current_freq * (2 ** (cents_float / 1200.0))
                        current_freq = current_freq * (1 - slope_factor) + target_freq * slope_factor
                    except ValueError:
                        print(f"Could not parse '{cents_str}' for Cents. Skipping.")
                
                self.data.df.loc[idx, 'frequency'] = current_freq

        # --- Step 3: Scaling ---
        time_scale_str = edits.get('time_scale', '').strip()
        if time_scale_str:
            try:
                scale_factor = float(time_scale_str)
                if scale_factor > 0:
                    min_time = self.data.df.loc[selected_indices, 'time'].min()
                    for idx in selected_indices:
                        slope_factor = slope_factors.get(idx, 1.0)
                        original_time = self.data.df.loc[idx, 'time']
                        scaled_time = min_time + (original_time - min_time) * scale_factor
                        self.data.df.loc[idx, 'time'] = original_time * (1 - slope_factor) + scaled_time * slope_factor
            except ValueError:
                print(f"Could not parse '{time_scale_str}' for Time Scale. Skipping.")

        pitch_scale_factor_str = edits.get('pitch_scale_factor', '').strip()
        pitch_scale_fixed_partial_str = edits.get('pitch_scale_fixed_partial', '').strip()
        if pitch_scale_factor_str and pitch_scale_fixed_partial_str:
            try:
                pitch_scale_factor = float(Fraction(pitch_scale_factor_str))
                fixed_partial = int(pitch_scale_fixed_partial_str)

                for idx in selected_indices:
                    slope_factor = slope_factors.get(idx, 1.0)
                    if slope_factor == 0: continue
                    original_freq = self.data.df.loc[idx, 'frequency']
                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    
                    if harmonic_index > fixed_partial:
                        scaled_freq = original_freq * pitch_scale_factor
                    elif harmonic_index < fixed_partial:
                        scaled_freq = original_freq / pitch_scale_factor
                    else:
                        scaled_freq = original_freq
                    self.data.df.loc[idx, 'frequency'] = original_freq * (1 - slope_factor) + scaled_freq * slope_factor
            except (ValueError, ZeroDivisionError) as e:
                print(f"Could not apply pitch scaling: {e}")

        amplitude_scale_factor_str = edits.get('amplitude_scale_factor', '').strip()
        amplitude_scale_fixed_partial_str = edits.get('amplitude_scale_fixed_partial', '').strip()
        if amplitude_scale_factor_str and amplitude_scale_fixed_partial_str:
            try:
                amplitude_scale_factor = float(Fraction(amplitude_scale_factor_str))
                fixed_partial = int(amplitude_scale_fixed_partial_str)

                for idx in selected_indices:
                    slope_factor = slope_factors.get(idx, 1.0)
                    if slope_factor == 0: continue
                    original_amp = self.data.df.loc[idx, 'amplitude']
                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    distance = abs(harmonic_index - fixed_partial)
                    if distance > 0:
                        scaled_amp = original_amp * (amplitude_scale_factor ** distance)
                        self.data.df.loc[idx, 'amplitude'] = original_amp * (1 - slope_factor) + scaled_amp * slope_factor
            except (ValueError, ZeroDivisionError) as e:
                print(f"Could not apply amplitude scaling: {e}")
        
        # --- Step 4: Smoothing ---
        use_smoothstep = edits.get('smoothstep', False)
        def smoothstep(x):
            return x * x * (3 - 2 * x)

        smoothing_hz = edits.get('smoothing_hz', 0)
        if smoothing_hz > 0:
            p = smoothing_hz / 100.0
            if use_smoothstep:
                p = smoothstep(p)
            for h_idx, group in self.data.df.loc[selected_indices].groupby('harmonic_index'):
                if len(group) > 1:
                    avg_freq = group['frequency'].mean()
                    for idx, row in group.iterrows():
                        slope_factor = slope_factors.get(idx, 1.0)
                        effective_p = p * slope_factor
                        original_freq = self.data.df.loc[idx, 'frequency']
                        self.data.df.loc[idx, 'frequency'] = original_freq * (1 - effective_p) + avg_freq * effective_p

        smoothing_db = edits.get('smoothing_db', 0)
        if smoothing_db > 0:
            p = smoothing_db / 100.0
            if use_smoothstep:
                p = smoothstep(p)
            for h_idx, group in self.data.df.loc[selected_indices].groupby('harmonic_index'):
                if len(group) > 1:
                    avg_amp = group['amplitude'].mean()
                    for idx, row in group.iterrows():
                        slope_factor = slope_factors.get(idx, 1.0)
                        effective_p = p * slope_factor
                        original_amp = self.data.df.loc[idx, 'amplitude']
                        self.data.df.loc[idx, 'amplitude'] = original_amp * (1 - effective_p) + avg_amp * effective_p

        # --- Step 5: Apply Sliding ---
        sliding_percentage = edits.get('sliding_percentage', 0)
        if sliding_percentage > 0:
            p = sliding_percentage / 100.0
            for h_idx, group in self.data.df.loc[selected_indices].groupby('harmonic_index'):
                group = group.sort_values(by='time')
                if len(group) >= 2:
                    start_freq, end_freq = group['frequency'].iloc[0], group['frequency'].iloc[-1]
                    start_time, end_time = group['time'].iloc[0], group['time'].iloc[-1]
                    for idx, row in group.iterrows():
                        slope_factor = slope_factors.get(idx, 1.0)
                        effective_p = p * slope_factor
                        original_freq = row['frequency']
                        if end_time - start_time != 0:
                            time_ratio = (row['time'] - start_time) / (end_time - start_time)
                            interpolated_freq = start_freq + time_ratio * (end_freq - start_freq)
                            self.data.df.loc[idx, 'frequency'] = original_freq * (1 - effective_p) + interpolated_freq * effective_p

        # --- Step 6: Apply Snapping ---
        try:
            f_ref = float(edits['ref_pitch'])
        except (ValueError, TypeError):
            f_ref = 261.6256

        edo_str = edits['edo'].strip()
        ratio_str = edits['ratios'].strip()
        scale_str = edits['scale'].strip()

        if edo_str:
            try:
                edo = int(edo_str)
                for idx in selected_indices:
                    slope_factor = slope_factors.get(idx, 1.0)
                    if slope_factor == 0: continue
                    original_freq = self.data.df.loc[idx, 'frequency']
                    if original_freq > 0:
                        n = edo * np.log2(original_freq / f_ref)
                        n_nearest = round(n)
                        snapped_freq = f_ref * (2 ** (n_nearest / edo))
                        self.data.df.loc[idx, 'frequency'] = original_freq * (1 - slope_factor) + snapped_freq * slope_factor
            except (ValueError, TypeError):
                print(f"Invalid EDO value: {edo_str}")

        elif ratio_str:
            try:
                ratios = [float(Fraction(r.strip())) for r in ratio_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']
                
                for idx in selected_indices:
                    slope_factor = slope_factors.get(idx, 1.0)
                    if slope_factor == 0: continue
                    original_freq = self.data.df.loc[idx, 'frequency']
                    if original_freq <= 0: continue

                    target_freqs = []
                    for ratio in ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(original_freq / (f_ref * ratio)) if (f_ref * ratio) > 0 else 0
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    
                    if target_freqs:
                        snapped_freq = min(target_freqs, key=lambda f: abs(f - original_freq))
                        self.data.df.loc[idx, 'frequency'] = original_freq * (1 - slope_factor) + snapped_freq * slope_factor
            except Exception as e:
                print(f"Error parsing ratios: {e}")

        elif scale_str:
            try:
                base_scale_ratios = [float(Fraction(r.strip())) for r in scale_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']

                for idx in selected_indices:
                    slope_factor = slope_factors.get(idx, 1.0)
                    if slope_factor == 0: continue
                    original_freq = self.data.df.loc[idx, 'frequency']
                    if original_freq <= 0: continue

                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    scaled_target_ratios = [r * harmonic_index for r in base_scale_ratios]
                    
                    target_freqs = []
                    for ratio in scaled_target_ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(original_freq / (f_ref * ratio)) if (f_ref * ratio) > 0 else 0
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    
                    if target_freqs:
                        snapped_freq = min(target_freqs, key=lambda f: abs(f - original_freq))
                        self.data.df.loc[idx, 'frequency'] = original_freq * (1 - slope_factor) + snapped_freq * slope_factor
            except Exception as e:
                print(f"Error parsing scale or applying snap to scale: {e}")

        # --- Finalize ---
        self.data._modified = True
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
