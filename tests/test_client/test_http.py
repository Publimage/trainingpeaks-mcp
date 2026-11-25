"""Tests for HTTP client, including throttling and athlete ID caching."""

import time
from unittest.mock import AsyncMock

import httpx
import pytest

from tp_mcp.client.http import MIN_REQUEST_INTERVAL, APIResponse, TPClient


class TestThrottling:
    """Tests for request throttling."""

    @pytest.mark.asyncio
    async def test_throttle_enforces_minimum_interval(self):
        """Throttle should enforce minimum interval between requests."""
        client = TPClient()

        # First call should not block
        start = time.monotonic()
        await client._throttle()
        first_duration = time.monotonic() - start
        assert first_duration < 0.05  # Should be nearly instant

        # Immediate second call should be delayed
        start = time.monotonic()
        await client._throttle()
        second_duration = time.monotonic() - start
        assert second_duration >= MIN_REQUEST_INTERVAL * 0.9  # Allow 10% tolerance

    @pytest.mark.asyncio
    async def test_throttle_no_delay_when_spaced(self):
        """Throttle should not delay when requests are naturally spaced."""
        client = TPClient()

        await client._throttle()

        # Wait longer than the interval
        import asyncio

        await asyncio.sleep(MIN_REQUEST_INTERVAL + 0.05)

        # Next call should not block
        start = time.monotonic()
        await client._throttle()
        duration = time.monotonic() - start
        assert duration < 0.05  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_throttle_multiple_rapid_calls(self):
        """Multiple rapid calls should each be throttled."""
        client = TPClient()

        start = time.monotonic()

        # Make 4 rapid throttle calls
        for _ in range(4):
            await client._throttle()

        total_duration = time.monotonic() - start

        # Should take at least 3 * MIN_REQUEST_INTERVAL (first is instant, next 3 are throttled)
        expected_min = MIN_REQUEST_INTERVAL * 3 * 0.9  # 10% tolerance
        assert total_duration >= expected_min

    @pytest.mark.asyncio
    async def test_client_init_sets_last_request_time(self):
        """Client should initialize last request time to 0."""
        client = TPClient()
        assert client._last_request_time == 0.0


class TestEnsureAthleteId:
    """The coach roster is live authority, never a process-lifetime cache."""

    @pytest.fixture(autouse=True)
    def _reset_token(self):
        TPClient._shared_token_cache = None
        yield
        TPClient._shared_token_cache = None

    @pytest.mark.asyncio
    async def test_fetches_from_provider(self):
        client = TPClient()
        client.get = AsyncMock(return_value=APIResponse(
            success=True, data={"user": {"personId": 42}},
        ))
        assert await client.ensure_athlete_id() == 42
        assert client.athlete_id == 42
        client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_athletes_array(self):
        client = TPClient()
        client.get = AsyncMock(return_value=APIResponse(
            success=True, data={"user": {"athletes": [{"athleteId": 77}]}},
        ))
        assert await client.ensure_athlete_id() == 77

    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self):
        client = TPClient()
        client.get = AsyncMock(return_value=APIResponse(
            success=False, message="Auth failed",
        ))
        assert await client.ensure_athlete_id() is None
        assert client.athlete_id is None

    @pytest.mark.asyncio
    async def test_reads_provider_again_across_instances(self):
        first = TPClient()
        first.get = AsyncMock(return_value=APIResponse(
            success=True, data={"user": {"personId": 123}},
        ))
        assert await first.ensure_athlete_id() == 123

        second = TPClient()
        second.get = AsyncMock(return_value=APIResponse(
            success=True, data={"user": {"personId": 456}},
        ))
        assert await second.ensure_athlete_id() == 456
        second.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_instance_id_does_not_bypass_provider_verification(self):
        client = TPClient()
        client.athlete_id = 555
        client.get = AsyncMock(return_value=APIResponse(
            success=False, message="Auth failed",
        ))
        assert await client.ensure_athlete_id() is None
        assert client.athlete_id is None

    @pytest.mark.asyncio
    async def test_newly_linked_athlete_found_without_restart(self):
        from tp_mcp.client.context import athlete_override
        client = TPClient()
        old = {"personId": 100, "athletes": [
            {"athleteId": 100, "firstName": "Coach", "lastName": "One"},
        ]}
        new = {"personId": 100, "athletes": [
            {"athleteId": 100, "firstName": "Coach", "lastName": "One"},
            {"athleteId": 201, "firstName": "New", "lastName": "Athlete"},
        ]}
        client.get = AsyncMock(side_effect=[
            APIResponse(success=True, data={"user": old}),
            APIResponse(success=True, data={"user": new}),
        ])
        token = athlete_override.set("201")
        try:
            assert await client.ensure_athlete_id() is None
            assert await client.ensure_athlete_id() == 201
            assert client.athlete_id == 201
            assert client.get.await_count == 2
        finally:
            athlete_override.reset(token)

    @pytest.mark.asyncio
    async def test_unlinked_athlete_is_not_retained(self):
        from tp_mcp.client.context import athlete_override
        client = TPClient()
        linked = {"personId": 100, "athletes": [
            {"athleteId": 201, "firstName": "Former", "lastName": "Athlete"},
        ]}
        unlinked = {"personId": 100, "athletes": []}
        client.get = AsyncMock(side_effect=[
            APIResponse(success=True, data={"user": linked}),
            APIResponse(success=True, data={"user": unlinked}),
        ])
        token = athlete_override.set("201")
        try:
            assert await client.ensure_athlete_id() == 201
            assert await client.ensure_athlete_id() is None
            assert client.athlete_id is None
        finally:
            athlete_override.reset(token)

    @pytest.mark.asyncio
    async def test_malformed_provider_roster_is_not_reused(self):
        client = TPClient()
        client.get = AsyncMock(side_effect=[
            APIResponse(success=True, data={"user": {"personId": 100}}),
            APIResponse(success=True, data={"user": {"personId": 100, "athletes": "invalid"}}),
        ])
        assert await client.ensure_athlete_id() == 100
        assert await client.ensure_athlete_id() is None
        assert client.athlete_id is None


class TestSharedTokenCache:
    """Tests for shared TokenCache across TPClient instances."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset shared token cache between tests."""
        TPClient._shared_token_cache = None
        yield
        TPClient._shared_token_cache = None

    def test_token_cache_shared_across_instances(self):
        """Multiple TPClient instances should share the same TokenCache."""
        client1 = TPClient()
        client2 = TPClient()
        assert client1._token_cache is client2._token_cache

    def test_token_cache_lazily_created(self):
        """Shared cache should be None until first TPClient is created."""
        assert TPClient._shared_token_cache is None
        TPClient()
        assert TPClient._shared_token_cache is not None


class TestHandleResponse:
    """Tests for HTTP response handling."""

    def test_204_is_success(self):
        """204 No Content responses should be treated as successful writes."""
        client = TPClient()

        response = httpx.Response(status_code=204)

        result = client._handle_response(response)

        assert result.success is True
        assert result.data is None


class TestForbiddenEndpoints:
    """Safeguard: destructive plan commands are hard-blocked at the client (the
    native applyplan + unapply emptied a published plan's template, 2026-06-17)."""

    def test_helper_matches_applyplan_only(self):
        from tp_mcp.client.http import _is_forbidden
        assert _is_forbidden("/plans/v1/commands/applyplan")
        assert _is_forbidden("/plans/v1/commands/applyplan?x=1")
        # the synthetic-apply read paths + status poll stay allowed
        assert not _is_forbidden("/plans/v1/plans/163992/workouts/2018-12-17/2019-04-10")
        assert not _is_forbidden("/plans/v1/appliedplans/applyPlanStatus")
        assert not _is_forbidden("/fitness/v6/athletes/123/workouts")

    @pytest.mark.asyncio
    async def test_applyplan_blocked_with_no_network_call(self):
        from tp_mcp.client.http import ErrorCode
        client = TPClient()
        # Sent via post() → _request(): blocked before any auth/HTTP happens.
        r = await client.post("/plans/v1/commands/applyplan", json=[{"planId": 1}])
        assert r.is_error and r.error_code == ErrorCode.FORBIDDEN_ENDPOINT
        # get_raw() is guarded too.
        rr = await client.get_raw("/plans/v1/commands/applyplan")
        assert rr.is_error and rr.error_code == ErrorCode.FORBIDDEN_ENDPOINT
