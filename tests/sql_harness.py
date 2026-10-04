"""Re-export of the local engine for tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localdev.engine import *  # noqa: F401,F403,E402
from localdev.engine import SQL_DIR, TABLE_RE, build_all, connect, run_file, to_duckdb  # noqa: F401,E402
