# IRONMAN — Cloud Operator bootstrap (one time)

## Objective

After the initial deployment ChatGPT can invoke the MCP tool
`tp_ironman_operator` to run **registered and revision-pinned** IRONMAN jobs
on the already running DigitalOcean droplet, without another Mac Terminal or
TinyFish session for each approved task.

This is a controlled job runner, **not** a generic shell. The job implementation
lives in this trusted GitHub repository and must be registered in
`data/ironman_operator_jobs.json`, scoped to coach owner `2116886`.
The tool checks GitHub origin, branch-tip commit, unmodified worktree, owner
identity, job scope, and a named offline test before running any job.
`GUARDED_WRITE` jobs also require exact scope acknowledgment and create a
durable one-attempt ledger before execution. On ambiguous outcomes, STOP and
read the provider; never automatically repeat a POST.

The initial job `native_strength_library_audit` is **READ ONLY**. It compares
known Classic Library content with candidate API routes for the native Strength
Builder. It does **not** establish that all possible undocumented provider routes
have been enumerated; an empty result is NOT proof that the manual entries are
absent, and must not authorize duplicate publishing.

## One-time droplet bootstrap

From the existing DigitalOcean Web Console SSH session running as `root`, run Git operations as the actual repository owner `ironman`, and change the working directory to the repository before starting pytest. The `ironman` account cannot enter `/root`, even if the interpreter is launched with `sudo -u ironman -H`. Do not whitelist the repository globally via `git config --global safe.directory` just to bypass Git ownership protection. Replace `REVIEWED_FULL_SHA` with the full, verified feature-branch commit supplied for this deployment:

```bash
(
set -e
REPO=/home/ironman/trainingpeaks-mcp
PY=/home/ironman/tp-mcp-venv/bin/python
PIN=REVIEWED_FULL_SHA
# pytest inherits this working directory; /root is inaccessible to ironman.
cd "$REPO"
OLD=$(sudo -u ironman -H git -C "$REPO" rev-parse HEAD)
sudo -u ironman -H git -C "$REPO" fetch origin feat/mcp-test-training-plan-lab
NEW=$(sudo -u ironman -H git -C "$REPO" rev-parse FETCH_HEAD)
test "$NEW" = "$PIN" || { echo "STOP: GitHub branch changed; no checkout"; exit 1; }
sudo -u ironman -H git -C "$REPO" checkout --detach "$PIN"
if ! sudo -u ironman -H "$PY" -m pytest -q "$REPO/tests/test_ironman_operator.py" "$REPO/tests/test_native_note_library.py" ||
   ! sudo -u ironman -H "$PY" -c "from tp_mcp.server import TOOLS, _TOOL_HANDLERS; assert any(t.name == 'tp_ironman_operator' for t in TOOLS); assert 'tp_ironman_operator' in _TOOL_HANDLERS"; then
  echo "TEST FAILED. Restoring previous revision; NOT restarting service."
  sudo -u ironman -H git -C "$REPO" checkout --detach "$OLD"
  exit 1
fi
sudo systemctl restart ironman-trainingpeaks-tunnel
sudo systemctl is-active ironman-trainingpeaks-tunnel
echo "IRONMAN OPERATOR BOOTSTRAPPED"
)
```

The user should have to do this **once**, because no already connected
DigitalOcean/GitHub plugin exposes arbitrary remote SSH command execution.
Do not claim that this code is running until the bootstrap is executed and
the cloud MCP readback demonstrates the tool.

## Subsequent ChatGPT-native operations

1. User defines outcome, target and guardrails (approval carries through the
   workflow for ordinary dependent steps).
2. Assistant reviews live canonical Drive KB and exact job specification.
3. Assistant publishes reviewed source + tests through the GitHub connector.
4. Assistant pins the **full Git commit SHA** (the trusted branch tip).
5. Assistant invokes `tp_ironman_operator(operation="preview", job="...", revision="...")`.
6. Assistant invokes `tp_ironman_operator(operation="execute", ...)`.
7. Assistant performs **independent provider readback**, updates Google Drive,
   and reports `DONE_VERIFIED` / `BLOCKED` honestly.

For native Strength:
- audit existing templates, including those manually dragged by the coach;
- build precise fingerprints from ordered blocks, exercises, sets, notes,
  instructions, and exercise IDs;
- reconcile the 19 canonical unique variants and 30 Training Plan occurrences;
- canary in Lab only after positive provider API type verification;
- publish **only verified missing native items** and check readback per item;
- preserve 20 Classic strength templates and all 30 native Plan occurrences.
- The result of a read-only diagnostic alone is **not** proof of completed
  publishing.

## Security and limitations

- Server runs as unprivileged user `ironman`; no server root credentials are
  handed to ChatGPT.
- The GitHub branch is an execution trust boundary: only trusted maintainers
  should have permission to push to it. A changed reviewed branch tip requires
  a **new full SHA**; a stale revision is refused.
- Child jobs inherit only a minimal environment. TrainingPeaks credential files
  remain on the server; never include credentials or tokens in logs.
- No TinyFish or browser profile is needed.
- The first deployment cannot be done by currently connected DigitalOcean
  tools: the available plugin manages droplet lifecycle but offers no SSH
  command execution. Do not falsely claim autonomous bootstrap.
- This tool does not imply unrestricted autonomy across unrelated providers:
  new apps/clients still require an authorized connector and domain-specific
  access permissions.
