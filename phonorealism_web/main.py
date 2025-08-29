import sys
import os
import subprocess
import atexit
import asyncio
import threading
import json
import websockets
import sounddevice as sd
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QComboBox, QLabel
from PySide6.QtCore import QThread, Signal, QObject

# --- Global Process Management ---
processes = []

def cleanup_processes():
    print("Terminating backend processes...")
    for p in processes:
        if p.poll() is None:
            p.terminate()
            p.wait()
    print("Cleanup complete.")

atexit.register(cleanup_processes)

# --- WebSocket Communication Thread ---
class WebSocketClient(QObject):
    # This object will run in a separate thread to handle asyncio websocket communication
    # without blocking the main GUI thread.
    message_to_send = Signal(str)

    def __init__(self):
        super().__init__()
        self.uri = "ws://localhost:8000/ws"
        self.message_queue = asyncio.Queue()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run_event_loop, daemon=True)
        self.thread.start()
        self.message_to_send.connect(self.queue_message)

    def run_event_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main_logic())

    async def main_logic(self):
        while True:
            try:
                async with websockets.connect(self.uri) as websocket:
                    print("GUI WebSocket client connected to hub.")
                    while True:
                        message = await self.message_queue.get()
                        await websocket.send(message)
            except (ConnectionRefusedError, websockets.exceptions.ConnectionClosed):
                print("GUI WebSocket client disconnected. Retrying in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"GUI WebSocket client error: {e}")
                await asyncio.sleep(3)

    def queue_message(self, message):
        self.loop.call_soon_threadsafe(self.message_queue.put_nowait, message)

# --- Main GUI Window ---
class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Control Panel")
        self.setGeometry(100, 100, 450, 150)

        # --- State and Workers ---
        self.devices = sd.query_devices()
        self.websocket_client = WebSocketClient()

        # --- UI Elements ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.status_label = QLabel("Starting backend services...")
        self.layout.addWidget(self.status_label)

        self.device_label = QLabel("Select Audio Output Device:")
        self.layout.addWidget(self.device_label)

        self.device_combo = QComboBox()
        self.populate_devices()
        self.device_combo.currentIndexChanged.connect(self.on_device_change)
        self.layout.addWidget(self.device_combo)

        self.start_backend_servers()

    def populate_devices(self):
        self.device_combo.addItem("Default Device", userData=None)
        for i, device in enumerate(self.devices):
            # List only output devices
            if device['max_output_channels'] > 0:
                self.device_combo.addItem(device['name'], userData=i)

    def on_device_change(self, index):
        device_id = self.device_combo.itemData(index)
        print(f"GUI: Selected device ID: {device_id}")
        message = json.dumps({
            "type": "set_audio_device",
            "payload": {"device_id": device_id}
        })
        self.websocket_client.message_to_send.emit(message)

    def start_backend_servers(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            backend_dir = os.path.join(current_dir, 'backend')
            python_executable = sys.executable

            # Start FastAPI server
            fastapi_cmd = [python_executable, "-m", "uvicorn", "main:app", "--port", "8000"]
            fastapi_process = subprocess.Popen(fastapi_cmd, cwd=backend_dir)
            processes.append(fastapi_process)

            # Start Conductor backend
            conductor_cmd = [python_executable, "conductor_backend.py"]
            conductor_process = subprocess.Popen(conductor_cmd, cwd=backend_dir)
            processes.append(conductor_process)

            self.status_label.setText("Backend services are running.")
            print("Both backend processes started.")
        except Exception as e:
            self.status_label.setText(f"Error starting backend: {e}")
            print(f"Error starting backend: {e}")

def main():
    app = QApplication(sys.argv)
    # Ensure PySide6 is a dependency if you distribute this
    control_panel = ControlPanel()
    control_panel.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()