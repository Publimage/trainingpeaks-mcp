# TrainingPeaks MCP — Tool metadata and refresh audit
Date: 2026-10-08
Branch: feat/mcp-test-training-plan-lab
State: SOURCE PATCHED / LOCAL TESTS PENDING / PROVIDER WRITE BLOCK UNRESOLVED

## Purpose
Check the truthful metadata for the custom TrainingPeaks MCP and the discrepancy
between the source tool inventory and actions visible to ChatGPT.
This audit MUST NOT be used to relax safety policy or hide write effects.

## Evidence
- Live native Training Plan `[MCP TEST] Training Plan — Swim Bike Run`, id 684206.
- Native first item: Swim 1200 m, 30 min, structured; week 1 / day 1, readback PASS.
- The attempt to add the second item (Bike) was blocked before a corresponding
  `Tool call: tp_add_training_plan_library_workout` appeared in the local
  TrainingPeaks MCP log. The subsequent readback still showed one Swim only.
- A transient tunnel HTTP 503 recovered; subsequent GET 200 responses demonstrate
  restored connectivity. Neither observation proves why a specific action was blocked.
- Source `src/tp_mcp/server.py`: 89 named tools. At audit time the ChatGPT
  plugin interface exposed 88: `tp_get_training_plan_notes` was the only missing tool.
- No pending changes to athlete calendars: all plan writes so far have targeted
  the private coach Training Plan Library, not a real athlete.

## Metadata policy
Official OpenAI guidance:
- https://developers.openai.com/plugins/reference
- https://developers.openai.com/plugins/deploy/app-review
- https://developers.openai.com/plugins/plan/tools

Interpret hints by what the tool ACTUALLY does:
- `readOnlyHint=true`: reads/computes only; NO changes.
- `destructiveHint=true`: may delete or overwrite existing user information,
  including via update calls. Additions to a separate TEST plan are not
  destructive unless they overwrite existing data.
- `idempotentHint=false`: retrying with identical arguments may cause a
  second insertion (notably the Training Plan create/add workout/add note tools).
- `openWorldHint=false`: all currently registered tools operate on the
  authenticated, bounded TrainingPeaks account/workspace (or the local
  exercise catalog), and accept no arbitrary public HTTP host or recipient
  as a destination. External API hosting ALONE does not make a tool open-world.
- New tools that communicate with arbitrary external recipients, public
  websites or open-ended destinations MUST be reassessed and explicitly
  represented in `_OPEN_WORLD_TOOLS`.
- No hint bypasses ChatGPT security checks, consent, provider permissions,
  server-side validation or the IRONMAN publishing gate.

The code now classifies updates of existing workout/library/notes/settings
and other potentially overwritten values as destructive. The three test-plan
write operations remain additive but non-idempotent, and their existing
`[MCP TEST]` guards remain intact.

## Missing tool: tp_get_training_plan_notes
Official OpenAI explanation:
https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt

Updated/new actions in a developer-mode custom app are not necessarily enabled
automatically. After refreshing tools, inspect the displayed action diff/list
and check whether the NEW `tp_get_training_plan_notes` action is enabled.
If not, enable it in the app tools UI. If it is enabled but absent in ChatGPT,
check the selected app snapshot/installation, re-open the conversation, or
report a mismatch with the list of tool names and sanitized log evidence.

Do NOT rename an unrelated tool or create a generic executor to circumvent
an unexposed action. Do NOT request reinstalling Python or restarting the
tunnel repeatedly without first comparing the actual `list_tools` output.

## Outstanding platform write block
The absence of a corresponding server-side tool call is evidence that the
failed Bike request was not executed by the local server, but does not by
itself distinguish policy block, app/tool permission, transport, or an
implementation fault elsewhere in the host.
Do not claim to know the precise internal block reason. Do not weaken MCP
metadata or repeat non-idempotent write calls in order to bypass a block.

For a support report: provide time of call (local timezone), selected tool
name, observed error text, fact that local log lacks the tool invocation,
and sanitized corresponding read successes, without access tokens, runtime
keys, athlete personal information or unrelated logs.

## Regression gate
Run on the coach Mac, while preserving the separate running tunnel session:
```bash
cd ~/trainingpeaks-mcp
git pull --ff-only
source .venv/bin/activate
python -m pytest tests/test_tool_metadata.py tests/test_server_functional.py tests/test_tools/test_plans.py -q
```
Only after PASS:
```bash
python -m pip install -e .
python -c "import asyncio; from tp_mcp.server import list_tools; t=asyncio.run(list_tools()); print(len(t)); print([(x.name,x.annotations.read_only_hint,x.annotations.destructive_hint,x.annotations.open_world_hint) for x in t if 'training_plan' in x.name])"
```
Restart the tunnel only after installation, then review/refresh the ChatGPT
tool actions and explicitly enable any new action if available.

## Safety boundaries
- No write to real athlete calendars without specific authorization.
- Do not touch the protected Intermediate 24W plan/sandbox range
  2027-01-04 to 2027-06-20.
- Tests affecting calendars, if later approved, ONLY athlete `941614`
  Piattaforma TEST and only after confirming an empty target range.
- Training Plan `684206` currently holds one native Swim workout. Inspect
  plan and its notes before ANY retry to avoid duplication.
- `tp_apply_training_plan` currently COPIES plan workouts onto an athlete
  calendar. It is not an official native linked TrainingPeaks plan application.
- The provider integration is an unofficial authenticated TrainingPeaks
  session and is still a POC, not production-ready.
