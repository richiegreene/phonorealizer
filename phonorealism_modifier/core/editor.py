from fractions import Fraction
import numpy as np

class HarmonicEditor:
    def __init__(self, harmonic_data):
        self.data = harmonic_data

    def apply_batch_edits(self, selected_points, edits):
        # --- Step 1: Apply standard relative/absolute edits ---
        key_map = {'Sec': 'time', 'dB': 'amplitude'}
        for spot in selected_points:
            data = spot.data()
            idx_mask = (self.data.df['time'] == float(data['time'])) & \
                       (self.data.df['frequency'] == float(data['frequency'])) & \
                       (self.data.df['amplitude'] == float(data['amplitude'])) & \
                       (self.data.df['harmonic_index'] == int(data['harmonic_index']))

            for key, col_name in key_map.items():
                val_str = edits[key].strip()
                if val_str:
                    try:
                        val_float = float(val_str)
                        if val_str.startswith(('+', '-')):
                            self.data.df.loc[idx_mask, col_name] += val_float
                        else:
                            self.data.df.loc[idx_mask, col_name] = val_float
                    except ValueError:
                        print(f"Could not parse '{val_str}' for {key}. Skipping.")

            current_freq = self.data.df.loc[idx_mask, 'frequency'].iloc[0]
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
            
            self.data.df.loc[idx_mask, 'frequency'] = current_freq

        # --- Step 2: Apply Snapping (to the newly modified frequencies) ---
        try:
            f_ref = float(edits['ref_pitch'])
        except (ValueError, TypeError):
            f_ref = 261.6256

        edo_str = edits['edo'].strip()
        ratio_str = edits['ratios'].strip()
        scale_str = edits['scale'].strip() # New line

        if edo_str:
            try:
                edo = int(edo_str)
                for spot in selected_points:
                    data = spot.data()
                    idx_mask = (self.data.df['time'] == float(data['time'])) & \
                               (self.data.df['harmonic_index'] == int(data['harmonic_index']))
                    current_freq = self.data.df.loc[idx_mask, 'frequency'].iloc[0]
                    if current_freq > 0:
                        n = edo * np.log2(current_freq / f_ref)
                        n_nearest = round(n)
                        new_freq = f_ref * (2 ** (n_nearest / edo))
                        self.data.df.loc[idx_mask, 'frequency'] = new_freq
            except (ValueError, TypeError):
                print(f"Invalid EDO value: {edo_str}")

        elif ratio_str:
            try:
                ratios = [float(Fraction(r.strip())) for r in ratio_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']
                
                for spot in selected_points:
                    data = spot.data()
                    idx_mask = (self.data.df['time'] == float(data['time'])) & \
                               (self.data.df['harmonic_index'] == int(data['harmonic_index']))
                    current_freq = self.data.df.loc[idx_mask, 'frequency'].iloc[0]
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
                        self.data.df.loc[idx_mask, 'frequency'] = closest_freq
            except Exception as e:
                print(f"Error parsing ratios: {e}")

        elif scale_str: # New Snap to Scale logic
            try:
                base_scale_ratios = [float(Fraction(r.strip())) for r in scale_str.split(',') if r.strip()]
                octave_repeat = edits['octave_repeat']

                for spot in selected_points:
                    data = spot.data()
                    idx_mask = (self.data.df['time'] == float(data['time'])) & \
                               (self.data.df['harmonic_index'] == int(data['harmonic_index']))
                    current_freq = self.data.df.loc[idx_mask, 'frequency'].iloc[0]
                    if current_freq <= 0: continue

                    harmonic_index = int(data['harmonic_index'])
                    
                    # Calculate the target scale for this harmonic index
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
                        self.data.df.loc[idx_mask, 'frequency'] = closest_freq
            except Exception as e:
                print(f"Error parsing scale or applying snap to scale: {e}")

        # --- Step 3: Finalize ---
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
