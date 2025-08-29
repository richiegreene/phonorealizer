import subprocess
import os
import sys
import atexit

# Keep track of processes to terminate them on exit
processes = []

def cleanup():
    print("Terminating child processes...")
    for p in processes:
        if p.poll() is None: # Check if process is still running
            p.terminate()
            p.wait() # Wait for process to terminate
    print("Cleanup complete.")

atexit.register(cleanup)

def main():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.join(current_dir, 'backend')
        
        # Ensure we use the python from the activated environment
        python_executable = sys.executable

        # Command for the FastAPI server
        fastapi_command = [
            python_executable, "-m", "uvicorn", "main:app", 
            "--host", "0.0.0.0", "--port", "8000"
        ]
        
        # Command for the Conductor backend
        conductor_command = [python_executable, "conductor_backend.py"]

        print(f"Starting both backend servers from directory: {backend_dir}")

        # Start FastAPI server
        print(f"Running command: {' '.join(fastapi_command)}")
        fastapi_process = subprocess.Popen(fastapi_command, cwd=backend_dir)
        processes.append(fastapi_process)
        print("FastAPI server process started.")

        # Start Conductor backend
        print(f"Running command: {' '.join(conductor_command)}")
        conductor_process = subprocess.Popen(conductor_command, cwd=backend_dir)
        processes.append(conductor_process)
        print("Conductor backend process started.")

        print("\nBoth servers are running. Press CTRL+C to stop.")
        
        # Wait for the conductor process to exit. If it crashes, the script will end.
        conductor_process.wait()

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Shutting down...")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    main()
