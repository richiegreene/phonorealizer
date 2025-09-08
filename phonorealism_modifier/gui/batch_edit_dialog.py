from fractions import Fraction
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QCheckBox, 
    QSpinBox, QVBoxLayout, QGroupBox, QScrollArea, QWidget, QMessageBox
)

from .superimpose_dialog import SuperimposeDialog
from core.commands import SuperimposeCommand

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent # Store a reference to the main window
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

        self.inputs['pitch_scale_fixed_partial'] = QLineEdit("1")
        self.inputs['pitch_scale_fixed_partial'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Fixed Partial", self.inputs['pitch_scale_fixed_partial'])

        self.inputs['amplitude_scale_factor'] = QLineEdit()
        self.inputs['amplitude_scale_factor'].setPlaceholderText("e.g. 0.5 or 1/16")
        self.inputs['amplitude_scale_factor'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Dynamic Scaling", self.inputs['amplitude_scale_factor'])

        self.inputs['amplitude_scale_fixed_partial'] = QLineEdit("1")
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

        # Fixed Slope
        self.inputs['fixed_slope'] = QCheckBox("Fixed")
        slope_layout.addRow(self.inputs['fixed_slope'])
        self.inputs['slope_sec'] = QLineEdit("2")
        self.inputs['slope_cents'] = QLineEdit("702")
        slope_layout.addRow("  Sec", self.inputs['slope_sec'])
        slope_layout.addRow("  Cents", self.inputs['slope_cents'])

        # Variable Slope
        self.inputs['variable_slope'] = QCheckBox("Variable")
        slope_layout.addRow(self.inputs['variable_slope'])
        self.inputs['y_rate'] = QSpinBox()
        self.inputs['y_rate'].setRange(0, 100)
        self.inputs['y_rate'].setValue(100)
        self.inputs['x_rate'] = QSpinBox()
        self.inputs['x_rate'].setRange(0, 100)
        self.inputs['x_rate'].setValue(100)
        slope_layout.addRow("  X", self.inputs['x_rate'])
        slope_layout.addRow("  Y", self.inputs['y_rate'])

        slope_group.setLayout(slope_layout)
        main_layout.addWidget(slope_group)

        # Connect signals for enabling/disabling slope modes
        self.inputs['fixed_slope'].toggled.connect(self.toggle_slope_mode)
        self.inputs['variable_slope'].toggled.connect(self.toggle_slope_mode)
        self.inputs['apply_slope'].toggled.connect(self.toggle_slope_controls)

        # Set initial state
        self.inputs['variable_slope'].setChecked(True)
        self.toggle_slope_mode(True)
        self.toggle_slope_controls(False)
        
        # Set the container widget for the scroll area
        scroll_area.setWidget(container)
        
        # Add scroll area to the main dialog layout
        dialog_layout.addWidget(scroll_area)

        # Superimpose Button
        self.superimpose_btn = QPushButton("Superimpose Image...")
        self.superimpose_btn.clicked.connect(self.open_superimpose_dialog)
        dialog_layout.addWidget(self.superimpose_btn)

        # OK/Cancel Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_layout)

    def toggle_slope_mode(self, checked):
        sender = self.sender()
        if checked:
            if sender == self.inputs['fixed_slope']:
                self.inputs['variable_slope'].setChecked(False)
            elif sender == self.inputs['variable_slope']:
                self.inputs['fixed_slope'].setChecked(False)
        self.toggle_slope_controls(self.inputs['apply_slope'].isChecked())

    def toggle_slope_controls(self, checked):
        is_fixed = self.inputs['fixed_slope'].isChecked()
        is_variable = self.inputs['variable_slope'].isChecked()

        self.inputs['fixed_slope'].setEnabled(checked)
        self.inputs['variable_slope'].setEnabled(checked)

        self.inputs['slope_sec'].setEnabled(checked and is_fixed)
        self.inputs['slope_cents'].setEnabled(checked and is_fixed)
        self.inputs['x_rate'].setEnabled(checked and is_variable)
        self.inputs['y_rate'].setEnabled(checked and is_variable)

    def open_superimpose_dialog(self):
        if not self.main_window.plot.selected_points:
            QMessageBox.warning(self, "No Selection", "Please select points on the plot before superimposing.")
            return

        dialog = SuperimposeDialog(self)
        if dialog.exec():
            options = dialog.get_options()
            if options:
                # Get the y-axis mode from the plot to pass to the editor
                options["y_axis_mode"] = self.main_window.plot.y_axis_mode
                command = SuperimposeCommand(
                    self.main_window.data,
                    self.main_window.harmonic_editor,
                    self.main_window.plot.selected_points,
                    options,
                    "Superimpose Image"
                )
                self.main_window.undo_stack.push(command)
                self.accept() # Close the batch edit dialog
            else:
                QMessageBox.warning(self, "Error", "Invalid options or no image selected.")

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