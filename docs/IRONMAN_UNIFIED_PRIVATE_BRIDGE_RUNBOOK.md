# IRONMAN unified preview — private VPC staging runbook (NOT DEPLOYED)

Purpose: connect the **existing** Prefect staging worker to the **existing** private TrainingPeaks bridge, without moving TP cookies/tokens and without opening another web service. One `IRONMAN_CHANGESET_V1` can preview workout, note, PDF metadata, native Strength and Library changes across authorized plans. No new job per plan, workout or PDF.

## Source and trust boundary

- Source of truth: canonical Drive `11_AGENT_ORCHESTRATION_ROADMAP`, `00B_IRONMAN_EMERGENCY_ACCESS_AND_RECOVERY`, `00C_IRONMAN_PROVEN_PATHS_REGISTRY`.
- Endpoint in existing `tp_mcp.private_bridge`: `POST /v1/unified-resource-read`, bound to the currently configured private VPC address, not public interfaces.
- Caller allowlist uses the existing `allowed_sources` IP control. Do not expand it or alter the existing Radar or CSS policies unless independently approved.
- New opt-in key `allowed_unified_reads` defaults to `[]` (deny all). Each entry must list the exact Training Plan/Workout Library container, resource kinds, and nonempty `resource_ids` allowlist. A resource ID outside that list is denied before the provider read. Older entries without `resource_ids` are invalid and must not be silently broadened.
- Only exact `{"spec":{"kind": "...", "target":{...}}}` payloads. Every target is bound to owner ID `2116886`, typed container ID, resource ID and provider.
- TP authentication and native data reads remain in the existing TrainingPeaks host process. The read-only VPC response is strictly bounded and strips credential-like keys and signed URLs.
- The Prefect client disallows HTTP redirects, network proxies, arbitrary URL selection and writer methods. An out-of-scope response is rejected.
- The new Prefect flow rejects `mode=publish` before opening any provider connection. A new manifest does not authorize writes.

## Staging preparation (requires normal authorized operator/deployment approval)

1. Review PR 18 and its offline tests. Do not merge or deploy on a failed/unknown CI result.
2. Inspect the real server-local `private_bridge.json`, preserve Radar/CSS entries and add ONLY the exact approved plan/library scopes to `allowed_unified_reads`. Sample **schema only**, not a ready-made approval:

```json
"allowed_unified_reads": [
  {
    "provider": "trainingpeaks",
    "owner_id": 2116886,
    "container_kind": "training_plan",
    "container_id": 123456,
    "kinds": ["plan.workout.patch", "plan.note.patch"],
    "resource_ids": [111111, 222222]
  }
]
```

3. Validate existing source IP allowlist and private bind; stage a controlled reload of the existing bridge after revision review. No new public listener or credential forwarding.
4. Ensure the separate Prefect worker has a copy of the reviewed code and an existing private directory for `/var/lib/ironman-prefect/unified-changesets/ledger.sqlite3`, owned by its non-root service account. No changes to TP-host credential permissions.
5. Deploy only `prefect/ironman-unified-changeset-v1.yaml` (`mode=preview`, `read_transport=private_bridge`, no schedule). It reuses the existing work pool. Do not use the old CSS deployment for generic requests.
6. Run a **single synthetic/approved read-only** changeset on a disposable Training Plan and verify every returned object, SHA, expected pre-image, owner and counts. Check Radar and CSS still return their original read-only results.
7. Verify no provider mutations, HTTP redirects, credential fields or unexpected file URLs. Verify denial of a different plan and a different source IP, and state recovery for a duplicate request ID.
8. Record provider readback and logs in the canonical KB only after successful staging evidence.

## Next gated capability: generic writes

A separately reviewed release can wire the original Proven Path adapters ONCE for each resource kind to the same changeset runner. Required: cross-host lock, durable idempotency, exact review/approval scope, full before/after provider readback and disposable-plan fault injection. Never run previously denied T1500/PDF operations as an alternative route around security controls.

## Status

**Code and CI candidate in PR 18; not merged, not reloaded, not yet smoke-tested on staging, no real TP writes.** This contract is a controlled implementation checkpoint, not a deployment authorization.
