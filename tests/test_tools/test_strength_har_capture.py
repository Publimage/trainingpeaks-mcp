"""Safety/shape checks for the local, read-only plan strength HAR inspector."""
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect_native_strength_capture.py"
spec = importlib.util.spec_from_file_location("tp_local_har_inspector", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_redacts_auth_fields_and_arbitrary_string_values():
    sample = {
        "planId": 684543,
        "calendarId": 999999,
        "authorization": "Bearer PRIVATE_VALUE",
        "payload": {
            "token": "PRIVATE_TOKEN",
            "workoutType": "StructuredStrength",
            "name": "PERSONAL NAME",
        },
    }
    cooked = module.schema(sample)
    as_text = json.dumps(cooked)
    assert cooked["planId"] == 684543
    assert cooked["authorization"] == "<redacted>"
    assert cooked["payload"]["token"] == "<redacted>"
    assert cooked["payload"]["workoutType"] == "StructuredStrength"
    assert "PERSONAL NAME" not in as_text
    assert "PRIVATE_" not in as_text
    assert "999999" not in as_text


def test_filters_hosts_query_tokens_and_har_body(tmp_path, capsys):
    source = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://api.peakswaresb.com/rx/activity/v1/workouts/save?token=TOPSECRET",
                        "headers": [{"name": "Authorization", "value": "Bearer SECRET"}],
                        "postData": {
                            "text": json.dumps({
                                "planId": 684543,
                                "instructions": "SENSITIVE_TEXT",
                                "blocks": [{"title": "Goblet Squat", "sets": [{"Reps": 6}]}],
                            })
                        },
                    },
                    "response": {
                        "status": 200,
                        "content": {
                            "text": json.dumps({
                                "data": {"id": "PRIVATE_ID", "workoutType": "StructuredStrength"},
                                "errors": {},
                            })
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://evil.example.com/workouts/684543",
                    },
                    "response": {"status": 200},
                },
            ]
        }
    }
    har = tmp_path / "inspect.har"
    har.write_text(json.dumps(source), encoding="utf-8")
    assert module.inspect(har) == 0
    summary = capsys.readouterr().out
    parsed = json.loads(summary)
    assert parsed["matching_post_put_patch"] == 1
    assert parsed["relevant_requests"] == 1
    assert parsed["requests"][0]["test_plan_referenced"]
    assert parsed["requests"][0]["status"] == 200
    assert parsed["requests"][0]["response_data_keys"] == ["id", "workoutType"]
    for leaked in ("TOPSECRET", "SENSITIVE_TEXT", "PRIVATE_ID", "Bearer SECRET", "evil.example.com"):
        assert leaked not in summary
