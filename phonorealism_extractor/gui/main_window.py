import dearpygui.dearpygui as dpg
from core.analyzer import analyze_audio
from core.io import save_partials_to_csv, save_full_svg, save_partial_svg, save_waveform_svg
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
        if not os.path.isfile(file_path):
            dpg.set_value("status_text", f"Error: Selected path is not a valid file: {file_path}")
            return
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
            dpg.set_item_user_data("export_wav_button", (filtered_partials, file_path, sr, duration))
            dpg.set_item_user_data("export_log_svg_button", (filtered_partials, file_path, sr, duration))
            dpg.set_item_user_data("export_lin_svg_button", (filtered_partials, file_path, sr, duration))
            dpg.set_item_user_data("export_waveform_svg_button", (filtered_partials, file_path, sr, duration))

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

    def export_wav(sender, app_data, user_data):
        partials, file_path, sr, duration = user_data
        if not file_path:
            dpg.set_value("status_text", "Please analyze a file first before synthesizing.")
            return
        
        # Export full waveform
        base, ext = os.path.splitext(file_path)
        output_path = base + "_render" + ext
        synthesize_from_partials(partials, sr, output_path, duration)
        dpg.set_value("status_text", f"Synthesized full audio to: {output_path}")

        # Export partial waveforms
        output_dir = os.path.splitext(file_path)[0] + "_selected_harmonics_wav"
        os.makedirs(output_dir, exist_ok=True)
        
        exported_count = 0
        for i, harmonic in enumerate(partials):
            harmonic_number = i + 1
            harmonic_tag = f"harmonic_line_{harmonic_number}"
            if dpg.does_item_exist(harmonic_tag) and dpg.is_item_shown(harmonic_tag):
                output_path = os.path.join(output_dir, f"harmonic_{harmonic_number}.wav")
                synthesize_from_partials([harmonic], sr, output_path, duration)
                exported_count += 1
        
        dpg.set_value("status_text", f"Synthesized {exported_count} selected harmonics to: {output_dir}")

    def export_log_svg(sender, app_data, user_data):
        dpg.show_item("svg_export_modal")
        dpg.set_item_user_data("export_svg_button", ("log", user_data))

    def export_lin_svg(sender, app_data, user_data):
        dpg.show_item("svg_export_modal")
        dpg.set_item_user_data("export_svg_button", ("lin", user_data))

    def export_waveform_svg(sender, app_data, user_data):
        dpg.show_item("svg_export_modal")
        dpg.set_item_user_data("export_svg_button", ("waveform", user_data))

    def do_export_svg(sender, app_data, user_data):
        export_type, original_user_data = user_data
        partials, file_path, sr, duration = original_user_data
        svg_width = dpg.get_value("svg_width_input")
        svg_height = dpg.get_value("svg_height_input")
        svg_gain = dpg.get_value("svg_gain_input")
        svg_max_points = dpg.get_value("svg_max_points_input")

        if not file_path:
            dpg.set_value("status_text", "Please analyze a file first before exporting.")
            return

        if export_type == "log" or export_type == "lin":
            base, ext = os.path.splitext(file_path)
            output_path = base + f"_render_{export_type}.svg"
            save_full_svg(partials, output_path, sr, duration, scale=export_type, svg_width=svg_width, svg_height=svg_height, gain=svg_gain)

            output_dir = os.path.splitext(file_path)[0] + f"_selected_harmonics_{export_type}_svg"
            os.makedirs(output_dir, exist_ok=True)
            
            exported_count = 0
            for i, harmonic in enumerate(partials):
                harmonic_number = i + 1
                harmonic_tag = f"harmonic_line_{harmonic_number}"
                if dpg.does_item_exist(harmonic_tag) and dpg.is_item_shown(harmonic_tag):
                    output_path = os.path.join(output_dir, f"harmonic_{harmonic_number}.svg")
                    save_partial_svg(harmonic, output_path, sr, duration, scale=export_type, svg_width=svg_width, svg_height=svg_height, gain=svg_gain)
                    exported_count += 1
            
            dpg.set_value("status_text", f"Exported {exported_count} selected harmonics to: {output_dir}")
        
        elif export_type == "waveform":
            # Export full waveform
            y, sr = librosa.load(file_path, sr=None)
            base, ext = os.path.splitext(file_path)
            output_path = base + "_waveform.svg"
            save_waveform_svg(y, output_path, sr, svg_width=svg_width, svg_height=svg_height, gain=svg_gain, max_points=svg_max_points)

            # Export partial waveforms
            output_dir = os.path.splitext(file_path)[0] + "_selected_harmonics_waveform_svg"
            os.makedirs(output_dir, exist_ok=True)
            
            exported_count = 0
            for i, harmonic in enumerate(partials):
                harmonic_number = i + 1
                harmonic_tag = f"harmonic_line_{harmonic_number}"
                if dpg.does_item_exist(harmonic_tag) and dpg.is_item_shown(harmonic_tag):
                    output_path = os.path.join(output_dir, f"harmonic_{harmonic_number}_waveform.svg")
                    
                    # Synthesize harmonic to get audio data
                    if not harmonic:
                        continue
                    times, freqs, amps_db = zip(*harmonic)
                    t = np.linspace(0., duration, int(sr * duration))
                    interp_freqs = np.interp(t, times, freqs)
                    interp_amps_db = np.interp(t, times, amps_db)
                    interp_amps = librosa.db_to_amplitude(interp_amps_db)
                    harmonic_wave = interp_amps * np.sin(2 * np.pi * interp_freqs * t)
                    if np.max(np.abs(harmonic_wave)) > 0:
                        harmonic_wave /= np.max(np.abs(harmonic_wave))

                    save_waveform_svg(harmonic_wave, output_path, sr, svg_width=svg_width, svg_height=svg_height, gain=svg_gain, max_points=svg_max_points)
                    exported_count += 1
            
            dpg.set_value("status_text", f"Exported {exported_count} selected harmonics waveforms to: {output_dir}")

        dpg.hide_item("svg_export_modal")


    with dpg.window(tag="main_window"):
        dpg.set_primary_window("main_window", True)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Open", callback=open_file_dialog)
            dpg.add_button(label="csv", callback=export_csv_data, tag="export_csv_button", user_data=([], ""))
            dpg.add_button(label="Synthesize (wav)", callback=export_wav, tag="export_wav_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Log (svg)", callback=export_log_svg, tag="export_log_svg_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Lin (svg)", callback=export_lin_svg, tag="export_lin_svg_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Waveform (svg)", callback=export_waveform_svg, tag="export_waveform_svg_button", user_data=([], "", 0, 0))
            dpg.add_button(label="Spectrogram", callback=toggle_spectrogram)
        dpg.add_text("", tag="status_text")

    with dpg.window(label="SVG Export Dimensions", modal=True, show=False, tag="svg_export_modal", width=400):
        dpg.add_input_int(label="Width", tag="svg_width_input", default_value=1000)
        dpg.add_input_int(label="Height", tag="svg_height_input", default_value=500)
        dpg.add_input_float(label="Gain", tag="svg_gain_input", default_value=1.0, step=0.1)
        dpg.add_input_int(label="Max Waveform Points", tag="svg_max_points_input", default_value=5000, step=100)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Export", callback=do_export_svg, tag="export_svg_button")
            dpg.add_button(label="Cancel", callback=lambda: dpg.hide_item("svg_export_modal"))

    dpg.create_viewport(title='Phonorealism Analysis Tool', width=800, height=600)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()
