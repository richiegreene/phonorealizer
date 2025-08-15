"""
phonorealism_modifier.py

Phonorealism Modifier: Interactive plot with selection, smoothing, Dodge/Burn amplitude, 
and live preview circle for tools.
"""

import sys
from functools import partial
import numpy as np
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QPointF, QRectF
import pyqtgraph as pg
from matplotlib.path import Path

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

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Edit Selected Points")
        layout = QFormLayout(self)
        self.inputs = {}
        for key in ['time', 'frequency', 'amplitude']:
            le = QLineEdit()
            le.setPlaceholderText("Leave blank to skip")
            layout.addRow(key, le)
            self.inputs[key] = le

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self):
        return {k: self.inputs[k].text() for k in self.inputs}

class HarmonicsPlot(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground('w')
        self.showGrid(x=True, y=True)
        self.setLabel('bottom', 'Time', units='s')
        self.setLabel('left', 'Frequency', units='Hz')

        self.harmonic_curves = []
        self.scatter_items = []
        self.data = None
        self.selected_points = []

        # Tool modes
        self.tool_mode = 'view'  # 'view', 'box', 'lasso', 'smooth', 'dodge'
        self._dragging = False
        self._drag_start = None
        self._lasso_points = []

        # Visual selection rectangle
        self.selection_rect = pg.QtWidgets.QGraphicsRectItem(0, 0, 0, 0)
        self.selection_rect.setPen(pg.mkPen('k', width=1, style=Qt.DashLine))
        self.selection_rect.setBrush(pg.mkBrush(100, 100, 255, 50))
        self.selection_rect.setZValue(100) # Ensure it's drawn on top
        self.addItem(self.selection_rect)
        self.selection_rect.setVisible(False)

        # Visual lasso path
        self.lasso_path = pg.PlotDataItem(pen=pg.mkPen('r', width=1, style=Qt.DashLine))
        self.addItem(self.lasso_path)
        self.lasso_path.setVisible(False)

        # Preview circle for Smooth/Dodge
        self.preview_circle = pg.ScatterPlotItem(size=20, pen=pg.mkPen('r', width=2), brush=pg.mkBrush(0,0,0,0))
        self.addItem(self.preview_circle)

        # Disable default right/left drag
        self.getViewBox().setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self.getAxis('left').setLogMode(False)

    def clear_plot(self):
        for item in self.harmonic_curves + self.scatter_items:
            self.removeItem(item)
        self.harmonic_curves.clear()
        self.scatter_items.clear()
        self.selected_points.clear()

    def plot_harmonics(self, harmonic_data: HarmonicData):
        self.clear_plot()
        self.data = harmonic_data
        cmap = pg.colormap.get('viridis')
        for idx, group in harmonic_data.grouped.items():
            times = group['time'].values
            freqs = group['frequency'].values
            freqs[freqs <= 0] = 1  # Avoid log(0) issues
            amps = group['amplitude'].values
            norm_amps = (amps - amps.min()) / (amps.max() - amps.min() + 1e-9)
            color = [cmap.map(a, mode='qcolor') for a in norm_amps]
            curve = pg.PlotDataItem(times, freqs, pen=pg.mkPen(color=color[-1], width=2))
            self.addItem(curve)
            self.harmonic_curves.append(curve)
            scatter = pg.ScatterPlotItem(times, freqs, pen=None, brush=color, size=8,
                                         data=group.to_dict('records'))
            self.addItem(scatter)
            self.scatter_items.append(scatter)
        self.autoRange()

    # -------------------- Selection Tools --------------------
    def box_select(self, rect: QRectF):
        self.selected_points.clear()
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if rect.contains(spot.pos()):
                    self.selected_points.append(spot)
        self.update_point_highlight()

    def lasso_select(self, polygon):
        poly_path = Path([(p.x(), p.y()) for p in polygon])
        self.selected_points.clear()
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if poly_path.contains_point((spot.pos().x(), spot.pos().y())):
                    self.selected_points.append(spot)
        self.update_point_highlight()

    def update_point_highlight(self):
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if spot in self.selected_points:
                    spot.setPen(pg.mkPen('r', width=2))
                else:
                    spot.setPen(None)

    def _freq_to_spn_label(self, freq):
        if freq <= 0:
            return ""

        midi_note_float = 69 + 12 * np.log2(freq / 440.0)
        midi_note = int(round(midi_note_float))
        
        cents_deviation = int(round((midi_note_float - midi_note) * 100))

        octave = (midi_note // 12) - 1
        note_index = midi_note % 12
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        note_name = note_names[note_index]

        if note_name == "C":
            return f"C<sub>{octave}</sub>"
        else:
            sign = "+" if cents_deviation >= 0 else ""
            return f"{note_name}{octave} {sign}{cents_deviation}c"

    # -------------------- Mouse Events --------------------
    def mousePressEvent(self, event):
        pos = self.plotItem.vb.mapSceneToView(event.position())
        if event.button() == Qt.LeftButton:
            if self.tool_mode == 'box':
                self._dragging = True
                self._drag_start = pos
                self.selection_rect.setRect(QRectF(self._drag_start, self._drag_start))
                self.selection_rect.setVisible(True)
            elif self.tool_mode == 'lasso':
                self._dragging = True
                self._drag_start = pos
                self._lasso_points = [pos]
                self.lasso_path.setData([p.x() for p in self._lasso_points], [p.y() for p in self._lasso_points])
                self.lasso_path.setVisible(True)
            elif self.tool_mode in ['smooth', 'dodge']:
                self._dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self.plotItem.vb.mapSceneToView(event.position())
        # Update preview circle
        if self.tool_mode in ['smooth', 'dodge']:
            radius = self.pixel_to_plot_radius(50)  # 50 pixels
            self.preview_circle.setData([pos.x()], [pos.y()])
            self.preview_circle.setSize(radius*1000)
        if self._dragging:
            if self.tool_mode == 'box':
                rect = QRectF(self._drag_start, pos).normalized()
                self.selection_rect.setRect(rect)
            elif self.tool_mode == 'lasso':
                self._lasso_points.append(pos)
                self.lasso_path.setData([p.x() for p in self._lasso_points], [p.y() for p in self._lasso_points])
            elif self.tool_mode == 'smooth':
                self.apply_smooth(pos)
            elif self.tool_mode == 'dodge':
                self.apply_dodge(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.tool_mode == 'box' and self._dragging:
                rect = QRectF(self._drag_start, self.plotItem.vb.mapSceneToView(event.position())).normalized()
                self.box_select(rect)
                self.selection_rect.setVisible(False)
            elif self.tool_mode == 'lasso' and self._dragging:
                self.lasso_select(self._lasso_points)
                self.lasso_path.setVisible(False)

            self._dragging = False
            self._drag_start = None
            self._lasso_points = []
            self.preview_circle.setData([], [])
        super().mouseReleaseEvent(event)

    def pixel_to_plot_radius(self, pixel_radius):
        vb = self.plotItem.vb
        p1 = vb.mapSceneToView(QPointF(0,0))
        p2 = vb.mapSceneToView(QPointF(pixel_radius,0))
        return abs(p2.x()-p1.x())

    # -------------------- Editing Tools --------------------
    def apply_smooth(self, pos, radius=0.05):
        radius = self.pixel_to_plot_radius(50)
        modified = False
        for scatter in self.scatter_items:
            for spot in scatter.points():
                p = spot.pos()
                dist = np.hypot(p.x() - pos.x(), p.y() - pos.y())
                if dist < radius:
                    data = spot.data()
                    if data:
                        mask = (self.data.df['time'] == data['time']) & (self.data.df['harmonic_index'] == data['harmonic_index'])
                        self.data.df.loc[mask, 'frequency'] = (self.data.df.loc[mask, 'frequency'] + pos.y()) / 2
                        modified = True
        if modified:
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.plot_harmonics(self.data)

    def apply_dodge(self, pos, radius=0.05, increment=0.1):
        radius = self.pixel_to_plot_radius(50)
        modified = False
        for scatter in self.scatter_items:
            for spot in scatter.points():
                p = spot.pos()
                dist = np.hypot(p.x() - pos.x(), p.y() - pos.y())
                if dist < radius:
                    data = spot.data()
                    if data:
                        mask = (self.data.df['time'] == data['time']) & (self.data.df['harmonic_index'] == data['harmonic_index'])
                        self.data.df.loc[mask, 'amplitude'] += increment
                        modified = True
        if modified:
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.plot_harmonics(self.data)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Modifier")
        self.resize(1000, 700)
        self.data = HarmonicData()
        self.plot = HarmonicsPlot()
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
        if dlg.exec() == QDialog.Accepted:
            edits = dlg.get_data()
            for spot in self.plot.selected_points:
                data = spot.data()
                idx = (self.data.df['time'] == float(data['time'])) & \
                      (self.data.df['frequency'] == float(data['frequency'])) & \
                      (self.data.df['amplitude'] == float(data['amplitude'])) & \
                      (self.data.df['harmonic_index'] == int(data['harmonic_index']))
                for key, val in edits.items():
                    if val.strip() != '':
                        self.data.df.loc[idx, key] = float(val)
            self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
            self.plot.plot_harmonics(self.data)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
