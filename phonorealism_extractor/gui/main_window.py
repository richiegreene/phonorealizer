import dearpygui.dearpygui as dpg
from core.analyzer import analyze_audio
from core.io import save_partials_to_csv
from core.synthesizer import synthesize_from_partials
import numpy as np
import librosa
import matplotlib.cm as cm
import matplotlib.colors as colors
import os

def create_main_window():
    dpg.create_context()

    def handle_file_selection(sender, app_data):
        file_path = app_data['file_path_name']
        dpg.set_value("status_text", f"Analyzing: {file_path}")
        y, sr = librosa.load(file_path, sr=None)
        
        N_FFT = 2048
        HOP_LENGTH = 512
        stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
        duration = librosa.get_duration(S=stft, sr=sr, hop_length=HOP_LENGTH)

        # Analyze for 32 harmonics to get 16 correct ones
        partials = analyze_audio(file_path, num_harmonics=32)
        if partials:
            # Filter for even-numbered harmonics (which are the actual harmonics)
            filtered_partials = [p for i, p in enumerate(partials) if (i + 1) % 2 == 0]

            dpg.set_value("status_text", f"Analysis complete for: {file_path}")
            visualize_partials(file_path, filtered_partials)
            dpg.set_item_user_data("export_csv_button", (filtered_partials, file_path))
            dpg.set_item_user_data("export_full_button", (filtered_partials, file_path, sr, duration))
            dpg.set_item_user_data("export_partials_button", (filtered_partials, file_path, sr, duration))

    # Create file dialog once
    with dpg.file_dialog(directory_selector=False, show=False, callback=handle_file_selection, tag="file_dialog_id"):
        dpg.add_file_extension(".wav")
        dpg.add_file_extension(".aiff")
        dpg.add_file_extension(".aif")
        dpg.add_file_extension(".mp3")

    def open_file_dialog():
        dpg.show_item("file_dialog_id")

    def visualize_partials(file_path, partials):
        y, sr = librosa.load(file_path, sr=None)
        
        N_FFT = 2048
        HOP_LENGTH = 512

        stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
        spectrogram = librosa.amplitude_to_db(np.abs(stft), ref=np.max)

        # Normalize spectrogram for colormap application and flip vertically
        norm_spectrogram = (spectrogram - np.min(spectrogram)) / (np.max(spectrogram) - np.min(spectrogram))
        norm_spectrogram = np.flipud(norm_spectrogram)
        
        # Apply inferno colormap
        cmap = cm.get_cmap('inferno')
        colored_spectrogram = cmap(norm_spectrogram)
        
        # Flatten to 1D array for Dear PyGui texture
        texture_data = colored_spectrogram.flatten()

        if dpg.does_item_exist("spectrogram_texture"):
            dpg.set_value("spectrogram_texture", texture_data)
        else:
            with dpg.texture_registry(show=False):
                dpg.add_dynamic_texture(width=spectrogram.shape[1], height=spectrogram.shape[0], default_value=texture_data, tag="spectrogram_texture")

        if dpg.does_item_exist("spectrogram_plot"):
            dpg.delete_item("spectrogram_plot")

        with dpg.plot(label="Spectrogram", height=-1, width=-1, parent="main_window", tag="spectrogram_plot"):
            dpg.add_plot_legend()
            x_axis = dpg.add_plot_axis(dpg.mvXAxis, label="Time (s)")
            
            # Calculate the actual time duration of the spectrogram
            x_max = librosa.get_duration(S=stft, sr=sr, hop_length=HOP_LENGTH)

            y_axis = dpg.add_plot_axis(dpg.mvYAxis, label="Frequency (Hz)")
            dpg.add_image_series(texture_tag="spectrogram_texture", bounds_min=(0, 0), bounds_max=(x_max, sr / 2), parent=y_axis, tag="spectrogram_image_series")

            for i, harmonic in enumerate(partials):
                if harmonic:
                    times, freqs, _ = zip(*harmonic)
                    # Halve the frequency for correct visualization
                    freqs_halved = [f * 0.5 for f in freqs]
                    dpg.add_line_series(x=list(times), y=list(freqs_halved), label=f"Harmonic {i+1}", parent=y_axis, tag=f"harmonic_line_{i+1}")

    def toggle_spectrogram(sender, app_data, user_data):
        if dpg.does_item_exist("spectrogram_image_series"):
            current_show_state = dpg.is_item_shown("spectrogram_image_series")
            dpg.configure_item("spectrogram_image_series", show=not current_show_state)
        else:
            dpg.set_value("status_text", "No spectrogram to toggle. Please analyze an audio file first.")

    def export_csv_data(sender, app_data, user_data):
        partials, file_path = user_data
        if not file_path:
            dpg.set_value("status_text", "Please analyze a file first before exporting.")
            return
        output_path = file_path.replace(".wav", "_partials.csv")
        save_partials_to_csv(partials, output_path)
        dpg.set_value("status_text", f"Exported partials to: {output_path}")

    def export_full_wav(sender, app_data, user_data):
        partials, file_path, sr, duration = user_data
        if not file_path:
            dpg.set_value("status_text", "Please analyze a file first before synthesizing.")
            return
        
        base, ext = os.path.splitext(file_path)
        output_path = base + "_render" + ext
        synthesize_from_partials(partials, sr, output_path, duration)
        dpg.set_value("status_text", f"Synthesized audio saved to: {output_path}")

    def export_selected_partials(sender, app_data, user_data):
        partials, file_path, sr, duration = user_data
        if not file_path:
            dpg.set_value("status_text", "Please analyze a file first before exporting partials.")
            return

        output_dir = os.path.splitext(file_path)[0] + "_selected_harmonics"
        os.makedirs(output_dir, exist_ok=True)
        
        exported_count = 0
        for i, harmonic in enumerate(partials):
            harmonic_number = i + 1
            harmonic_tag = f"harmonic_line_{harmonic_number}"
            if dpg.does_item_exist(harmonic_tag) and dpg.is_item_shown(harmonic_tag):
                output_path = os.path.join(output_dir, f"harmonic_{harmonic_number}.wav")
                synthesize_from_partials([harmonic], sr, output_path, duration)
                exported_count += 1
        
        dpg.set_value("status_text", f"Exported {exported_count} selected harmonics to: {output_dir}")


    with dpg.window(tag="main_window"):
        dpg.set_primary_window("main_window", True)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Open", callback=open_file_dialog)
            dpg.add_button(label="csv", callback=export_csv_data, tag="export_csv_button", user_data=([], ""))
            dpg.add_button(label="Full (wav)", callback=export_full_wav, tag="export_full_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Partials (wav)", callback=export_selected_partials, tag="export_partials_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Spectrogram", callback=toggle_spectrogram)
        dpg.add_text("", tag="status_text")

    dpg.create_viewport(title='Phonorealism Analysis Tool', width=800, height=600)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()