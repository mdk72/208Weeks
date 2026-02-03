import os
import sys

# Add the project root directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the main application module
# This works because Streamlit scripts usually execute code at the module level.
# Importing it effectively runs the app.
try:
    from src.ui import app
except Exception as e:
    import streamlit as st
    st.error(f"Error loading application: {e}")
    st.error("Please check the logs for more details.")
    raise e
