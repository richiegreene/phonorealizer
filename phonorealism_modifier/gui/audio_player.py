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
        self.media_player = None
        self.audio_output = None
        self.temp_wav_file = None

    def toggle_playback(self, harmonic_data, play_action_widget):
        if self.media_player and self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.stop_playback(play_action_widget)
        else:
            self._start_playback(harmonic_data, play_action_widget)

    def stop_playback(self, play_action_widget):
        if self.media_player:
            self.media_player.stop()
            self.media_player.setSource(QUrl()) # Clear source
            self.media_player = None
        if self.audio_output:
            self.audio_output = None
        if self.temp_wav_file:
            self.temp_wav_file.close() # Close and remove temporary file
            self.temp_wav_file = None
        play_action_widget.setText("Play Audio")

    def _start_playback(self, harmonic_data, play_action_widget):
        if harmonic_data.df is None or harmonic_data.df.empty:
            QMessageBox.warning(self.parent, "No Data", "Please load a CSV file first.")
            return

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
            synthesize_from_partials(partials_data, sr, output_path, duration)
            
            self.audio_output = QAudioOutput()
            self.media_player = QMediaPlayer()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setSource(QUrl.fromLocalFile(output_path))
            self.audio_output.setVolume(0.5)
            self.media_player.play()

            self.media_player.mediaStatusChanged.connect(lambda status: self._media_status_changed(status, play_action_widget))
            self.media_player.positionChanged.connect(self._on_position_changed)

        except Exception as e:
            QMessageBox.critical(self.parent, "Error", f"Failed to synthesize or play audio: {e}")
            if self.temp_wav_file:
                self.temp_wav_file.remove()
            play_action_widget.setText("Play Audio")

    def _on_position_changed(self, position_ms):
        self.playback_position_changed.emit(position_ms / 1000.0)

    def set_start_position(self, time_in_seconds):
        if self.media_player:
            self.media_player.setPosition(int(time_in_seconds * 1000))

    def _media_status_changed(self, status, play_action_widget):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback(play_action_widget)
