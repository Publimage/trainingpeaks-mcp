from __future__ import annotations

import gzip
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from tp_mcp.tools.fit_reader import _decode_fit_bytes, _fit_candidates, _json_safe


class FakeField:
    def __init__(self, name, value, units=None):
        self.name = name
        self.value = value
        self.units = units


class FakeFrame:
    frame_type = 1

    def __init__(self, name, fields):
        self.name = name
        self.fields = fields


class FakeReader:
    def __init__(self, *_args, **_kwargs):
        start = datetime(2026, 10, 16, 8, 0, 0)
        self.frames = [
            FakeFrame("session", [FakeField("sport", "cycling")]),
            FakeFrame(
                "record",
                [
                    FakeField("timestamp", start),
                    FakeField("heart_rate", 130, "bpm"),
                    FakeField("power", 150, "watts"),
                ],
            ),
            FakeFrame(
                "record",
                [
                    FakeField("timestamp", start + timedelta(seconds=1)),
                    FakeField("heart_rate", 131, "bpm"),
                    FakeField("power", 151, "watts"),
                ],
            ),
            FakeFrame(
                "record",
                [
                    FakeField("timestamp", start + timedelta(seconds=5)),
                    FakeField("heart_rate", 134, "bpm"),
                    FakeField("power", 160, "watts"),
                ],
            ),
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def __iter__(self):
        return iter(self.frames)


def test_decode_fit_bytes_sampling(monkeypatch):
    fake_module = SimpleNamespace(
        __version__="test",
        FIT_FRAME_DATA=1,
        CrcCheck=SimpleNamespace(WARN="warn"),
        ErrorHandling=SimpleNamespace(WARN="warn"),
        FitReader=FakeReader,
    )
    monkeypatch.setitem(sys.modules, "fitdecode", fake_module)

    decoded = _decode_fit_bytes(
        gzip.compress(b"fake-fit"),
        sample_seconds=5,
        start_seconds=0,
        end_seconds=None,
        max_records=10,
    )

    assert decoded["record_count_raw"] == 3
    assert decoded["record_count_eligible"] == 2
    assert [row["elapsed_seconds"] for row in decoded["records"]] == [0.0, 5.0]
    assert "power" in decoded["record_fields"]
    assert decoded["record_units"]["heart_rate"] == "bpm"
    assert decoded["sessions"][0]["sport"] == "cycling"
    assert decoded["truncated"] is False


def test_fit_candidates_accepts_fit_and_fit_gz():
    details = {
        "workoutDeviceFileInfos": [
            {"fileId": 11, "fileName": "activity.FIT.gz"},
            {"fileId": 12, "fileName": "activity.tcx"},
        ],
        "attachmentFileInfos": [{"fileId": -4, "fileName": "manual.fit"}],
    }
    assert [item["file_id"] for item in _fit_candidates(details)] == ["11", "-4"]


def test_json_safe_datetime_and_bytes():
    assert _json_safe(datetime(2026, 10, 16, 8, 0, 0)) == "2026-10-16T08:00:00"
    assert _json_safe(b"\x01\x02") == "0102"
