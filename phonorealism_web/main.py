import sys
import os
import subprocess
import atexit
import asyncio
import threading
import json
import websockets
import sounddevice as sd
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QComboBox, QLabel, 
    QScrollArea, QGridLayout, QFrame, QPushButton, QHBoxLayout, QFileDialog
)
from PySide6.QtCore import Signal, QObject, Qt

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
    message_received = Signal(str)
    message_to_send = Signal(str)

    def __init__(self):
        super().__init__()
        self.uri = "ws://localhost:8000/ws"
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run_event_loop, daemon=True)
        self.message_to_send.connect(self.queue_message)
        self.thread.start()

    def run_event_loop(self):
        asyncio.set_event_loop(self.loop)
        self.message_queue = asyncio.Queue()
        self.loop.run_until_complete(self.main_logic())

    async def main_logic(self):
        while True:
            try:
                async with websockets.connect(self.uri) as websocket:
                    print("GUI WebSocket client connected to hub.")
                    send_task = asyncio.create_task(self.send_handler(websocket))
                    receive_task = asyncio.create_task(self.receive_handler(websocket))
                    await asyncio.gather(send_task, receive_task)
            except Exception as e:
                print(f"GUI WebSocket client error: {e}")
                await asyncio.sleep(3)

    async def send_handler(self, websocket):
        while True:
            message = await self.message_queue.get()
            await websocket.send(message)

    async def receive_handler(self, websocket):
        async for message in websocket:
            self.message_received.emit(message)

    def queue_message(self, message):
        if hasattr(self, 'message_queue'):
            self.loop.call_soon_threadsafe(self.message_queue.put_nowait, message)

# --- Main GUI Window ---
class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phonorealism Control Panel")
        self.setGeometry(100, 100, 500, 500)

        self.websocket_client = WebSocketClient()
        self.websocket_client.message_received.connect(self.on_message_received)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # --- Top Controls ---
        self.status_label = QLabel("Starting backend services...")
        self.device_combo = QComboBox()
        self.populate_devices()
        self.device_combo.currentIndexChanged.connect(self.on_device_change)
        self.layout.addWidget(self.status_label)
        self.layout.addWidget(QLabel("Audio Output Device:"))
        self.layout.addWidget(self.device_combo)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(line)

        # --- File & Playback Controls ---
        self.file_label = QLabel("No CSV file loaded.")
        self.layout.addWidget(self.file_label)
        
        controls_layout = QHBoxLayout()
        self.load_button = QPushButton("Load CSV File")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.stop_button)
        self.layout.addLayout(controls_layout)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(line)

        # --- Harmonics Panning Controls ---
        self.harmonics_label = QLabel("Harmonic Channel Routing (Load a score to populate)")
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.harmonics_layout = QGridLayout(self.scroll_content)
        self.harmonics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.harmonics_label)
        self.layout.addWidget(self.scroll_area)

        # --- Connect Signals ---
        self.load_button.clicked.connect(self.open_file_dialog)
        self.play_button.clicked.connect(lambda: self.send_command("start_performance"))
        self.pause_button.clicked.connect(lambda: self.send_command("pause_performance"))
        self.stop_button.clicked.connect(lambda: self.send_command("stop_performance"))

        self.start_backend_servers()
        self.on_device_change(0)

    def send_command(self, command_type, payload={}):
        message = json.dumps({"type": command_type, "payload": payload})
        self.websocket_client.message_to_send.emit(message)
        print(f"GUI: Sent command: {command_type}")

    def open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open CSV Score", "", "CSV Files (*.csv)")
        if file_path:
            self.file_label.setText(f"Loaded: {os.path.basename(file_path)}")
            with open(file_path, 'r') as f:
                csv_content = f.read()
            self.send_command("load_score", csv_content)

    def on_message_received(self, message):
        print(f"GUI: Received message from hub: {message}")
        try:
            data = json.loads(message)
            if data.get("type") == "harmonics_list":
                payload = data.get("payload", {})
                self.update_harmonic_controls(payload.get("harmonics", []), payload.get("routing", {}))
        except Exception as e:
            print(f"GUI: Error processing message: {e}")

    def update_harmonic_controls(self, harmonics, routing):
        for i in reversed(range(self.harmonics_layout.count())):
            self.harmonics_layout.itemAt(i).widget().setParent(None)
        if not harmonics:
            self.harmonics_label.setText("Harmonic Channel Routing (No harmonics found)")
            return
        self.harmonics_label.setText("Harmonic Channel Routing:")
        device_id = self.device_combo.currentData()
        num_channels = sd.query_devices(device_id, 'output')['max_output_channels'] if device_id is not None else sd.query_devices(kind='output')['max_output_channels']
        for i, h_index in enumerate(harmonics):
            label = QLabel(f"Harmonic {h_index}:")
            routing_combo = QComboBox()
            routing_combo.addItem("Deactivated", userData=-1)
            for ch in range(num_channels):
                routing_combo.addItem(f"Channel {ch + 1}", userData=ch)
            initial_channel = routing.get(str(h_index), -1)
            initial_index = routing_combo.findData(initial_channel)
            if initial_index != -1:
                routing_combo.setCurrentIndex(initial_index)
            routing_combo.currentIndexChanged.connect(
                lambda checked, h=h_index, c=routing_combo: self.on_routing_change(h, c.currentData())
            )
            self.harmonics_layout.addWidget(label, i, 0)
            self.harmonics_layout.addWidget(routing_combo, i, 1)

    def on_routing_change(self, harmonic_index, channel):
        self.send_command("set_harmonic_routing", {"harmonic_index": harmonic_index, "channel": channel})

    def populate_devices(self):
        self.device_combo.addItem("Default Device", userData=None)
        for i, device in enumerate(sd.query_devices()):
            if device['max_output_channels'] > 0:
                self.device_combo.addItem(f"{device['name']} ({device['max_output_channels']} out)", userData=i)

    def on_device_change(self, index):
        self.send_command("set_audio_device", {"device_id": self.device_combo.itemData(index)})
        for i in reversed(range(self.harmonics_layout.count())):
            self.harmonics_layout.itemAt(i).widget().setParent(None)
        self.harmonics_label.setText("Harmonic Channel Routing (Load a score to populate)")

    def start_backend_servers(self):
        try:
            backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')
            python_executable = sys.executable
            fastapi_cmd = [python_executable, "-m", "uvicorn", "main:app", "--port", "8000", "--ws-max-size", "10485760"] # 10 MB limit
            processes.append(subprocess.Popen(fastapi_cmd, cwd=backend_dir))
            conductor_cmd = [python_executable, "conductor_backend.py"]
            processes.append(subprocess.Popen(conductor_cmd, cwd=backend_dir))
            self.status_label.setText("Backend services are running.")
            print("Both backend processes started.")
        except Exception as e:
            self.status_label.setText(f"Error starting backend: {e}")

def main():
    app = QApplication(sys.argv)
    control_panel = ControlPanel()
    control_panel.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
