"""Public demo entry point for Streamlit Community Cloud (main file: streamlit_app.py).

Lives at the repo root so Community Cloud installs the root requirements.txt instead of
app/environment.yml (Snowflake channel, used by Streamlit in Snowflake). Without Snowflake
secrets the app runs on the offline DuckDB replica.
"""
import runpy
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent / "app"
sys.path.insert(0, str(APP))
runpy.run_path(str(APP / "streamlit_app.py"), run_name="__main__")
