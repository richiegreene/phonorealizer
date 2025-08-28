import sys
import asyncio
import webbrowser
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QThread, pyqtSignal

# Import the backend starting function
from phonorealism_web.backend.main import start_all_backends

class BackendThread(QThread):
    # Signal to indicate that the backend has started
    backend_started = pyqtSignal()

    def run(self):
        # Run the asyncio event loop for the backend
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(start_all_backends())

    def stop(self):
        # Stop the asyncio event loop
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop.close()

class LauncherWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Launcher")
        self.setGeometry(100, 100, 400, 200)

        self.layout = QVBoxLayout()

        self.status_label = QLabel("Starting backend services...")
        self.layout.addWidget(self.status_label)

        self.open_frontend_button = QPushButton("Open Frontend in Browser")
        self.open_frontend_button.setEnabled(False) # Disabled until backend starts
        self.open_frontend_button.clicked.connect(self.open_frontends)
        self.layout.addWidget(self.open_frontend_button)

        self.setLayout(self.layout)

        self.backend_thread = BackendThread()
        self.backend_thread.backend_started.connect(self.on_backend_started)
        self.backend_thread.start()

    def on_backend_started(self):
        self.status_label.setText("Backend services are running.")
        self.open_frontend_button.setEnabled(True)
        # Automatically open frontends once backend is ready
        self.open_frontends()

    def open_frontends(self):
        # Paths to your HTML files
        conductor_path = "file:///Users/richiegreene/Desktop/Phonorealism/phonorealism_web/frontend/conductor.html"
        performer_path = "file:///Users/richiegreene/Desktop/Phonorealism/phonorealism_web/frontend/index.html"
        
        webbrowser.open(conductor_path)
        webbrowser.open(performer_path)
        self.status_label.setText("Frontend opened. You can close this window.")

    def closeEvent(self, event):
        # Stop the backend thread when the GUI window is closed
        self.status_label.setText("Shutting down backend services...")
        self.backend_thread.stop()
        self.backend_thread.wait() # Wait for the thread to finish
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    launcher = LauncherWindow()
    launcher.show()
    sys.exit(app.exec())
