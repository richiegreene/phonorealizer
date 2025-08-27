# Phonorealism Web

This project is a web-based adaptation of the Phonorealism desktop application, designed for real-time, collaborative musical performance and practice.

## Core Concept

The application enables a "conductor" to lead a group of remote "musicians." The conductor's application selects and distributes a master musical score (as a CSV file). Each musician, using a web browser on their personal device (like a phone or laptop), can then select their individual part from that score. 

The primary goal is to provide a synchronized visual reference. The application does **not** stream or play any audio. Instead, the conductor triggers a synchronized start command, and each musician sees:

1.  **The "Sheet Music":** A real-time, scrolling visualization of their selected musical part (pitch and amplitude over time).
2.  **Live Performance Feedback:** A real-time visualization of the pitch and amplitude of their own instrument or voice, captured from their device's microphone.

This allows a group of musicians to play along to a shared reference track (e.g., from a DAW, delivered via in-ear monitors) while receiving precise, individual feedback on their performance against the score.

## Technical Architecture

To avoid latency issues with audio streaming and to bypass issues with server-side dependencies like FFmpeg, this project will be built with a **client-side first** approach.

-   **Musician's View (Frontend):** The core of the application is a static web page built with HTML, CSS, and JavaScript. It will be responsible for:
    -   Receiving score data from the conductor (initially simulated by a local file input).
    -   Parsing the CSV data.
    -   Allowing the user to select their partial (`harmonic_index`).
    -   Using a pure JavaScript library to perform real-time pitch and amplitude analysis of the microphone input directly in the browser.
    -   Using a JavaScript-based canvas or SVG to render both the scrolling score and the live performance data.

-   **Conductor's View (Backend/Desktop App):** The conductor's application will be responsible for loading the master CSV and broadcasting it, along with the "start" command, to all connected musicians. This will be implemented in a later phase using a simple WebSocket server, but the initial focus is on perfecting the client-side musician's experience.
