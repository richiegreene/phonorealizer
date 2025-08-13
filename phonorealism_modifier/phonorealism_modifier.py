"""
phonorealism_modifier.py

Phonorealism Modifier: Interactive plot with point selection and editing.
"""

import sys
import numpy as np
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar, QMessageBox, QDialog, QFormLayout, QLineEdit, QPushButton
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
import pyqtgraph as pg

class HarmonicData:
    """
    Handles loading, storing, and exporting harmonic partial data from CSV.
    Maintains mapping from plot points to original CSV rows for future editing.
    """
    def __init__(self):
        self.df = None  # pandas DataFrame
        self.grouped = None  # dict: harmonic_index -> DataFrame

    def load_csv(self, filepath):
        self.df = pd.read_csv(filepath)
        required_cols = {'time', 'harmonic_index', 'frequency', 'amplitude'}
        if not required_cols.issubset(self.df.columns):
            raise ValueError(f"CSV missing required columns: {required_cols - set(self.df.columns)}")
        # Group by harmonic_index for plotting
        self.grouped = {idx: group.sort_values('time') for idx, group in self.df.groupby('harmonic_index')}

    def export_csv(self, filepath):
        if self.df is not None:
            self.df.to_csv(filepath, index=False)

class EditPointDialog(QDialog):
    def __init__(self, point_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Harmonic Point")
        self.result_data = None
        layout = QFormLayout(self)
        self.inputs = {}
        for key in ['time', 'harmonic_index', 'frequency', 'amplitude']:
            le = QLineEdit(str(point_data[key]))
            layout.addRow(key, le)
            self.inputs[key] = le
        btns = QWidget()
        btn_layout = QVBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        btns.setLayout(btn_layout)
        layout.addRow(btns)

    def get_data(self):
        return {k: self.inputs[k].text() for k in self.inputs}

class HarmonicsPlot(pg.PlotWidget):
    """
    Handles rendering of harmonics data using pyqtgraph.
    Each harmonic is a line, amplitude is mapped to color intensity.
    """
    def __init__(self, parent=None, on_point_clicked=None):
        super().__init__(parent)
        self.setBackground('w')
        self.showGrid(x=True, y=True)
        self.setLabel('bottom', 'Time', units='s')
        self.setLabel('left', 'Frequency', units='Hz')
        self.harmonic_curves = []
        self.data = None
        self.scatter_items = []
        self.setMouseEnabled(x=True, y=True)
        self.setMenuEnabled(False)
        self.setAspectLocked(False)
        self.setLimits(xMin=0, yMin=0)
        self.enableAutoRange()
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._tooltip = pg.TextItem(anchor=(0,1), border='k', fill=(255,255,255,200))
        self.addItem(self._tooltip)
        self._tooltip.hide()
        self.on_point_clicked = on_point_clicked

    def clear_plot(self):
        for item in self.harmonic_curves + self.scatter_items:
            self.removeItem(item)
        self.harmonic_curves.clear()
        self.scatter_items.clear()
        self._tooltip.hide()

    def plot_harmonics(self, harmonic_data: HarmonicData):
        self.clear_plot()
        self.data = harmonic_data
        cmap = pg.colormap.get('viridis')
        for idx, group in harmonic_data.grouped.items():
            times = group['time'].values
            freqs = group['frequency'].values
            amps = group['amplitude'].values
            # Normalize amplitude for color mapping
            norm_amps = (amps - amps.min()) / (amps.max() - amps.min() + 1e-9)
            color = cmap.map(norm_amps, mode='qcolor')
            # Draw line for each harmonic
            curve = pg.PlotDataItem(times, freqs, pen=pg.mkPen(color=color[-1], width=2), name=f"Harmonic {idx}")
            self.addItem(curve)
            self.harmonic_curves.append(curve)
            # Draw scatter points for tooltips and editing
            scatter = pg.ScatterPlotItem(times, freqs, pen=None, brush=color, size=8, data=group.to_dict('records'))
            scatter.sigClicked.connect(self._on_point_clicked)
            self.addItem(scatter)
            self.scatter_items.append(scatter)

    def _on_mouse_moved(self, pos):
        vb = self.getViewBox()
        if vb is None or not self.scatter_items:
            self._tooltip.hide()
            return
        mouse_point = vb.mapSceneToView(pos)
        x, y = mouse_point.x(), mouse_point.y()
        min_dist = float('inf')
        closest = None
        for scatter in self.scatter_items:
            spots = scatter.points()
            for spot in spots:
                sx, sy = spot.pos().x(), spot.pos().y()
                dist = (sx - x)**2 + (sy - y)**2
                if dist < min_dist and dist < 0.01:  # threshold for proximity
                    min_dist = dist
                    closest = spot
        if closest is not None:
            data = closest.data()
            text = f"Time: {data['time']:.3f}s\nFreq: {data['frequency']:.2f}Hz\nAmp: {data['amplitude']:.2f}\nHarmonic: {data['harmonic_index']}"
            self._tooltip.setText(text)
            self._tooltip.setPos(closest.pos().x(), closest.pos().y())
            self._tooltip.show()
        else:
            self._tooltip.hide()

    def _on_point_clicked(self, scatter, points):
        if self.on_point_clicked and points:
            self.on_point_clicked(points[0].data(), points[0])

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Modifier")
        self.resize(1000, 700)
        self.data = HarmonicData()
        self.plot = HarmonicsPlot(on_point_clicked=self.edit_point_dialog)
        self._init_ui()

    def _init_ui(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        open_action = QAction("Open CSV", self)
        open_action.triggered.connect(self.open_csv)
        toolbar.addAction(open_action)
        save_action = QAction("Save CSV", self)
        save_action.triggered.connect(self.save_csv)
        toolbar.addAction(save_action)
        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.plot)
        central.setLayout(layout)
        self.setCentralWidget(central)

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

    def edit_point_dialog(self, point_data, point_item):
        dlg = EditPointDialog(point_data, self)
        if dlg.exec() == QDialog.Accepted:
            new_data = dlg.get_data()
            # Update the DataFrame
            idx = (self.data.df['time'] == float(point_data['time'])) & \
                  (self.data.df['frequency'] == float(point_data['frequency'])) & \
                  (self.data.df['amplitude'] == float(point_data['amplitude'])) & \
                  (self.data.df['harmonic_index'] == int(point_data['harmonic_index']))
            for k in new_data:
                # Convert to correct dtype
                if k in ['time', 'frequency', 'amplitude']:
                    self.data.df.loc[idx, k] = float(new_data[k])
                elif k == 'harmonic_index':
                    self.data.df.loc[idx, k] = int(new_data[k])
            # Re-group and re-plot
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.plot.plot_harmonics(self.data)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())