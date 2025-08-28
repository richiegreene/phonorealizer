document.addEventListener('DOMContentLoaded', () => {
    const csvContentTextarea = document.getElementById('csvContent');
    const loadCsvButton = document.getElementById('loadCsvFromText');
    const playButton = document.getElementById('playButton');
    const pauseButton = document.getElementById('pauseButton');
    const stopButton = document.getElementById('stopButton');
    const logArea = document.getElementById('log');

    const WS_URL = "ws://localhost:8001/ws";
    const socket = new WebSocket(WS_URL);

    function logMessage(message) {
        const time = new Date().toLocaleTimeString();
        logArea.textContent = `[${time}] ${message}\n` + logArea.textContent;
    }

    logMessage("Script loaded and initialized.");

    socket.onopen = () => {
        logMessage("Connected to server as Conductor.");
        socket.send(JSON.stringify({ type: 'conductor_join' }));
    };

    socket.onclose = () => {
        logMessage("Disconnected from server.");
    };

    socket.onerror = (error) => {
        logMessage(`!!! WebSocket Error: ${error.message} !!!`);
    };

    loadCsvButton.addEventListener('click', () => {
        const content = csvContentTextarea.value;
        if (!content) {
            logMessage("Textarea is empty. Please paste CSV content.");
            return;
        }
        logMessage("CSV content loaded from textarea. Broadcasting to musicians...");
        socket.send(JSON.stringify({
            type: 'load_score',
            payload: content
        }));
        playButton.disabled = false;
        pauseButton.disabled = true;
        stopButton.disabled = true;
        logMessage("Play button enabled.");
    });

    playButton.addEventListener('click', () => {
        logMessage(`Sending START_PERFORMANCE signal to all musicians...`);
        socket.send(JSON.stringify({ type: 'start_performance' }));
        playButton.disabled = true;
        pauseButton.disabled = false;
        stopButton.disabled = false;
    });

    pauseButton.addEventListener('click', () => {
        logMessage(`Sending PAUSE_PERFORMANCE signal to all musicians...`);
        socket.send(JSON.stringify({ type: 'pause_performance' }));
        playButton.disabled = false;
        pauseButton.disabled = true;
        stopButton.disabled = false;
    });

    stopButton.addEventListener('click', () => {
        logMessage(`Sending STOP_PERFORMANCE signal to all musicians...`);
        socket.send(JSON.stringify({ type: 'stop_performance' }));
        playButton.disabled = false;
        pauseButton.disabled = true;
        stopButton.disabled = true;
    });
});
