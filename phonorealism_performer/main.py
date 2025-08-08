import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
import sounddevice as sd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Phonorealism Performer")

        self.data = None
        self.stream = None
        self.scrolling = False
        self.start_time = 0
        self.elapsed_time = 0

        # Create the main frames
        self.realtime_panel = tk.Frame(self, width=600, height=600)
        self.score_panel = tk.Frame(self, width=600, height=600)

        self.realtime_panel.pack(side="left", fill="both", expand=True)
        self.score_panel.pack(side="right", fill="both", expand=True)

        # Create the charts
        self.realtime_pitch_fig, self.realtime_pitch_ax = plt.subplots()
        self.realtime_loudness_fig, self.realtime_loudness_ax = plt.subplots()
        self.score_pitch_fig, self.score_pitch_ax = plt.subplots()
        self.score_loudness_fig, self.score_loudness_ax = plt.subplots()

        self.realtime_pitch_canvas = FigureCanvasTkAgg(self.realtime_pitch_fig, master=self.realtime_panel)
        self.realtime_loudness_canvas = FigureCanvasTkAgg(self.realtime_loudness_fig, master=self.realtime_panel)
        self.score_pitch_canvas = FigureCanvasTkAgg(self.score_pitch_fig, master=self.score_panel)
        self.score_loudness_canvas = FigureCanvasTkAgg(self.score_loudness_fig, master=self.score_panel)

        self.realtime_pitch_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.realtime_loudness_canvas.get_tk_widget().pack(side="bottom", fill="both", expand=True)
        self.score_pitch_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.score_loudness_canvas.get_tk_widget().pack(side="bottom", fill="both", expand=True)

        # Create the menu
        self.menu = tk.Menu(self)
        self.config(menu=self.menu)
        self.file_menu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="Open CSV", command=self.open_csv)

        # Create the controls
        self.controls_frame = tk.Frame(self)
        self.controls_frame.pack(side="bottom", fill="x")
        self.play_pause_button = tk.Button(self.controls_frame, text="▶", command=self.toggle_play_pause)
        self.play_pause_button.pack(side="left")

        # Start the audio stream
        self.start_audio_stream()

    def open_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            self.data = pd.read_csv(file_path)
            self.plot_score()

    def plot_score(self):
        if self.data is not None:
            # Plot pitch
            self.score_pitch_ax.clear()
            self.score_pitch_ax.plot(self.data['time'], self.data['frequency'])
            self.score_pitch_canvas.draw()

            # Plot loudness
            self.score_loudness_ax.clear()
            self.score_loudness_ax.plot(self.data['time'], self.data['amplitude'])
            self.score_loudness_canvas.draw()

    def start_audio_stream(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()

        self.stream = sd.InputStream(callback=self.audio_callback)
        self.stream.start()

    def audio_callback(self, indata, frames, time, status):
        if status:
            print(status)

        # Plot real-time loudness
        self.realtime_loudness_ax.clear()
        self.realtime_loudness_ax.plot(indata)
        self.realtime_loudness_canvas.draw()

        # Simple pitch detection
        pitch = self.get_pitch(indata)
        self.realtime_pitch_ax.clear()
        self.realtime_pitch_ax.plot([pitch, pitch])
        self.realtime_pitch_canvas.draw()

    def get_pitch(self, data):
        # A simple pitch detection algorithm using autocorrelation
        data = data.flatten()
        corr = np.correlate(data, data, mode='full')
        corr = corr[len(corr)//2:]
        d = np.diff(corr)
        start = np.nonzero(d > 0)[0][0]
        peak = np.argmax(corr[start:]) + start
        return 44100 / peak

    def toggle_play_pause(self):
        self.scrolling = not self.scrolling
        if self.scrolling:
            self.play_pause_button.config(text="⏸")
            self.start_time = self.master.winfo_reqheight() - self.elapsed_time
            self.scroll()
        else:
            self.play_pause_button.config(text="▶")
            self.elapsed_time = self.master.winfo_reqheight() - self.start_time

    def scroll(self):
        if self.scrolling:
            current_time = (self.master.winfo_reqheight() - self.start_time) / 1000
            
            if self.data is not None:
                max_time = self.data['time'].max()
                if current_time >= max_time:
                    self.scrolling = False
                    self.play_pause_button.config(text="▶")
                
                scroll_proportion = current_time / max_time
                
                # Update the x-axis limits of the score charts to create the scrolling effect
                x_min = self.data['time'].min() + scroll_proportion * (self.data['time'].max() - self.data['time'].min())
                x_max = x_min + (self.data['time'].max() - self.data['time'].min()) * 0.1 # Show 10% of the data at a time
                self.score_pitch_ax.set_xlim(x_min, x_max)
                self.score_loudness_ax.set_xlim(x_min, x_max)
                self.score_pitch_canvas.draw()
                self.score_loudness_canvas.draw()

            self.after(50, self.scroll)

if __name__ == "__main__":
    app = App()
    app.mainloop()