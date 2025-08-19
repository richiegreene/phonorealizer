from functools import partial
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))) # Add project root to path

import pandas as pd # Added import
from phonorealism_extractor.core.analyzer import analyze_audio # New import

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox, QDialog, QInputDialog # Added QInputDialog
)
from PySide6.QtGui import QAction, QKeySequence
from gui.selection_dialog import SelectionDialog
from PySide6.QtCore import Qt

from core.io import HarmonicData
from gui.batch_edit_dialog import BatchEditDialog
from gui.harmonics_plot import HarmonicsPlot
from gui.audio_player import AudioPlayer
from core.editor import HarmonicEditor

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Modifier")
        self.resize(1000, 700)
        self.data = HarmonicData()
        self.plot = HarmonicsPlot(self) # Pass self (MainWindow) as parent
        self.audio_player = AudioPlayer(self) # Pass self (MainWindow) as parent
        self.harmonic_editor = HarmonicEditor(self.data)
        self._init_ui()
        # Central widget
        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.plot)
        central.setLayout(layout)
        self.setCentralWidget(central)

        # Connect signals
        self.audio_player.playback_position_changed.connect(self.plot.update_playback_marker)
        self.plot.plot_clicked_signal.connect(self.set_playback_position_from_plot)

        self.set_marker_mode = False # Flag for setting playback marker
        self.clipboard_data = None # For copy/cut/paste

    def _init_ui(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        self.statusBar() # Initialize status bar

        # File actions
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_csv)
        self.toolbar.addAction(open_action)

        insert_action = QAction("Insert", self) # New action
        insert_action.triggered.connect(self.insert_csv) # Connect to new method
        self.toolbar.addAction(insert_action) # Add to toolbar

        save_action = QAction("Save", self)
        save_action.triggered.connect(self.save_csv)
        self.toolbar.addAction(save_action)

        self.play_action = QAction("Play", self)
        self.play_action.triggered.connect(lambda: self.audio_player.toggle_playback(self.data, self.play_action))
        self.toolbar.addAction(self.play_action)

        # Tool buttons
        self.tool_actions = {}
        for tool in ['view', 'box', 'lasso', 'select_partial']:
            if tool == 'select_partial':
                display_name = 'Select Partial'
            else:
                display_name = tool.capitalize()
            act = QAction(display_name, self)
            act.setCheckable(True)
            act.triggered.connect(partial(self.set_tool, tool))
            self.toolbar.addAction(act)
            self.tool_actions[tool] = act

        define_action = QAction("Define", self)
        define_action.triggered.connect(self.open_define_selection_dialog)
        self.toolbar.addAction(define_action)

        batch_edit_action = QAction("Edit Selected", self)
        batch_edit_action.triggered.connect(self.batch_edit)
        self.toolbar.addAction(batch_edit_action)

        # New: Y-axis Display Mode Toggle
        self.y_axis_mode_action = QAction("Log", self)
        self.y_axis_mode_action.setCheckable(True)
        self.y_axis_mode_action.setChecked(False) # Default to linear (Hz)
        self.y_axis_mode_action.triggered.connect(self.toggle_y_axis_mode)
        self.toolbar.addAction(self.y_axis_mode_action)

    def set_tool(self, tool):
        self.plot.tool_mode = tool
        is_view_mode = tool == 'view'
        self.plot.getViewBox().setMouseEnabled(x=is_view_mode, y=is_view_mode)
        for t, a in self.tool_actions.items():
            a.setChecked(t == tool)

    # New method
    def toggle_y_axis_mode(self):
        # After the button is clicked, its checked state has already flipped.
        # So, if it's now checked, it means we are going to Cents (Lin) mode.
        # If it's now unchecked, it means we are going to Hz (Log) mode.
        if self.y_axis_mode_action.isChecked(): # Now checked, so going to Cents (Lin)
            self.plot.set_y_axis_mode("Cents", 261.6256) # Fixed reference pitch
            self.y_axis_mode_action.setText("Lin") # Button should now say "Lin"
        else: # Now unchecked, so going to Hz (Log)
            self.plot.set_y_axis_mode("Hz", 261.6256) # Reference pitch doesn't matter for Hz
            self.y_axis_mode_action.setText("Log") # Button should now say "Log"

    def _process_audio_file(self, file_path, num_harmonics): # Added num_harmonics parameter
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.statusBar().showMessage("Analyzing audio, please wait...")
            
            # Analyze audio
            partials_data = analyze_audio(file_path, num_harmonics=num_harmonics)

            if not partials_data:
                QMessageBox.warning(self, "Analysis Failed", "No harmonic data extracted from the audio file.")
                return None

            # Convert partials data to DataFrame
            df_rows = []
            for harmonic_index, harmonic_points in enumerate(partials_data):
                for time, frequency, amplitude in harmonic_points:
                    df_rows.append({
                        'time': time,
                        'harmonic_index': harmonic_index + 1, # Harmonic index is 1-based
                        'frequency': frequency,
                        'amplitude': amplitude
                    })
            
            if not df_rows:
                QMessageBox.warning(self, "Analysis Failed", "No data points generated from audio analysis.")
                return None

            new_df = pd.DataFrame(df_rows)
            return new_df

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process audio file: {e}")
            return None
        finally:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

    def open_csv(self):
        file_filter = "All Supported Files (*.csv *.wav *.mp3 *.aif);;CSV Files (*.csv);;Audio Files (*.wav *.mp3 *.aif)"
        path, _ = QFileDialog.getOpenFileName(self, "Open Harmonic Data", "", file_filter)
        if not path:
            return

        file_extension = os.path.splitext(path)[1].lower()

        try:
            if file_extension in ['.wav', '.mp3', '.aif']:
                num_harmonics, ok = QInputDialog.getInt(self, "Number of Harmonics", "Enter the number of harmonic partials to analyze:", 32, 1, 128, 1)
                if not ok:
                    return # User cancelled
                df = self._process_audio_file(path, num_harmonics) # Pass num_harmonics
                if df is not None:
                    self.data.load_dataframe(df)
                    self.plot.plot_harmonics(self.data)
                    self.current_file_path = path
            elif file_extension == '.csv':
                self.data.load_csv(path)
                self.plot.plot_harmonics(self.data)
                self.current_file_path = path
            else:
                QMessageBox.warning(self, "Unsupported File Type", "Selected file type is not supported.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")

    def insert_csv(self):
        if self.data.df is None or self.data.df.empty:
            QMessageBox.warning(self, "No Data Loaded", "Please load an initial file before inserting.")
            return

        file_filter = "All Supported Files (*.csv *.wav *.mp3 *.aif);;CSV Files (*.csv);;Audio Files (*.wav *.mp3 *.aif)"
        path, _ = QFileDialog.getOpenFileName(self, "Insert Harmonic Data", "", file_filter)
        if not path:
            return

        file_extension = os.path.splitext(path)[1].lower()

        try:
            insert_time = self.audio_player.media_player.position() / 1000.0
            
            if file_extension in ['.wav', '.mp3', '.aif']:
                num_harmonics, ok = QInputDialog.getInt(self, "Number of Harmonics", "Enter the number of harmonic partials to analyze:", 32, 1, 128, 1)
                if not ok:
                    return # User cancelled
                new_df = self._process_audio_file(path, num_harmonics) # Pass num_harmonics
                if new_df is not None:
                    self.data.insert_data(new_df, insert_time)
                    self.plot.plot_harmonics(self.data)
                    QMessageBox.information(self, "Success", f"Audio data inserted at {insert_time:.2f} seconds.")
            elif file_extension == '.csv':
                new_df = pd.read_csv(path)
                self.data.insert_data(new_df, insert_time)
                self.plot.plot_harmonics(self.data)
                QMessageBox.information(self, "Success", f"CSV inserted at {insert_time:.2f} seconds.")
            else:
                QMessageBox.warning(self, "Unsupported File Type", "Selected file type is not supported for insertion.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to insert data:\n{e}")

    def save_csv(self):
        if hasattr(self, "current_file_path"):
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", self.current_file_path, "CSV Files (*.csv)")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            self.data.export_csv(path)
            QMessageBox.information(self, "Success", f"File saved to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    def batch_edit(self):
        if not self.plot.selected_points:
            QMessageBox.warning(self, "No Points Selected", "Please select points first.")
            return
        
        dlg = BatchEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            edits = dlg.get_data()
            
            self.harmonic_editor.apply_batch_edits(self.plot.selected_points, edits)
            self.plot.plot_harmonics(self.data)

    def copy_selected_harmonics(self):
        if not self.plot.selected_points:
            self.statusBar().showMessage("No points selected to copy.", 2000)
            return
        self.clipboard_data = self.data.get_selected_data(self.plot.selected_points)
        if not self.clipboard_data.empty:
            self.statusBar().showMessage(f"Copied {len(self.clipboard_data)} points.", 2000)
        else:
            self.statusBar().showMessage("No data copied.", 2000)

    def cut_selected_harmonics(self):
        if not self.plot.selected_points:
            self.statusBar().showMessage("No points selected to cut.", 2000)
            return
        self.copy_selected_harmonics()
        if not self.clipboard_data.empty:
            self.data.delete_selected_data(self.plot.selected_points)
            self.plot.selected_points.clear() # Clear selection after cutting
            self.plot.plot_harmonics(self.data)
            self.statusBar().showMessage(f"Cut {len(self.clipboard_data)} points.", 2000)
        else:
            self.statusBar().showMessage("No data cut.", 2000)

    def paste_harmonics(self):
        if self.clipboard_data is None or self.clipboard_data.empty:
            self.statusBar().showMessage("No data in clipboard to paste.", 2000)
            return
        
        insert_time = self.audio_player.media_player.position() / 1000.0
        try:
            self.data.insert_data(self.clipboard_data, insert_time)
            self.plot.plot_harmonics(self.data)
            self.statusBar().showMessage(f"Pasted {len(self.clipboard_data)} points at {insert_time:.2f}s.", 2000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to paste data:\n{e}")

    def delete_selected_harmonics(self):
        if not self.plot.selected_points:
            self.statusBar().showMessage("No points selected to delete.", 2000)
            return
        
        num_deleted = len(self.plot.selected_points)
        self.data.delete_selected_data(self.plot.selected_points)
        self.plot.selected_points.clear() # Clear selection after deleting
        self.plot.plot_harmonics(self.data)
        self.statusBar().showMessage(f"Deleted {num_deleted} points.", 2000)

    def open_define_selection_dialog(self):
        dlg = SelectionDialog(self, self)
        if dlg.exec():
            values = dlg.get_values()
            self.apply_defined_selection(values)

    def apply_defined_selection(self, values):
        if self.data.df is None or self.data.df.empty:
            self.statusBar().showMessage("No data loaded.", 2000)
            return

        partial_str = values.get("partial")
        time_str = values.get("time")

        selected_indices = self.harmonic_editor.select_by_criteria(
            partial_str, time_str, [p.data()['index'] for p in self.plot.selected_points]
        )
        
        new_selection = []
        for scatter in self.plot.scatter_items:
            for spot in scatter.points():
                if spot.data()['index'] in selected_indices:
                    new_selection.append(spot)

        self.plot.selected_points = new_selection
        self.plot.update_selection_visuals()
        self.statusBar().showMessage(f"{len(new_selection)} points selected.", 2000)

    def select_all_harmonics(self):
        if self.data.df is None or self.data.df.empty:
            self.statusBar().showMessage("No data loaded.", 2000)
            return
        selected_indices = self.harmonic_editor.select_all()
        new_selection = []
        for scatter in self.plot.scatter_items:
            for spot in scatter.points():
                if spot.data()['index'] in selected_indices:
                    new_selection.append(spot)
        self.plot.selected_points = new_selection
        self.plot.update_selection_visuals()
        self.statusBar().showMessage(f"{len(self.plot.selected_points)} points selected.", 2000)

    def invert_selection(self):
        if self.data.df is None or self.data.df.empty:
            self.statusBar().showMessage("No data loaded.", 2000)
            return
        selected_indices = self.harmonic_editor.invert_selection([p.data()['index'] for p in self.plot.selected_points])
        new_selection = []
        for scatter in self.plot.scatter_items:
            for spot in scatter.points():
                if spot.data()['index'] in selected_indices:
                    new_selection.append(spot)
        self.plot.selected_points = new_selection
        self.plot.update_selection_visuals()
        self.statusBar().showMessage(f"{len(self.plot.selected_points)} points selected.", 2000)

    def keyPressEvent(self, event):
        # Check for platform-specific modifiers (Cmd on macOS, Ctrl on others)
        is_modifier_pressed = (event.modifiers() & Qt.ControlModifier) or (event.modifiers() & Qt.MetaModifier)

        if is_modifier_pressed and event.key() == Qt.Key_A:
            self.select_all_harmonics()
        elif event.key() == Qt.Key_I:
            self.set_marker_mode = not self.set_marker_mode
            if self.set_marker_mode:
                QApplication.setOverrideCursor(Qt.CrossCursor)
                self.statusBar().showMessage("Playback marker mode: Click on plot to set playback position.")
            else:
                QApplication.restoreOverrideCursor()
                self.statusBar().clearMessage()
            self.plot.tool_mode = 'set_marker' if self.set_marker_mode else 'view' # Set plot tool mode
        elif event.key() == Qt.Key_P:
            self.audio_player.toggle_playback(self.data, self.play_action)
        elif is_modifier_pressed and event.key() == Qt.Key_C:
            self.copy_selected_harmonics()
        elif is_modifier_pressed and event.key() == Qt.Key_X:
            self.cut_selected_harmonics()
        elif is_modifier_pressed and event.key() == Qt.Key_V:
            self.paste_harmonics()
        elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            self.delete_selected_harmonics()
        elif event.key() == Qt.Key_V:
            self.set_tool('view')
        elif event.key() == Qt.Key_B:
            self.set_tool('box')
        elif event.key() == Qt.Key_L:
            self.set_tool('lasso')
        elif event.key() == Qt.Key_S:
            self.set_tool('select_partial')
        elif event.key() == Qt.Key_E:
            self.batch_edit()
        else:
            super().keyPressEvent(event)

    def set_playback_position_from_plot(self, time_position):
        self.audio_player.set_start_position(time_position)
        self.plot.update_playback_marker(time_position)
        self.set_marker_mode = False # Exit marker mode after setting
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
