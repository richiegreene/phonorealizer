from fractions import Fraction
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QCheckBox, 
    QSpinBox, QVBoxLayout, QGroupBox, QScrollArea, QWidget
)

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selected")
        
        # Main dialog layout
        dialog_layout = QVBoxLayout(self)
        
        # Scroll Area
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        
        # Container widget for all the group boxes
        container = QWidget()
        main_layout = QVBoxLayout(container)
        
        self.inputs = {}
        placeholder_style = "QLineEdit::placeholder { color: rgb(53, 53, 53); }"

        # Shifting Group
        shifting_group = QGroupBox("Shift")
        shifting_layout = QFormLayout()
        for key in ['Sec', 'Hz', 'Cents', 'dB']:
            le = QLineEdit()
            le.setPlaceholderText("e.g., +10 or -5.5")
            le.setStyleSheet(placeholder_style)
            shifting_layout.addRow(key, le)
            self.inputs[key] = le
        shifting_group.setLayout(shifting_layout)
        main_layout.addWidget(shifting_group)

        # Scaling Group
        scaling_group = QGroupBox("Scale")
        scaling_layout = QFormLayout()
        
        self.inputs['pitch_scale_factor'] = QLineEdit()
        self.inputs['pitch_scale_factor'].setPlaceholderText("e.g. 2 or 5/4")
        self.inputs['pitch_scale_factor'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Pitch Scaling", self.inputs['pitch_scale_factor'])

        self.inputs['pitch_scale_fixed_partial'] = QLineEdit()
        self.inputs['pitch_scale_fixed_partial'].setPlaceholderText("1")
        self.inputs['pitch_scale_fixed_partial'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Fixed Partial", self.inputs['pitch_scale_fixed_partial'])

        self.inputs['amplitude_scale_factor'] = QLineEdit()
        self.inputs['amplitude_scale_factor'].setPlaceholderText("e.g. 0.5 or 1/16")
        self.inputs['amplitude_scale_factor'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Dynamic Scaling", self.inputs['amplitude_scale_factor'])

        self.inputs['amplitude_scale_fixed_partial'] = QLineEdit()
        self.inputs['amplitude_scale_fixed_partial'].setPlaceholderText("1")
        self.inputs['amplitude_scale_fixed_partial'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Fixed Partial", self.inputs['amplitude_scale_fixed_partial'])

        self.inputs['time_scale'] = QLineEdit()
        self.inputs['time_scale'].setPlaceholderText("e.g., 2.0 or 0.5")
        self.inputs['time_scale'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Time Scale", self.inputs['time_scale'])
        scaling_group.setLayout(scaling_layout)
        main_layout.addWidget(scaling_group)

        # Smoothing Group
        smoothing_group = QGroupBox("Smooth")
        smoothing_layout = QFormLayout()
        self.inputs['smoothing_hz'] = QSpinBox()
        self.inputs['smoothing_hz'].setRange(0, 100)
        self.inputs['smoothing_hz'].setValue(0)
        smoothing_layout.addRow("Pitch", self.inputs['smoothing_hz'])

        self.inputs['smoothing_db'] = QSpinBox()
        self.inputs['smoothing_db'].setRange(0, 100)
        self.inputs['smoothing_db'].setValue(0)
        smoothing_layout.addRow("Dynamic", self.inputs['smoothing_db'])

        self.inputs['smoothstep'] = QCheckBox()
        smoothing_layout.addRow("Smoothstep", self.inputs['smoothstep'])
        smoothing_group.setLayout(smoothing_layout)
        main_layout.addWidget(smoothing_group)

        # Sliding Group
        sliding_group = QGroupBox("Slide")
        sliding_layout = QFormLayout()
        self.inputs['sliding_percentage'] = QSpinBox()
        self.inputs['sliding_percentage'].setRange(0, 100)
        self.inputs['sliding_percentage'].setValue(0) # Default to no slide
        sliding_layout.addRow("Pitch", self.inputs['sliding_percentage'])

        self.inputs['dynamic_percentage'] = QSpinBox()
        self.inputs['dynamic_percentage'].setRange(0, 100)
        self.inputs['dynamic_percentage'].setValue(0) # Default to no dynamic
        sliding_layout.addRow("Dynamic", self.inputs['dynamic_percentage'])

        sliding_group.setLayout(sliding_layout)
        main_layout.addWidget(sliding_group)

        # Snapping Group
        snapping_group = QGroupBox("Snap")
        snapping_layout = QFormLayout()
        self.inputs['ref_pitch'] = QLineEdit("261.6256")
        snapping_layout.addRow("Reference Pitch (Hz)", self.inputs['ref_pitch'])

        self.inputs['edo'] = QLineEdit()
        self.inputs['edo'].setPlaceholderText("e.g., 12")
        self.inputs['edo'].setStyleSheet(placeholder_style)
        snapping_layout.addRow("Snap to EDO", self.inputs['edo'])

        self.inputs['ratios'] = QLineEdit()
        self.inputs['ratios'].setPlaceholderText("e.g., 1/1, 5/4, 3/2")
        self.inputs['ratios'].setStyleSheet(placeholder_style)
        snapping_layout.addRow("Snap to Ratios", self.inputs['ratios'])

        self.inputs['scale'] = QLineEdit()
        self.inputs['scale'].setPlaceholderText("e.g., 1/1, 9/8, 5/4, 4/3, 3/2, 5/3, 15/8")
        self.inputs['scale'].setStyleSheet(placeholder_style)
        snapping_layout.addRow("Snap to Scale", self.inputs['scale'])

        self.inputs['octave_repeat'] = QCheckBox()
        self.inputs['octave_repeat'].setChecked(True)
        snapping_layout.addRow("Octave Repeating", self.inputs['octave_repeat'])
        snapping_group.setLayout(snapping_layout)
        main_layout.addWidget(snapping_group)

        # Slope Group
        slope_group = QGroupBox("Slope")
        slope_layout = QFormLayout()
        self.inputs['apply_slope'] = QCheckBox()
        slope_layout.addRow("Apply", self.inputs['apply_slope'])
        self.inputs['y_rate'] = QSpinBox()
        self.inputs['y_rate'].setRange(0, 100)
        slope_layout.addRow("Y Rate", self.inputs['y_rate'])
        self.inputs['x_rate'] = QSpinBox()
        self.inputs['x_rate'].setRange(0, 100)
        slope_layout.addRow("X Rate", self.inputs['x_rate'])
        slope_group.setLayout(slope_layout)
        main_layout.addWidget(slope_group)
        
        # Set the container widget for the scroll area
        scroll_area.setWidget(container)
        
        # Add scroll area to the main dialog layout
        dialog_layout.addWidget(scroll_area)

        # OK/Cancel Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_layout)

    def get_data(self):
        data = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                data[key] = widget.value()
        return data