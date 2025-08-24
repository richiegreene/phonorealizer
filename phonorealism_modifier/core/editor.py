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

        smoothing_hz = edits.get('smoothing_hz', 0)
        if smoothing_hz > 0:
            try:
                smoothing_perc = float(smoothing_hz)
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
                print(f"Could not parse '{smoothing_hz}' for Smoothing Hz. Skipping.")

        smoothing_db = edits.get('smoothing_db', 0)
        if smoothing_db > 0:
            try:
                smoothing_perc = float(smoothing_db)
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
                print(f"Could not parse '{smoothing_db}' for Smoothing dB. Skipping.")

        # --- Step 5: Apply Sliding (Linear Interpolation) ---
        sliding_percentage = edits.get('sliding_percentage', 0)
        if sliding_percentage > 0:
            p = sliding_percentage / 100.0
            
            # Get only the selected data points
            selected_df = self.data.df.loc[selected_indices].copy()

            # Group by harmonic_index and process each harmonic separately
            for h_idx, group in selected_df.groupby('harmonic_index'):
                # Sort by time to ensure correct chain identification
                group = group.sort_values(by='time')
                
                if len(group) < 2:
                    continue # Need at least two points to form a chain

                # Calculate typical time step for this group
                time_diffs = group['time'].diff().dropna()
                if not time_diffs.empty:
                    # Find the smallest non-zero time difference
                    min_time_diff = time_diffs[time_diffs > 1e-9].min() # Use a small epsilon to avoid zero
                    if pd.isna(min_time_diff):
                        continue # All time diffs are zero or very small, cannot determine typical step
                    gap_threshold = min_time_diff * 1.5 # A gap is 1.5 times larger than the smallest step
                else:
                    continue # Cannot determine time differences

                # Identify chains of sequentially selected partials
                chains = []
                current_chain_indices = [group.index[0]]

                for i in range(1, len(group)):
                    time_diff = group.iloc[i]['time'] - group.iloc[i-1]['time']
                    # If the time difference is significantly larger than the typical step, start a new chain
                    if time_diff > gap_threshold:
                        chains.append(current_chain_indices)
                        current_chain_indices = [group.index[i]]
                    else:
                        current_chain_indices.append(group.index[i])
                chains.append(current_chain_indices) # Add the last chain

                for chain_indices in chains:
                    if len(chain_indices) >= 2:
                        chain_data = self.data.df.loc[chain_indices]
                        start_time = chain_data.iloc[0]['time']
                        end_time = chain_data.iloc[-1]['time']
                        start_freq = chain_data.iloc[0]['frequency']
                        end_freq = chain_data.iloc[-1]['frequency']

                        # Apply linear interpolation for points within the chain
                        for idx in chain_indices:
                            current_point_time = self.data.df.loc[idx, 'time']
                            original_freq = self.data.df.loc[idx, 'frequency']

                            if end_time - start_time != 0:
                                # Calculate interpolated frequency
                                interpolated_freq = start_freq + (current_point_time - start_time) * \
                                                    (end_freq - start_freq) / (end_time - start_time)
                            else:
                                # Handle case where start and end times are the same (e.g., only two points at same time)
                                interpolated_freq = start_freq # Or end_freq, they are the same
                            
                            # Blend original and interpolated frequency based on sliding_percentage
                            new_freq = original_freq * (1 - p) + interpolated_freq * p
                            
                            # Update the frequency in the main DataFrame
                            self.data.df.loc[idx, 'frequency'] = new_freq

        # --- Step 5.1: Apply Dynamic (Linear Interpolation for Amplitude) ---
        dynamic_percentage = edits.get('dynamic_percentage', 0)
        if dynamic_percentage > 0:
            p = dynamic_percentage / 100.0
            
            # Get only the selected data points
            selected_df = self.data.df.loc[selected_indices].copy()

            # Group by harmonic_index and process each harmonic separately
            for h_idx, group in selected_df.groupby('harmonic_index'):
                # Sort by time to ensure correct chain identification
                group = group.sort_values(by='time')
                
                if len(group) < 2:
                    continue # Need at least two points to form a chain

                # Calculate typical time step for this group
                time_diffs = group['time'].diff().dropna()
                if not time_diffs.empty:
                    # Find the smallest non-zero time difference
                    min_time_diff = time_diffs[time_diffs > 1e-9].min() # Use a small epsilon to avoid zero
                    if pd.isna(min_time_diff):
                        continue # All time diffs are zero or very small, cannot determine typical step
                    gap_threshold = min_time_diff * 1.5 # A gap is 1.5 times larger than the smallest step
                else:
                    continue # Cannot determine time differences

                # Identify chains of sequentially selected partials
                chains = []
                current_chain_indices = [group.index[0]]

                for i in range(1, len(group)):
                    time_diff = group.iloc[i]['time'] - group.iloc[i-1]['time']
                    # If the time difference is significantly larger than the typical step, start a new chain
                    if time_diff > gap_threshold:
                        chains.append(current_chain_indices)
                        current_chain_indices = [group.index[i]]
                    else:
                        current_chain_indices.append(group.index[i])
                chains.append(current_chain_indices) # Add the last chain

                for chain_indices in chains:
                    if len(chain_indices) >= 2:
                        chain_data = self.data.df.loc[chain_indices]
                        start_time = chain_data.iloc[0]['time']
                        end_time = chain_data.iloc[-1]['time']
                        start_amp = chain_data.iloc[0]['amplitude']
                        end_amp = chain_data.iloc[-1]['amplitude']

                        # Apply linear interpolation for points within the chain
                        for idx in chain_indices:
                            current_point_time = self.data.df.loc[idx, 'time']
                            original_amp = self.data.df.loc[idx, 'amplitude']

                            if end_time - start_time != 0:
                                # Calculate interpolated amplitude
                                interpolated_amp = start_amp + (current_point_time - start_time) * \
                                                    (end_amp - start_amp) / (end_time - start_time)
                            else:
                                # Handle case where start and end times are the same (e.g., only two points at same time)
                                interpolated_amp = start_amp # Or end_amp, they are the same
                            
                            # Blend original and interpolated amplitude based on dynamic_percentage
                            new_amp = original_amp * (1 - p) + interpolated_amp * p
                            
                            # Update the amplitude in the main DataFrame
                            self.data.df.loc[idx, 'amplitude'] = new_amp

        # --- Step 6: Apply Snapping (to the newly modified frequencies) ---
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
