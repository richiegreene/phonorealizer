from functools import partial
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))) # Add project root to path

import pandas as pd # Added import
from phonorealism_extractor.core.analyzer import analyze_audio # New import

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox, QDialog, QFormLayout, QSpinBox, QComboBox, QDialogButtonBox
)
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from gui.selection_dialog import SelectionDialog
from PySide6.QtCore import Qt

from core.io import HarmonicData
from gui.batch_edit_dialog import BatchEditDialog
from gui.harmonics_plot import HarmonicsPlot
from gui.audio_player import AudioPlayer
from core.editor import HarmonicEditor
from .export_dialog import ExportDialog
from core.exporter import Exporter
from .perform_window import PerformWindow
from .wavetable_dialog import WavetableDialog
from core.commands import EditCommand, DeleteCommand, InsertCommand, CompensationCommand, RevertCommand
from core.timbre import get_harmonic_profile

class AnalysisOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analysis Options")
        
        self.layout = QVBoxLayout(self)
        
        self.formLayout = QFormLayout()
        self.num_harmonics_spinbox = QSpinBox()
        self.num_harmonics_spinbox.setRange(1, 128)
        self.num_harmonics_spinbox.setValue(32)
        self.formLayout.addRow("Number of Harmonics:", self.num_harmonics_spinbox)
        
        self.analysis_mode_combo = QComboBox()
        self.analysis_mode_combo.addItems(["Spectral Bleed Through", "Isolated Harmonics", "Isolated Artifacts"])
        self.formLayout.addRow("Analysis Mode:", self.analysis_mode_combo)
        
        self.layout.addLayout(self.formLayout)
        
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        
        self.layout.addWidget(self.buttonBox)

    def get_options(self):
        return {
            "num_harmonics": self.num_harmonics_spinbox.value(),
            "analysis_mode": self.analysis_mode_combo.currentText()
        }

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Modifier")
        self.resize(1000, 700)
        self.undo_stack = QUndoStack(self)
        self.data = HarmonicData()
        self.plot = HarmonicsPlot(self) # Pass self (MainWindow) as parent
        self.audio_player = AudioPlayer(self) # Pass self (MainWindow) as parent
        self.harmonic_editor = HarmonicEditor(self.data)
        self.exporter = Exporter(self.data)
        self.perform_window = None
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
        self.undo_stack.indexChanged.connect(lambda: self.plot.plot_harmonics(self.data))


        self.set_marker_mode = False # Flag for setting playback marker
        self.clipboard_data = None # For copy/cut/paste

    def _init_ui(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        self.statusBar() # Initialize status bar

        # Undo/Redo actions
        undo_action = self.undo_stack.createUndoAction(self, "&Undo")
        undo_action.setShortcuts(QKeySequence.StandardKey.Undo)
        undo_action.setStatusTip("Undo the last action.")
        redo_action = self.undo_stack.createRedoAction(self, "&Redo")
        redo_action.setShortcuts(QKeySequence.StandardKey.Redo)
        redo_action.setStatusTip("Redo the last undone action.")
        self.addAction(undo_action)
        self.addAction(redo_action)

        # File actions
        open_action = QAction("Open", self)
        open_action.setStatusTip("Open a harmonic data file (.csv, .wav, .mp3, .aif).")
        open_action.triggered.connect(self.open_csv)
        self.toolbar.addAction(open_action)

        insert_action = QAction("Insert", self)
        insert_action.setStatusTip("Insert a harmonic data file at the current playback position.")
        insert_action.triggered.connect(self.insert_csv)
        self.toolbar.addAction(insert_action)

        save_action = QAction("Save", self)
        save_action.setStatusTip("Save the current harmonic data.")
        save_action.triggered.connect(self.save_action)
        self.toolbar.addAction(save_action)

        wavetable_action = QAction("Wavetable", self)
        wavetable_action.setStatusTip("Open wavetable synthesizer settings.")
        wavetable_action.triggered.connect(self.open_wavetable_dialog)
        self.toolbar.addAction(wavetable_action)

        self.play_action = QAction("Play", self)
        self.play_action.setStatusTip("Play or pause the audio.")
        self.play_action.triggered.connect(lambda: self.audio_player.toggle_playback(self.data, self.play_action))
        self.toolbar.addAction(self.play_action)

        # Tool buttons
        self.tool_actions = {}
        tool_tips = {
            'view': 'Pan and zoom the view.',
            'box': 'Select points by dragging a rectangle.',
            'lasso': 'Select points by drawing a freeform shape.',
            'select_partial': 'Select an entire partial with a single click.'
        }
        for tool in ['view', 'box', 'lasso', 'select_partial']:
            if tool == 'select_partial':
                display_name = 'Partial'
            else:
                display_name = tool.capitalize()
            act = QAction(display_name, self)
            act.setCheckable(True)
            act.setStatusTip(tool_tips.get(tool, ''))
            act.triggered.connect(partial(self.set_tool, tool))
            self.toolbar.addAction(act)
            self.tool_actions[tool] = act

        define_action = QAction("Define", self)
        define_action.setStatusTip("Define a selection using specific criteria.")
        define_action.triggered.connect(self.open_define_selection_dialog)
        self.toolbar.addAction(define_action)

        batch_edit_action = QAction("Selected", self)
        batch_edit_action.setStatusTip("Open the batch editing dialog for selected points.")
        batch_edit_action.triggered.connect(self.batch_edit)
        self.toolbar.addAction(batch_edit_action)

        self.y_axis_mode_action = QAction("Log", self)
        self.y_axis_mode_action.setCheckable(True)
        self.y_axis_mode_action.setChecked(False)
        self.y_axis_mode_action.setStatusTip("Toggle the frequency axis between logarithmic (Cents) and linear (Hz) scales.")
        self.y_axis_mode_action.triggered.connect(self.toggle_y_axis_mode)
        self.toolbar.addAction(self.y_axis_mode_action)

        perform_action = QAction("Perform", self)
        perform_action.setStatusTip("Open the real-time performance window.")
        perform_action.triggered.connect(self.open_perform_window)
        self.toolbar.addAction(perform_action)

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

    def _process_audio_file(self, file_path, num_harmonics, analysis_mode="Isolated Harmonics"):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.statusBar().showMessage("Analyzing audio, please wait...")
            
            # Analyze audio
            partials_data = analyze_audio(file_path, num_harmonics=num_harmonics, analysis_mode=analysis_mode)

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
            QMessageBox.critical(self, "Error", f"Failed to process audio file: {str(e)}")
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
                dialog = AnalysisOptionsDialog(self)
                if dialog.exec():
                    options = dialog.get_options()
                    df = self._process_audio_file(path, options["num_harmonics"], options["analysis_mode"])
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
            
            new_df = None
            if file_extension in ['.wav', '.mp3', '.aif']:
                dialog = AnalysisOptionsDialog(self)
                if dialog.exec():
                    options = dialog.get_options()
                    new_df = self._process_audio_file(path, options["num_harmonics"], options["analysis_mode"])
            elif file_extension == '.csv':
                new_df = pd.read_csv(path)
            else:
                QMessageBox.warning(self, "Unsupported File Type", "Selected file type is not supported for insertion.")
                return

            if new_df is not None:
                command = InsertCommand(self.data, new_df, insert_time, "Insert Data")
                self.undo_stack.push(command)
                QMessageBox.information(self, "Success", f"Data inserted at {insert_time:.2f} seconds.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to insert data:\n{e}")

    def save_action(self):
        dialog = ExportDialog(self)
        if dialog.exec():
            settings = dialog.get_settings()
            wavetable = None
            if hasattr(self, 'wavetable_dialog') and self.wavetable_dialog is not None:
                wavetable = self.wavetable_dialog.get_wavetable()
            self.export_files(settings, wavetable)

    def export_files(self, settings, wavetable=None):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Exported Files", "", "All Files (*.*)")
        if file_path:
            self.exporter.export(settings, file_path, wavetable=wavetable)
            self.data.reset_modified()

    def batch_edit(self):
        if not self.plot.selected_points:
            QMessageBox.warning(self, "No Points Selected", "Please select points first.")
            return
        
        dlg = BatchEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            edits = dlg.get_data()
            
            command = EditCommand(self.data, self.harmonic_editor, self.plot.selected_points, edits, "Batch Edit")
            self.undo_stack.push(command)

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
        if self.clipboard_data is not None and not self.clipboard_data.empty:
            command = DeleteCommand(self.data, self.harmonic_editor, self.plot.selected_points, "Cut Harmonics")
            self.undo_stack.push(command)
            self.plot.selected_points.clear()
            self.statusBar().showMessage(f"Cut {len(command.selected_indices)} points.", 2000)
        else:
            self.statusBar().showMessage("No data cut.", 2000)

    def paste_harmonics(self):
        if self.clipboard_data is None or self.clipboard_data.empty:
            self.statusBar().showMessage("No data in clipboard to paste.", 2000)
            return
        
        insert_time = self.audio_player.media_player.position() / 1000.0
        
        command = InsertCommand(self.data, self.clipboard_data, insert_time, "Paste Harmonics")
        self.undo_stack.push(command)
        self.statusBar().showMessage(f"Pasted {len(self.clipboard_data)} points at {insert_time:.2f}s.", 2000)

    def delete_selected_harmonics(self):
        if not self.plot.selected_points:
            self.statusBar().showMessage("No points selected to delete.", 2000)
            return
        
        command = DeleteCommand(self.data, self.harmonic_editor, self.plot.selected_points, "Delete Harmonics")
        self.undo_stack.push(command)
        self.plot.selected_points.clear()
        self.statusBar().showMessage(f"Deleted {len(command.selected_indices)} points.", 2000)

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

    def open_wavetable_dialog(self):
        if not hasattr(self, 'wavetable_dialog') or self.wavetable_dialog is None:
            self.wavetable_dialog = WavetableDialog(self)
        self.wavetable_dialog.show()

    def open_perform_window(self):
        if self.perform_window is None or not self.perform_window.isVisible():
            self.perform_window = PerformWindow(self.data, self)
            self.perform_window.show()
        else:
            self.perform_window.activateWindow()

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
        elif is_modifier_pressed and (event.modifiers() & Qt.ShiftModifier) and event.key() == Qt.Key_T:
            self.print_selected_points_traceback()
        else:
            super().keyPressEvent(event)

    def print_selected_points_traceback(self):
        print("--- Selected Points Traceback ---")
        if not self.plot.selected_points:
            print("No points currently selected.")
            return

        for i, spot in enumerate(self.plot.selected_points):
            data = spot.data()
            print(f"Point {i+1}: Time={data.get('time', 'N/A'):.4f}s, "
                  f"Frequency={data.get('frequency', 'N/A'):.4f}Hz, "
                  f"Amplitude={data.get('amplitude', 'N/A'):.4f}dB, "
                  f"Harmonic Index={data.get('harmonic_index', 'N/A')}")
        print("-----------------------------------")

    def set_playback_position_from_plot(self, time_position):
        self.audio_player.set_start_position(time_position)
        self.plot.update_playback_marker(time_position)
        self.set_marker_mode = False # Exit marker mode after setting
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
