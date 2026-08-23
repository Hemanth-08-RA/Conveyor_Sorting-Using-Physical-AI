"""
Root entrypoint fallback for Arduino App Lab.
Executes the main application from python/main.py.
"""
import os
import sys

# Ensure python/ directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_DIR = os.path.join(BASE_DIR, "python")
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from main import run_app

if __name__ == "__main__":
    run_app()
