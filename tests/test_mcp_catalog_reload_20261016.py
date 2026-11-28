from pathlib import Path
import ast
def test_mcp_catalog_reload_is_bounded():
 s=Path("scripts/ironman_jobs/mcp_catalog_reload_20261016.py").read_text()
 ast.parse(s)
 assert 'EXPECTED_HOST = "ironman-tp-mcp"' in s
 assert "tp-mcp serve" in s
 assert "tunnel-client run --profile trainingpeaks" in s
 assert "kill -TERM" in s
 assert "MCP_RELOAD_SCHEDULED" in s
 assert "trainingpeaks.com" not in s


def test_target_binding_is_enforced_before_server_reload(tmp_path, monkeypatch):
    """Offline regression: the current WINTER plan cannot inherit Intermediate."""
    import pytest
    from tp_mcp.tools import ironman_operator as op
    from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop
    from scripts.ironman_jobs.reviewed_plan_patch_pipeline import require_explicit_target

    for path in (
        "src/tp_mcp/server.py",
        "src/tp_mcp/tools/ironman_operator.py",
        "scripts/ironman_jobs/reviewed_plan_patch_pipeline.py",
    ):
        ast.parse(Path(path).read_text(encoding="utf-8"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data/ironman_reviewed_plan_patch.json").write_text(
        '{"configured":true,"manifest":{"plan_id":684602}}', encoding="utf-8"
    )
    monkeypatch.setattr(op, "REPO", tmp_path)
    with pytest.raises(op.BridgeStop, match="STOP_TARGET_MISMATCH"):
        op._check_reviewed_manifest_target("reviewed_plan_patch_publish", 689369)
    with pytest.raises(PlanPatchStop, match="STOP_TARGET_MISMATCH"):
        require_explicit_target({"manifest": {"plan_id": 684602}}, "689369")
