"""Offline safety and recovery checks for an isolated SQLite crash canary."""
from pathlib import Path
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ironman_jobs"
sys.path.insert(0, str(SCRIPTS))
from ironman_state_store_v1 import DB_PATH
from ledger_crash_restart_canary_20261014 import require_isolated, run_isolated_canary


def test_child_sigkill_rolls_back_and_restart_commits_once():
    result = run_isolated_canary()
    assert result["stage"] == "DO_LEDGER_ISOLATED_CRASH_RESTART_PASS"
    assert result["child_exit"] == -9
    assert result["rolled_back"] == {"jobs": 0, "items": 0, "events": 0}
    assert result["resumed_items"] == 2
    assert result["event_count"] == 1
    assert result["idempotent_retry"] is True
    assert result["provider_writes"] == 0
    assert result["production_ledger_access"] is False
    assert result["service_restarted"] is False


def test_lab_guard_rejects_production_database_and_unscoped_paths(tmp_path):
    with pytest.raises(RuntimeError, match="ISOLATED_DATABASE_REQUIRED"):
        require_isolated(DB_PATH)
    with pytest.raises(RuntimeError, match="LAB_TEMP_DIRECTORY_REQUIRED"):
        require_isolated(tmp_path / "unscoped.sqlite3")
