import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np

# Configuration for the WebSocket server
WS_HOST = "localhost"
WS_PORT = 8001  # Use a different port than the existing backend (8000)

# Performer Backend WebSocket URL
import asyncio
import websockets
import json
import sounddevice as sd
import numpy as np
import csv
import io

# Configuration for the WebSocket server
WS_HOST = "localhost"
WS_PORT = 8001  # Use a different port than the existing backend (8000)

# Performer Backend WebSocket URL
PERFORMER_WS_URL = "ws://localhost:8000/ws"
performer_websocket = None

# Audio parameters
SAMPLE_RATE = 44100  # Hz
CHANNELS = 2       # Default, will be dynamically set based on score
BLOCK_SIZE = 512   # Audio processing block size

# Global state for audio playback
score_events = [] # Parsed CSV data
channel_map = {}  # Maps harmonic_index to output_channel_index
active_voices = {} # {harmonic_index: {'phase': float, 'amplitude': float}}
current_position = 0 # in samples
is_playing = False

audio_stream = None # Global audio stream object

def db_to_linear(db):
    return 10**(db / 20.0)

def parse_csv_score(csv_content):
    global channel_map, CHANNELS
    events = []
    harmonic_indices = set()
    
    csv_file = io.StringIO(csv_content)
    reader = csv.reader(csv_file)
    
    header = next(reader) # Skip header row
    
    for row in reader:
        try:
            # Assuming CSV format: time,harmonic_index,frequency,amplitude
            time = float(row[0])
            harmonic_index = int(row[1])
            frequency = float(row[2])
            amplitude_db = float(row[3])
            
            events.append({
                'time': time,
                'harmonic_index': harmonic_index,
                'frequency': frequency,
                'amplitude': db_to_linear(amplitude_db) # Convert dB to linear
            })
            harmonic_indices.add(harmonic_index)
        except (ValueError, IndexError) as e:
            print(f"Skipping malformed CSV row: {row} - {e}")
            continue
            
    # Create channel map and set CHANNELS
    sorted_harmonics = sorted(list(harmonic_indices))
    channel_map = {harmonic: i for i, harmonic in enumerate(sorted_harmonics)}
    CHANNELS = len(sorted_harmonics) if len(sorted_harmonics) > 0 else 1 # Ensure at least 1 channel
    
    print(f"Parsed {len(events)} events. Found {len(harmonic_indices)} unique harmonics. Setting {CHANNELS} channels.")
    return events

def audio_callback(outdata, frames, time, status):
    global is_playing, current_position, score_events, active_voices, channel_map, CHANNELS

    if status:
        print(status)

    # Ensure outdata has the correct number of channels
    if outdata.shape[1] != CHANNELS:
        # This warning should ideally not happen if stream is correctly re-initialized
        # but it's here as a safeguard.
        print(f"Warning: outdata channels ({outdata.shape[1]}) mismatch CHANNELS ({CHANNELS}). Filling with zeros.")
        outdata.fill(0)
        return

    if not is_playing or not score_events:
        outdata.fill(0)
        return

    # Initialize output buffer for mixing
    output_buffer = np.zeros((frames, CHANNELS), dtype=np.float32)

    # Calculate time range for this block
    block_start_time = current_position / SAMPLE_RATE
    block_end_time = (current_position + frames) / SAMPLE_RATE

    # Update active voices based on score events within this block's time frame
    # This is a simplified event processing. For precise timing, events should be scheduled.
    for event in score_events:
        if block_start_time <= event['time'] < block_end_time:
            harmonic = event['harmonic_index']
            if harmonic in channel_map:
                # For simplicity, we'll just update the active voice's state
                # A more robust system would handle note-on/off and envelopes
                active_voices[harmonic] = {
                    'frequency': event['frequency'],
                    'amplitude': event['amplitude'],
                    'phase': active_voices.get(harmonic, {}).get('phase', 0.0) # Retain phase if voice already active
                }
            
    # Generate and mix sine waves for active voices
    for harmonic, voice_state in list(active_voices.items()): # Use list() to allow modification during iteration
        frequency = voice_state['frequency']
        amplitude = voice_state['amplitude']
        phase = voice_state['phase']
        channel_idx = channel_map.get(harmonic)

        if channel_idx is not None and channel_idx < CHANNELS:
            t = (np.arange(frames) + current_position) / SAMPLE_RATE
            sine_wave = amplitude * np.pi * np.sin(2 * np.pi * frequency * t + phase) # Added pi for amplitude scaling
            
            # Add to the correct channel in the output buffer
            output_buffer[:, channel_idx] += sine_wave
            
            # Update phase for next block
            voice_state['phase'] = (phase + 2 * np.pi * frequency * frames / SAMPLE_RATE) % (2 * np.pi)
            active_voices[harmonic] = voice_state # Update global state
        else:
            print(f"Warning: Harmonic {harmonic} mapped to invalid channel {channel_idx}.")
            
    # Mix output_buffer into outdata, clipping to prevent overflow
    np.clip(output_buffer, -1.0, 1.0, out=outdata)

    current_position += frames

async def connect_to_performer_backend():
    global performer_websocket
    while True:
        try:
            print(f"Attempting to connect to Performer backend at {PERFORMER_WS_URL}...")
            performer_websocket = await websockets.connect(PERFORMER_WS_URL)
            print("Connected to Performer backend.")
            # Send a join message if needed by the performer backend
            await performer_websocket.send(json.dumps({"type": "conductor_join"}))
            break # Exit loop on successful connection
        except (websockets.exceptions.ConnectionRefusedError, ConnectionRefusedError):
            print("Performer backend not available, retrying in 3 seconds...")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Error connecting to Performer backend: {e}, retrying in 3 seconds...")
            await asyncio.sleep(3)

async def start_audio_stream():
    global audio_stream, CHANNELS, SAMPLE_RATE, BLOCK_SIZE
    if audio_stream is not None and audio_stream.active:
        audio_stream.stop()
        audio_stream.close()
        print("Existing audio stream stopped and closed.")

    try:
        print(f"Starting audio stream with {CHANNELS} channels, sample rate {SAMPLE_RATE}.")
        audio_stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=BLOCK_SIZE, callback=audio_callback)
        audio_stream.start()
        print(f"Audio stream started. Default output device: {sd.query_devices(kind='output')['name']}")
    except Exception as e:
        print(f"Failed to start audio stream: {e}")
        print("Please ensure you have an audio output device configured and sounddevice is installed correctly.")
        print("You might need to install portaudio: 'brew install portaudio' (macOS) or 'sudo apt-get install libportaudio2' (Debian/Ubuntu)")
        print("Then install sounddevice: 'pip install sounddevice'")

async def handle_websocket(websocket, path):
    global is_playing, current_position, score_events, channel_map, CHANNELS, performer_websocket

    print(f"Conductor backend connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload")

            print(f"Received message: {msg_type}")

            if msg_type == "load_score":
                score_events = parse_csv_score(payload) # Parse the CSV content
                print(f"Loaded score data with {len(score_events)} events.")
                current_position = 0 # Reset position on new score load
                is_playing = False # Ensure not playing until 'start'
                await start_audio_stream() # Start/re-start audio stream with correct channels

                # Forward the load_score message to the Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "load_score", "payload": payload}))
                        print("Forwarded load_score to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding load_score to Performer backend: {e}")
                        performer_websocket = None # Mark as disconnected
                else:
                    print("Performer backend not connected, cannot forward load_score.")

            elif msg_type == "start_performance":
                if not is_playing:
                    print("Starting performance...")
                    is_playing = True
                # Forward start_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "start_performance"}))
                        print("Forwarded start_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding start_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "pause_performance":
                print("Pausing performance...")
                is_playing = False
                # Forward pause_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "pause_performance"}))
                        print("Forwarded pause_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding pause_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "stop_performance":
                print("Stopping performance and resetting position...")
                is_playing = False
                current_position = 0 # Reset to beginning
                # Forward stop_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "stop_performance"}))
                        print("Forwarded stop_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding stop_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "conductor_join":
                print("Conductor joined.")
            else:
                print(f"Unknown message type: {msg_type}")

    except websockets.exceptions.ConnectionClosedOK:
        print("Conductor backend disconnected gracefully.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"Conductor backend disconnected with error: {e}")
    except Exception as e:
        print(f"Unexpected error in WebSocket handler: {e}")

async def main():
    # Start the task to connect to the Performer backend
    asyncio.create_task(connect_to_performer_backend())

    # Initial audio stream setup (will be re-initialized on load_score)
    # This ensures a stream is active even before a score is loaded
    await start_audio_stream()

    try:
        print(f"WebSocket server starting on ws://{WS_HOST}:{WS_PORT}")
        async with websockets.serve(handle_websocket, WS_HOST, WS_PORT, max_size=10 * 1024 * 1024):
            await asyncio.Future()  # Run forever
    except Exception as e:
        print(f"Failed to start WebSocket server: {e}")
        print("Please ensure you have an audio output device configured and sounddevice is installed correctly.")
        print("You might need to install portaudio: 'brew install portaudio' (macOS) or 'sudo apt-get install libportaudio2' (Debian/Ubuntu)")
        print("Then install sounddevice: 'pip install sounddevice'")

if __name__ == "__main__":
    asyncio.run(main())

# Audio parameters (placeholders for now)
SAMPLE_RATE = 44100  # Hz
CHANNELS = 2       # Stereo output for testing, will be dynamic later
BLOCK_SIZE = 512   # Audio processing block size

# Global state for audio playback
current_score_data = []
is_playing = False
current_position = 0 # in samples

def audio_callback(outdata, frames, time, status):
    global is_playing, current_position, current_score_data

    if status:
        print(status)

    if not is_playing or not current_score_data:
        outdata.fill(0)
        return

    # Placeholder for actual sine wave generation and mixing
    # This is where the CSV data will be used to generate audio
    # For now, let's generate a simple sine wave
    
    # Example: Generate a 440 Hz sine wave
    frequency = 440.0
    t = (current_position + np.arange(frames)) / SAMPLE_RATE
    sine_wave = 0.5 * np.sin(2 * np.pi * frequency * t)

    # If stereo, duplicate for both channels
    if CHANNELS > 1:
        outdata[:, 0] = sine_wave
        outdata[:, 1] = sine_wave
    else:
        outdata[:] = sine_wave.reshape(-1, 1)

    current_position += frames

async def connect_to_performer_backend():
    global performer_websocket
    while True:
        try:
            print(f"Attempting to connect to Performer backend at {PERFORMER_WS_URL}...")
            performer_websocket = await websockets.connect(PERFORMER_WS_URL)
            print("Connected to Performer backend.")
            # Send a join message if needed by the performer backend
            await performer_websocket.send(json.dumps({"type": "conductor_join"}))
            break # Exit loop on successful connection
        except (websockets.exceptions.ConnectionRefusedError, ConnectionRefusedError):
            print("Performer backend not available, retrying in 3 seconds...")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Error connecting to Performer backend: {e}, retrying in 3 seconds...")
            await asyncio.sleep(3)

async def handle_websocket(websocket, path):
    global is_playing, current_position, current_score_data, performer_websocket

    print(f"Conductor backend connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload")

            print(f"Received message: {msg_type}")

            if msg_type == "load_score":
                current_score_data = payload # Store the CSV content for now
                print(f"Loaded score data (length: {len(payload)}).")
                current_position = 0 # Reset position on new score load
                is_playing = False # Ensure not playing until 'start'

                # Forward the load_score message to the Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "load_score", "payload": payload}))
                        print("Forwarded load_score to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding load_score to Performer backend: {e}")
                        performer_websocket = None # Mark as disconnected
                else:
                    print("Performer backend not connected, cannot forward load_score.")

            elif msg_type == "start_performance":
                if not is_playing:
                    print("Starting performance...")
                    is_playing = True
                # Forward start_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "start_performance"}))
                        print("Forwarded start_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding start_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "pause_performance":
                print("Pausing performance...")
                is_playing = False
                # Forward pause_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "pause_performance"}))
                        print("Forwarded pause_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding pause_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "stop_performance":
                print("Stopping performance and resetting position...")
                is_playing = False
                current_position = 0 # Reset to beginning
                # Forward stop_performance to Performer backend
                if performer_websocket and performer_websocket.open:
                    try:
                        await performer_websocket.send(json.dumps({"type": "stop_performance"}))
                        print("Forwarded stop_performance to Performer backend.")
                    except Exception as e:
                        print(f"Error forwarding stop_performance to Performer backend: {e}")
                        performer_websocket = None

            elif msg_type == "conductor_join":
                print("Conductor joined.")
            else:
                print(f"Unknown message type: {msg_type}")

    except websockets.exceptions.ConnectionClosedOK:
        print("Conductor backend disconnected gracefully.")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"Conductor backend disconnected with error: {e}")
    except Exception as e:
        print(f"Unexpected error in WebSocket handler: {e}")

async def main():
    # Start the task to connect to the Performer backend
    asyncio.create_task(connect_to_performer_backend())

    try:
        print(f"Initializing audio stream with sample rate {SAMPLE_RATE} and {CHANNELS} channels.")
        # Using a context manager for the stream
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=BLOCK_SIZE, callback=audio_callback) as stream:
            print(f"Audio stream started. Default output device: {sd.query_devices(kind='output')['name']}")
            print(f"WebSocket server starting on ws://{WS_HOST}:{WS_PORT}")
            async with websockets.serve(handle_websocket, WS_HOST, WS_PORT, max_size=10 * 1024 * 1024):
                await asyncio.Future()  # Run forever
    except Exception as e:
        print(f"Failed to start audio stream or WebSocket server: {e}")
        print("Please ensure you have an audio output device configured and sounddevice is installed correctly.")
        print("You might need to install portaudio: 'brew install portaudio' (macOS) or 'sudo apt-get install libportaudio2' (Debian/Ubuntu)")
        print("Then install sounddevice: 'pip install sounddevice'")

if __name__ == "__main__":
    asyncio.run(main())
