"""
phonorealism_modifier.py

First stage of the Phonorealism Modifier desktop app.
- Loads CSV harmonic partial data (time, harmonic_index, frequency, amplitude)
- Displays interactive, editable plot using PySide6 and pyqtgraph
- Modular design for future expansion
"""

import sys
import csv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QFileDialog, QToolBar, QAction, QMessageBox
)
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism CSV Editor")
        self.resize(800, 600)

        self.csv_data = []  # Internal storage for CSV data

        self._init_ui()

    def _init_ui(self):
        # Table widget for CSV
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
        self.table.cellChanged.connect(self.handle_cell_change)

        layout = QVBoxLayout()
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Toolbar
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        # Open CSV action
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.load_csv)
        toolbar.addAction(open_action)

        # Save CSV action
        save_action = QAction("Save", self)
        save_action.triggered.connect(self.save_csv_dialog)
        toolbar.addAction(save_action)

    def load_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, newline='') as file:
                    reader = csv.reader(file)
                    self.csv_data = list(reader)

                self.populate_table()
                self.current_file_path = file_path
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")

    def populate_table(self):
        if not self.csv_data:
            return

        self.table.blockSignals(True)  # Avoid triggering cellChanged while populating
        self.table.setRowCount(len(self.csv_data))
        self.table.setColumnCount(len(self.csv_data[0]))

        for row_idx, row_data in enumerate(self.csv_data):
            for col_idx, value in enumerate(row_data):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

        self.table.blockSignals(False)

    def handle_cell_change(self, row, column):
        new_value = self.table.item(row, column).text()
        self.csv_data[row][column] = new_value

    def save_csv_dialog(self):
        if hasattr(self, "current_file_path"):
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save CSV", self.current_file_path, "CSV Files (*.csv);;All Files (*)"
            )
        else:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save CSV", "", "CSV Files (*.csv);;All Files (*)"
            )

        if file_path:
            self.save_csv(file_path)

    def save_csv(self, file_path):
        try:
            with open(file_path, 'w', newline='') as file:
                writer = csv.writer(file)
                for row in range(self.table.rowCount()):
                    row_data = [
                        self.table.item(row, col).text() if self.table.item(row, col) else ''
                        for col in range(self.table.columnCount())
                    ]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Success", f"File saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
