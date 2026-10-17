from pathlib import Path
import ast

P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/archive_mcp_test_plans_folder_20261017.py"

def test_exact_scope_and_guards():
    s=P.read_text(encoding="utf-8")
    ast.parse(s)
    assert 'FOLDER_NAME = "ARCHIVIATI | TEST MCP"' in s
    for pid in ("684762","684463","684555","684543","684484","684206"):
        assert pid in s
    assert "679801" in s and "179.0" in s
    assert "684602" in s and "685173" in s
    assert '"/planfolder/v1/folder"' in s
    assert '"/planfolder/v1/command/assignplanstofolder"' in s
    assert s.count("_retry_on_401=False") == 2
    assert "CANARY_ASSIGN_VERIFIED" in s
    assert "COMPLETE_VERIFIED" in s
    assert "PLAN_METADATA_DRIFT" in s
    assert "TARGET_FOLDER_CONTAINS_NON_TARGET_PLAN" in s
    assert "retry=False" in s
    assert '"/fitness/' not in s
    assert '"/exerciselibrary/' not in s
    assert '"DELETE"' not in s


def test_folder_id_accepts_provider_uuid():
    from scripts.ironman_jobs.archive_mcp_test_plans_folder_20261017 import folder_id
    assert folder_id({"folderId": "1e0e5952-c6a9-4633-97a4-e859d9ae69fb"}) == "1e0e5952-c6a9-4633-97a4-e859d9ae69fb"
    assert folder_id({"folderId": None}) is None
