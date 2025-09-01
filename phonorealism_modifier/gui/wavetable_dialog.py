import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDialog, QVBoxLayout, QSlider, QWidget, QComboBox
from PySide6.QtCore import Qt

def generate_harmonic_wave(amplitudes, wavetable_size=512):
    """Generates a wave from a list of harmonic amplitudes."""
    wavetable = np.zeros(wavetable_size)
    x = np.arange(wavetable_size)
    for i, amp in enumerate(amplitudes):
        if amp > 0:
            wavetable += amp * np.sin(2 * np.pi * (i + 1) * x / wavetable_size)
    
    # Normalize
    if np.max(np.abs(wavetable)) > 0:
        wavetable /= np.max(np.abs(wavetable))
        
    return wavetable

class WavetableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wavetable Synthesizer")
        self.setMinimumSize(400, 300)

        self.layout = QVBoxLayout(self)

        # --- UI Elements ---
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Basic Shapes", "Voice", "Strings", "Brass", "Winds"])
        self.layout.addWidget(self.preset_combo)

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
        self._generate_base_wavetables()

        # --- Connections ---
        self.preset_combo.currentTextChanged.connect(self.update_ui)
        self.slider.valueChanged.connect(self.update_waveform)

        # --- Initial State ---
        self.wavetable = None
        self.update_ui()

    def _generate_base_wavetables(self):
        x = np.arange(self.wavetable_size)
        
        # Basic Shapes
        self.sine_wave = np.sin(2 * np.pi * x / self.wavetable_size)
        self.triangle_wave = 2 * np.abs((x / self.wavetable_size) - 0.5) * 2 - 1
        self.sawtooth_wave = (x / self.wavetable_size) * 2 - 1
        self.square_wave = np.sign(np.sin(2 * np.pi * x / self.wavetable_size))

        # Voice
        self.voice_aaa = generate_harmonic_wave([1.0, 0.4, 0.7, 0.3, 0.2, 0.1, 0.1, 0.05])
        self.voice_eee = generate_harmonic_wave([0.2, 0.3, 0.8, 0.1, 0.6, 0.1, 0.4, 0.05])
        self.voice_ooo = generate_harmonic_wave([1.0, 0.2, 0.4, 0.1, 0.1, 0.05, 0.0, 0.0])

        # Strings
        self.string_bright = generate_harmonic_wave([1/n for n in range(1, 17)])
        self.string_soft = generate_harmonic_wave([1/(n*n) for n in range(1, 17)])

        # Brass
        self.brass_horn = generate_harmonic_wave([1.0, 0.8, 0.6, 0.4, 0.2, 0.1, 0.05, 0.02])
        self.brass_trumpet = generate_harmonic_wave([1.0, 1.2, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3])

        # Winds
        self.wind_flute = generate_harmonic_wave([1.0, 0.1, 0.05])
        self.wind_clarinet = generate_harmonic_wave([1.0 if n%2!=0 else 0 for n in range(1, 17)])
        self.wind_oboe = generate_harmonic_wave([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3])

    def update_ui(self):
        self.update_waveform(self.slider.value())

    def update_waveform(self, value):
        """Generate and plot the interpolated waveform."""
        preset = self.preset_combo.currentText()

        if preset == "Basic Shapes":
            if value <= 100:
                mix = value / 100.0
                wave1, wave2 = self.sine_wave, self.triangle_wave
            elif value <= 200:
                mix = (value - 100) / 100.0
                wave1, wave2 = self.triangle_wave, self.sawtooth_wave
            else:
                mix = (value - 200) / 100.0
                wave1, wave2 = self.sawtooth_wave, self.square_wave
        elif preset == "Voice":
            if value <= 150:
                mix = value / 150.0
                wave1, wave2 = self.voice_aaa, self.voice_eee
            else:
                mix = (value - 150) / 150.0
                wave1, wave2 = self.voice_eee, self.voice_ooo
        elif preset == "Strings":
            mix = value / 300.0
            wave1, wave2 = self.string_soft, self.string_bright
        elif preset == "Brass":
            mix = value / 300.0
            wave1, wave2 = self.brass_horn, self.brass_trumpet
        elif preset == "Winds":
            if value <= 150:
                mix = value / 150.0
                wave1, wave2 = self.wind_flute, self.wind_clarinet
            else:
                mix = (value - 150) / 150.0
                wave1, wave2 = self.wind_clarinet, self.wind_oboe
        
        self.wavetable = (1 - mix) * wave1 + mix * wave2
        self.waveform_plot.setData(self.wavetable)

    def get_wavetable(self):
        """Returns the current wavetable."""
        return self.wavetable
