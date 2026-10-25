"""Offline gate for generic TrainingPeaks organization MCP registrations."""
from tp_mcp.server import TOOLS, _TOOL_HANDLERS

EXPECTED={
 "tp_list_plan_folders","tp_copy_training_plan","tp_create_plan_folder",
 "tp_delete_training_plan","tp_rename_plan_folder",
 "tp_move_training_plans","tp_rename_training_plan",
 "tp_move_athletes_between_groups",
 "tp_rename_library","tp_copy_library_items","tp_move_library_items","tp_delete_library_items",
}
names={x.name for x in TOOLS}
missing=sorted(EXPECTED-names)
handlers=sorted(x for x in EXPECTED if x not in _TOOL_HANDLERS)
if missing or handlers:
    raise SystemExit(f"organization registration missing tools={missing} handlers={handlers}")
print("TRAININGPEAKS_ORGANIZATION_MCP_REGISTRATION_PASS")
print("provider_writes=0")
