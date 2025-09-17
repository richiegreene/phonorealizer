import numpy as np
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLineEdit, QPushButton, QHBoxLayout,
    QComboBox, QSpinBox, QDialogButtonBox, QLabel, QWidget
)
from PySide6.QtCore import Qt

class KernelEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Convolution Kernel")
        self.kernel_size = 3
        self.kernel_grid = []

        # Presets
        self.presets = {
            "Custom": np.zeros((3, 3)).tolist(),
            "Sharpen": [[0, -1, 0], [-1, 5, -1], [0, -1, 0]],
            "Box Blur": (np.ones((3, 3)) / 9).tolist(),
            "Edge Detection": [[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]],
            "Gaussian Blur 3x3": (np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]]) / 16).tolist(),
            "Gaussian Blur 5x5": (np.array([
                [1, 4, 6, 4, 1],
                [4, 16, 24, 16, 4],
                [6, 24, 36, 24, 6],
                [4, 16, 24, 16, 4],
                [1, 4, 6, 4, 1]
            ]) / 256).tolist()
        }

        layout = QVBoxLayout(self)

        # Top controls
        controls_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.presets.keys())
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        controls_layout.addWidget(QLabel("Preset:"))
        controls_layout.addWidget(self.preset_combo)

        self.size_spinbox = QSpinBox()
        self.size_spinbox.setRange(1, 15)
        self.size_spinbox.setSingleStep(2)
        self.size_spinbox.setValue(self.kernel_size)
        self.size_spinbox.valueChanged.connect(self.rebuild_grid)
        controls_layout.addWidget(QLabel("Kernel Size:"))
        controls_layout.addWidget(self.size_spinbox)
        layout.addLayout(controls_layout)

        # Grid for kernel
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        layout.addWidget(self.grid_container)

        # Bottom buttons
        buttons_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_grid)
        normalize_btn = QPushButton("Normalize")
        normalize_btn.clicked.connect(self.normalize_grid)
        buttons_layout.addWidget(clear_btn)
        buttons_layout.addWidget(normalize_btn)
        layout.addLayout(buttons_layout)

        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.rebuild_grid(self.kernel_size)
        self.preset_combo.setCurrentIndex(0)


    def rebuild_grid(self, size):
        self.kernel_size = size
        # Clear old grid
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.itemAt(i).widget().setParent(None)
        self.kernel_grid = []

        # Create new grid
        for r in range(size):
            row = []
            for c in range(size):
                le = QLineEdit("0.0")
                le.setAlignment(Qt.AlignCenter)
                self.grid_layout.addWidget(le, r, c)
                row.append(le)
            self.kernel_grid.append(row)
        
        if self.preset_combo.currentText() != "Custom":
            self.preset_combo.setCurrentText("Custom")


    def apply_preset(self, preset_name):
        if preset_name == "Custom":
            return
            
        kernel = self.presets[preset_name]
        size = len(kernel)
        
        # Block signals to prevent recursive calls
        self.size_spinbox.blockSignals(True)
        self.size_spinbox.setValue(size)
        self.size_spinbox.blockSignals(False)

        if self.kernel_size != size:
            self.rebuild_grid(size)

        for r in range(size):
            for c in range(size):
                self.kernel_grid[r][c].setText(f"{kernel[r][c]:.4f}")

    def clear_grid(self):
        for r in range(self.kernel_size):
            for c in range(self.kernel_size):
                self.kernel_grid[r][c].setText("0.0")
        self.preset_combo.setCurrentText("Custom")

    def normalize_grid(self):
        kernel = self.get_kernel()
        total = np.sum(kernel)
        if total != 0:
            kernel = kernel / total
        for r in range(self.kernel_size):
            for c in range(self.kernel_size):
                self.kernel_grid[r][c].setText(f"{kernel[r, c]:.4f}")

    def get_kernel(self):
        kernel = np.zeros((self.kernel_size, self.kernel_size))
        for r in range(self.kernel_size):
            for c in range(self.kernel_size):
                try:
                    kernel[r, c] = float(self.kernel_grid[r][c].text())
                except ValueError:
                    # Keep it as 0.0 if text is invalid
                    pass
        return kernel

    @staticmethod
    def get_kernel_from_user(parent=None):
        dialog = KernelEditorDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_kernel()
        return None

