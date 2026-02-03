import os
import sys

# Add the project root directory to the Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Import the actual entry point
# This is safer than exec when dealing with deep imports on Streamlit Cloud
from src.ui import app
