import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDialog, QVBoxLayout, QSlider, QWidget
from PySide6.QtCore import Qt

class WavetableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wavetable Synthesizer")
        self.setMinimumSize(400, 300)

        self.layout = QVBoxLayout(self)

        # --- UI Elements ---
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 300)
        self.layout.addWidget(self.slider)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setYRange(-1.1, 1.1, padding=0)
        self.plot_widget.setXRange(0, 512, padding=0)
        self.plot_widget.getPlotItem().hideAxis('bottom')
        self.plot_widget.getPlotItem().hideAxis('left')
        self.waveform_plot = self.plot_widget.plot(pen=pg.mkPen('w', width=2))
        self.layout.addWidget(self.plot_widget)

        # --- Generate Base Waveforms ---
        self.wavetable_size = 512
        x = np.arange(self.wavetable_size)
        self.sine_wave = np.sin(2 * np.pi * x / self.wavetable_size)
        self.triangle_wave = 2 * np.abs((x / self.wavetable_size) - 0.5) * 2 - 1
        self.sawtooth_wave = (x / self.wavetable_size) * 2 - 1
        self.square_wave = np.sign(np.sin(2 * np.pi * x / self.wavetable_size))

        # --- Connections ---
        self.slider.valueChanged.connect(self.update_waveform)

        # --- Initial State ---
        self.wavetable = None
        self.update_waveform(self.slider.value())

    def update_waveform(self, value):
        """Generate and plot the interpolated waveform."""
        if value <= 100:
            # Sine to Triangle
            mix = value / 100.0
            wave1 = self.sine_wave
            wave2 = self.triangle_wave
        elif value <= 200:
            # Triangle to Sawtooth
            mix = (value - 100) / 100.0
            wave1 = self.triangle_wave
            wave2 = self.sawtooth_wave
        else:
            # Sawtooth to Square
            mix = (value - 200) / 100.0
            wave1 = self.sawtooth_wave
            wave2 = self.square_wave
        
        self.wavetable = (1 - mix) * wave1 + mix * wave2
        self.waveform_plot.setData(self.wavetable)

    def get_wavetable(self):
        """Returns the current wavetable."""
        return self.wavetable
