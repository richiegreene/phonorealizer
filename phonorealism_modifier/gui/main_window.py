from functools import partial
import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox, QDialog
)
from PySide6.QtGui import QAction
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

    def _init_ui(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)
        self.statusBar() # Initialize status bar

        # File actions
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_csv)
        self.toolbar.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.triggered.connect(self.save_csv)
        self.toolbar.addAction(save_action)

        self.play_action = QAction("Play", self)
        self.play_action.triggered.connect(lambda: self.audio_player.toggle_playback(self.data, self.play_action))
        self.toolbar.addAction(self.play_action)

        # Tool buttons
        self.tool_actions = {}
        for tool in ['view', 'box', 'lasso', 'circle', 'select_partial']: # Removed 'smooth', 'dodge', added 'circle'
            # Special handling for 'select_partial' and 'circle' to display correctly
            if tool == 'select_partial':
                display_name = 'Select Partial'
            elif tool == 'circle':
                display_name = 'Circle'
            else:
                display_name = tool.capitalize()
            act = QAction(display_name, self)
            act.setCheckable(True)
            act.triggered.connect(partial(self.set_tool, tool))
            self.toolbar.addAction(act)
            self.tool_actions[tool] = act

        batch_edit_action = QAction("Edit Selected", self)
        batch_edit_action.triggered.connect(self.batch_edit)
        self.toolbar.addAction(batch_edit_action)

    def set_tool(self, tool):
        self.plot.tool_mode = tool
        is_view_mode = tool == 'view'
        self.plot.getViewBox().setMouseEnabled(x=is_view_mode, y=is_view_mode)
        for t, a in self.tool_actions.items():
            a.setChecked(t == tool)

    def open_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Harmonic CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            self.data.load_csv(path)
            self.plot.plot_harmonics(self.data)
            self.current_file_path = path
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")

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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_I:
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
        else:
            super().keyPressEvent(event)

    def set_playback_position_from_plot(self, time_position):
        self.audio_player.set_start_position(time_position)
        self.plot.update_playback_marker(time_position)
        self.set_marker_mode = False # Exit marker mode after setting
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
