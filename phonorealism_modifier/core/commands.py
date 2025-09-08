from PySide6.QtGui import QUndoCommand
import pandas as pd

class CompensationCommand(QUndoCommand):
    def __init__(self, data_model, harmonic_editor, waveform_harmonics, amount, description, parent=None):
        super().__init__(description, parent)
        self.data_model = data_model
        self.harmonic_editor = harmonic_editor
        self.waveform_harmonics = waveform_harmonics
        self.amount = amount
        self.original_df_copy = self.data_model.df.copy()

    def redo(self):
        self.harmonic_editor.apply_timbre_compensation(self.waveform_harmonics, self.amount)

    def undo(self):
        self.data_model.df = self.original_df_copy
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}
        self.data_model._modified = True

class RevertCommand(QUndoCommand):
    def __init__(self, data_model, harmonic_editor, description, parent=None):
        super().__init__(description, parent)
        self.data_model = data_model
        self.harmonic_editor = harmonic_editor
        self.original_df_copy = self.data_model.df.copy()

    def redo(self):
        self.harmonic_editor.revert_to_original()

    def undo(self):
        self.data_model.df = self.original_df_copy
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}
        self.data_model._modified = True

class EditCommand(QUndoCommand):
    def __init__(self, data_model, harmonic_editor, selected_points, edits, description, parent=None):
        super().__init__(description, parent)
        self.data_model = data_model
        self.harmonic_editor = harmonic_editor
        self.selected_points = selected_points
        self.edits = edits
        
        self.selected_indices = self.harmonic_editor.get_indices_from_points(self.selected_points)
        self.original_data = self.data_model.df.loc[self.selected_indices].copy()

    def redo(self):
        self.harmonic_editor.apply_batch_edits(self.selected_points, self.edits)

    def undo(self):
        self.data_model.df.loc[self.original_data.index, :] = self.original_data
        self.data_model._modified = True
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}

class DeleteCommand(QUndoCommand):
    def __init__(self, data_model, harmonic_editor, selected_points, description, parent=None):
        super().__init__(description, parent)
        self.data_model = data_model
        self.harmonic_editor = harmonic_editor
        self.selected_points = selected_points
        
        self.selected_indices = self.harmonic_editor.get_indices_from_points(self.selected_points)
        self.deleted_data = self.data_model.df.loc[self.selected_indices].copy()

    def redo(self):
        self.data_model.df.drop(self.selected_indices, inplace=True)
        self.data_model._modified = True
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}

    def undo(self):
        self.data_model.df = pd.concat([self.data_model.df, self.deleted_data]).sort_index()
        self.data_model._modified = True
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}

class InsertCommand(QUndoCommand):
    def __init__(self, data_model, new_df, insert_time, description, parent=None):
        super().__init__(description, parent)
        self.data_model = data_model
        self.new_df = new_df
        self.insert_time = insert_time
        self.inserted_indices = None

    def redo(self):
        self.inserted_indices = self.data_model.insert_data(self.new_df, self.insert_time)
        self.data_model._modified = True
        self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}

    def undo(self):
        if self.inserted_indices is not None:
            self.data_model.df.drop(self.inserted_indices, inplace=True)
            self.data_model._modified = True
            self.data_model.grouped = {idx: group.sort_values('time') for idx, group in self.data_model.df.groupby('harmonic_index')}
