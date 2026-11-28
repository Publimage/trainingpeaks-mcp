from unittest.mock import AsyncMock, patch

from scripts.ironman_jobs import chasing_native_plan_lab_audit as audit


async def test_audit_uses_the_read_only_preflight():
    with patch.object(audit, "tp_create_strength_plan_lab_probe", new_callable=AsyncMock) as probe:
        probe.return_value = {"success": True}
        assert await audit.main() == 0
    probe.assert_awaited_once_with(dry_run=True)
