#!/bin/bash

# Define the project root and script directory
PROJECT_ROOT="/Users/richiegreene/Documents/Scores/Works/(2025) Phonorealism/Phonorealism"
SCRIPT_DIR="$PROJECT_ROOT/phonorealism_modifier"
VENV_ACTIVATE="$PROJECT_ROOT/.venv/bin/activate"

# Navigate to the script directory
echo "Navigating to: $SCRIPT_DIR"
cd "$SCRIPT_DIR" || { echo "Failed to change directory to $SCRIPT_DIR"; exit 1; }

# Activate the virtual environment
echo "Activating virtual environment: $VENV_ACTIVATE"
source "$VENV_ACTIVATE" || { echo "Failed to activate virtual environment $VENV_ACTIVATE"; exit 1; }

# Execute the main.py script
echo "Launching main.py..."
python main.py

# Keep the terminal open after execution (optional, for debugging)
# read -p "Press any key to close this window..."