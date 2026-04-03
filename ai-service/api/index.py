import sys
import os

# Ensure the parent directory is on the path so main.py and its imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
