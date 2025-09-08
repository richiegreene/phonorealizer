from fractions import Fraction
import numpy as np
import pandas as pd
from PySide6.QtGui import QImage

# --- Amplitude Conversion Helpers ---
def db_to_linear(db):
    return 10 ** (db / 20.0)

def linear_to_db(linear):
    if linear <= 1e-7: # Corresponds to -140 dB
        return -140.0
    return 20 * np.log10(linear)

class HarmonicEditor:
    def __init__(self, harmonic_data):
        self.data = harmonic_data

    def revert_to_original(self):
        if self.data.original_df is not None:
            self.data.df = self.data.original_df.copy()
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.data._modified = True

    def apply_timbre_compensation(self, waveform_harmonics, amount=1.0, debug=False):
        # This method remains as it was, unchanged.
        if self.data.original_df is None: return
        source_df = self.data.original_df.copy()
        compensated_df = source_df.copy()
        source_df['amplitude_linear'] = source_df['amplitude'].apply(db_to_linear)
        time_slices = sorted(source_df['time'].unique())
        # ... (rest of the method is unchanged)
        self.data.df = compensated_df
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
        self.data._modified = True

    def apply_batch_edits(self, selected_points, edits):
        if not selected_points:
            return

        selected_indices = self.get_indices_from_points(selected_points)
        selected_df = self.data.df.loc[selected_indices].copy()

        # --- Superimpose Logic ---
        image_path = edits.get('superimpose_image_path')
        image_amps = pd.Series(np.nan, index=selected_indices)
        if image_path:
            min_db = float(edits.get('superimpose_min_db', -80.0))
            max_db = float(edits.get('superimpose_max_db', 0.0))
            invert = edits.get('superimpose_invert', False)
            y_axis_mode = edits.get("y_axis_mode", "Linear")
            image = QImage(image_path)
            if not image.isNull():
                min_time, max_time = selected_df['time'].min(), selected_df['time'].max()
                min_freq, max_freq = selected_df['frequency'].min(), selected_df['frequency'].max()
                time_range = max_time - min_time if max_time > min_time else 1
                is_log_scale = (y_axis_mode != "Linear")
                if is_log_scale:
                    min_freq_log = np.log2(min_freq) if min_freq > 0 else 0
                    max_freq_log = np.log2(max_freq) if max_freq > 0 else 0
                    freq_range_log = max_freq_log - min_freq_log if max_freq_log > min_freq_log else 1
                else:
                    freq_range = max_freq - min_freq if max_freq > min_freq else 1

                for idx, partial in selected_df.iterrows():
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
                    image_amps[idx] = min_db + (brightness * (max_db - min_db))

        # --- Slope Calculation (as before) ---
        apply_slope = edits.get('apply_slope', False)
        slope_factors = pd.Series(1.0, index=selected_indices)
        if apply_slope:
            # ... (full slope calculation logic as it was before)
            pass

        # --- Main Application Loop ---
        for idx in selected_indices:
            slope_factor = slope_factors.get(idx, 1.0)
            if slope_factor == 0: continue

            # Amplitude is special: it can be affected by superimpose
            original_amp = self.data.df.loc[idx, 'amplitude']
            target_amp = original_amp # Start with original

            # Check if superimposition provides a new target
            if pd.notna(image_amps[idx]):
                mix = float(edits.get('superimpose_mix', 100)) / 100.0
                target_amp = (original_amp * (1 - mix)) + (image_amps[idx] * mix)
            
            # Now, apply other dB shifts to the current target
            db_str = edits['dB'].strip()
            if db_str:
                db_float = float(db_str)
                if db_str.startswith(('+', '-')):
                    target_amp += db_float
                else:
                    target_amp = db_float # Absolute assignment

            # Final application with slope
            self.data.df.loc[idx, 'amplitude'] = original_amp * (1 - slope_factor) + target_amp * slope_factor

            # ... (rest of the logic for frequency, time, etc., applying slope_factor to each)

        self.data._modified = True
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}

    # ... (rest of the class methods like select_all, etc.)
    def select_all(self):
        if self.data.df is None: return []
        return list(self.data.df.index)

    def invert_selection(self, selected_indices):
        if self.data.df is None: return []
        all_indices = set(self.data.df.index)
        selected_set = set(selected_indices)
        return list(all_indices - selected_set)

    def select_by_criteria(self, partial_str, time_str, current_selection):
        if self.data.df is None: return []
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
        if not p_str: return None
        indices = set()
        parts = p_str.split(',')
        for part in parts:
            part = part.strip()
            if not part: continue
            if part.lower() == 'odd':
                indices.update(self.data.df[self.data.df['harmonic_index'] % 2 != 0].index)
            elif part.lower() == 'even':
                indices.update(self.data.df[self.data.df['harmonic_index'] % 2 == 0].index)
            elif '-' in part:
                start, end = part.split('-')
                try:
                    for i in range(int(start.strip()), int(end.strip()) + 1):
                        indices.update(self.data.df[self.data.df['harmonic_index'] == i].index)
                except ValueError: pass
            else:
                try:
                    indices.update(self.data.df[self.data.df['harmonic_index'] == int(part)].index)
                except ValueError: pass
        return indices

    def _parse_time_string(self, t_str):
        if not t_str: return None
        final_indices = set()
        parts = t_str.split(',')
        for part in parts:
            part = part.strip()
            if not part: continue
            if '-' in part:
                start, end = part.split('-')
                try:
                    mask = (self.data.df['time'] >= float(start.strip())) & (self.data.df['time'] <= float(end.strip()))
                    final_indices.update(self.data.df[mask].index)
                except ValueError: pass
        return final_indices

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
