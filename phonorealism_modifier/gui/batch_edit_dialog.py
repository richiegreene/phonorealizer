from fractions import Fraction
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QCheckBox, 
    QSpinBox, QVBoxLayout, QGroupBox, QScrollArea, QWidget, QMessageBox, 
    QFileDialog, QLabel
)
from PySide6.QtCore import Qt

from gui.kernel_editor_dialog import KernelEditorDialog

class BatchEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("Selected")
        self.image_path = None
        self.kernel = None
        
        dialog_layout = QVBoxLayout(self)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        main_layout = QVBoxLayout(container)
        self.inputs = {}
        placeholder_style = "QLineEdit::placeholder { color: rgb(53, 53, 53); }"

        # Add existing groups (Shift, Scale, Smooth, Slide)
        self.add_shifting_group(main_layout, placeholder_style)
        self.add_scaling_group(main_layout, placeholder_style)
        self.add_smoothing_group(main_layout)
        self.add_sliding_group(main_layout)
        self.add_snapping_group(main_layout, placeholder_style)
        self.add_soften_sharpen_group(main_layout)
        self.add_superimpose_group(main_layout)
        self.add_slope_group(main_layout)
        
        scroll_area.setWidget(container)
        dialog_layout.addWidget(scroll_area)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_layout)

    def add_soften_sharpen_group(self, parent_layout):
        group = QGroupBox("Soften/Sharpen")
        layout = QFormLayout()

        define_kernel_btn = QPushButton("Define Kernel")
        define_kernel_btn.clicked.connect(self.open_kernel_editor)
        layout.addRow(define_kernel_btn)

        self.inputs['soften_sharpen_loudness'] = QCheckBox("loudness")
        self.inputs['soften_sharpen_loudness'].setChecked(True)
        self.inputs['soften_sharpen_pitch'] = QCheckBox("pitch")
        
        main_check_layout = QHBoxLayout()
        main_check_layout.addWidget(self.inputs['soften_sharpen_loudness'])
        main_check_layout.addWidget(self.inputs['soften_sharpen_pitch'])
        
        # Use a container widget for the pitch options to easily show/hide
        pitch_options_container = QWidget()
        pitch_options_layout = QHBoxLayout(pitch_options_container)
        pitch_options_layout.setContentsMargins(0, 0, 0, 0) # Remove extra margins
        self.inputs['soften_sharpen_hz'] = QCheckBox("Hz")
        self.inputs['soften_sharpen_cents'] = QCheckBox("cents")
        pitch_options_layout.addWidget(self.inputs['soften_sharpen_hz'])
        pitch_options_layout.addWidget(self.inputs['soften_sharpen_cents'])
        
        main_check_layout.addWidget(pitch_options_container)
        
        layout.addRow(main_check_layout)

        # --- Connections ---
        self.inputs['soften_sharpen_pitch'].toggled.connect(pitch_options_container.setVisible)
        
        # Mutually exclusive Hz/Cents
        self.inputs['soften_sharpen_hz'].toggled.connect(
            lambda checked: self.inputs['soften_sharpen_cents'].setChecked(not checked) if checked else None
        )
        self.inputs['soften_sharpen_cents'].toggled.connect(
            lambda checked: self.inputs['soften_sharpen_hz'].setChecked(not checked) if checked else None
        )

        group.setLayout(layout)
        parent_layout.addWidget(group)
        
        # --- Initial state ---
        pitch_options_container.setVisible(False)
        self.inputs['soften_sharpen_hz'].setChecked(True)

    def open_kernel_editor(self):
        kernel = KernelEditorDialog.get_kernel_from_user(self)
        if kernel is not None:
            self.kernel = kernel
            QMessageBox.information(self, "Kernel Defined", f"Kernel of size {kernel.shape[0]}x{kernel.shape[1]} has been set.")

    def add_superimpose_group(self, parent_layout):
        group = QGroupBox("Superimpose")
        layout = QFormLayout()

        self.inputs['image_path_label'] = QLabel("No image selected.")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_image)
        img_layout = QHBoxLayout()
        img_layout.addWidget(self.inputs['image_path_label'])
        img_layout.addWidget(browse_btn)
        layout.addRow(img_layout)

        # Amplitude and Pitch selection
        self.inputs['superimpose_amplitude'] = QCheckBox("loudness")
        self.inputs['superimpose_amplitude'].setChecked(True)
        self.inputs['superimpose_pitch'] = QCheckBox("pitch")
        check_layout = QHBoxLayout()
        check_layout.addWidget(self.inputs['superimpose_amplitude'])
        check_layout.addWidget(self.inputs['superimpose_pitch'])
        layout.addRow(check_layout)

        # Min/Max dB
        self.inputs['superimpose_min_db'] = QLineEdit("-80.0")
        layout.addRow("Min dB", self.inputs['superimpose_min_db'])
        self.inputs['superimpose_max_db'] = QLineEdit("0.0")
        layout.addRow("Max dB", self.inputs['superimpose_max_db'])

        # Min/Max Cents
        self.inputs['superimpose_min_cents'] = QLineEdit("-100")
        layout.addRow("Min cents", self.inputs['superimpose_min_cents'])
        self.inputs['superimpose_max_cents'] = QLineEdit("100")
        layout.addRow("Max cents", self.inputs['superimpose_max_cents'])

        # Invert and Mix
        self.inputs['superimpose_invert'] = QCheckBox()
        layout.addRow("Invert Mapping", self.inputs['superimpose_invert'])
        self.inputs['superimpose_mix'] = QLineEdit("100")
        layout.addRow("Mix Amount %", self.inputs['superimpose_mix'])

        group.setLayout(layout)
        parent_layout.addWidget(group)

    def browse_for_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select an Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.image_path = path
            self.inputs['image_path_label'].setText(f"...{path[-35:]}")

    def get_data(self):
        data = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                data[key] = widget.value()
        
        if self.image_path:
            data['superimpose_image_path'] = self.image_path
            data["y_axis_mode"] = self.main_window.plot.y_axis_mode
        
        if self.kernel is not None:
            data['soften_sharpen_kernel'] = self.kernel

        return data

    # The methods to add other groups remain the same as before
    # To keep the code clean, I will omit them here, but they are assumed to be present.
    def add_shifting_group(self, parent_layout, placeholder_style):
        shifting_group = QGroupBox("Shift")
        shifting_layout = QFormLayout()
        for key in ['Sec', 'Hz', 'Cents', 'dB']:
            le = QLineEdit()
            le.setPlaceholderText("e.g., +10 or -5.5")
            le.setStyleSheet(placeholder_style)
            shifting_layout.addRow(key, le)
            self.inputs[key] = le
        shifting_group.setLayout(shifting_layout)
        parent_layout.addWidget(shifting_group)

    def add_scaling_group(self, parent_layout, placeholder_style):
        scaling_group = QGroupBox("Scale")
        scaling_layout = QFormLayout()
        self.inputs['pitch_scale_factor'] = QLineEdit()
        self.inputs['pitch_scale_factor'].setPlaceholderText("e.g. 2 or 5/4")
        self.inputs['pitch_scale_factor'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Pitch Scaling", self.inputs['pitch_scale_factor'])
        self.inputs['pitch_scale_fixed_partial'] = QLineEdit("1")
        scaling_layout.addRow("Fixed Partial", self.inputs['pitch_scale_fixed_partial'])
        self.inputs['amplitude_scale_factor'] = QLineEdit()
        self.inputs['amplitude_scale_factor'].setPlaceholderText("e.g. 0.5 or 1/16")
        self.inputs['amplitude_scale_factor'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Dynamic Scaling", self.inputs['amplitude_scale_factor'])
        self.inputs['amplitude_scale_fixed_partial'] = QLineEdit("1")
        scaling_layout.addRow("Fixed Partial", self.inputs['amplitude_scale_fixed_partial'])
        self.inputs['time_scale'] = QLineEdit()
        self.inputs['time_scale'].setPlaceholderText("e.g., 2.0 or 0.5")
        self.inputs['time_scale'].setStyleSheet(placeholder_style)
        scaling_layout.addRow("Time Scale", self.inputs['time_scale'])
        scaling_group.setLayout(scaling_layout)
        parent_layout.addWidget(scaling_group)

    def add_smoothing_group(self, parent_layout):
        smoothing_group = QGroupBox("Smooth")
        smoothing_layout = QFormLayout()
        self.inputs['smoothing_hz'] = QSpinBox()
        self.inputs['smoothing_hz'].setRange(0, 100)
        smoothing_layout.addRow("Pitch", self.inputs['smoothing_hz'])
        self.inputs['smoothing_db'] = QSpinBox()
        self.inputs['smoothing_db'].setRange(0, 100)
        smoothing_layout.addRow("Dynamic", self.inputs['smoothing_db'])
        self.inputs['smoothstep'] = QCheckBox()
        smoothing_layout.addRow("Smoothstep", self.inputs['smoothstep'])
        smoothing_group.setLayout(smoothing_layout)
        parent_layout.addWidget(smoothing_group)

    def add_sliding_group(self, parent_layout):
        sliding_group = QGroupBox("Slide")
        sliding_layout = QFormLayout()
        self.inputs['sliding_percentage'] = QSpinBox()
        self.inputs['sliding_percentage'].setRange(0, 100)
        sliding_layout.addRow("Pitch", self.inputs['sliding_percentage'])
        self.inputs['dynamic_percentage'] = QSpinBox()
        self.inputs['dynamic_percentage'].setRange(0, 100)
        sliding_layout.addRow("Dynamic", self.inputs['dynamic_percentage'])
        sliding_group.setLayout(sliding_layout)
        parent_layout.addWidget(sliding_group)

    def add_snapping_group(self, parent_layout, placeholder_style):
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
        parent_layout.addWidget(snapping_group)

    def add_slope_group(self, parent_layout):
        slope_group = QGroupBox("Slope")
        slope_layout = QFormLayout()
        self.inputs['apply_slope'] = QCheckBox()
        slope_layout.addRow("Apply", self.inputs['apply_slope'])
        self.inputs['fixed_slope'] = QCheckBox("Fixed")
        slope_layout.addRow(self.inputs['fixed_slope'])
        self.inputs['slope_sec'] = QLineEdit("2")
        self.inputs['slope_cents'] = QLineEdit("702")
        slope_layout.addRow("  Sec", self.inputs['slope_sec'])
        slope_layout.addRow("  Cents", self.inputs['slope_cents'])
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
        parent_layout.addWidget(slope_group)
        self.inputs['fixed_slope'].toggled.connect(self.toggle_slope_mode)
        self.inputs['variable_slope'].toggled.connect(self.toggle_slope_mode)
        self.inputs['apply_slope'].toggled.connect(self.toggle_slope_controls)
        self.inputs['variable_slope'].setChecked(True)
        self.toggle_slope_mode(True)
        self.toggle_slope_controls(False)

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
