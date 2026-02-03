import os
import sys

# Add the project root directory to the Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Run the actual application script
# Using exec ensures that the code runs every time Streamlit reruns this script.
app_path = os.path.join(ROOT_DIR, "src", "ui", "app.py")
with open(app_path, encoding='utf-8') as f:
    code = f.read()
    # Execute with inherited globals and local __file__ set correctly
    exec(code, globals(), {"__file__": app_path, "__name__": "__main__"})
