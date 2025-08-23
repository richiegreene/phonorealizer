from fractions import Fraction
import numpy as np

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

    def apply_batch_edits(self, selected_points, edits):
        if not selected_points:
            return

        # --- Step 1: Get selected indices ---
        try:
            selected_indices = [spot.data()['index'] for spot in selected_points]
        except KeyError:
            # Fallback for older selection data that might not have the direct index
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
            selected_indices = self.data.df[selection_mask].index
        
        # --- Step 2: Apply standard relative/absolute edits ---
        key_map = {'Sec': 'time', 'dB': 'amplitude'}
        for key, col_name in key_map.items():
            val_str = edits[key].strip()
            if val_str:
                try:
                    val_float = float(val_str)
                    if val_str.startswith(('+', '-')):
                        self.data.df.loc[selected_indices, col_name] += val_float
                    else:
                        self.data.df.loc[selected_indices, col_name] = val_float
                except ValueError:
                    print(f"Could not parse '{val_str}' for {key}. Skipping.")

        # Frequency edits (Hz and Cents) are applied per point due to their nature
        for idx in selected_indices:
            current_freq = self.data.df.loc[idx, 'frequency']
            hz_str = edits['Hz'].strip()
            if hz_str:
                try:
                    hz_float = float(hz_str)
                    if hz_str.startswith(('+', '-')):
                        current_freq += hz_float
                    else:
                        current_freq = hz_float
                except ValueError:
                    print(f"Could not parse '{hz_str}' for Hz. Skipping.")
            
            cents_str = edits['Cents'].strip()
            if cents_str:
                try:
                    cents_float = float(cents_str)
                    current_freq *= (2 ** (cents_float / 1200.0))
                except ValueError:
                    print(f"Could not parse '{cents_str}' for Cents. Skipping.")
            
            self.data.df.loc[idx, 'frequency'] = current_freq

        # --- Step 3: Scaling ---
        # Time Scaling
        time_scale_str = edits.get('time_scale', '').strip()
        if time_scale_str:
            try:
                scale_factor = float(time_scale_str)
                if scale_factor > 0:
                    min_time = self.data.df.loc[selected_indices, 'time'].min()
                    self.data.df.loc[selected_indices, 'time'] = min_time + (self.data.df.loc[selected_indices, 'time'] - min_time) * scale_factor
            except ValueError:
                print(f"Could not parse '{time_scale_str}' for Time Scale. Skipping.")
        
        # Pitch Scaling
        pitch_scale_factor_str = edits.get('pitch_scale_factor', '').strip()
        pitch_scale_fixed_partial_str = edits.get('pitch_scale_fixed_partial', '').strip()
        if pitch_scale_factor_str and pitch_scale_fixed_partial_str:
            try:
                pitch_scale_factor = float(Fraction(pitch_scale_factor_str))
                fixed_partial = int(pitch_scale_fixed_partial_str)

                for idx in selected_indices:
                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    if harmonic_index > fixed_partial:
                        self.data.df.loc[idx, 'frequency'] *= pitch_scale_factor
                    elif harmonic_index < fixed_partial:
                        self.data.df.loc[idx, 'frequency'] /= pitch_scale_factor
            except (ValueError, ZeroDivisionError) as e:
                print(f"Could not apply pitch scaling: {e}")

        # Amplitude Scaling (Dynamic Scaling)
        amplitude_scale_factor_str = edits.get('amplitude_scale_factor', '').strip()
        amplitude_scale_fixed_partial_str = edits.get('amplitude_scale_fixed_partial', '').strip()
        if amplitude_scale_factor_str and amplitude_scale_fixed_partial_str:
            try:
                amplitude_scale_factor = float(Fraction(amplitude_scale_factor_str))
                fixed_partial = int(amplitude_scale_fixed_partial_str)

                for idx in selected_indices:
                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    distance = abs(harmonic_index - fixed_partial)
                    if distance > 0:
                        self.data.df.loc[idx, 'amplitude'] *= (amplitude_scale_factor ** distance)
            except (ValueError, ZeroDivisionError) as e:
                print(f"Could not apply amplitude scaling: {e}")

        # --- Step 4: Smoothing ---
        use_smoothstep = edits.get('smoothstep', False)

        def smoothstep(x):
            return x * x * (3 - 2 * x)

        smoothing_hz_str = edits.get('smoothing_hz', '').strip()
        if smoothing_hz_str:
            try:
                smoothing_perc = float(smoothing_hz_str)
                if 0 <= smoothing_perc <= 100:
                    p = smoothing_perc / 100.0
                    if use_smoothstep:
                        p = smoothstep(p)
                    
                    selected_df = self.data.df.loc[selected_indices]
                    for h_idx, group in selected_df.groupby('harmonic_index'):
                        if len(group) > 1:
                            avg_freq = group['frequency'].mean()
                            
                            self.data.df.loc[group.index, 'frequency'] = group['frequency'] * (1 - p) + avg_freq * p
                else:
                    print("Smoothing percentage must be between 0 and 100.")
            except ValueError:
                print(f"Could not parse '{smoothing_hz_str}' for Smoothing Hz. Skipping.")

        smoothing_db_str = edits.get('smoothing_db', '').strip()
        if smoothing_db_str:
            try:
                smoothing_perc = float(smoothing_db_str)
                if 0 <= smoothing_perc <= 100:
                    p = smoothing_perc / 100.0
                    if use_smoothstep:
                        p = smoothstep(p)
                    
                    selected_df = self.data.df.loc[selected_indices]
                    for h_idx, group in selected_df.groupby('harmonic_index'):
                        if len(group) > 1:
                            avg_amp = group['amplitude'].mean()
                            
                            self.data.df.loc[group.index, 'amplitude'] = group['amplitude'] * (1 - p) + avg_amp * p
                else:
                    print("Smoothing percentage must be between 0 and 100.")
            except ValueError:
                print(f"Could not parse '{smoothing_db_str}' for Smoothing dB. Skipping.")

        # --- Step 5: Apply Snapping (to the newly modified frequencies) ---
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
                    current_freq = self.data.df.loc[idx, 'frequency']
                    if current_freq > 0:
                        n = edo * np.log2(current_freq / f_ref)
                        n_nearest = round(n)
                        new_freq = f_ref * (2 ** (n_nearest / edo))
                        self.data.df.loc[idx, 'frequency'] = new_freq
            except (ValueError, TypeError):
                print(f"Invalid EDO value: {edo_str}")

        elif ratio_str:
            try:
                ratios = [float(Fraction(r.strip())) for r in ratio_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']
                
                for idx in selected_indices:
                    current_freq = self.data.df.loc[idx, 'frequency']
                    if current_freq <= 0: continue

                    target_freqs = []
                    for ratio in ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(current_freq / (f_ref * ratio)) if (f_ref * ratio) != 0 else 0
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    
                    if target_freqs:
                        closest_freq = min(target_freqs, key=lambda f: abs(f - current_freq))
                        self.data.df.loc[idx, 'frequency'] = closest_freq
            except Exception as e:
                print(f"Error parsing ratios: {e}")

        elif scale_str:
            try:
                base_scale_ratios = [float(Fraction(r.strip())) for r in scale_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']

                for idx in selected_indices:
                    current_freq = self.data.df.loc[idx, 'frequency']
                    if current_freq <= 0: continue

                    harmonic_index = self.data.df.loc[idx, 'harmonic_index']
                    
                    scaled_target_ratios = [r * harmonic_index for r in base_scale_ratios]
                    
                    target_freqs = []
                    for ratio in scaled_target_ratios:
                        if ratio <= 0: continue
                        if octave_repeat:
                            k = np.log2(current_freq / (f_ref * ratio)) if (f_ref * ratio) != 0 else 0
                            k_nearest = round(k)
                            target_freqs.append(f_ref * ratio * (2 ** k_nearest))
                        else:
                            target_freqs.append(f_ref * ratio)
                    
                    if target_freqs:
                        closest_freq = min(target_freqs, key=lambda f: abs(f - current_freq))
                        self.data.df.loc[idx, 'frequency'] = closest_freq
            except Exception as e:
                print(f"Error parsing scale or applying snap to scale: {e}")

        # --- Step 6: Mark data as modified ---
        self.data._modified = True

        # --- Step 7: Finalize ---
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
