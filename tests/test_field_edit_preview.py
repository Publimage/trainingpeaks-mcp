"""Run the reusable selective-field-edit suite in the existing CI pipeline.

GitHub Actions already runs `pytest tests/ -v` on push. The field-edit
core is pure Python, does not import TP auth and must never write provider data.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from test_field_edits import FieldEditTests as TestFieldEdits  # noqa: E402,F401
