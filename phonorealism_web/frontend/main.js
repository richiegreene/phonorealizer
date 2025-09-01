document.addEventListener('DOMContentLoaded', () => {
    // --- Element Setup ---
    const statusDiv = document.getElementById('status');
    const partialSelector = document.getElementById('partialSelector');
    const micButton = document.getElementById('micButton');
    const toggleButton = document.getElementById('toggle');
    const gainSlider = document.getElementById('micGain');
    const gainValue = document.getElementById('gainValue');
    const logArea = document.getElementById('log');
    const liveCanvas = document.getElementById('live-visualizer');
    const scoreCanvas = document.getElementById('score-visualizer');
    const liveCtx = liveCanvas.getContext('2d');
    const scoreCtx = scoreCanvas.getContext('2d');

    // --- State Variables ---
    let scoreData = [], liveHistory = [];
    let audioContext, pitchModel, analyserNode, micStream;
    let isRunning = false, isMicEnabled = false, isScoreLoaded = false;
    let startTime = 0, animationFrameId;
    let currentPitch = null;
    let pitchMin = 200, pitchMax = 1200, scoreAmpMaxLinear = 0.01;

    // Constants for Live Pitch Range (Hz)
    const LIVE_PITCH_MIN = 50; // Roughly low C
    const LIVE_PITCH_MAX = 2000; // Roughly high C

    const PITCH_SECTION_HEIGHT_RATIO = 0.6;
    const AMP_SECTION_HEIGHT_RATIO = 0.4;

    function logMessage(message) {
        const time = new Date().toLocaleTimeString();
        logArea.textContent = `[${time}] ${message}\n` + logArea.textContent;
    }

    logMessage("Script loaded. Please enable mic.");

    // --- WebSocket Communication ---
    const socket = new WebSocket("ws://localhost:8000/ws");
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

    // --- UI & Data Logic ---
    gainSlider.addEventListener('input', () => { gainValue.textContent = parseFloat(gainSlider.value).toFixed(1); });
    partialSelector.addEventListener('change', () => { updateAxes(scoreData, parseInt(partialSelector.value, 10)); });

    function dbToLinear(db) { return Math.pow(10, db / 20.0); }
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
            const ampsLinear = partialData.map(d => dbToLinear(d.amplitude));
            scoreAmpMaxLinear = Math.max(...ampsLinear);
            logMessage(`Axes updated for partial ${partialIndex}.`);
        }
    }

    // --- Audio Initialization (One-time) ---
    micButton.addEventListener('click', async () => {
        if (isMicEnabled) return;
        logMessage("Attempting to enable mic...");
        try {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            logMessage("Microphone access granted.");

            analyserNode = audioContext.createAnalyser();
            const sourceNode = audioContext.createMediaStreamSource(micStream);
            sourceNode.connect(analyserNode);

            pitchModel = ml5.pitchDetection('https://cdn.jsdelivr.net/gh/ml5js/ml5-data-and-models/models/pitch-detection/crepe/', audioContext, micStream, () => {
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

    // --- Visualization Control ---
    function runVisualization() {
        if (isRunning || !isMicEnabled || !isScoreLoaded) return;
        logMessage("Starting visualization...");
        startTime = audioContext.currentTime;
        isRunning = true;
        liveHistory = [];
        pitchModel.getPitch(gotPitch);
        draw();
    }

    function stopVisualization() {
        if (!isRunning) return;
        logMessage("Visualization stopped.");
        isRunning = false;
        if (animationFrameId) { cancelAnimationFrame(animationFrameId); }
    }

    function gotPitch(error, frequency) {
        if (error) { currentPitch = null; return; }
        currentPitch = frequency ? frequency * 2 : null;
        if (isRunning) { // Only continue getting pitch if visualization is running
            pitchModel.getPitch(gotPitch);
        }
    }

    function getLiveAmplitude() {
        if (!analyserNode) return 0;
        const buffer = new Float32Array(analyserNode.fftSize);
        analyserNode.getFloatTimeDomainData(buffer);
        let sumOfSquares = 0;
        for (let i = 0; i < buffer.length; i++) { sumOfSquares += buffer[i] * buffer[i]; }
        const rms = Math.sqrt(sumOfSquares / buffer.length);
        const gain = parseFloat(gainSlider.value);
        return Math.min(1, rms * 1 * gain);
    }

    // --- Drawing Functions (Unchanged) ---
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
        const pitchSectionHeight = canvas.height * PITCH_SECTION_HEIGHT_RATIO;
        if (logMax === logMin) return pitchSectionHeight / 2;
        const scale = (logPitch - logMin) / (logMax - logMin);
        return pitchSectionHeight - (scale * pitchSectionHeight);
    }
    function amplitudeToY(normalizedAmplitude, canvas, mirror = false) {
        const ampSectionHeight = canvas.height * AMP_SECTION_HEIGHT_RATIO;
        const ampSectionTop = canvas.height * PITCH_SECTION_HEIGHT_RATIO;
        const ampCenterY = ampSectionTop + (ampSectionHeight / 2);
        const ampValue = normalizedAmplitude * (ampSectionHeight / 2);
        return mirror ? ampCenterY - ampValue : ampCenterY + ampValue;
    }
    function drawGraph(ctx, data, xProp, yFunc, color, lineWidth) {
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        let firstPoint = true;
        for (const d of data) {
            const x = d[xProp];
            const y = yFunc(d);
            if (y !== null) {
                if (firstPoint) { ctx.moveTo(x, y); firstPoint = false; } else { ctx.lineTo(x, y); }
            }
        }
        ctx.stroke();
    }
    function drawLive(ctx, currentTime) {
        const lookbehind = 2.5;
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = '#333333';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, ctx.canvas.height * PITCH_SECTION_HEIGHT_RATIO);
        ctx.lineTo(ctx.canvas.width, ctx.canvas.height * PITCH_SECTION_HEIGHT_RATIO);
        ctx.stroke();
        const timedData = liveHistory.map(d => ({ ...d, x: ((d.time - currentTime) / lookbehind) * ctx.canvas.width + ctx.canvas.width }));
        drawGraph(ctx, timedData, 'x', d => pitchToY(d.pitch, ctx.canvas, LIVE_PITCH_MIN, LIVE_PITCH_MAX), '#FFFFFF', 2);
        drawGraph(ctx, timedData, 'x', d => amplitudeToY(d.amplitude, ctx.canvas, true), '#FFFFFF', 1);
        drawGraph(ctx, timedData, 'x', d => amplitudeToY(d.amplitude, ctx.canvas, false), '#FFFFFF', 1);
        drawTimeMarker(ctx, ctx.canvas.width);
    }
    function drawScore(ctx, partialIndex, currentTime) {
        const lookahead = 5;
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = '#333333';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, ctx.canvas.height * PITCH_SECTION_HEIGHT_RATIO);
        ctx.lineTo(ctx.canvas.width, ctx.canvas.height * PITCH_SECTION_HEIGHT_RATIO);
        ctx.stroke();
        const visibleData = scoreData.filter(d => d.harmonic_index === partialIndex && d.time >= currentTime && d.time < currentTime + lookahead);
        drawGraph(ctx, visibleData.map(d => ({...d, x: ((d.time - currentTime) / lookahead) * ctx.canvas.width})), 'x', d => pitchToY(d.frequency, ctx.canvas, pitchMin, pitchMax), '#FFFFFF', 2);
        drawGraph(ctx, visibleData.map(d => ({...d, x: ((d.time - currentTime) / lookahead) * ctx.canvas.width})), 'x', d => amplitudeToY(dbToLinear(d.amplitude) / scoreAmpMaxLinear, ctx.canvas, true), '#FFFFFF', 1);
        drawGraph(ctx, visibleData.map(d => ({...d, x: ((d.time - currentTime) / lookahead) * ctx.canvas.width})), 'x', d => amplitudeToY(dbToLinear(d.amplitude) / scoreAmpMaxLinear, ctx.canvas, false), '#FFFFFF', 1);
        drawTimeMarker(ctx, 0);
    }
    function drawTimeMarker(ctx, xPos) {
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xPos, 0);
        ctx.lineTo(xPos, ctx.canvas.height);
        ctx.stroke();
    }
});