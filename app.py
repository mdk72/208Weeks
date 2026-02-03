import os
import sys

# Add the project root directory to the Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Run the actual application script
# Using a single dictionary for globals and locals ensures functions/lambdas can access top-level variables.
app_path = os.path.join(ROOT_DIR, "src", "ui", "app.py")
with open(app_path, encoding='utf-8') as f:
    code = f.read()
    # Share globals to allow lambdas and functions to find top-level script variables
    ctx = globals().copy()
    ctx.update({"__file__": app_path, "__name__": "__main__"})
    exec(code, ctx)
