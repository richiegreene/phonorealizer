import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from matplotlib.path import Path

class HarmonicsPlot(pg.PlotWidget):
    plot_clicked_signal = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground('k')
        self.showGrid(x=True, y=True)
        self.setLabel('bottom', 'Time', units='s')
        self.setLabel('left', 'Frequency', units='Hz')

        self.harmonic_curves = []
        self.scatter_items = []
        self.data = None
        self.selected_points = []
        self._shift_pressed = False # New: To store shift key state
        self._remove_from_selection = False # New: To store shift-command key state
        self.cmap = pg.colormap.get('inferno')
        self.min_amp = 0
        self.max_amp = 1

        # Tool modes
        self.tool_mode = 'view'
        self.tool_radius = 50
        self._dragging = False
        self._drag_start = None # Will store the start position of the drag
        self._lasso_points = []

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
            
            group_data = group.reset_index().to_dict('records')

            scatter = pg.ScatterPlotItem(times, freqs, pen=None, brush=color, size=8,
                                         data=group_data)
            self.addItem(scatter)
            self.scatter_items.append(scatter)
        self.autoRange()

    def box_select(self, rect: QRectF, clear_selection: bool = True, remove_from_selection: bool = False):
        print(f"box_select: clear_selection={clear_selection}, remove_from_selection={remove_from_selection}")
        if clear_selection:
            print("  box_select: Clearing selection.")
            self.selected_points.clear()
        
        newly_affected = []
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if rect.contains(spot.pos()):
                    newly_affected.append(spot)
        
        if remove_from_selection:
            print(f"  box_select: Removing {len(newly_affected)} points from selection.")
            self.selected_points = [p for p in self.selected_points if p not in newly_affected]
        else:
            print(f"  box_select: Adding {len(newly_affected)} points to selection.")
            # Add only unique points to selected_points
            for spot in newly_affected:
                if spot not in self.selected_points:
                    self.selected_points.append(spot)
        self.update_point_highlight()

    def lasso_select(self, polygon, clear_selection: bool = True, remove_from_selection: bool = False):
        print(f"lasso_select: clear_selection={clear_selection}, remove_from_selection={remove_from_selection}")
        if len(polygon) < 3:
            return
        poly_path = Path([(p.x(), p.y()) for p in polygon])
        
        if clear_selection:
            print("  lasso_select: Clearing selection.")
            self.selected_points.clear()
        
        newly_affected = []
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if poly_path.contains_point((spot.pos().x(), spot.pos().y())):
                    newly_affected.append(spot)
        
        if remove_from_selection:
            print(f"  lasso_select: Removing {len(newly_affected)} points from selection.")
            self.selected_points = [p for p in self.selected_points if p not in newly_affected]
        else:
            print(f"  lasso_select: Adding {len(newly_affected)} points to selection.")
            # Add only unique points to selected_points
            for spot in newly_affected:
                if spot not in self.selected_points:
                    self.selected_points.append(spot)
        self.update_point_highlight()

    def update_point_highlight(self):
        for scatter in self.scatter_items:
            for spot in scatter.points():
                if spot in self.selected_points:
                    spot.setPen(pg.mkPen('r', width=2))
                else:
                    spot.setPen(None)

    def select_partial(self, pos, clear_selection: bool = True, remove_from_selection: bool = False):
        print(f"select_partial: clear_selection={clear_selection}, remove_from_selection={remove_from_selection}")
        # Find the closest point to the click
        closest_spot = None
        min_dist_sq = float('inf')
        for scatter in self.scatter_items:
            for spot in scatter.points():
                p = spot.pos()
                dist_sq = (p.x() - pos.x())**2 + (p.y() - pos.y())**2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    closest_spot = spot

        if closest_spot:
            clicked_harmonic_index = closest_spot.data()['harmonic_index']
            
            # Collect points for this harmonic_index
            harmonic_points = []
            for scatter in self.scatter_items:
                for spot in scatter.points():
                    if spot.data()['harmonic_index'] == clicked_harmonic_index:
                        harmonic_points.append(spot)
            
            if remove_from_selection:
                print(f"  select_partial: Removing {len(harmonic_points)} points from selection.")
                self.selected_points = [p for p in self.selected_points if p not in harmonic_points]
            elif clear_selection:
                print(f"  select_partial: Clearing selection and adding {len(harmonic_points)} points.")
                self.selected_points.clear()
                self.selected_points.extend(harmonic_points) # Add all points of the harmonic
            else: # Shift is pressed, so add/toggle
                print(f"  select_partial: Shift pressed, adding/toggling {len(harmonic_points)} points.")
                # Check if all points of this harmonic are already selected
                all_selected = all(p in self.selected_points for p in harmonic_points)
                if all_selected:
                    # If all are selected, deselect them
                    print("    select_partial: All points already selected, deselecting.")
                    self.selected_points = [p for p in self.selected_points if p not in harmonic_points]
                else:
                    # Otherwise, add any unselected points from this harmonic
                    print("    select_partial: Adding unselected points.")
                    for p in harmonic_points:
                        if p not in self.selected_points:
                            self.selected_points.append(p)
            
            self.update_point_highlight()

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
            modifiers = event.modifiers()
            self._shift_pressed = bool(modifiers & Qt.ShiftModifier and not (modifiers & Qt.ControlModifier)) # Shift only (not with Command)
            self._remove_from_selection = bool(modifiers & Qt.ShiftModifier and modifiers & Qt.ControlModifier) # Shift + Command

            print(f"mousePressEvent: Modifiers: {modifiers}, Shift: {self._shift_pressed}, Remove: {self._remove_from_selection}")

            if self.tool_mode == 'box':
                self._drag_start = self.plotItem.vb.mapSceneToView(event.position())
                self.selection_rect.setRect(QRectF(self._drag_start, self._drag_start))
                self.selection_rect.setVisible(True)
            elif self.tool_mode == 'lasso':
                self._drag_start = self.plotItem.vb.mapSceneToView(event.position())
                self._lasso_points = [self._drag_start]
                self.lasso_path.setData([p.x() for p in self._lasso_points], [p.y() for p in self._lasso_points])
                self.lasso_path.setVisible(True)
            elif self.tool_mode == 'circle': # New condition for circle tool
                self._drag_start = self.plotItem.vb.mapSceneToView(event.position()) # Store start position for drag
                self.preview_circle.setVisible(True) # Show the preview circle
            elif self.tool_mode == 'set_marker':
                pos = self.plotItem.vb.mapSceneToView(event.position())
                self.plot_clicked_signal.emit(pos.x())
            elif self.tool_mode == 'select_partial': # New condition
                pos = self.plotItem.vb.mapSceneToView(event.position())
                # Pass both clear_selection and remove_from_selection
                clear_sel = not self._shift_pressed and not self._remove_from_selection
                remove_sel = self._remove_from_selection
                print(f"  select_partial called from mousePressEvent: clear_selection={clear_sel}, remove_from_selection={remove_sel}")
                self.select_partial(pos, clear_selection=clear_sel, remove_from_selection=remove_sel)
                self._dragging = False # This tool is a single click, not a drag
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
                    # Pass both clear_selection and remove_from_selection
                    clear_sel = not self._shift_pressed and not self._remove_from_selection
                    remove_sel = self._remove_from_selection
                    print(f"  box_select called from mouseReleaseEvent: clear_selection={clear_sel}, remove_from_selection={remove_sel}")
                    self.box_select(rect, clear_selection=clear_sel, remove_from_selection=remove_sel)
                    self.selection_rect.setVisible(False)
                elif self.tool_mode == 'lasso':
                    # Pass both clear_selection and remove_from_selection
                    clear_sel = not self._shift_pressed and not self._remove_from_selection
                    remove_sel = self._remove_from_selection
                    print(f"  lasso_select called from mouseReleaseEvent: clear_selection={clear_sel}, remove_from_selection={remove_sel}")
                    self.lasso_select(self._lasso_points, clear_selection=clear_sel, remove_from_selection=remove_sel)
                    self.lasso_path.setVisible(False)
                elif self.tool_mode in ['smooth', 'dodge']:
                    end_pos = self.plotItem.vb.mapSceneToView(event.position())
                    center_pos = self._drag_start # For now, assume center is start. Can be refined later.
                    if self.tool_mode == 'dodge':
                        self.apply_dodge_on_release(center_pos, self.tool_radius) # New method call
                    elif self.tool_mode == 'smooth':
                        self.apply_smooth_on_release(center_pos, self.tool_radius) # New method call

            self._dragging = False
            self._drag_start = None
            self._lasso_points = []
            self.preview_circle.setData([], [])
            self._shift_pressed = False # Reset shift state after release
            self._remove_from_selection = False # Reset remove from selection state after release
        super().mouseReleaseEvent(event)

    def pixel_to_plot_radius(self, pixel_radius):
        vb = self.plotItem.vb
        p1 = vb.mapSceneToView(QPointF(0,0))
        p2 = vb.mapSceneToView(QPointF(pixel_radius,0))
        return abs(p2.x()-p1.x())

    

    

    

    
