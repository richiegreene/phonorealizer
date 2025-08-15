import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from matplotlib.path import Path

class HarmonicsPlot(pg.PlotWidget):
    plot_clicked_signal = Signal(float)

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
        self.cmap = pg.colormap.get('viridis')
        self.min_amp = 0
        self.max_amp = 1

        # Tool modes
        self.tool_mode = 'view'
        self.tool_radius = 50
        self._dragging = False
        self._drag_start = None
        self._lasso_points = []
        self._drag_modifications = {}

        # Timer for continuous tool application
        self.tool_timer = pg.QtCore.QTimer(self)
        self.tool_timer.timeout.connect(self._on_tool_timer)

        # Visual selection rectangle
        self.selection_rect = pg.QtWidgets.QGraphicsRectItem(0, 0, 0, 0)
        self.selection_rect.setPen(pg.mkPen('k', width=1, style=Qt.DashLine))
        self.selection_rect.setBrush(pg.mkBrush(100, 100, 255, 50))
        self.selection_rect.setZValue(100)
        self.addItem(self.selection_rect)
        self.selection_rect.setVisible(False)

        # Visual lasso path
        self.lasso_path = pg.PlotDataItem(pen=pg.mkPen('r', width=1, style=Qt.DashLine))
        self.addItem(self.lasso_path)
        self.lasso_path.setVisible(False)

        # Preview circle for Smooth/Dodge
        self.preview_circle = pg.ScatterPlotItem(size=self.tool_radius, pen=pg.mkPen('r', width=2), brush=pg.mkBrush(0,0,0,0))
        self.addItem(self.preview_circle)

        # Playback marker
        self.playback_marker = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=pg.mkPen('b', width=2))
        self.addItem(self.playback_marker)
        self.playback_marker.setVisible(False)

        self.getViewBox().setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self.getAxis('left').setLogMode(False)

    def clear_plot(self):
        for item in self.harmonic_curves + self.scatter_items:
            if item in self.items():
                self.removeItem(item)
        self.harmonic_curves.clear()
        self.scatter_items.clear()
        self.selected_points.clear()

    def plot_harmonics(self, harmonic_data):
        self.clear_plot()
        self.data = harmonic_data
        if self.data.df is None or self.data.df.empty:
            return
        
        self.min_amp = self.data.df['amplitude'].min()
        self.max_amp = self.data.df['amplitude'].max()

        for idx, group in self.data.grouped.items():
            times = group['time'].values
            freqs = group['frequency'].values
            freqs[freqs <= 0] = 1
            amps = group['amplitude'].values
            
            norm_amps = (amps - self.min_amp) / (self.max_amp - self.min_amp + 1e-9)
            color = [self.cmap.map(np.clip(a, 0, 1), mode='qcolor') for a in norm_amps]
            
            curve = pg.PlotDataItem(times, freqs, pen=pg.mkPen(color=color[-1], width=2))
            self.addItem(curve)
            self.harmonic_curves.append(curve)
            
            scatter = pg.ScatterPlotItem(times, freqs, pen=None, brush=color, size=8,
                                         data=group.to_dict('records'))
            self.addItem(scatter)
            self.scatter_items.append(scatter)
        self.autoRange()

    def box_select(self, rect: QRectF):
        self.selected_points.clear()
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if rect.contains(spot.pos()):
                    self.selected_points.append(spot)
        self.update_point_highlight()

    def lasso_select(self, polygon):
        if len(polygon) < 3:
            return
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

    def update_playback_marker(self, time_position):
        self.playback_marker.setPos(time_position)
        self.playback_marker.setVisible(True)

    def hide_playback_marker(self):
        self.playback_marker.setVisible(False)

    def wheelEvent(self, event):
        if self.tool_mode in ['smooth', 'dodge']:
            delta = event.angleDelta().y()
            if delta > 0:
                self.tool_radius *= 1.1
            else:
                self.tool_radius *= 0.9
            self.tool_radius = np.clip(self.tool_radius, 5, 200)
            self.preview_circle.setSize(self.tool_radius)
            pos = self.plotItem.vb.mapSceneToView(event.position())
            self.preview_circle.setData([pos.x()], [pos.y()])
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            if self.tool_mode == 'box':
                self._drag_start = self.plotItem.vb.mapSceneToView(event.position())
                self.selection_rect.setRect(QRectF(self._drag_start, self._drag_start))
                self.selection_rect.setVisible(True)
            elif self.tool_mode == 'lasso':
                self._drag_start = self.plotItem.vb.mapSceneToView(event.position())
                self._lasso_points = [self._drag_start]
                self.lasso_path.setData([p.x() for p in self._lasso_points], [p.y() for p in self._lasso_points])
                self.lasso_path.setVisible(True)
            elif self.tool_mode in ['smooth', 'dodge']:
                self._drag_modifications.clear()
                self._on_tool_timer()
                self.tool_timer.start(50)
            elif self.tool_mode == 'set_marker':
                pos = self.plotItem.vb.mapSceneToView(event.position())
                self.plot_clicked_signal.emit(pos.x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self.plotItem.vb.mapSceneToView(event.position())
        if self.tool_mode in ['smooth', 'dodge']:
            self.preview_circle.setData([pos.x()], [pos.y()])
        
        if not self._dragging:
            super().mouseMoveEvent(event)
            return

        if self.tool_mode == 'box':
            rect = QRectF(self._drag_start, pos).normalized()
            self.selection_rect.setRect(rect)
        elif self.tool_mode == 'lasso':
            self._lasso_points.append(pos)
            self.lasso_path.setData([p.x() for p in self._lasso_points], [p.y() for p in self._lasso_points])
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._dragging:
                if self.tool_mode == 'box':
                    rect = QRectF(self._drag_start, self.plotItem.vb.mapSceneToView(event.position())).normalized()
                    self.box_select(rect)
                    self.selection_rect.setVisible(False)
                elif self.tool_mode == 'lasso':
                    self.lasso_select(self._lasso_points)
                    self.lasso_path.setVisible(False)
                elif self.tool_mode in ['smooth', 'dodge']:
                    self.tool_timer.stop()
                    self._finalize_drag_modifications()

            self._dragging = False
            self._drag_start = None
            self._lasso_points = []
            self.preview_circle.setData([], [])
            self._drag_modifications.clear()
        super().mouseReleaseEvent(event)

    def pixel_to_plot_radius(self, pixel_radius):
        vb = self.plotItem.vb
        p1 = vb.mapSceneToView(QPointF(0,0))
        p2 = vb.mapSceneToView(QPointF(pixel_radius,0))
        return abs(p2.x()-p1.x())

    def _on_tool_timer(self):
        if not self._dragging:
            self.tool_timer.stop()
            return
        
        pos = self.mapSceneToView(self.mapFromGlobal(pg.QtGui.QCursor.pos()))
        
        if self.tool_mode == 'dodge':
            self._update_dodge_visuals(pos)
        elif self.tool_mode == 'smooth':
            self.apply_smooth(pos)

    def _update_dodge_visuals(self, pos):
        radius = self.pixel_to_plot_radius(self.tool_radius)
        increment = 0.5

        for scatter in self.scatter_items:
            for spot in scatter.points():
                p = spot.pos()
                if np.hypot(p.x() - pos.x(), p.y() - pos.y()) < radius:
                    current_amp = self._drag_modifications.get(spot, spot.data()['amplitude'])
                    new_amp = current_amp + increment
                    self._drag_modifications[spot] = new_amp

                    norm_amp = (new_amp - self.min_amp) / (self.max_amp - self.min_amp + 1e-9)
                    color = self.cmap.map(np.clip(norm_amp, 0, 1), mode='qcolor')
                    spot.setBrush(color)

    def _finalize_drag_modifications(self):
        if not self._drag_modifications:
            return

        for spot, new_value in self._drag_modifications.items():
            original_data = spot.data()
            mask = (self.data.df['time'] == original_data['time']) & \
                   (self.data.df['harmonic_index'] == original_data['harmonic_index'])
            self.data.df.loc[mask, 'amplitude'] = new_value
        
        self.data.grouped = {idx: group.sort_values('time') for idx, group in self.data.df.groupby('harmonic_index')}
        self.plot_harmonics(self.data)

    def apply_smooth(self, pos, radius=0.05):
        # This is still the old, slow method and can be updated later.
        radius = self.pixel_to_plot_radius(self.tool_radius)
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
            self.plot.plot_harmonics(self.data)
