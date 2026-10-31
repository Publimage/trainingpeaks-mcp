"""Approved read-only job wrapper. The existing full diagnostic lives in scripts/."""
from pathlib import Path
import runpy

source = Path(__file__).resolve().parents[1] / "inspect_native_strength_library_readonly.py"
runpy.run_path(str(source), run_name="__main__")
