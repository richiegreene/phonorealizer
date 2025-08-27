document.addEventListener('DOMContentLoaded', () => {
    // --- Element Setup ---
    const statusDiv = document.getElementById('status');
    const partialSelector = document.getElementById('partialSelector');
    const micButton = document.getElementById('micButton');
    const toggleButton = document.getElementById('toggle');
    const logArea = document.getElementById('log');
    const liveCanvas = document.getElementById('live-visualizer');
    const scoreCanvas = document.getElementById('score-visualizer');
    const liveCtx = liveCanvas.getContext('2d');
    const scoreCtx = scoreCanvas.getContext('2d');

    // --- State Variables ---
    let scoreData = [], liveHistory = [];
    let audioContext, pitchModel;
    let isRunning = false, isMicEnabled = false, isScoreLoaded = false;
    let startTime = 0, animationFrameId;
    let currentPitch = null;
    let pitchMin = 200, pitchMax = 1200, ampMin = -60, ampMax = 0;

    function logMessage(message) {
        const time = new Date().toLocaleTimeString();
        logArea.textContent = `[${time}] ${message}\n` + logArea.textContent;
    }

    logMessage("Script loaded. Please enable mic.");

    // --- 1. WebSocket Communication ---
    const WS_URL = "ws://localhost:8000/ws";
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
        logMessage("Connected to server.");
        statusDiv.textContent = "Connected. Waiting for conductor to load score.";
    };

    socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        logMessage(`Message received: ${message.type}`);

        if (message.type === 'load_score') {
            scoreData = parseCSV(message.payload);
            logMessage(`Score received with ${scoreData.length} records.`);
            populatePartials(scoreData);
            updateAxes(scoreData, parseInt(partialSelector.value, 10));
            partialSelector.disabled = false;
            isScoreLoaded = true;
            if (isMicEnabled) { toggleButton.disabled = false; }
            statusDiv.textContent = "Score loaded. Ready.";
        } else if (message.type === 'start_performance') {
            if (isMicEnabled && isScoreLoaded) { runVisualization(); }
        } else if (message.type === 'stop_performance') {
            if (isRunning) { stopVisualization(); }
        }
    };

    socket.onclose = () => {
        logMessage("Disconnected from server.");
        statusDiv.textContent = "Disconnected.";
        toggleButton.disabled = true;
    };

    // --- 2. UI & Data Logic ---
    partialSelector.addEventListener('change', () => {
        updateAxes(scoreData, parseInt(partialSelector.value, 10));
    });

    function parseCSV(text) {
        const lines = text.split(/\r\n|\n/).slice(1);
        return lines.map(line => {
            const [time, harmonic_index, frequency, amplitude] = line.split(',');
            return { time: parseFloat(time), harmonic_index: parseInt(harmonic_index, 10), frequency: parseFloat(frequency), amplitude: parseFloat(amplitude) };
        }).filter(d => !isNaN(d.time) && d.frequency > 0);
    }

    function populatePartials(data) {
        const partials = [...new Set(data.map(d => d.harmonic_index))].sort((a, b) => a - b);
        partialSelector.innerHTML = '';
        partials.forEach(p => {
            if (!isNaN(p)) {
                const option = document.createElement('option');
                option.value = p;
                option.textContent = `Part ${p}`;
                partialSelector.appendChild(option);
            }
        });
    }

    function updateAxes(data, partialIndex) {
        const partialData = data.filter(d => d.harmonic_index === partialIndex);
        if (partialData.length > 0) {
            const freqs = partialData.map(d => d.frequency);
            pitchMin = Math.min(...freqs) * 0.9;
            pitchMax = Math.max(...freqs) * 1.1;
            const amps = partialData.map(d => d.amplitude);
            ampMin = Math.min(...amps);
            ampMax = Math.max(...amps);
            logMessage(`Axes updated for partial ${partialIndex}.`);
        }
    }

    // --- 3. Audio and Animation Control ---
    micButton.addEventListener('click', async () => {
        if (isMicEnabled) return;
        logMessage("Attempting to enable mic...");
        try {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            logMessage("Microphone access granted.");
            const model_url = 'https://cdn.jsdelivr.net/gh/ml5js/ml5-data-and-models/models/pitch-detection/crepe/';
            pitchModel = ml5.pitchDetection(model_url, audioContext, stream, () => {
                logMessage("Pitch detection model loaded.");
                micButton.textContent = "Mic Enabled";
                micButton.disabled = true;
                isMicEnabled = true;
                if (isScoreLoaded) { toggleButton.disabled = false; }
            });
        } catch (err) {
            logMessage(`!!! ERROR enabling mic: ${err.message} !!!`);
        }
    });

    toggleButton.addEventListener('click', () => {
        isRunning ? stopVisualization() : runVisualization();
    });

    function runVisualization() {
        if (isRunning || !isMicEnabled || !isScoreLoaded) return;
        logMessage("Starting visualization...");
        startTime = audioContext.currentTime;
        isRunning = true;
        toggleButton.textContent = 'Stop';
        liveHistory = [];
        pitchModel.getPitch(gotPitch);
        draw();
    }

    function gotPitch(error, frequency) {
        if (error) { currentPitch = null; return; }
        currentPitch = frequency ? frequency * 2 : null;
        if (isRunning) {
            pitchModel.getPitch(gotPitch);
        }
    }

    function getLiveAmplitude() {
        if (!pitchModel || !pitchModel.analyser) return 0;
        const buffer = new Float32Array(pitchModel.analyser.fftSize);
        pitchModel.analyser.getFloatTimeDomainData(buffer);
        let sumOfSquares = 0;
        for (let i = 0; i < buffer.length; i++) { sumOfSquares += buffer[i] * buffer[i]; }
        const rms = Math.sqrt(sumOfSquares / buffer.length);
        return Math.min(1, rms * 5); // Scale for better visualization
    }

    function stopVisualization() {
        if (audioContext && audioContext.state !== 'closed') { audioContext.close(); isMicEnabled = false; micButton.disabled = false; micButton.textContent = "Enable Mic";}
        if (animationFrameId) { cancelAnimationFrame(animationFrameId); }
        isRunning = false;
        toggleButton.textContent = 'Start';
        liveCtx.clearRect(0, 0, liveCanvas.width, liveCanvas.height);
        scoreCtx.clearRect(0, 0, scoreCanvas.width, scoreCanvas.height);
        logMessage("Visualization stopped.");
    }

    // --- 4. Full Visualization ---
    function draw() {
        if (!isRunning) return;

        const currentTime = audioContext.currentTime - startTime;
        const liveAmplitude = getLiveAmplitude();
        liveHistory.push({ pitch: currentPitch, amplitude: liveAmplitude, time: currentTime });
        if (liveHistory.length > 400) { liveHistory.shift(); }

        drawLive(liveCtx, currentTime);
        drawScore(scoreCtx, parseInt(partialSelector.value, 10), currentTime);

        animationFrameId = requestAnimationFrame(draw);
    }

    function pitchToY(pitch, canvas) {
        if (pitch === null || pitch <= 0 || !isFinite(pitch)) return null;
        const logPitch = Math.log(pitch);
        const logMin = Math.log(pitchMin);
        const logMax = Math.log(pitchMax);
        if (logMax === logMin) return canvas.height / 4;
        const scale = (logPitch - logMin) / (logMax - logMin);
        return (canvas.height / 2) - (scale * canvas.height / 2);
    }

    function amplitudeToY(amplitude, canvas) {
        const ampHeight = Math.max(0, Math.min(1, amplitude)) * (canvas.height / 2);
        return (canvas.height / 2) + ampHeight;
    }

    function drawLive(ctx, currentTime) {
        const lookbehind = 5; // seconds
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = '#f0f0f0';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.strokeStyle = '#000000';
        ctx.strokeRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.beginPath();
        ctx.moveTo(0, ctx.canvas.height / 2);
        ctx.lineTo(ctx.canvas.width, ctx.canvas.height / 2);
        ctx.stroke();

        // Draw pitch
        ctx.strokeStyle = '#FF0000';
        ctx.lineWidth = 2;
        ctx.beginPath();
        let lastY = null;
        for (const d of liveHistory) {
            const x = ((d.time - currentTime) / lookbehind) * ctx.canvas.width + ctx.canvas.width;
            const y = pitchToY(d.pitch, ctx.canvas);
            if (y !== null) {
                if (lastY === null) { ctx.moveTo(x, y); } else { ctx.lineTo(x, y); }
            }
            lastY = y;
        }
        ctx.stroke();

        // Draw amplitude
        ctx.strokeStyle = '#FFA500';
        ctx.lineWidth = 1;
        ctx.beginPath();
        lastY = null;
        for (const d of liveHistory) {
            const x = ((d.time - currentTime) / lookbehind) * ctx.canvas.width + ctx.canvas.width;
            const y = amplitudeToY(d.amplitude, ctx.canvas);
            if (y !== null) {
                if (lastY === null) { ctx.moveTo(x, y); } else { ctx.lineTo(x, y); }
            }
            lastY = y;
        }
        ctx.stroke();

        drawTimeMarker(ctx, ctx.canvas.width);
    }

    function drawScore(ctx, partialIndex, currentTime) {
        const lookahead = 5; // seconds
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = '#f0f0f0';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.strokeStyle = '#000000';
        ctx.strokeRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.beginPath();
        ctx.moveTo(0, ctx.canvas.height / 2);
        ctx.lineTo(ctx.canvas.width, ctx.canvas.height / 2);
        ctx.stroke();

        const visibleData = scoreData.filter(d => 
            d.harmonic_index === partialIndex &&
            d.time >= currentTime &&
            d.time < currentTime + lookahead
        );

        // Draw pitch
        ctx.strokeStyle = '#0000FF';
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let i = 1; i < visibleData.length; i++) {
            const d1 = visibleData[i-1], d2 = visibleData[i];
            const x1 = ((d1.time - currentTime) / lookahead) * ctx.canvas.width;
            const y1 = pitchToY(d1.frequency, ctx.canvas);
            const x2 = ((d2.time - currentTime) / lookahead) * ctx.canvas.width;
            const y2 = pitchToY(d2.frequency, ctx.canvas);
            if (y1 !== null && y2 !== null) { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
        }
        ctx.stroke();

        // Draw amplitude
        ctx.strokeStyle = '#ADD8E6';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 1; i < visibleData.length; i++) {
            const d1 = visibleData[i-1], d2 = visibleData[i];
            const x1 = ((d1.time - currentTime) / lookahead) * ctx.canvas.width;
            const y1 = amplitudeToY((d1.amplitude - ampMin) / (ampMax - ampMin), ctx.canvas);
            const x2 = ((d2.time - currentTime) / lookahead) * ctx.canvas.width;
            const y2 = amplitudeToY((d2.amplitude - ampMin) / (ampMax - ampMin), ctx.canvas);
            if (y1 !== null && y2 !== null) { ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); }
        }
        ctx.stroke();

        drawTimeMarker(ctx, 0);
    }

    function drawTimeMarker(ctx, xPos) {
        ctx.strokeStyle = '#000000';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xPos, 0);
        ctx.lineTo(xPos, ctx.canvas.height);
        ctx.stroke();
    }
});