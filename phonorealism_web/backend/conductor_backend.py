import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np
import csv
import io
import sys
import time as time_module
from collections import defaultdict

# --- Configuration ---
WS_HOST = "localhost"
WS_PORT = 8001
PERFORMER_WS_URL = "ws://localhost:8000/ws"
SAMPLE_RATE = 44100
BLOCK_SIZE = 2048

# --- Global State ---
performer_websocket = None
selected_output_device = None
audio_stream = None
score_events = []
source_buffer = None
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

def pre_render_source_buffer(events):
    if not events:
        return None, []
    print("AUDIO_ENGINE: Starting pre-rendering of source harmonics...")
    start_time = time_module.time()
    harmonic_indices = sorted(list({e['harmonic_index'] for e in events}))
    num_harmonics = len(harmonic_indices)
    channel_map = {h_idx: i for i, h_idx in enumerate(harmonic_indices)}
    grouped_events = defaultdict(list)
    for event in events:
        grouped_events[event['harmonic_index']].append(event)
    total_duration = max(event['time'] for event in events) + 2.0
    total_samples = int(total_duration * SAMPLE_RATE)
    buffer = np.zeros((total_samples, num_harmonics), dtype=np.float32)
    for h_idx, h_events in grouped_events.items():
        channel_idx = channel_map.get(h_idx)
        if channel_idx is None: continue
        time_array = [e['time'] for e in h_events]
        freq_array = [e['frequency'] for e in h_events]
        amp_array = [e['amplitude'] for e in h_events]
        freq_array = np.array(freq_array) / 2
        t = np.linspace(0, total_duration, total_samples)
        freq_interp = np.interp(t, time_array, freq_array)
        amp_interp = np.interp(t, time_array, amp_array)
        phase = 2 * np.pi * np.cumsum(freq_interp) / SAMPLE_RATE
        buffer[:, channel_idx] = amp_interp * np.sin(phase)
    end_time = time_module.time()
    print(f"AUDIO_ENGINE: Source buffer rendered in {end_time - start_time:.2f} seconds.")
    return buffer, harmonic_indices

def audio_callback(outdata, frames, time, status):
    global is_playing, current_position, source_buffer, harmonic_routing
    if status:
        print(status, file=sys.stderr)
    outdata.fill(0)
    if not is_playing or source_buffer is None: return
    start = current_position
    end = start + frames
    remaining_frames = len(source_buffer) - start
    if remaining_frames <= 0:
        is_playing = False
        return
    src_slice = source_buffer[start:end] if remaining_frames >= frames else source_buffer[start:]
    slice_len = len(src_slice)
    for h_index, out_channel in harmonic_routing.items():
        if out_channel != -1 and out_channel < outdata.shape[1]:
            if int(h_index) - 1 < src_slice.shape[1]:
                 outdata[:slice_len, out_channel] += src_slice[:, int(h_index) - 1]
    current_position += frames

async def start_audio_stream():
    global audio_stream, selected_output_device
    if audio_stream:
        print("AUDIO_ENGINE: Stopping and closing existing audio stream...")
        audio_stream.stop(ignore_errors=True)
        audio_stream.abort(ignore_errors=True)
        audio_stream.close(ignore_errors=True)
        audio_stream = None
        await asyncio.sleep(0.1) # Short pause to allow resources to be released
    try:
        device_info = sd.query_devices(selected_output_device, 'output')
        num_channels = device_info['max_output_channels']
        device_name = device_info['name']
        print(f"AUDIO_ENGINE: Opening {num_channels}-channel audio stream on device: '{device_name}'")
        audio_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=num_channels, 
            blocksize=BLOCK_SIZE, callback=audio_callback, device=selected_output_device)
        audio_stream.start()
        print(f"AUDIO_ENGINE: Audio stream started successfully.")
    except Exception as e:
        print(f"AUDIO_ENGINE: Failed to start audio stream: {e}")

async def listen_to_hub():
    global performer_websocket, is_playing, current_position, score_events, source_buffer, harmonic_routing, selected_output_device
    while True:
        try:
            message = await performer_websocket.recv()
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload")
            print(f"AUDIO_ENGINE: Received message '{msg_type}' from hub.")
            if msg_type == "load_score":
                score_events = parse_csv_score(payload)
                source_buffer, harmonic_indices = pre_render_source_buffer(score_events)
                device_info = sd.query_devices(selected_output_device, 'output')
                num_output_channels = device_info['max_output_channels']
                harmonic_routing = {h: (i % num_output_channels) for i, h in enumerate(harmonic_indices)}
                current_position, is_playing = 0, False
                await start_audio_stream()
                response = {"type": "harmonics_list", "payload": {"harmonics": harmonic_indices, "routing": {str(k): v for k, v in harmonic_routing.items()}}}
                await performer_websocket.send(json.dumps(response))
            elif msg_type == "start_performance":
                if not is_playing and source_buffer is not None:
                    if current_position >= len(source_buffer):
                        current_position = 0
                    is_playing = True
            elif msg_type == "pause_performance":
                is_playing = False
            elif msg_type == "stop_performance":
                is_playing, current_position = False, 0
            elif msg_type == "set_audio_device":
                selected_output_device = payload.get('device_id')
                await start_audio_stream()
            elif msg_type == "set_harmonic_routing":
                h_index = int(payload.get('harmonic_index'))
                channel = int(payload.get('channel'))
                if h_index is not None and channel is not None:
                    harmonic_routing[h_index] = channel
        except websockets.exceptions.ConnectionClosed:
            await connect_to_hub()
        except Exception as e:
            print(f"AUDIO_ENGINE: Error processing message from hub: {e}")

async def connect_to_hub():
    global performer_websocket
    while True:
        try:
            performer_websocket = await websockets.connect(PERFORMER_WS_URL, max_size=10*1024*1024)
            print("AUDIO_ENGINE: Connected to hub.")
            break
        except ConnectionRefusedError:
            await asyncio.sleep(3)
        except Exception as e:
            print(f"AUDIO_ENGINE: Error connecting to hub: {e}")
            await asyncio.sleep(3)

async def main():
    await connect_to_hub()
    await asyncio.gather(listen_to_hub(), start_audio_stream())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down audio engine...")