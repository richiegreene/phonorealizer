import os
import tempfile
from PySide6.QtCore import QUrl, QTemporaryFile, Signal, QObject
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QMessageBox

# Adjust sys.path to import from phonorealism_extractor
import sys
import os
sys.path.append("/Users/richiegreene/Desktop/Phonorealism/")
from phonorealism_extractor.core.synthesizer import synthesize_from_partials

class AudioPlayer(QObject):
    playback_position_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent # This will be the MainWindow instance
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.temp_wav_file = None
        self.last_wavetable_value = 0

        # Connect signals here and manage connections carefully
        self.media_player.positionChanged.connect(self._on_position_changed)
        # Defer connecting mediaStatusChanged until playback starts

    def toggle_playback(self, harmonic_data, play_action_widget):
        current_position = self.media_player.position()
        
        wavetable = None
        new_wavetable_value = 0
        if hasattr(self.parent, 'wavetable_dialog') and self.parent.wavetable_dialog is not None:
            wavetable = self.parent.wavetable_dialog.get_wavetable()
            new_wavetable_value = self.parent.wavetable_dialog.slider.value()

        wavetable_changed = new_wavetable_value != self.last_wavetable_value

        # If data is dirty or wavetable changed, always re-synthesize
        if harmonic_data.is_modified() or wavetable_changed:
            self.last_wavetable_value = new_wavetable_value
            self._start_playback(harmonic_data, play_action_widget, start_position=current_position, wavetable=wavetable)
            return

        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            play_action_widget.setText("Play")
        elif self.media_player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
            self.media_player.play()
            play_action_widget.setText("Pause")
        else: # StoppedState or no media
            self._start_playback(harmonic_data, play_action_widget, wavetable=wavetable)

    def stop_playback(self, play_action_widget=None):
        self.media_player.stop()
        if self.temp_wav_file:
            self.temp_wav_file.close()
            self.temp_wav_file = None
        if play_action_widget:
            play_action_widget.setText("Play")

    def _start_playback(self, harmonic_data, play_action_widget, start_position=0, wavetable=None):
        if harmonic_data.df is None or harmonic_data.df.empty:
            QMessageBox.warning(self.parent, "No Data", "Please load a CSV file first.")
            return

        # Stop and release previous temp file if any
        if self.media_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.media_player.stop()
        if self.temp_wav_file:
            self.temp_wav_file.close()

        partials_data = []
        for idx in harmonic_data.grouped:
            group = harmonic_data.grouped[idx]
            partial_list = group[['time', 'frequency', 'amplitude']].values.tolist()
            partials_data.append(partial_list)

        sr = 44100
        duration = harmonic_data.df['time'].max() if not harmonic_data.df.empty else 1.0

        self.temp_wav_file = QTemporaryFile("XXXXXX.wav")
        if not self.temp_wav_file.open():
            QMessageBox.critical(self.parent, "Error", "Could not create temporary file.")
            return
        self.temp_wav_file.setAutoRemove(True)
        output_path = self.temp_wav_file.fileName()

        try:
            synthesize_from_partials(partials_data, sr, output_path, duration, wavetable=wavetable)
            harmonic_data.reset_modified() # Mark data as clean
            
            # Disconnect old status connection if any, to avoid multiple triggers
            try:
                self.media_player.mediaStatusChanged.disconnect()
            except RuntimeError: # Throws error if not connected
                pass

            self.media_player.mediaStatusChanged.connect(lambda status: self._media_status_changed(status, play_action_widget))
            
            # Re-initialize audio output to ensure device is available
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)

            self.media_player.setSource(QUrl.fromLocalFile(output_path))
            self.media_player.setPosition(start_position) # Set position
            self.audio_output.setVolume(0.5)
            self.media_player.play()
            play_action_widget.setText("Pause")

        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to synthesize or play audio: {e}")
            if self.temp_wav_file:
                self.temp_wav_file.close()
            play_action_widget.setText("Play")

    def _on_position_changed(self, position_ms):
        self.playback_position_changed.emit(position_ms / 1000.0)

    def set_start_position(self, time_in_seconds):
        if self.media_player:
            self.media_player.setPosition(int(time_in_seconds * 1000))

    def _media_status_changed(self, status, play_action_widget):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback(play_action_widget)
