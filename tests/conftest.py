"""Keep direct pytest runs inside the repository, including child processes."""

import runpy
from pathlib import Path

support = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "_support.py"))
support["configure_process_environment"]()
