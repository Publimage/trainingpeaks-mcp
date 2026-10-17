"""Read-only audit: Beginner Strength plan tools import and register in MCP catalog."""
from tp_mcp.server import TOOLS, _TOOL_HANDLERS

NAMES = {
    "tp_batch_add_beginner_strength",
    "tp_batch_delete_beginner_classic_strength",
}

present = {tool.name for tool in TOOLS}
missing = NAMES - present
assert not missing, f"missing catalog tools: {sorted(missing)}"
assert NAMES <= set(_TOOL_HANDLERS), "Beginner Strength handlers missing"
for tool in TOOLS:
    if tool.name in NAMES:
        assert tool.input_schema["required"] == ["items", "expected_plan_count"]
print("BEGINNER_STRENGTH_CATALOG_PASS")
print(sorted(NAMES))
