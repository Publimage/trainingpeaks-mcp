from pathlib import Path
import ast
def test_runtime_inventory_is_read_only():
 s=Path("scripts/ironman_jobs/mcp_runtime_inventory_20261016.py").read_text()
 ast.parse(s)
 assert "systemctl" in s and "list-units" in s
 assert "restart" not in s and "stop" not in s and "kill" not in s
