"""Read-only verification of native Training Plan W1 Monday note ordering.

No provider writes. Prints only non-secret metadata relevant to ordering.
"""
import asyncio
import json
from datetime import date
from tp_mcp.client import TPClient

PLAN_ID = 684602
OWNER_ID = 2116886
FIRST_DAY = "2026-10-05"
LAST_DAY = "2027-04-01"
EXPECTED = [
    (2653513, "FASE | Calibration / General Development"),
    (2653514, "SETTIMANA 1 | Calibrazione e riferimenti"),
    (2653899, "README FIRST | INIZIA DA QUI"),
]
CANDIDATE_ORDER_FIELDS = (
    "id", "calendarNoteId", "noteId", "orderOnDay", "sortOrder",
    "displayOrder", "order", "sequence", "position", "priority",
    "dateCreated", "createdAt", "dateTimeCreatedUtc", "standardFormatDate",
    "isHidden", "planId", "attachments", "noteDate"
)

async def main():
    async with TPClient() as client:
        me = await client._get_user_data()
        assert isinstance(me, dict) and me.get("personId") == OWNER_ID, "Wrong account"
        r = await client.get(f"/plans/v1/plans/{PLAN_ID}")
        assert not r.is_error and isinstance(r.data, dict), "Plan unavailable"
        p = r.data
        assert p.get("planId") == PLAN_ID and p.get("workoutCount") == 259, "Wrong plan/count"
        assert p.get("weekCount") == 24 and p.get("isPublic") is False, "Unsafe plan"
        assert p.get("price") in (None, 0), "Plan price changed"
        assert p.get("title") == "[MCP TEST] IRONMAN Intermediate Assembly 24W", "Wrong title"
        r = await client.get(f"/plans/v1/plans/{PLAN_ID}/calendarNote/{FIRST_DAY}/{LAST_DAY}")
        assert not r.is_error and isinstance(r.data, list) and len(r.data) == 35, "Wrong notes count"
        arr = r.data
        w1 = [n for n in arr if (n.get("noteDate") or n.get("date") or "")[:10] == FIRST_DAY]
        assert len(w1) == 3, "Unexpected first Monday size"
        actual = [
            (int(n.get("id") or n.get("calendarNoteId") or n.get("noteId")), n.get("title"))
            for n in w1
        ]
        assert actual == EXPECTED, f"Unexpected first Monday order: {actual!r}"
        print("READ_ONLY:true")
        print("PLAN_ID:", PLAN_ID, "TOTAL_NOTES:", len(arr), "TOTAL_WORKOUTS:", p.get("workoutCount"))
        print("W1_RAW_KEYS:", json.dumps(sorted({k for x in w1 for k in x.keys()})))
        for i, n in enumerate(w1):
            print("W1_ENTRY:", json.dumps({
                "position": i+1,
                "title": n.get("title"),
                "metadata": {k:n.get(k) for k in CANDIDATE_ORDER_FIELDS if k in n}
            }, ensure_ascii=False))
        print("OTHER_NOTES:", len(arr)-len(w1))
        print("PROVIDER_WRITES:0")
        return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
