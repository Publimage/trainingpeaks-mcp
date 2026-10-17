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
