
import sys
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QPushButton, QLabel, QLineEdit, QGridLayout
)
from PySide6.QtCore import Qt

class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Options")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10) # Add some margin
        self.layout.setSpacing(10) # Add some spacing between groups

        # CSV Export (no GroupBox for compactness)
        self.csv_export_checkbox = QCheckBox("CSV Export (commit changes to new CSV file)")
        self.layout.addWidget(self.csv_export_checkbox)

        # WAV Export
        self.wav_group = QGroupBox("WAV Export")
        self.wav_layout = QVBoxLayout()
        self.wav_layout.setContentsMargins(10, 10, 10, 10)
        self.wav_layout.setSpacing(5)
        self.wav_export_checkbox = QCheckBox("Export to WAV")
        self.wav_export_checkbox.stateChanged.connect(self.toggle_wav_options)
        self.wav_layout.addWidget(self.wav_export_checkbox)

        self.wav_options_widget = QWidget()
        self.wav_options_layout = QHBoxLayout(self.wav_options_widget)
        self.wav_options_layout.setContentsMargins(0, 0, 0, 0)
        self.wav_options_layout.setSpacing(10)
        self.wav_full_checkbox = QCheckBox("Full")
        self.wav_full_checkbox.setChecked(True) # Set to checked by default
        self.wav_parts_checkbox = QCheckBox("Parts")
        self.wav_options_layout.addWidget(self.wav_full_checkbox)
        self.wav_options_layout.addWidget(self.wav_parts_checkbox)
        self.wav_options_layout.addStretch(1) # Push checkboxes to left
        self.wav_layout.addWidget(self.wav_options_widget)
        self.wav_options_widget.setEnabled(False) # Initially disabled

        self.wav_group.setLayout(self.wav_layout)
        self.layout.addWidget(self.wav_group)

        # SVG Melody Export
        self.svg_melody_group = QGroupBox("SVG Melody Export")
        self.svg_melody_layout = QVBoxLayout()
        self.svg_melody_layout.setContentsMargins(10, 10, 10, 10)
        self.svg_melody_layout.setSpacing(5)
        self.svg_melody_export_checkbox = QCheckBox("Export to SVG Melody")
        self.svg_melody_export_checkbox.stateChanged.connect(self.toggle_svg_melody_options)
        self.svg_melody_layout.addWidget(self.svg_melody_export_checkbox)

        self.svg_melody_options_widget = QWidget()
        self.svg_melody_options_layout = QGridLayout(self.svg_melody_options_widget) # Use QGridLayout
        self.svg_melody_options_layout.setContentsMargins(0, 0, 0, 0)
        self.svg_melody_options_layout.setSpacing(5)

        # Row 0: Lin/Log
        lin_log_layout = QHBoxLayout()
        self.svg_melody_lin_checkbox = QCheckBox("Lin")
        self.svg_melody_lin_checkbox.setChecked(True) # Set to checked by default
        self.svg_melody_log_checkbox = QCheckBox("Log")
        lin_log_layout.addWidget(self.svg_melody_lin_checkbox)
        lin_log_layout.addWidget(self.svg_melody_log_checkbox)
        lin_log_layout.addStretch(1)
        self.svg_melody_options_layout.addLayout(lin_log_layout, 0, 0, 1, 2) # Span 2 columns

        # Row 1: Full/Parts
        full_parts_layout = QHBoxLayout()
        self.svg_melody_full_checkbox = QCheckBox("Full")
        self.svg_melody_full_checkbox.setChecked(True) # Set to checked by default
        self.svg_melody_parts_checkbox = QCheckBox("Parts")
        full_parts_layout.addWidget(self.svg_melody_full_checkbox)
        full_parts_layout.addWidget(self.svg_melody_parts_checkbox)
        full_parts_layout.addStretch(1)
        self.svg_melody_options_layout.addLayout(full_parts_layout, 1, 0, 1, 2)

        # Row 2: Amplitude/Line
        amp_line_layout = QHBoxLayout()
        self.svg_melody_amp_checkbox = QCheckBox("Amplitude")
        self.svg_melody_amp_checkbox.setChecked(True) # Set to checked by default
        self.svg_melody_line_checkbox = QCheckBox("Line")
        amp_line_layout.addWidget(self.svg_melody_amp_checkbox)
        amp_line_layout.addWidget(self.svg_melody_line_checkbox)
        amp_line_layout.addStretch(1)
        self.svg_melody_options_layout.addLayout(amp_line_layout, 2, 0, 1, 2)

        # Input fields using QGridLayout
        self.svg_melody_width_input = QLineEdit("1000")
        self.svg_melody_height_input = QLineEdit("500")
        self.svg_melody_gain_input = QLineEdit("1.00")
        self.svg_melody_max_points_input = QLineEdit("5000")

        self.svg_melody_options_layout.addWidget(QLabel("Width:"), 3, 0)
        self.svg_melody_options_layout.addWidget(self.svg_melody_width_input, 3, 1)
        self.svg_melody_options_layout.addWidget(QLabel("Height:"), 4, 0)
        self.svg_melody_options_layout.addWidget(self.svg_melody_height_input, 4, 1)
        self.svg_melody_options_layout.addWidget(QLabel("Gain:"), 5, 0)
        self.svg_melody_options_layout.addWidget(self.svg_melody_gain_input, 5, 1)
        self.svg_melody_options_layout.addWidget(QLabel("Max Waveform Points:"), 6, 0)
        self.svg_melody_options_layout.addWidget(self.svg_melody_max_points_input, 6, 1)

        self.svg_melody_layout.addWidget(self.svg_melody_options_widget)
        self.svg_melody_options_widget.setEnabled(False)
        self.svg_melody_group.setLayout(self.svg_melody_layout)
        self.layout.addWidget(self.svg_melody_group)

        # SVG Waveform Export
        self.svg_waveform_group = QGroupBox("SVG Waveform Export")
        self.svg_waveform_layout = QVBoxLayout()
        self.svg_waveform_layout.setContentsMargins(10, 10, 10, 10)
        self.svg_waveform_layout.setSpacing(5)
        self.svg_waveform_export_checkbox = QCheckBox("Export to SVG Waveform")
        self.svg_waveform_export_checkbox.stateChanged.connect(self.toggle_svg_waveform_options)
        self.svg_waveform_layout.addWidget(self.svg_waveform_export_checkbox)

        self.svg_waveform_options_widget = QWidget()
        self.svg_waveform_options_layout = QGridLayout(self.svg_waveform_options_widget) # Use QGridLayout
        self.svg_waveform_options_layout.setContentsMargins(0, 0, 0, 0)
        self.svg_waveform_options_layout.setSpacing(5)

        # Row 0: Full/Parts
        full_parts_layout_waveform = QHBoxLayout()
        self.svg_waveform_full_checkbox = QCheckBox("Full")
        self.svg_waveform_full_checkbox.setChecked(True) # Set to checked by default
        self.svg_waveform_parts_checkbox = QCheckBox("Parts")
        full_parts_layout_waveform.addWidget(self.svg_waveform_full_checkbox)
        full_parts_layout_waveform.addWidget(self.svg_waveform_parts_checkbox)
        full_parts_layout_waveform.addStretch(1)
        self.svg_waveform_options_layout.addLayout(full_parts_layout_waveform, 0, 0, 1, 2)

        # Input fields using QGridLayout
        self.svg_waveform_width_input = QLineEdit("1000")
        self.svg_waveform_height_input = QLineEdit("500")
        self.svg_waveform_gain_input = QLineEdit("1.00")
        self.svg_waveform_max_points_input = QLineEdit("5000")

        self.svg_waveform_options_layout.addWidget(QLabel("Width:"), 1, 0)
        self.svg_waveform_options_layout.addWidget(self.svg_waveform_width_input, 1, 1)
        self.svg_waveform_options_layout.addWidget(QLabel("Height:"), 2, 0)
        self.svg_waveform_options_layout.addWidget(self.svg_waveform_height_input, 2, 1)
        self.svg_waveform_options_layout.addWidget(QLabel("Gain:"), 3, 0)
        self.svg_waveform_options_layout.addWidget(self.svg_waveform_gain_input, 3, 1)
        self.svg_waveform_options_layout.addWidget(QLabel("Max Waveform Points:"), 4, 0)
        self.svg_waveform_options_layout.addWidget(self.svg_waveform_max_points_input, 4, 1)

        self.svg_waveform_layout.addWidget(self.svg_waveform_options_widget)
        self.svg_waveform_options_widget.setEnabled(False)
        self.svg_waveform_group.setLayout(self.svg_waveform_layout)
        self.layout.addWidget(self.svg_waveform_group)

        # Buttons
        self.button_box = QWidget()
        self.button_box_layout = QHBoxLayout(self.button_box)
        self.export_button = QPushButton("Export")
        self.cancel_button = QPushButton("Cancel")
        self.export_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.button_box_layout.addWidget(self.export_button)
        self.button_box_layout.addWidget(self.cancel_button)
        self.layout.addWidget(self.button_box)

    def toggle_wav_options(self, state):
        self.wav_options_widget.setEnabled(state == Qt.Checked)

    def toggle_svg_melody_options(self, state):
        self.svg_melody_options_widget.setEnabled(state == Qt.Checked)

    def toggle_svg_waveform_options(self, state):
        self.svg_waveform_options_widget.setEnabled(state == Qt.Checked)

    def get_settings(self):
        return {
            "csv": {
                "export": self.csv_export_checkbox.isChecked()
            },
            "wav": {
                "export": self.wav_export_checkbox.isChecked(),
                "full": self.wav_full_checkbox.isChecked(),
                "parts": self.wav_parts_checkbox.isChecked()
            },
            "svg_melody": {
                "export": self.svg_melody_export_checkbox.isChecked(),
                "lin": self.svg_melody_lin_checkbox.isChecked(),
                "log": self.svg_melody_log_checkbox.isChecked(),
                "full": self.svg_melody_full_checkbox.isChecked(),
                "parts": self.svg_melody_parts_checkbox.isChecked(),
                "width": int(self.svg_melody_width_input.text()),
                "height": int(self.svg_melody_height_input.text()),
                "gain": float(self.svg_melody_gain_input.text()),
                "max_points": int(self.svg_melody_max_points_input.text()),
                "amplitude": self.svg_melody_amp_checkbox.isChecked(),
                "line": self.svg_melody_line_checkbox.isChecked()
            },
            "svg_waveform": {
                "export": self.svg_waveform_export_checkbox.isChecked(),
                "full": self.svg_waveform_full_checkbox.isChecked(),
                "parts": self.svg_waveform_parts_checkbox.isChecked(),
                "width": int(self.svg_waveform_width_input.text()),
                "height": int(self.svg_waveform_height_input.text()),
                "gain": float(self.svg_waveform_gain_input.text()),
                "max_points": int(self.svg_waveform_max_points_input.text())
            }
        }

if __name__ == '__main__':
    app = QApplication(sys.argv)
    dialog = ExportDialog()
    if dialog.exec():
        print(dialog.get_settings())
    sys.exit(app.exec())
