"""Verify that the FIT reader is registered in the server MCP catalog."""
from tp_mcp.server import TOOLS, _TOOL_HANDLERS

name = "tp_get_workout_fit_data"
assert any(tool.name == name for tool in TOOLS), "FIT tool missing from TOOLS"
assert name in _TOOL_HANDLERS, "FIT tool missing from handlers"
tool = next(tool for tool in TOOLS if tool.name == name)
assert tool.input_schema["required"] == ["workout_id"]
assert "athlete" in tool.input_schema["properties"]
print("FIT_TOOL_CATALOG_PASS")
print(tool.description)
