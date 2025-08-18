from fractions import Fraction
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QCheckBox
)
import pyqtgraph as pg

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Selected")
        layout = QFormLayout(self)
        self.inputs = {}

        # Standard Edits
        for key in ['Sec', 'Hz', 'Cents', 'dB']:
            le = QLineEdit()
            le.setPlaceholderText("e.g., +10 or -5.5")
            layout.addRow(key, le)
            self.inputs[key] = le

        # Time Edits
        layout.addRow(pg.QtWidgets.QLabel("———" + " Time Edits ———")) # Separator
        self.inputs['time_shift'] = QLineEdit()
        self.inputs['time_shift'].setPlaceholderText("e.g., +0.1 or -0.05")
        layout.addRow("Time Shift (s)", self.inputs['time_shift'])

        self.inputs['time_scale'] = QLineEdit()
        self.inputs['time_scale'].setPlaceholderText("e.g., 2.0 or 0.5")
        layout.addRow("Time Scale", self.inputs['time_scale'])

        # Smoothing
        layout.addRow(pg.QtWidgets.QLabel("———" + " Smoothing ———")) # Separator
        self.inputs['smoothing_hz'] = QLineEdit()
        self.inputs['smoothing_hz'].setPlaceholderText("0-100")
        layout.addRow("Hz", self.inputs['smoothing_hz'])

        self.inputs['smoothing_db'] = QLineEdit()
        self.inputs['smoothing_db'].setPlaceholderText("0-100")
        layout.addRow("dB", self.inputs['smoothing_db'])

        # Snapping Edits
        layout.addRow(pg.QtWidgets.QLabel("———" + " Snapping ———")) # Separator
        
        self.inputs['ref_pitch'] = QLineEdit("261.6256")
        layout.addRow("Reference Pitch (Hz)", self.inputs['ref_pitch'])

        self.inputs['edo'] = QLineEdit()
        self.inputs['edo'].setPlaceholderText("e.g., 12")
        layout.addRow("Snap to EDO", self.inputs['edo'])

        self.inputs['ratios'] = QLineEdit()
        self.inputs['ratios'].setPlaceholderText("e.g., 1/1, 5/4, 3/2")
        layout.addRow("Snap to Ratios", self.inputs['ratios'])

        # New: Snap to Scale
        self.inputs['scale'] = QLineEdit()
        self.inputs['scale'].setPlaceholderText("e.g., 1/1, 9/8, 5/4, 4/3, 3/2, 5/3, 15/8")
        layout.addRow("Snap to Scale", self.inputs['scale'])

        self.inputs['octave_repeat'] = QCheckBox()
        self.inputs['octave_repeat'].setChecked(True) # Set to true by default
        layout.addRow("Octave Repeating", self.inputs['octave_repeat'])

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_data(self):
        data = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
        return data
