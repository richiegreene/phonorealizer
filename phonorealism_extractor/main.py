import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import create_main_window

if __name__ == "__main__":
    create_main_window()