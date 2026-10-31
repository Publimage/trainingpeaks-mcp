from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_folder_get_route_shape_20261017.py")
def test_get_only_contract():
 s=P.read_text()
 assert 'c._client.request(\n     "GET"' in s
 assert '"POST"' not in s
 assert '"PUT"' not in s
 assert '"PATCH"' not in s
 assert '"DELETE"' not in s
 assert "/planfolder/v1/folder/all" in s
