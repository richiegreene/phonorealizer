from functools import partial
import os
import sys

from PySide6.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox
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
        self.plot = HarmonicsPlot()
        self.audio_player = AudioPlayer(self) # Pass self (MainWindow) as parent
        self.harmonic_editor = HarmonicEditor(self.data)
        self._init_ui()
        # Central widget
        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.plot)
        central.setLayout(layout)
        self.setCentralWidget(central)

    def _init_ui(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.toolbar)

        # File actions
        open_action = QAction("Open CSV", self)
        open_action.triggered.connect(self.open_csv)
        self.toolbar.addAction(open_action)

        save_action = QAction("Save CSV", self)
        save_action.triggered.connect(self.save_csv)
        self.toolbar.addAction(save_action)

        self.play_action = QAction("Play Audio", self)
        self.play_action.triggered.connect(lambda: self.audio_player.toggle_playback(self.data, self.play_action))
        self.toolbar.addAction(self.play_action)

        # Tool buttons
        self.tool_actions = {}
        for tool in ['view', 'box', 'lasso', 'smooth', 'dodge']:
            act = QAction(tool.capitalize(), self)
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
        if dlg.exec() == dlg.Accepted:
            edits = dlg.get_data()
            self.harmonic_editor.apply_batch_edits(self.plot.selected_points, edits)
            self.plot.plot_harmonics(self.data)
