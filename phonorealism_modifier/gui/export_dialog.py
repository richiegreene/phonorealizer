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

        self.wav_full_checkbox = QCheckBox("Full")
        self.wav_full_checkbox.setChecked(True) # Set to checked by default
        self.wav_parts_checkbox = QCheckBox("Parts")

        wav_options_layout = QHBoxLayout()
        wav_options_layout.setContentsMargins(0, 0, 0, 0)
        wav_options_layout.setSpacing(10)
        wav_options_layout.addWidget(self.wav_full_checkbox)
        wav_options_layout.addWidget(self.wav_parts_checkbox)
        wav_options_layout.addStretch(1) # Push checkboxes to left
        self.wav_layout.addLayout(wav_options_layout)

        self.wav_group.setLayout(self.wav_layout)
        self.layout.addWidget(self.wav_group)

        # SVG Pitch Export
        self.svg_pitch_group = QGroupBox("SVG Pitch Export")
        self.svg_pitch_layout = QVBoxLayout()
        self.svg_pitch_layout.setContentsMargins(10, 10, 10, 10)
        self.svg_pitch_layout.setSpacing(5)
        self.svg_pitch_export_checkbox = QCheckBox("Export Pitch to SVG")
        self.svg_pitch_export_checkbox.stateChanged.connect(self.toggle_svg_pitch_options)
        self.svg_pitch_layout.addWidget(self.svg_pitch_export_checkbox)

        self.svg_pitch_lin_checkbox = QCheckBox("Log")
        self.svg_pitch_lin_checkbox.setChecked(True) # Set to checked by default
        self.svg_pitch_log_checkbox = QCheckBox("Lin")
        self.svg_pitch_full_checkbox = QCheckBox("Full")
        self.svg_pitch_full_checkbox.setChecked(True) # Set to checked by default
        self.svg_pitch_parts_checkbox = QCheckBox("Parts")
        self.svg_pitch_amp_checkbox = QCheckBox("Amplitude")
        self.svg_pitch_amp_checkbox.setChecked(True) # Set to checked by default
        self.svg_pitch_line_checkbox = QCheckBox("Line")

        self.svg_pitch_width_input = QLineEdit("1000")
        self.svg_pitch_height_input = QLineEdit("500")
        self.svg_pitch_gain_input = QLineEdit("1.00")
        self.svg_pitch_max_points_input = QLineEdit("5000")

        svg_pitch_options_grid = QGridLayout()
        svg_pitch_options_grid.setContentsMargins(0, 0, 0, 0)
        svg_pitch_options_grid.setSpacing(5)

        svg_pitch_options_grid.addWidget(self.svg_pitch_lin_checkbox, 0, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_log_checkbox, 0, 1)
        svg_pitch_options_grid.addWidget(self.svg_pitch_full_checkbox, 1, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_parts_checkbox, 1, 1)
        svg_pitch_options_grid.addWidget(self.svg_pitch_amp_checkbox, 2, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_line_checkbox, 2, 1)

        svg_pitch_options_grid.addWidget(QLabel("Width:"), 3, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_width_input, 3, 1)
        svg_pitch_options_grid.addWidget(QLabel("Height:"), 4, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_height_input, 4, 1)
        svg_pitch_options_grid.addWidget(QLabel("Gain:"), 5, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_gain_input, 5, 1)
        svg_pitch_options_grid.addWidget(QLabel("Max Points:"), 6, 0)
        svg_pitch_options_grid.addWidget(self.svg_pitch_max_points_input, 6, 1)

        self.svg_pitch_layout.addLayout(svg_pitch_options_grid)
        self.svg_pitch_group.setLayout(self.svg_pitch_layout)
        self.layout.addWidget(self.svg_pitch_group)

        # SVG Amplitude Export
        self.svg_amplitude_group = QGroupBox("SVG Amplitude Export")
        self.svg_amplitude_layout = QVBoxLayout()
        self.svg_amplitude_layout.setContentsMargins(10, 10, 10, 10)
        self.svg_amplitude_layout.setSpacing(5)
        self.svg_amplitude_export_checkbox = QCheckBox("Export Amplitude to SVG")
        self.svg_amplitude_export_checkbox.stateChanged.connect(self.toggle_svg_amplitude_options)
        self.svg_amplitude_layout.addWidget(self.svg_amplitude_export_checkbox)

        self.svg_amplitude_full_checkbox = QCheckBox("Full")
        self.svg_amplitude_full_checkbox.setChecked(True) # Set to checked by default
        self.svg_amplitude_parts_checkbox = QCheckBox("Parts")

        self.svg_amplitude_width_input = QLineEdit("1000")
        self.svg_amplitude_height_input = QLineEdit("500")
        self.svg_amplitude_max_points_input = QLineEdit("5000")

        svg_amplitude_options_grid = QGridLayout()
        svg_amplitude_options_grid.setContentsMargins(0, 0, 0, 0)
        svg_amplitude_options_grid.setSpacing(5)

        svg_amplitude_options_grid.addWidget(self.svg_amplitude_full_checkbox, 0, 0)
        svg_amplitude_options_grid.addWidget(self.svg_amplitude_parts_checkbox, 0, 1)

        svg_amplitude_options_grid.addWidget(QLabel("Width:"), 1, 0)
        svg_amplitude_options_grid.addWidget(self.svg_amplitude_width_input, 1, 1)
        svg_amplitude_options_grid.addWidget(QLabel("Height:"), 2, 0)
        svg_amplitude_options_grid.addWidget(self.svg_amplitude_height_input, 2, 1)
        svg_amplitude_options_grid.addWidget(QLabel("Max Points:"), 3, 0)
        svg_amplitude_options_grid.addWidget(self.svg_amplitude_max_points_input, 3, 1)

        self.svg_amplitude_layout.addLayout(svg_amplitude_options_grid)
        self.svg_amplitude_group.setLayout(self.svg_amplitude_layout)
        self.layout.addWidget(self.svg_amplitude_group)

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

        # Initial state setup
        self.toggle_wav_options(self.wav_export_checkbox.checkState())
        self.toggle_svg_pitch_options(self.svg_pitch_export_checkbox.checkState())
        self.toggle_svg_amplitude_options(self.svg_amplitude_export_checkbox.checkState())

    def toggle_wav_options(self, state):
        enabled = (state == 2) # Compare integer value
        self.wav_full_checkbox.setEnabled(enabled)
        self.wav_parts_checkbox.setEnabled(enabled)

    def toggle_svg_pitch_options(self, state):
        enabled = (state == 2) # Compare integer value
        self.svg_pitch_lin_checkbox.setEnabled(enabled)
        self.svg_pitch_log_checkbox.setEnabled(enabled)
        self.svg_pitch_full_checkbox.setEnabled(enabled)
        self.svg_pitch_parts_checkbox.setEnabled(enabled)
        self.svg_pitch_amp_checkbox.setEnabled(enabled)
        self.svg_pitch_line_checkbox.setEnabled(enabled)
        self.svg_pitch_width_input.setEnabled(enabled)
        self.svg_pitch_height_input.setEnabled(enabled)
        self.svg_pitch_gain_input.setEnabled(enabled)
        self.svg_pitch_max_points_input.setEnabled(enabled)

    def toggle_svg_amplitude_options(self, state):
        enabled = (state == 2) # Compare integer value
        self.svg_amplitude_full_checkbox.setEnabled(enabled)
        self.svg_amplitude_parts_checkbox.setEnabled(enabled)
        self.svg_amplitude_width_input.setEnabled(enabled)
        self.svg_amplitude_height_input.setEnabled(enabled)
        self.svg_amplitude_max_points_input.setEnabled(enabled)

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
            "svg_pitch": {
                "export": self.svg_pitch_export_checkbox.isChecked(),
                "lin": self.svg_pitch_lin_checkbox.isChecked(),
                "log": self.svg_pitch_log_checkbox.isChecked(),
                "full": self.svg_pitch_full_checkbox.isChecked(),
                "parts": self.svg_pitch_parts_checkbox.isChecked(),
                "width": int(self.svg_pitch_width_input.text()),
                "height": int(self.svg_pitch_height_input.text()),
                "gain": float(self.svg_pitch_gain_input.text()),
                "max_points": int(self.svg_pitch_max_points_input.text()),
                "amplitude": self.svg_pitch_amp_checkbox.isChecked(),
                "line": self.svg_pitch_line_checkbox.isChecked()
            },
            "svg_amplitude": {
                "export": self.svg_amplitude_export_checkbox.isChecked(),
                "full": self.svg_amplitude_full_checkbox.isChecked(),
                "parts": self.svg_amplitude_parts_checkbox.isChecked(),
                "width": int(self.svg_amplitude_width_input.text()),
                "height": int(self.svg_amplitude_height_input.text()),
                "max_points": int(self.svg_amplitude_max_points_input.text())
            }
        }

if __name__ == '__main__':
    app = QApplication(sys.argv)
    dialog = ExportDialog()
    if dialog.exec():
        print(dialog.get_settings())
    sys.exit(app.exec())