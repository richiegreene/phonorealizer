import pandas as pd

class HarmonicData:
    def __init__(self):
        self.df = None
        self.grouped = None

    def load_csv(self, filepath):
        self.df = pd.read_csv(filepath)
        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(self.df.columns):
            raise ValueError(f"CSV missing required columns: {required_cols - set(self.df.columns)}")
        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}

    def export_csv(self, filepath):
        if self.df is not None:
            self.df.to_csv(filepath, index=False)
