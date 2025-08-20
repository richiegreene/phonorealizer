from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QSplitter, QWidget, QVBoxLayout, QInputDialog
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QUrl, QTemporaryFile
from PySide6.QtMultimedia import QAudioSource, QMediaDevices, QAudioFormat, QMediaPlayer, QAudioOutput
import pyqtgraph as pg
import numpy as np
import time
import traceback
from collections import deque
from .audio_io_dialog import AudioIODialog
from phonorealism_extractor.core.synthesizer import synthesize_from_partials

class PerformWindow(QMainWindow):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.setWindowTitle("Perform")
        self.resize(1200, 800)
        self.input_device = None
        self.output_device = None
        self.audio_source = None
        self.audio_input_device = None

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.temp_wav_file = None

        self.live_data_buffer = deque(maxlen=1000)
        self.live_amplitude_buffer = deque(maxlen=1000)
        self.selected_partial_data = None
        self.start_time = time.time()
        self.live_plot_time_range = 11

        self.media_player.positionChanged.connect(self.update_playback_position)

        self._init_ui()

    def _init_ui(self):
        self.toolbar = QToolBar("Perform Toolbar")
        self.addToolBar(self.toolbar)

        # Toolbar actions
        audio_io_action = QAction("Audio I/O", self)
        audio_io_action.triggered.connect(self.setup_audio_io)
        self.toolbar.addAction(audio_io_action)

        select_partial_action = QAction("Select Partial", self)
        select_partial_action.triggered.connect(self.select_partial)
        self.toolbar.addAction(select_partial_action)

        self.play_pause_action = QAction("Play", self)
        self.play_pause_action.setCheckable(True)
        self.play_pause_action.triggered.connect(self.toggle_playback)
        self.toolbar.addAction(self.play_pause_action)

        stop_action = QAction("Stop", self)
        stop_action.triggered.connect(self.stop_playback)
        self.toolbar.addAction(stop_action)

        time_zoom_in_action = QAction("Time (-)", self)
        time_zoom_in_action.triggered.connect(self.time_zoom_in)
        self.toolbar.addAction(time_zoom_in_action)

        time_zoom_out_action = QAction("Time (+)", self)
        time_zoom_out_action.triggered.connect(self.time_zoom_out)
        self.toolbar.addAction(time_zoom_out_action)

        pitch_zoom_in_action = QAction("Pitch (+)", self)
        pitch_zoom_in_action.triggered.connect(self.pitch_zoom_in)
        self.toolbar.addAction(pitch_zoom_in_action)

        pitch_zoom_out_action = QAction("Pitch (-)", self)
        pitch_zoom_out_action.triggered.connect(self.pitch_zoom_out)
        self.toolbar.addAction(pitch_zoom_out_action)

        gain_in_action = QAction("Gain (+)", self)
        gain_in_action.triggered.connect(self.gain_in)
        self.toolbar.addAction(gain_in_action)

        gain_out_action = QAction("Gain (-)", self)
        gain_out_action.triggered.connect(self.gain_out)
        self.toolbar.addAction(gain_out_action)

        # Central widget with splitter
        main_splitter = QSplitter(Qt.Vertical)
        self.setCentralWidget(main_splitter)

        # Top splitter for frequency plots
        freq_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(freq_splitter)

        # Left plot for live audio frequency
        self.live_plot_widget = pg.PlotWidget()
        self.live_plot = self.live_plot_widget.getPlotItem()
        self.live_plot.setTitle("Live Input Frequency")
        self.live_plot.showGrid(x=True, y=True)
        self.live_plot_curve = self.live_plot.plot(pen='y')
        freq_splitter.addWidget(self.live_plot_widget)

        # Right plot for CSV partial frequency
        self.csv_plot_widget = pg.PlotWidget()
        self.csv_plot = self.csv_plot_widget.getPlotItem()
        self.csv_plot.setTitle("CSV Partial Frequency")
        self.csv_plot.showGrid(x=True, y=True)
        self.csv_plot.showAxis('left', False)
        self.csv_plot_curve = self.csv_plot.plot(pen='c')
        self.csv_plot.setXRange(0, 10)
        freq_splitter.addWidget(self.csv_plot_widget)

        # Bottom splitter for amplitude plots
        amp_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(amp_splitter)

        # Left plot for live audio amplitude
        self.live_amplitude_plot_widget = pg.PlotWidget()
        self.live_amplitude_plot = self.live_amplitude_plot_widget.getPlotItem()
        self.live_amplitude_plot.setTitle("Live Input Amplitude")
        self.live_amplitude_plot.showGrid(x=True, y=True)
        self.live_amplitude_curve = self.live_amplitude_plot.plot(pen='r')
        amp_splitter.addWidget(self.live_amplitude_plot_widget)

        # Right plot for CSV partial amplitude
        self.csv_amplitude_plot_widget = pg.PlotWidget()
        self.csv_amplitude_plot = self.csv_amplitude_plot_widget.getPlotItem()
        self.csv_amplitude_plot.setTitle("CSV Partial Amplitude")
        self.csv_amplitude_plot.showGrid(x=True, y=True)
        self.csv_amplitude_plot.showAxis('left', False)
        self.csv_amplitude_curve = self.csv_amplitude_plot.plot(pen='m')
        self.csv_amplitude_plot.setXRange(0, 10)
        self.csv_amplitude_plot.setYRange(0, 1.2)
        amp_splitter.addWidget(self.csv_amplitude_plot_widget)

        # Link views
        self.live_plot.getViewBox().setYLink(self.csv_plot.getViewBox())
        self.live_plot.getViewBox().disableAutoRange(axis=pg.ViewBox.YAxis)
        self.live_amplitude_plot.getViewBox().setYLink(self.csv_amplitude_plot.getViewBox())
        self.live_amplitude_plot.getViewBox().disableAutoRange(axis=pg.ViewBox.YAxis)

        # Link x-axes for synchronized scrolling
        self.live_amplitude_plot.setXLink(self.live_plot)
        self.csv_amplitude_plot.setXLink(self.csv_plot)

        # Central line
        self.central_line_csv = pg.InfiniteLine(pos=0, angle=90, movable=False, pen='r')
        self.csv_plot.addItem(self.central_line_csv)

    def setup_audio_io(self):
        dialog = AudioIODialog(self)
        if dialog.exec():
            self.input_device, self.output_device = dialog.get_selected_devices()
            self.init_audio_input()
            self.audio_output.setDevice(self.output_device)

    def init_audio_input(self):
        if self.input_device:
            format = self.input_device.preferredFormat()
            self.audio_source = QAudioSource(self.input_device, format, self)
            self.audio_input_device = self.audio_source.start()
            self.audio_input_device.readyRead.connect(self.process_audio)

    def process_audio(self):
        try:
            if self.audio_input_device:
                data = self.audio_input_device.readAll()
                if data:
                    audio_format = self.audio_source.format()
                    sample_format = audio_format.sampleFormat()

                    if sample_format == QAudioFormat.SampleFormat.Int16:
                        dtype = np.int16
                    elif sample_format == QAudioFormat.SampleFormat.Int32:
                        dtype = np.int32
                    elif sample_format == QAudioFormat.SampleFormat.Float:
                        dtype = np.float32
                    else:
                        return

                    samples = np.frombuffer(data, dtype=dtype)
                    if audio_format.channelCount() == 2:
                        samples = samples[::2]

                    n = len(samples)
                    if n == 0:
                        return

                    sr = audio_format.sampleRate()

                    # Apply a Hanning window to reduce spectral leakage
                    windowed_samples = samples * np.hanning(n)

                    # Zero-padding for better frequency resolution (interpolation)
                    N_fft = 4096 # A common FFT size for pitch tracking

                    fft_result = np.fft.rfft(windowed_samples, N_fft)
                    freqs = np.fft.rfftfreq(N_fft, 1 / sr)

                    peak_index = np.argmax(np.abs(fft_result))

                    # Parabolic interpolation for more accurate peak frequency
                    if peak_index > 0 and peak_index < len(freqs) - 1:
                        mag_left = np.abs(fft_result[peak_index - 1])
                        mag_center = np.abs(fft_result[peak_index])
                        mag_right = np.abs(fft_result[peak_index + 1])

                        p = 0.5 * (mag_left - mag_right) / (mag_left - 2 * mag_center + mag_right)
                        peak_freq = freqs[peak_index] + p * (freqs[1] - freqs[0]) # (freqs[1] - freqs[0]) is bin width
                    else:
                        peak_freq = freqs[peak_index]

                    # Calculate RMS amplitude
                    rms_amplitude = np.sqrt(np.mean(samples**2))

                    # Normalize RMS amplitude based on audio format
                    if sample_format == QAudioFormat.SampleFormat.Int16:
                        max_val = 32768.0 # Max value for int16 PCM
                    elif sample_format == QAudioFormat.SampleFormat.Int32:
                        max_val = 2147483648.0 # Max value for int32 PCM
                    elif sample_format == QAudioFormat.SampleFormat.Float:
                        max_val = 1.0 # Max value for float PCM
                    else:
                        max_val = 1.0 # Default to 1.0 if unknown format

                    normalized_rms_amplitude = (rms_amplitude / max_val) * 50

                    self.live_data_buffer.append((time.time(), peak_freq))
                    self.live_amplitude_buffer.append((time.time(), normalized_rms_amplitude))
        except Exception as e:
            print(f"Error in process_audio: {e}")
            traceback.print_exc()

    def select_partial(self):
        if self.data.df is not None and not self.data.df.empty:
            num_partials = int(self.data.df['harmonic_index'].max())
            partial_num, ok = QInputDialog.getInt(
                self, "Select Partial", "Enter partial number:", 1, 1, num_partials, 1
            )
            if ok:
                self.load_partial(partial_num)

    def load_partial(self, partial_num):
        if self.data.df is not None:
            self.selected_partial_data = self.data.df[self.data.df['harmonic_index'] == partial_num]
            if not self.selected_partial_data.empty:
                self.csv_plot_curve.setData(
                    x=self.selected_partial_data['time'].to_numpy(),
                    y=self.selected_partial_data['frequency'].to_numpy()
                )
                self.csv_plot.setYRange(0, self.selected_partial_data['frequency'].max() * 1.1)

                # Update CSV amplitude plot
                csv_amplitudes = np.abs(self.selected_partial_data['amplitude'].to_numpy())
                max_csv_amplitude = np.max(csv_amplitudes)
                if max_csv_amplitude > 0:
                    normalized_csv_amplitudes = csv_amplitudes / max_csv_amplitude
                else:
                    normalized_csv_amplitudes = csv_amplitudes # Avoid division by zero

                self.csv_amplitude_curve.setData(
                    x=self.selected_partial_data['time'].to_numpy(),
                    y=normalized_csv_amplitudes
                )
                self.synthesize_partial()

    def synthesize_partial(self):
        if self.selected_partial_data is not None and not self.selected_partial_data.empty:
            if self.temp_wav_file:
                self.temp_wav_file.close()

            partials_data = [self.selected_partial_data[['time', 'frequency', 'amplitude']].values.tolist()]
            sr = 44100
            duration = self.selected_partial_data['time'].max()

            self.temp_wav_file = QTemporaryFile("XXXXXX.wav")
            if not self.temp_wav_file.open():
                return
            self.temp_wav_file.setAutoRemove(True)
            output_path = self.temp_wav_file.fileName()

            try:
                synthesize_from_partials(partials_data, sr, output_path, duration)
                self.media_player.setSource(QUrl.fromLocalFile(output_path))
            except Exception as e:
                print(f"Error synthesizing partial: {e}")
                traceback.print_exc()

    def toggle_playback(self, checked):
        if checked:
            if self.media_player.source().isEmpty():
                self.play_pause_action.setChecked(False)
                return
            self.play_pause_action.setText("Pause")
            self.media_player.play()
        else:
            self.play_pause_action.setText("Play")
            self.media_player.pause()

    def stop_playback(self):
        self.play_pause_action.setChecked(False)
        self.play_pause_action.setText("Play")
        self.media_player.stop()
        self.csv_plot_curve.setPos(0, 0)

    def update_playback_position(self, position):
        playback_position_sec = position / 1000.0
        self.csv_plot_curve.setPos(-playback_position_sec, 0)
        self.csv_amplitude_curve.setPos(-playback_position_sec, 0)

        # Update live plot
        if self.live_data_buffer:
            current_time = time.time()
            times, freqs = zip(*self.live_data_buffer)
            shifted_times = np.array(times) - current_time
            self.live_plot_curve.setData(x=shifted_times, y=freqs)
            self.live_plot.setXRange(-self.live_plot_time_range, 0)

        # Update live amplitude plot
        if self.live_amplitude_buffer:
            current_time = time.time()
            times_amp, amplitudes = zip(*self.live_amplitude_buffer)
            shifted_times_amp = np.array(times_amp) - current_time
            self.live_amplitude_curve.setData(x=shifted_times_amp, y=amplitudes)
            self.live_amplitude_plot.setXRange(-self.live_plot_time_range, 0)

    def time_zoom_in(self):
        self.csv_plot.getViewBox().scaleBy((0.5, 1), center=(0,0))
        self.live_plot_time_range *= 0.5

    def time_zoom_out(self):
        self.csv_plot.getViewBox().scaleBy((2, 1), center=(0,0))
        self.live_plot_time_range *= 2

    def pitch_zoom_in(self):
        self.csv_plot.getViewBox().scaleBy((1, 2), center=(0,0))

    def pitch_zoom_out(self):
        self.csv_plot.getViewBox().scaleBy((1, 0.5), center=(0,0))

    def gain_in(self):
        # Scale the Y-axis of the linked amplitude plots
        self.live_amplitude_plot.getViewBox().scaleBy((1, 0.5), center=(0,0))

    def gain_out(self):
        # Scale the Y-axis of the linked amplitude plots
        self.live_amplitude_plot.getViewBox().scaleBy((1, 2), center=(0,0))
