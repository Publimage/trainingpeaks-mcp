from pathlib import Path
import ast
def test_unit_inventory_read_only():
 s=Path("scripts/ironman_jobs/mcp_unit_inventory_20261016.py").read_text()
 ast.parse(s)
 assert '"cat"' in s and '"status"' in s and '"-l"' in s
 assert '"restart"' not in s and '"stop"' not in s
