document.addEventListener('DOMContentLoaded', () => {
    const csvContentTextarea = document.getElementById('csvContent');
    const loadCsvButton = document.getElementById('loadCsvFromText');
    const startButton = document.getElementById('startPerformance');
    const logArea = document.getElementById('log');

    const WS_URL = "ws://localhost:8000/ws";
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
        startButton.disabled = false;
        logMessage("Start button enabled.");
    });

    startButton.addEventListener('click', () => {
        const type = isStarted ? 'stop_performance' : 'start_performance';
        logMessage(`Sending ${type.toUpperCase()} signal to all musicians...`);
        socket.send(JSON.stringify({ type }));
        isStarted = !isStarted;
        startButton.textContent = isStarted ? 'Stop Performance' : 'Start Performance';
    });

    let isStarted = false;
});
