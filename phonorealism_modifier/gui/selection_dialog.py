from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QPushButton, QDialogButtonBox, QFormLayout
)

class SelectionDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("Define Selection")
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        self.partial_input = QLineEdit()
        self.time_input = QLineEdit()
        form_layout.addRow("Select Partial:", self.partial_input)
        form_layout.addRow("Time-Code:", self.time_input)
        
        layout.addLayout(form_layout)
        
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.main_window.select_all_harmonics)
        self.inverse_selection_button = QPushButton("Inverse Selection")
        self.inverse_selection_button.clicked.connect(self.main_window.invert_selection)
        
        layout.addWidget(self.select_all_button)
        layout.addWidget(self.inverse_selection_button)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        layout.addWidget(self.button_box)

    def get_values(self):
        return {
            "partial": self.partial_input.text(),
            "time": self.time_input.text()
        }
