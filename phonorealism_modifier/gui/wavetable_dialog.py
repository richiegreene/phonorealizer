import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QWidget

class WavetableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wavetable Synthesizer")
        self.setMinimumSize(400, 300)

        self.layout = QVBoxLayout(self)

        # --- UI Elements ---
        self.waveform_combo = QComboBox()
        self.waveform_combo.addItems(["Sine", "Square", "Sawtooth", "Triangle"])
        self.layout.addWidget(self.waveform_combo)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setYRange(-1.1, 1.1, padding=0)
        self.plot_widget.setXRange(0, 512, padding=0)
        self.plot_widget.getPlotItem().hideAxis('bottom')
        self.plot_widget.getPlotItem().hideAxis('left')
        self.waveform_plot = self.plot_widget.plot(pen=pg.mkPen('w', width=2))
        self.layout.addWidget(self.plot_widget)

        # --- Connections ---
        self.waveform_combo.currentTextChanged.connect(self.update_waveform)

        # --- Initial State ---
        self.wavetable = None
        self.update_waveform(self.waveform_combo.currentText())

    def update_waveform(self, waveform_name):
        """Generate and plot the selected waveform."""
        wavetable_size = 512
        x = np.arange(wavetable_size)

        if waveform_name == "Sine":
            self.wavetable = np.sin(2 * np.pi * x / wavetable_size)
        elif waveform_name == "Square":
            self.wavetable = np.sign(np.sin(2 * np.pi * x / wavetable_size))
        elif waveform_name == "Sawtooth":
            self.wavetable = (x / wavetable_size) * 2 - 1
        elif waveform_name == "Triangle":
            self.wavetable = 2 * np.abs((x / wavetable_size) - 0.5) * 2 - 1

        self.waveform_plot.setData(self.wavetable)

    def get_wavetable(self):
        """Returns the current wavetable."""
        print(f"WavetableDialog: Getting wavetable. Type: {self.waveform_combo.currentText()}")
        if self.wavetable is not None:
            print(f"WavetableDialog: Wavetable shape: {self.wavetable.shape}")
        else:
            print("WavetableDialog: Wavetable is None.")
        return self.wavetable
