import subprocess
import sys
import os

def launch():
    """Launch the Streamlit app in the new modular structure."""
    app_path = os.path.join("src", "ui", "app.py")
    if not os.path.exists(app_path):
        print(f"Error: Could not find {app_path}")
        return

    print("Launching BKIT (Backtest Kit)...")
    try:
        subprocess.run(["streamlit", "run", app_path], check=True)
    except KeyboardInterrupt:
        print("\nApplication stopped.")
    except Exception as e:
        print(f"Error launching application: {e}")

if __name__ == "__main__":
    launch()
