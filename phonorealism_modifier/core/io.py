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

    def load_dataframe(self, dataframe):
        """
        Loads a pandas DataFrame directly into the HarmonicData object.
        Assumes the DataFrame has the required columns: 'time', 'harmonic_index', 'frequency', 'amplitude'.
        """
        self.df = dataframe
        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(self.df.columns):
            raise ValueError(f"DataFrame missing required columns: {required_cols - set(self.df.columns)}")
        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}
        self.dirty = True

    def export_csv(self, filepath):
        if self.df is not None:
            self.df.to_csv(filepath, index=False)

    def get_selected_data(self, selected_points):
        if not selected_points or self.df is None:
            return pd.DataFrame()

        selected_indices = []
        for spot in selected_points:
            # Assuming spot.data() contains 'time', 'frequency', 'amplitude', 'harmonic_index'
            # and these uniquely identify a row in self.df
            data = spot.data()
            # Find the index in the original DataFrame
            # This approach assumes unique combinations of these four columns for each point
            # A more robust solution might involve adding a unique ID to each row upon loading
            match = self.df[
                (self.df['time'] == data['time']) &
                (self.df['frequency'] == data['frequency']) &
                (self.df['amplitude'] == data['amplitude']) &
                (self.df['harmonic_index'] == data['harmonic_index'])
            ]
            if not match.empty:
                selected_indices.extend(match.index.tolist())
        
        if not selected_indices:
            return pd.DataFrame()

        # Return a copy of the selected data
        return self.df.loc[list(set(selected_indices))].copy()

    def delete_selected_data(self, selected_points):
        if not selected_points or self.df is None:
            return

        indices_to_drop = []
        for spot in selected_points:
            data = spot.data()
            match = self.df[
                (self.df['time'] == data['time']) &
                (self.df['frequency'] == data['frequency']) &
                (self.df['amplitude'] == data['amplitude']) &
                (self.df['harmonic_index'] == data['harmonic_index'])
            ]
            if not match.empty:
                indices_to_drop.extend(match.index.tolist())
        
        if indices_to_drop:
            self.df.drop(list(set(indices_to_drop)), inplace=True)
            self.df.reset_index(drop=True, inplace=True) # Reset index after dropping
            self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}
            self.dirty = True

    def insert_data(self, new_df, insert_time):
        if new_df.empty:
            return

        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(new_df.columns):
            raise ValueError(f"New data missing required columns: {required_cols - set(new_df.columns)}")

        # Ensure new_df has the same columns as self.df, fill missing with NaN or default if necessary
        # This is important for pd.concat to work correctly if new_df has fewer columns
        if self.df is not None and not self.df.empty:
            for col in self.df.columns:
                if col not in new_df.columns:
                    new_df[col] = pd.NA # Or some other default value

        if self.df is None or self.df.empty:
            self.df = new_df.copy()
            self.df['time'] = self.df['time'] + insert_time
        else:
            df_before_insert = self.df[self.df['time'] < insert_time].copy()
            df_after_insert = self.df[self.df['time'] >= insert_time].copy()

            new_data_duration = new_df['time'].max() - new_df['time'].min() if not new_df.empty else 0

            shifted_new_df = new_df.copy()
            shifted_new_df['time'] = shifted_new_df['time'] + insert_time

            shifted_df_after_insert = df_after_insert.copy()
            shifted_df_after_insert['time'] = shifted_df_after_insert['time'] + new_data_duration

            self.df = pd.concat([df_before_insert, shifted_new_df, shifted_df_after_insert], ignore_index=True)

        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}
        self.dirty = True
        self.dirty = True
