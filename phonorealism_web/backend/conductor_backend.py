import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np
import csv
import io
import time as time_module
from collections import defaultdict

# Configuration
WS_HOST = "localhost"
WS_PORT = 8001
PERFORMER_WS_URL = "ws://localhost:8000/ws"
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
DEVICE_CHANNELS = 2 # Stereo output

# Global State
performer_websocket = None
pre_rendered_audio = None
current_position = 0
is_playing = False
audio_stream = None
selected_output_device = None # Will store the device ID selected by the user

def db_to_linear(db):
    return 10**(db / 20.0)

def _group_events_by_harmonic(events):
    harmonics = defaultdict(list)
    for event in events:
        harmonics[event['harmonic_index']].append(
            (event['time'], event['frequency'], event['amplitude'])
        )
    # Return a list of harmonics, where each harmonic is a list of (time, freq, amp) tuples
    return [harmonics[key] for key in sorted(harmonics.keys())]

def pre_render_score(events):
    if not events:
        print("Cannot render an empty score.")
        return None

    print("Starting pre-rendering of the score using interpolation method...")
    start_time = time_module.time()

    harmonics = _group_events_by_harmonic(events)
    
    total_duration = max(event['time'] for event in events) + 1.0 # Add a second of tail
    total_samples = int(total_duration * SAMPLE_RATE)
    
    # Master waveform buffer
    master_waveform = np.zeros(total_samples, dtype=np.float32)

    for harmonic_events in harmonics:
        if not harmonic_events:
            continue

        # Unzip the event tuples into separate arrays for interpolation
        time_array, freq_array, amp_array = zip(*harmonic_events)

        # Transpose frequency down by one octave as requested
        freq_array = np.array(freq_array) / 2

        # Create the master time vector for the entire duration
        t = np.linspace(0, total_duration, total_samples)
        
        # Interpolate frequency and amplitude over the master time vector
        # This creates smoothly varying frequency and amplitude envelopes
        freq_interp = np.interp(t, time_array, freq_array)
        amp_interp = np.interp(t, time_array, amp_array)

        # Calculate phase by integrating frequency (using cumulative sum)
        # This is the correct way to handle variable-frequency oscillators
        phase = 2 * np.pi * np.cumsum(freq_interp) / SAMPLE_RATE
        
        # Generate the waveform for this single harmonic
        partial_wave = amp_interp * np.sin(phase)

        # Add this harmonic's waveform to the master mix
        master_waveform += partial_wave

    print("Downmixing to stereo and normalizing...")
    # Tile the mono signal to stereo
    stereo_output = np.tile(master_waveform[:, np.newaxis], (1, DEVICE_CHANNELS))
    
    # Normalize the final audio to prevent clipping
    max_abs = np.max(np.abs(stereo_output))
    if max_abs > 0:
        stereo_output /= max_abs

    end_time = time_module.time()
    print(f"Pre-rendering finished in {end_time - start_time:.2f} seconds.")
    return stereo_output

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
        # Sorting is important for grouping by harmonic correctly
        events.sort(key=lambda e: e['time'])
        print(f"Parsed and sorted {len(events)} events.")
    except (ValueError, IndexError, StopIteration) as e:
        print(f"Error parsing CSV: {e}")
    return events

def audio_callback(outdata, frames, time, status):
    global is_playing, current_position, pre_rendered_audio

    if status:
        print(status, file=sys.stderr)

    if not is_playing or pre_rendered_audio is None:
        outdata.fill(0)
        return

    start = current_position
    end = start + frames
    
    remaining_frames = len(pre_rendered_audio) - start
    if remaining_frames >= frames:
        outdata[:] = pre_rendered_audio[start:end]
    else:
        # Reached the end of the pre-rendered audio
        outdata[:remaining_frames] = pre_rendered_audio[start:]
        outdata[remaining_frames:] = 0 # Fill the rest with silence
        is_playing = False # Stop playback
        print("Playback finished.")

    current_position += frames

async def connect_to_performer_backend():
    global performer_websocket
    while True:
        try:
            print(f"Attempting to connect to Performer backend at {PERFORMER_WS_URL}...")
            performer_websocket = await websockets.connect(PERFORMER_WS_URL)
            print("Connected to Performer backend.")
            await performer_websocket.send(json.dumps({"type": "conductor_join"}))
            break
        except ConnectionRefusedError:
            print("Performer backend hub not available, retrying in 3 seconds...")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Error connecting to Performer backend: {e}, retrying in 3 seconds...")
            await asyncio.sleep(3)

async def start_audio_stream():
    global audio_stream, selected_output_device
    if audio_stream and audio_stream.active:
        audio_stream.stop()
        audio_stream.close()
        print("Existing audio stream stopped.")
    try:
        device_name = 'default'
        if selected_output_device is not None:
            try:
                device_info = sd.query_devices(selected_output_device, 'output')
                device_name = device_info['name']
            except Exception as e:
                print(f"Could not query device ID {selected_output_device}: {e}")
        
        print(f"Opening stereo audio stream on device: {device_name}")
        audio_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, 
            channels=DEVICE_CHANNELS, 
            blocksize=BLOCK_SIZE, 
            callback=audio_callback,
            device=selected_output_device # Use the selected device
        )
        audio_stream.start()
        print(f"Audio stream started successfully on {device_name}.")
    except Exception as e:
        print(f"Failed to start audio stream: {e}")

async def handle_websocket(websocket, path):
    global is_playing, current_position, pre_rendered_audio, selected_output_device

    print(f"Conductor backend client connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload")

            if msg_type == "load_score":
                events = parse_csv_score(payload)
                pre_rendered_audio = pre_render_score(events)
                current_position = 0
                is_playing = False
                await start_audio_stream()
                if performer_websocket and performer_websocket.open:
                    await performer_websocket.send(json.dumps({"type": "load_score", "payload": payload}))

            elif msg_type == "start_performance":
                if not is_playing and pre_rendered_audio is not None:
                    print("Starting playback...")
                    if current_position >= len(pre_rendered_audio):
                        current_position = 0 # Restart if at the end
                    is_playing = True
                if performer_websocket and performer_websocket.open:
                    await performer_websocket.send(json.dumps({"type": "start_performance"}))

            elif msg_type == "pause_performance":
                if is_playing:
                    print("Pausing playback...")
                    is_playing = False
                if performer_websocket and performer_websocket.open:
                    await performer_websocket.send(json.dumps({"type": "pause_performance"}))

            elif msg_type == "stop_performance":
                print("Stopping playback and resetting position...")
                is_playing = False
                current_position = 0
                if performer_websocket and performer_websocket.open:
                    await performer_websocket.send(json.dumps({"type": "stop_performance"}))
            
            elif msg_type == "set_audio_device":
                device_id = payload.get('device_id')
                print(f"Received request to set audio device to: {device_id}")
                selected_output_device = device_id
                # Restart the audio stream to apply the new device
                await start_audio_stream()

    except Exception as e:
        print(f"WebSocket handler error: {e}")

async def main():
    asyncio.create_task(connect_to_performer_backend())
    await start_audio_stream() # Start with a silent stream
    print(f"WebSocket server starting on ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(handle_websocket, WS_HOST, WS_PORT, max_size=10*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")