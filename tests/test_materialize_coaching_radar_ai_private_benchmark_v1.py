import json
import stat

import pytest

from scripts.ironman_jobs.materialize_coaching_radar_ai_private_benchmark_v1 import _write_private_json


def test_private_json_writer_uses_0600_and_returns_sha(tmp_path):
    path = tmp_path / "case.json"
    digest = _write_private_json(path, {"schema": "TEST", "value": 1})
    assert len(digest) == 64
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["value"] == 1


def test_private_json_writer_refuses_overwrite(tmp_path):
    path = tmp_path / "case.json"
    _write_private_json(path, {"value": 1})
    with pytest.raises(FileExistsError):
        _write_private_json(path, {"value": 2})
    assert json.loads(path.read_text(encoding="utf-8"))["value"] == 1
