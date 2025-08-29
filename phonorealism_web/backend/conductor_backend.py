import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np
import csv
import io
import sys
from collections import defaultdict

# --- Configuration ---
WS_HOST = "localhost"
WS_PORT = 8001
PERFORMER_WS_URL = "ws://localhost:8000/ws"
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024

# --- Global State ---
performer_websocket = None
selected_output_device = None
audio_stream = None
score_events = []
score_event_index = 0
active_voices = {}
harmonic_routing = {}
is_playing = False
current_position = 0

def db_to_linear(db):
    return 10**(db / 20.0)

def parse_csv_score(csv_content):
    events = []
    try:
        csv_file = io.StringIO(csv_content)
        reader = csv.reader(csv_file)
        header = next(reader)
        for row in reader:
            events.append({
                'time': float(row[0]),
                'harmonic_index': int(row[1]),
                'frequency': float(row[2]),
                'amplitude': db_to_linear(float(row[3]))
            })
        events.sort(key=lambda e: e['time'])
        print(f"AUDIO_ENGINE: Parsed and sorted {len(events)} events.")
    except Exception as e:
        print(f"AUDIO_ENGINE: Error parsing CSV: {e}")
    return events

def audio_callback(outdata, frames, time, status):
    global is_playing, current_position, score_event_index, active_voices, harmonic_routing
    if status:
        print(status, file=sys.stderr)
    outdata.fill(0)
    if not is_playing or not score_events:
        return

    block_end_time = (current_position + frames) / SAMPLE_RATE
    while score_event_index < len(score_events) and score_events[score_event_index]['time'] < block_end_time:
        event = score_events[score_event_index]
        active_voices[event['harmonic_index']] = {
            'freq': event['frequency'],
            'amp': event['amplitude'],
            'phase': active_voices.get(event['harmonic_index'], {}).get('phase', 0.0)
        }
        score_event_index += 1

    for h_index, voice_state in list(active_voices.items()):
        output_channel = harmonic_routing.get(h_index, -1)
        if output_channel != -1 and output_channel < outdata.shape[1]:
            frequency = voice_state['freq'] / 2
            amplitude = voice_state['amp']
            phase = voice_state['phase']
            t = (np.arange(frames) + current_position) / SAMPLE_RATE
            sine_wave = amplitude * np.sin(2 * np.pi * frequency * t + phase)
            outdata[:, output_channel] += sine_wave
            voice_state['phase'] = (phase + 2 * np.pi * frequency * frames / SAMPLE_RATE) % (2 * np.pi)
            active_voices[h_index] = voice_state
    current_position += frames

async def start_audio_stream():
    global audio_stream, selected_output_device
    if audio_stream and audio_stream.active:
        audio_stream.stop()
        audio_stream.close()
    
    num_channels = 2
    device_name = 'default'
    try:
        device_info = sd.query_devices(selected_output_device, 'output')
        device_name = device_info['name']
        num_channels = device_info['max_output_channels']
        print(f"AUDIO_ENGINE: Opening {num_channels}-channel audio stream on device: {device_name}")
        audio_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=num_channels, 
            blocksize=BLOCK_SIZE, callback=audio_callback, device=selected_output_device)
        audio_stream.start()
        print(f"AUDIO_ENGINE: Audio stream started successfully.")
    except Exception as e:
        print(f"AUDIO_ENGINE: Failed to start audio stream: {e}")

# This is the new main message processor for messages received FROM the hub
async def listen_to_hub():
    global performer_websocket, is_playing, current_position, score_events, score_event_index, active_voices, harmonic_routing, selected_output_device
    while True:
        try:
            message = await performer_websocket.recv()
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload")
            print(f"AUDIO_ENGINE: Received message '{msg_type}' from hub.")

            if msg_type == "load_score":
                score_events = parse_csv_score(payload)
                harmonic_indices = sorted(list({e['harmonic_index'] for e in score_events}))
                num_output_channels = sd.query_devices(selected_output_device, 'output')['max_output_channels']
                harmonic_routing = {h: (i % num_output_channels) for i, h in enumerate(harmonic_indices)}
                current_position, score_event_index, is_playing, active_voices = 0, 0, False, {}
                await start_audio_stream()
                response = {"type": "harmonics_list", "payload": {"harmonics": harmonic_indices, "routing": harmonic_routing}}
                print(f"AUDIO_ENGINE: Sending harmonics list back to hub.")
                await performer_websocket.send(json.dumps(response))

            elif msg_type == "start_performance":
                if not is_playing:
                    if current_position == 0:
                        score_event_index, active_voices = 0, {}
                    is_playing = True

            elif msg_type == "pause_performance":
                is_playing = False

            elif msg_type == "stop_performance":
                is_playing, current_position, score_event_index, active_voices = False, 0, 0, {}

            elif msg_type == "set_audio_device":
                selected_output_device = payload.get('device_id')
                await start_audio_stream()

            elif msg_type == "set_harmonic_routing":
                h_index = payload.get('harmonic_index')
                channel = payload.get('channel')
                if h_index is not None and channel is not None:
                    harmonic_routing[h_index] = channel

        except websockets.exceptions.ConnectionClosed:
            print("AUDIO_ENGINE: Connection to hub lost. Reconnecting...")
            await connect_to_hub() # Re-establish connection
        except Exception as e:
            print(f"AUDIO_ENGINE: Error processing message from hub: {e}")

# Renamed for clarity
async def connect_to_hub():
    global performer_websocket
    while True:
        try:
            performer_websocket = await websockets.connect(PERFORMER_WS_URL, max_size=10*1024*1024) # 10 MB limit
            print("AUDIO_ENGINE: Connected to hub.")
            # The join message is not strictly needed anymore but is harmless
            await performer_websocket.send(json.dumps({"type": "conductor_join"}))
            break
        except ConnectionRefusedError:
            print("AUDIO_ENGINE: Hub not available, retrying in 3s...")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"AUDIO_ENGINE: Error connecting to hub: {e}")
            await asyncio.sleep(3)

async def main():
    await connect_to_hub()
    # Run the hub listener and the initial audio stream concurrently
    await asyncio.gather(
        listen_to_hub(),
        start_audio_stream()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down audio engine...")