from fractions import Fraction
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QCheckBox
)
import pyqtgraph as pg

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Edit Selected Points")
        layout = QFormLayout(self)
        self.inputs = {}

        # Standard Edits
        for key in ['Sec', 'Hz', 'Cents', 'dB']:
            le = QLineEdit()
            le.setPlaceholderText("e.g., +10 or -5.5")
            layout.addRow(key, le)
            self.inputs[key] = le

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

        self.inputs['octave_repeat'] = QCheckBox()
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
