document.addEventListener('DOMContentLoaded', () => {
    const csvFileInput = document.getElementById('csvFile');
    const startButton = document.getElementById('startPerformance');
    const logArea = document.getElementById('log');

    const WS_URL = "ws://localhost:8000/ws";
    const socket = new WebSocket(WS_URL);

    function logMessage(message) {
        const time = new Date().toLocaleTimeString();
        logArea.textContent = `[${time}] ${message}
` + logArea.textContent;
    }

    socket.onopen = () => {
        logMessage("Connected to server as Conductor.");
        // Identify this client as the conductor
        socket.send(JSON.stringify({ type: 'conductor_join' }));
    };

    socket.onclose = () => {
        logMessage("Disconnected from server.");
    };

    socket.onerror = (error) => {
        logMessage(`!!! WebSocket Error: ${error.message} !!!`);
    };

    csvFileInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target.result;
            logMessage(`Score loaded: ${file.name}. Broadcasting to musicians...`);
            socket.send(JSON.stringify({
                type: 'load_score',
                payload: content
            }));
            startButton.disabled = false;
        };
        reader.readAsText(file);
    });

    startButton.addEventListener('click', () => {
        logMessage("Sending START signal to all musicians...");
        socket.send(JSON.stringify({
            type: 'start_performance'
        }));
    });
});
