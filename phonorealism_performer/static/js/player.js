const socket = io();
const playerId = {{ player_id }};

// Score Charts
const scorePitchCtx = document.getElementById('score-pitch-chart').getContext('2d');
const scoreLoudnessCtx = document.getElementById('score-loudness-chart').getContext('2d');
let scorePitchChart, scoreLoudnessChart;

// Real-time Charts
const realtimePitchCtx = document.getElementById('realtime-pitch-chart').getContext('2d');
const realtimeLoudnessCtx = document.getElementById('realtime-loudness-chart').getContext('2d');
let realtimePitchChart, realtimeLoudnessChart;

socket.on('connect', () => {
    console.log('Connected to server');
    socket.emit('register_player', { player_id: playerId });
});

socket.on('score_data', (data) => {
    const scorePitchData = {
        labels: data.time,
        datasets: [{
            label: 'Frequency',
            data: data.frequency,
            borderColor: 'blue',
            fill: false
        }]
    };

    const scoreLoudnessData = {
        labels: data.time,
        datasets: [{
            label: 'Amplitude',
            data: data.amplitude,
            borderColor: 'red',
            fill: false
        }]
    };

    scorePitchChart = new Chart(scorePitchCtx, {
        type: 'line',
        data: scorePitchData,
        options: { animation: false, scales: { x: { display: false }, y: { display: false } } }
    });

    scoreLoudnessChart = new Chart(scoreLoudnessCtx, {
        type: 'line',
        data: scoreLoudnessData,
        options: { animation: false, scales: { x: { display: false }, y: { display: false } } }
    });
});

socket.on('scroll_update', (data) => {
    const scrollX = data.x_position * (scorePitchChart.width - scorePitchCtx.canvas.width);
    scorePitchChart.options.scales.x.min = scorePitchChart.data.labels[Math.floor(scrollX)];
    scorePitchChart.options.scales.x.max = scorePitchChart.data.labels[Math.ceil(scrollX + scorePitchCtx.canvas.width)];
    scorePitchChart.update();

    scoreLoudnessChart.options.scales.x.min = scoreLoudnessChart.data.labels[Math.floor(scrollX)];
    scoreLoudnessChart.options.scales.x.max = scoreLoudnessChart.data.labels[Math.ceil(scrollX + scoreLoudnessCtx.canvas.width)];
    scoreLoudnessChart.update();
});

// Real-time audio processing
const audioContext = new AudioContext();
let analyser, dataArray, bufferLength;

navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        source.connect(analyser);

        analyser.fftSize = 2048;
        bufferLength = analyser.frequencyBinCount;
        dataArray = new Uint8Array(bufferLength);

        // Initialize real-time charts
        realtimePitchChart = new Chart(realtimePitchCtx, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Pitch', data: [], borderColor: 'green', fill: false }] },
            options: { animation: false, scales: { x: { display: false }, y: { display: false } } }
        });

        realtimeLoudnessChart = new Chart(realtimeLoudnessCtx, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Loudness', data: [], borderColor: 'orange', fill: false }] },
            options: { animation: false, scales: { x: { display: false }, y: { display: false } } }
        });

        const pitchy = new Pitchy(audioContext);

        function draw() {
            requestAnimationFrame(draw);

            analyser.getByteTimeDomainData(dataArray);
            // For simplicity, we'll just show the raw waveform as loudness
            realtimeLoudnessChart.data.labels = Array.from({ length: bufferLength }, (_, i) => i);
            realtimeLoudnessChart.data.datasets[0].data = Array.from(dataArray);
            realtimeLoudnessChart.update();

            const [pitch, clarity] = pitchy.getPitch(dataArray, audioContext.sampleRate);
            if (clarity > 0.9) {
                realtimePitchChart.data.labels.push('');
                realtimePitchChart.data.datasets[0].data.push(pitch);
                if(realtimePitchChart.data.labels.length > 100) {
                    realtimePitchChart.data.labels.shift();
                    realtimePitchChart.data.datasets[0].data.shift();
                }
                realtimePitchChart.update();
            }
        }

        draw();
    });