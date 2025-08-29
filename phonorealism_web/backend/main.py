from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List
import json

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"HUB: New client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"HUB: Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: str, source_websocket: WebSocket):
        # Don't send messages back to the original sender.
        other_clients = [conn for conn in self.active_connections if conn is not source_websocket]
        print(f"HUB: Broadcasting message to {len(other_clients)} other clients: {message[:200]}...")
        for connection in other_clients:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"HUB: Error sending to a client: {e}")

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    print(f"HUB: Entered message loop for client {client_id}.")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"HUB: Received from {client_id}: {data[:200]}...")
            # Pass the source websocket to the broadcast function to prevent echo
            await manager.broadcast(data, websocket)
    except WebSocketDisconnect:
        print(f"HUB: Client {client_id} disconnected cleanly.")
        manager.disconnect(websocket)
    except Exception as e:
        print(f"HUB: Error in handler for {client_id}: {e}")
        manager.disconnect(websocket)
    print(f"HUB: Exited message loop for client {client_id}.")