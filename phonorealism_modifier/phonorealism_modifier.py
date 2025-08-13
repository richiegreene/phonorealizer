"""
phonorealism_modifier.py

Phonorealism Modifier: Interactive plot with Pan, Box, Lasso tools and batch editing.
"""

import sys
import numpy as np
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QFileDialog, QToolBar,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout
)
from PySide6.QtGui import QAction, QPainter, QColor
from PySide6.QtCore import Qt, QRectF, QPointF
import pyqtgraph as pg

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

        # Tool management: 'pan', 'box', 'lasso'
        self.current_tool = 'pan'
        self.box_roi = None
        self.lasso_polygon = []
        self.temp_line = None

        self.setMouseEnabled(x=True, y=True)
        self.setMenuEnabled(False)
        self.setAspectLocked(False)
        self.setLimits(xMin=0, yMin=0)
        self.enableAutoRange()

        self._tooltip = pg.TextItem(anchor=(0,1), border='k', fill=(255,255,255,200))
        self.addItem(self._tooltip)
        self._tooltip.hide()

    def clear_plot(self):
        for item in self.harmonic_curves + self.scatter_items:
            self.removeItem(item)
        self.harmonic_curves.clear()
        self.scatter_items.clear()
        self.selected_points.clear()
        self.box_roi = None
        self.lasso_polygon.clear()

    def plot_harmonics(self, harmonic_data: HarmonicData):
        self.clear_plot()
        self.data = harmonic_data
        cmap = pg.colormap.get('viridis')
        for idx, group in harmonic_data.grouped.items():
            times = group['time'].values
            freqs = group['frequency'].values
            amps = group['amplitude'].values
            norm_amps = (amps - amps.min()) / (amps.max() - amps.min() + 1e-9)
            color = cmap.map(norm_amps, mode='qcolor')
            curve = pg.PlotDataItem(times, freqs, pen=pg.mkPen(color=color[-1], width=2))
            self.addItem(curve)
            self.harmonic_curves.append(curve)
            scatter = pg.ScatterPlotItem(times, freqs, pen=None, brush=color, size=8,
                                         data=group.to_dict('records'))
            self.addItem(scatter)
            self.scatter_items.append(scatter)

    def set_tool(self, tool_name):
        """Switch tool mode: 'pan', 'box', 'lasso'"""
        self.current_tool = tool_name
        if tool_name == 'pan':
            self.setMouseEnabled(x=True, y=True)
        else:
            self.setMouseEnabled(x=False, y=False)
        self.clear_temp_selection()

    # -------------------- Selection Logic -------------------- #
    def mousePressEvent(self, ev):
        pos = ev.position() if hasattr(ev, 'position') else ev.pos()
        if self.current_tool == 'box':
            self.box_start = self.plotItem.vb.mapSceneToView(pos)
            self.box_roi = pg.QtGui.QGraphicsRectItem()
            self.box_roi.setPen(pg.mkPen('r', width=2))
            self.plotItem.addItem(self.box_roi)
        elif self.current_tool == 'lasso':
            self.lasso_polygon = [self.plotItem.vb.mapSceneToView(pos)]
            self.temp_line = pg.PlotDataItem(pen=pg.mkPen('r', width=2))
            self.addItem(self.temp_line)
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = ev.position() if hasattr(ev, 'position') else ev.pos()
        if self.current_tool == 'box' and self.box_roi:
            current_pos = self.plotItem.vb.mapSceneToView(pos)
            x0 = min(self.box_start.x(), current_pos.x())
            y0 = min(self.box_start.y(), current_pos.y())
            w = abs(self.box_start.x() - current_pos.x())
            h = abs(self.box_start.y() - current_pos.y())
            self.box_roi.setRect(QRectF(x0, y0, w, h))
        elif self.current_tool == 'lasso' and self.temp_line:
            point = self.plotItem.vb.mapSceneToView(pos)
            self.lasso_polygon.append(point)
            xs = [p.x() for p in self.lasso_polygon]
            ys = [p.y() for p in self.lasso_polygon]
            self.temp_line.setData(xs, ys)
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.current_tool == 'box' and self.box_roi:
            rect = self.box_roi.rect()
            self.select_points_box(rect)
            self.plotItem.removeItem(self.box_roi)
            self.box_roi = None
        elif self.current_tool == 'lasso' and self.temp_line:
            self.select_points_lasso(self.lasso_polygon)
            self.removeItem(self.temp_line)
            self.temp_line = None
            self.lasso_polygon.clear()
        else:
            super().mouseReleaseEvent(ev)

    def clear_temp_selection(self):
        self.selected_points.clear()

    def select_points_box(self, rect):
        self.selected_points.clear()
        for scatter in self.scatter_items:
            for spot in scatter.points():
                pos = spot.pos()
                if rect.contains(QPointF(pos.x(), pos.y())):
                    self.selected_points.append(spot)
        self.highlight_selected()

    def select_points_lasso(self, polygon):
        from matplotlib.path import Path
        poly_path = Path([(p.x(), p.y()) for p in polygon])
        self.selected_points.clear()
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if poly_path.contains_point((spot.pos().x(), spot.pos().y())):
                    self.selected_points.append(spot)
        self.highlight_selected()

    def highlight_selected(self):
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if spot in self.selected_points:
                    spot.setBrush(pg.mkBrush(QColor(255,0,0)))
                else:
                    data = spot.data()
                    spot.setBrush(pg.mkBrush('b'))

    def update_selected_points(self, edits):
        for spot in self.selected_points:
            data = spot.data()
            idx = (self.data.df['time'] == float(data['time'])) & \
                  (self.data.df['frequency'] == float(data['frequency'])) & \
                  (self.data.df['amplitude'] == float(data['amplitude'])) & \
                  (self.data.df['harmonic_index'] == int(data['harmonic_index']))
            for key in ['time', 'frequency', 'amplitude']:
                val = edits.get(key)
                if val.strip() != '':
                    self.data.df.loc[idx, key] = float(val)
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
        self.plot_harmonics(self.data)

# -------------------- Main Window -------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Modifier")
        self.resize(1000, 700)
        self.data = HarmonicData()
        self.plot = HarmonicsPlot()
        self._init_ui()

    def _init_ui(self):
        toolbar = QToolBar("Tools")
        self.addToolBar(toolbar)

        open_action = QAction("Open CSV", self)
        open_action.triggered.connect(self.open_csv)
        toolbar.addAction(open_action)

        save_action = QAction("Save CSV", self)
        save_action.triggered.connect(self.save_csv)
        toolbar.addAction(save_action)

        pan_action = QAction("Pan/Zoom", self)
        pan_action.triggered.connect(lambda: self.plot.set_tool('pan'))
        toolbar.addAction(pan_action)

        box_action = QAction("Box Select", self)
        box_action.triggered.connect(lambda: self.plot.set_tool('box'))
        toolbar.addAction(box_action)

        lasso_action = QAction("Lasso Select", self)
        lasso_action.triggered.connect(lambda: self.plot.set_tool('lasso'))
        toolbar.addAction(lasso_action)

        batch_edit_action = QAction("Edit Selected", self)
        batch_edit_action.triggered.connect(self.batch_edit)
        toolbar.addAction(batch_edit_action)

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

    def batch_edit(self):
        if not self.plot.selected_points:
            QMessageBox.warning(self, "No Points Selected", "Please select points first.")
            return
        dlg = BatchEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            edits = dlg.get_data()
            self.plot.update_selected_points(edits)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())