import pandas as pd

class HarmonicData:
    def __init__(self):
        self.df = None
        self.grouped = None
        self.dirty = True

    def load_csv(self, filepath):
        self.df = pd.read_csv(filepath)
        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(self.df.columns):
            raise ValueError(f"CSV missing required columns: {required_cols - set(self.df.columns)}")
        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}
        self.dirty = True

    def export_csv(self, filepath):
        if self.df is not None:
            self.df.to_csv(filepath, index=False)

    def insert_csv_data(self, new_df, insert_time):
        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(new_df.columns):
            raise ValueError(f"New CSV missing required columns: {required_cols - set(new_df.columns)}")

        if self.df is None or self.df.empty:
            # If no data exists, just load the new_df as the primary data
            self.df = new_df.copy()
            self.df['time'] = self.df['time'] + insert_time # Apply initial offset
        else:
            # Split existing data
            df_before_insert = self.df[self.df['time'] < insert_time].copy()
            df_after_insert = self.df[self.df['time'] >= insert_time].copy()

            # Calculate duration of the new data
            # Assuming new_df 'time' starts from 0 or relative to its own start
            new_data_duration = new_df['time'].max() - new_df['time'].min() if not new_df.empty else 0

            # Shift new data
            shifted_new_df = new_df.copy()
            shifted_new_df['time'] = shifted_new_df['time'] + insert_time

            # Shift existing data after insert_time
            shifted_df_after_insert = df_after_insert.copy()
            shifted_df_after_insert['time'] = shifted_df_after_insert['time'] + new_data_duration

            # Concatenate all parts
            self.df = pd.concat([df_before_insert, shifted_new_df, shifted_df_after_insert], ignore_index=True)

        # Re-group and mark dirty
        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}
        self.dirty = True
