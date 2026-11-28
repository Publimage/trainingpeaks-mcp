from unittest.mock import AsyncMock, patch

from scripts.ironman_jobs import chasing_native_strength_plan_lab_canary as canary


async def test_canary_requests_a_guarded_write():
    with patch.object(canary, "tp_create_strength_plan_lab_probe", new_callable=AsyncMock) as probe:
        probe.return_value = {"success": False}
        assert await canary.main() == 1
    probe.assert_awaited_once_with(dry_run=False)
