from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QPushButton, QLabel
from PySide6.QtMultimedia import QMediaDevices

class AudioIODialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio I/O Setup")

        self.input_devices = QMediaDevices.audioInputs()
        self.output_devices = QMediaDevices.audioOutputs()

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select Input Device:"))
        self.input_combo = QComboBox()
        for device in self.input_devices:
            self.input_combo.addItem(device.description())
        layout.addWidget(self.input_combo)

        layout.addWidget(QLabel("Select Output Device:"))
        self.output_combo = QComboBox()
        for device in self.output_devices:
            self.output_combo.addItem(device.description())
        layout.addWidget(self.output_combo)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        layout.addWidget(self.ok_button)

    def get_selected_devices(self):
        selected_input = self.input_devices[self.input_combo.currentIndex()]
        selected_output = self.output_devices[self.output_combo.currentIndex()]
        return selected_input, selected_output
