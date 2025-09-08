from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QLabel, 
    QSlider, QLineEdit, QCheckBox, QDialogButtonBox
)
from PySide6.QtCore import Qt

class SuperimposeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Superimposition Options")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)
        self.image_path = None

        # --- Image Selection ---
        image_layout = QHBoxLayout()
        self.image_label = QLabel("No image selected.")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_for_image)
        image_layout.addWidget(self.image_label)
        image_layout.addWidget(self.browse_button)
        self.layout.addLayout(image_layout)

        # --- Amplitude Range ---
        amp_layout = QHBoxLayout()
        self.min_db_label = QLabel("Min dB:")
        self.min_db_input = QLineEdit("-80.0")
        self.max_db_label = QLabel("Max dB:")
        self.max_db_input = QLineEdit("0.0")
        amp_layout.addWidget(self.min_db_label)
        amp_layout.addWidget(self.min_db_input)
        amp_layout.addWidget(self.max_db_label)
        amp_layout.addWidget(self.max_db_input)
        self.layout.addLayout(amp_layout)

        # --- Invert Mapping ---
        self.invert_checkbox = QCheckBox("Invert Mapping (Dark = Loud)")
        self.layout.addWidget(self.invert_checkbox)

        # --- Mix Amount Slider ---
        mix_layout = QHBoxLayout()
        self.mix_label = QLabel("Mix Amount: 100%")
        self.mix_slider = QSlider(Qt.Horizontal)
        self.mix_slider.setRange(0, 100)
        self.mix_slider.setValue(100)
        self.mix_slider.valueChanged.connect(lambda v: self.mix_label.setText(f"Mix Amount: {v}%"))
        mix_layout.addWidget(self.mix_label)
        mix_layout.addWidget(self.mix_slider)
        self.layout.addLayout(mix_layout)

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def browse_for_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select an Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.image_path = path
            self.image_label.setText(f"Image: ...{self.image_path[-30:]}")

    def get_options(self):
        if not self.image_path:
            return None
        try:
            return {
                "image_path": self.image_path,
                "min_db": float(self.min_db_input.text()),
                "max_db": float(self.max_db_input.text()),
                "invert": self.invert_checkbox.isChecked(),
                "mix_amount": self.mix_slider.value() / 100.0
            }
        except ValueError:
            return None
