from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List
import json

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.musician_connections: List[WebSocket] = []
        self.conductor_connection: WebSocket = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # For simplicity, the first client to identify as conductor is it.
        # A more robust app would have rooms and authentication.
        self.musician_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.musician_connections:
            self.musician_connections.remove(websocket)
        if self.conductor_connection == websocket:
            self.conductor_connection = None

    async def broadcast_to_musicians(self, message: str):
        for connection in self.musician_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            if msg_type == 'conductor_join':
                manager.conductor_connection = websocket
                # The conductor is not also a musician
                manager.musician_connections.remove(websocket)
                print("Conductor has joined.")

            elif websocket == manager.conductor_connection:
                # Only the conductor can send these messages
                if msg_type == 'load_score':
                    print(f"Conductor loaded score, broadcasting to {len(manager.musician_connections)} musicians.")
                    await manager.broadcast_to_musicians(data)
                elif msg_type == 'start_performance':
                    print(f"Conductor started performance, broadcasting to {len(manager.musician_connections)} musicians.")
                    await manager.broadcast_to_musicians(data)
            else:
                # Regular musician client, ignore messages for now
                print(f"Received message from musician: {data}")

    except WebSocketDisconnect:
        print("A client disconnected.")
        manager.disconnect(websocket)
    except Exception as e:
        print(f"Error: {e}")
        manager.disconnect(websocket)
