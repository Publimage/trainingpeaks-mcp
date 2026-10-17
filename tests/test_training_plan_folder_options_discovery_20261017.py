from pathlib import Path

P = Path("scripts/ironman_jobs/training_plan_folder_options_discovery_20261017.py")

def test_options_only_contract():
    s = P.read_text()
    assert 'client._client.request(\n                "OPTIONS"' in s
    assert '"POST"' not in s
    assert '"PUT"' not in s
    assert '"PATCH"' not in s
    assert '"DELETE"' not in s
    assert "/planfolder/v1/folder" in s
