from fastapi import FastAPI, WebSocket
import numpy as np
import librosa
import soundfile as sf
import io

app = FastAPI()

def analyze_audio_bytes(audio_bytes: bytes):
    """
    Analyzes audio bytes to extract the fundamental frequency (f0).
    """
    try:
        # Use BytesIO to treat the bytes as a file
        y, sr = sf.read(io.BytesIO(audio_bytes))
        
        # If the audio is stereo, convert it to mono
        if y.ndim > 1:
            y = y.mean(axis=1)

        # Estimate fundamental frequency (f0)
        f0, _, _ = librosa.pyin(y, sr=sr, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
        
        # Get the average f0, ignoring NaNs
        avg_f0 = np.nanmean(f0)
        
        if np.isnan(avg_f0):
            return {"f0": "-"}
        else:
            return {"f0": f"{avg_f0:.2f} Hz"}

    except Exception as e:
        print(f"Error processing audio: {e}")
        return {"error": str(e)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_bytes()
        analysis_result = analyze_audio_bytes(data)
        await websocket.send_json(analysis_result)