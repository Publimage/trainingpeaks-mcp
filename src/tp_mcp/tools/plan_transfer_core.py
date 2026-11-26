"""Provider-independent, recoverable copy of a complete plan into an empty range.

The gateway owns permissions, complete source discovery, supported capabilities,
and content normalization. This module has no HTTP routes or provider credentials.
An uncertain create is only reconciled by readback; it is never replayed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

KINDS = ("classic", "strength", "note", "attachment")


@dataclass(frozen=True)
class TransferRequest:
    request_id: str
    source_plan_id: int
    athlete_id: int
    start_date: str
    visible_through: str | None = None
    expected_source_digest: str | None = None


@dataclass(frozen=True)
class TransferItem:
    kind: str
    source_id: str
    offset_days: int
    order: int
    content: dict[str, Any]
    parent_source_id: str | None = None


@dataclass(frozen=True)
class PlanSnapshot:
    plan_id: int
    title: str
    anchor_date: str
    day_count: int
    digest: str
    items: list[TransferItem]


class Gateway(Protocol):
    async def preflight(self, request: TransferRequest) -> PlanSnapshot: ...
    async def inventory(self, request: TransferRequest) -> list[dict[str, Any]]: ...
    async def create(self, request: TransferRequest, item: TransferItem,
                     target_date: str, hidden: bool,
                     parent_target_id: str | None) -> str | int: ...
    async def verify_source(self, snapshot: PlanSnapshot) -> bool: ...
    # Optional optimization, detected dynamically: read_item(request, item,
    # target_id, parent_target_id) -> one normalized inventory row.


class TransferError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.progress: dict[str, Any] | None = None


def _need(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise TransferError(code, message)


def _json(value: Any) -> str:
    if isinstance(value, dict):
        _need(all(type(k) is str for k in value), "INVALID_DATA", "JSON keys must be strings.")
        for child in value.values():
            _json(child)
    elif isinstance(value, list):
        for child in value:
            _json(child)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TransferError("INVALID_DATA", "Content must be finite JSON data.") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _day(value: Any) -> date:
    try:
        _need(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
              "INVALID_DATE", "Dates must use YYYY-MM-DD.")
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TransferError("INVALID_DATE", "Invalid calendar date.") from exc


def _id(value: Any) -> str:
    _need((type(value) is int and value > 0) or (type(value) is str and bool(value.strip())),
          "INVALID_ID", "Provider identities must be nonempty strings or positive integers.")
    return str(value)


def _request(request: TransferRequest) -> None:
    _need(isinstance(request, TransferRequest), "INVALID_REQUEST", "TransferRequest required.")
    _need(type(request.request_id) is str and 1 <= len(request.request_id) <= 200,
          "INVALID_REQUEST", "A stable request ID is required.")
    for value in (request.source_plan_id, request.athlete_id):
        _need(type(value) is int and value > 0, "INVALID_REQUEST", "Positive plan and athlete IDs required.")
    _day(request.start_date)
    if request.visible_through is not None:
        _day(request.visible_through)
    if request.expected_source_digest is not None:
        _need(type(request.expected_source_digest) is str
              and re.fullmatch(r"[0-9a-f]{64}", request.expected_source_digest) is not None,
              "INVALID_DIGEST", "Expected source digest must be SHA256.")


def _key(item: TransferItem) -> str:
    return f"{item.kind}:{item.source_id}"


def _schedule(request: TransferRequest, item: TransferItem) -> tuple[str, bool]:
    target = _day(request.start_date) + timedelta(days=item.offset_days)
    return target.isoformat(), request.visible_through is not None and target > _day(request.visible_through)


def _snapshot(request: TransferRequest, snapshot: PlanSnapshot) -> list[TransferItem]:
    _need(isinstance(snapshot, PlanSnapshot) and snapshot.plan_id == request.source_plan_id,
          "SOURCE_IDENTITY", "Source plan identity differs from the request.")
    _need(type(snapshot.title) is str and bool(snapshot.title.strip()), "INVALID_SOURCE", "Source title missing.")
    _day(snapshot.anchor_date)
    _need(type(snapshot.day_count) is int and snapshot.day_count > 0,
          "INVALID_SOURCE", "Source calendar range missing.")
    _need(type(snapshot.digest) is str and re.fullmatch(r"[0-9a-f]{64}", snapshot.digest) is not None,
          "INVALID_SOURCE", "Source digest must be SHA256.")
    _need(type(snapshot.items) is list and bool(snapshot.items), "INVALID_SOURCE", "Complete nonempty source required.")
    keys: set[str] = set()
    for item in snapshot.items:
        _need(isinstance(item, TransferItem) and item.kind in KINDS, "UNSUPPORTED_KIND", "Unknown source object kind.")
        _need(type(item.source_id) is str and bool(item.source_id.strip()), "INVALID_SOURCE", "Source ID missing.")
        _need(_key(item) not in keys, "DUPLICATE_SOURCE_ID", "Source occurrence IDs must be unique per kind.")
        keys.add(_key(item))
        _need(type(item.offset_days) is int and 0 <= item.offset_days < snapshot.day_count,
              "INVALID_SOURCE", "Source object falls outside the declared range.")
        _need(type(item.order) is int and item.order >= 0 and type(item.content) is dict,
              "INVALID_SOURCE", "Source content or order is malformed.")
        _json(item.content)
        _schedule(request, item)
    notes = {item.source_id: item for item in snapshot.items if item.kind == "note"}
    for item in snapshot.items:
        if item.kind == "attachment":
            _need(type(item.parent_source_id) is str and item.parent_source_id in notes,
                  "INVALID_PARENT", "Attachment must reference one source note.")
            _need(notes[cast(str, item.parent_source_id)].offset_days == item.offset_days,
                  "INVALID_PARENT", "Attachment date differs from its parent note.")
        else:
            _need(item.parent_source_id is None, "INVALID_PARENT", "Only attachments may have a parent.")
    return sorted(snapshot.items, key=lambda x: (x.kind == "attachment", x.offset_days, x.order, _key(x)))


async def _inventory(request: TransferRequest, snapshot: PlanSnapshot, gateway: Gateway) -> list[dict[str, Any]]:
    rows = await gateway.inventory(request)
    return _validate_rows(request, snapshot, rows)


def _validate_rows(request: TransferRequest, snapshot: PlanSnapshot, rows: Any) -> list[dict[str, Any]]:
    _need(type(rows) is list, "INVALID_INVENTORY", "Complete destination inventory required.")
    seen: set[tuple[str, str]] = set()
    start = _day(request.start_date)
    for row in rows:
        _need(type(row) is dict and row.get("kind") in KINDS, "INVALID_INVENTORY", "Unknown destination kind.")
        row_id = _id(row.get("id"))
        identity = row["kind"], row_id
        _need(identity not in seen, "INVALID_INVENTORY", "Duplicate destination identity.")
        seen.add(identity)
        _need(0 <= (_day(row.get("date")) - start).days < snapshot.day_count,
              "INVALID_INVENTORY", "Gateway must return only the complete requested range.")
        _need(type(row.get("order")) is int and row["order"] >= 0
              and type(row.get("hidden")) is bool and type(row.get("content")) is dict,
              "INVALID_INVENTORY", "Missing destination order, visibility, or normalized content.")
        _json(row["content"])
        if row["kind"] == "attachment":
            _id(row.get("parent_id"))
        else:
            _need(row.get("parent_id") is None, "INVALID_INVENTORY", "Unexpected destination parent.")
    return rows


def _parent(item: TransferItem, entries: dict[str, Any]) -> str | None:
    if item.parent_source_id is None:
        return None
    note = entries.get(f"note:{item.parent_source_id}", {})
    _need(note.get("state") == "VERIFIED", "PARENT_UNVERIFIED", "Parent note has not been verified.")
    return note["target_id"]


def _matches(request: TransferRequest, item: TransferItem, row: dict[str, Any], parent: str | None) -> bool:
    target, hidden = _schedule(request, item)
    return (row["kind"] == item.kind and row["date"] == target and row["order"] == item.order
            and row["hidden"] == hidden and _json(row["content"]) == _json(item.content)
            and (None if row.get("parent_id") is None else str(row["parent_id"])) == parent)


def _accounted(request: TransferRequest, items: list[TransferItem], rows: list[dict[str, Any]],
               entries: dict[str, Any], *, allow_new: bool = False) -> None:
    owned: set[tuple[str, str]] = set()
    for item in items:
        entry = entries.get(_key(item), {})
        if entry.get("state") != "VERIFIED":
            continue
        identity = item.kind, entry["target_id"]
        _need(identity not in owned, "JOURNAL_CONFLICT", "Two source objects map to the same destination.")
        owned.add(identity)
        match = [r for r in rows if (r["kind"], str(r["id"])) == identity]
        _need(len(match) == 1 and _matches(request, item, match[0], _parent(item, entries)),
              "DESTINATION_DRIFT", "A transferred object is missing or differs from the source.")
    if not allow_new:
        _need({(r["kind"], str(r["id"])) for r in rows} == owned,
              "DESTINATION_DRIFT", "Unrelated or unrecognized objects appeared in the target range.")


def _summary(request: TransferRequest, snapshot: PlanSnapshot, status: str,
             journal: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    entries = (journal or {}).get("entries", {})
    counts = Counter(item.kind for item in snapshot.items)
    return {"status": status, "request_id": request.request_id, "source_plan_id": snapshot.plan_id,
            "athlete_id": request.athlete_id, "source_digest": snapshot.digest,
            "counts": {kind: counts[kind] for kind in KINDS},
            "created_ids": {key: e["target_id"] for key, e in entries.items() if e.get("state") == "VERIFIED"},
            "unverified_ids": {key: e["returned_id"] for key, e in entries.items()
                               if e.get("state") != "VERIFIED" and "returned_id" in e},
            **extra}


async def preview(request: TransferRequest, gateway: Gateway) -> dict[str, Any]:
    """Discover and compare without creating files or mutating the provider."""
    _request(request)
    snapshot = deepcopy(await gateway.preflight(request))
    items = _snapshot(request, snapshot)
    rows = await _inventory(request, snapshot, gateway)
    return _summary(request, snapshot, "PREVIEW", ready=not rows,
                    collisions=[{"kind": r["kind"], "id": str(r["id"]), "date": r["date"]} for r in rows],
                    target_dates=[{"source_key": _key(i), "date": _schedule(request, i)[0],
                                   "hidden": _schedule(request, i)[1]} for i in items])


def _persist(path: Path, journal: dict[str, Any]) -> None:
    _need(not path.is_symlink(), "UNSAFE_JOURNAL", "Journal cannot be a symbolic link.")
    fd, name = tempfile.mkstemp(prefix=".transfer-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_json(journal))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_journal(path: Path) -> dict[str, Any]:
    _need(not path.is_symlink(), "UNSAFE_JOURNAL", "Journal cannot be a symbolic link.")
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise TransferError("JOURNAL_CORRUPT", "Cannot read the existing transfer journal.") from exc
    _need(type(value) is dict and value.get("schema") == "PLAN_TRANSFER_V1"
          and type(value.get("binding")) is dict and type(value.get("entries")) is dict,
          "JOURNAL_CORRUPT", "Malformed transfer journal.")
    return value


def _check_reservations(directory: Path, own_path: Path, request: TransferRequest, snapshot: PlanSnapshot) -> None:
    """Pending provider writes reserve their range even when it still reads empty."""
    start = _day(request.start_date)
    end = start + timedelta(days=snapshot.day_count)
    for path in directory.glob("*.json"):
        if path == own_path:
            continue
        other = _read_journal(path)
        binding = other["binding"]
        previous = binding.get("request")
        _need(type(previous) is dict, "JOURNAL_CORRUPT", "Journal request binding missing.")
        if previous.get("athlete_id") != request.athlete_id:
            continue
        pending = False
        for entry in other["entries"].values():
            _need(type(entry) is dict, "JOURNAL_CORRUPT", "Malformed journal item.")
            pending = pending or entry.get("state") in ("INTENT", "UNCERTAIN")
        if pending:
            days = binding.get("day_count")
            _need(type(days) is int and days > 0, "JOURNAL_CORRUPT", "Reserved calendar range is missing.")
            other_start = _day(previous.get("start_date"))
            _need(end <= other_start or start >= other_start + timedelta(days=days),
                  "UNRESOLVED_OVERLAP", "An earlier request has an unresolved write in this range; resume it first.")


@contextmanager
def _locked(directory: Path, lock_key: str):
    _need(not any(p.is_symlink() for p in (directory, *directory.parents)),
          "UNSAFE_JOURNAL", "Journal directory cannot contain symbolic links.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    fd = os.open(directory / f"{lock_key}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransferError("BUSY", "Another transfer is running for this request or athlete.") from exc
        yield
    finally:
        os.close(fd)


@contextmanager
def _track_progress(request: TransferRequest, progress: dict[str, Any]):
    try:
        yield
    except Exception as exc:
        if "snapshot" not in progress or "journal" not in progress:
            raise
        error = exc if isinstance(exc, TransferError) else TransferError(
            "TRANSFER_INTERRUPTED", "Transfer interrupted; inspect the recorded provider state before continuing.")
        error.progress = _summary(request, progress["snapshot"], "BLOCKED", progress["journal"],
                                  error_code=error.code, message=str(error),
                                  next_step="Resolve the reported difference; reuse the same request for readback.")
        if error is exc:
            raise
        raise error from exc


async def transfer(request: TransferRequest, gateway: Gateway, journal_dir: Path | str,
                   execute: bool = False) -> dict[str, Any]:
    """Copy once, recording intent before each write and independently verifying it.

An existing request is resumed only against the identical source and parameters.
INTENT/UNCERTAIN entries may be reconciled by readback, never recreated.
"""
    _request(request)
    _need(type(execute) is bool, "INVALID_REQUEST", "execute must be boolean.")
    if not execute:
        return await preview(request, gateway)
    _need(request.expected_source_digest is not None, "DIGEST_REQUIRED", "Preview the source before execution.")
    directory = Path(journal_dir).absolute()
    progress: dict[str, Any] = {}
    request_hash = _sha(request.request_id)
    with (_locked(directory, f"request-{request_hash}"),
          _locked(directory, f"athlete-{request.athlete_id}"), _track_progress(request, progress)):
        snapshot = deepcopy(await gateway.preflight(request))
        items = _snapshot(request, snapshot)
        _need(snapshot.digest == request.expected_source_digest, "SOURCE_CHANGED", "Source changed since preview.")
        progress["snapshot"] = snapshot
        path = directory / f"{request_hash}.json"
        binding = {"request": asdict(request), "source_fingerprint": _sha(asdict(snapshot)),
                   "day_count": snapshot.day_count}
        if path.exists() or path.is_symlink():
            journal = _read_journal(path)
            _need(journal.get("binding") == binding,
                  "JOURNAL_CONFLICT", "Request ID already belongs to different source or parameters.")
            _need(set(journal["entries"]) <= {_key(i) for i in items},
                  "JOURNAL_CONFLICT", "Journal contains unknown source identities.")
            rows = await _inventory(request, snapshot, gateway)
        else:
            rows = await _inventory(request, snapshot, gateway)
            _need(not rows, "OCCUPIED_RANGE", "A new transfer requires an empty destination range.")
            journal = {"schema": "PLAN_TRANSFER_V1", "binding": binding, "entries": {}, "state": "RUNNING"}
            _persist(path, journal)
        progress["journal"] = journal
        entries = journal["entries"]
        if any(entries.get(_key(item), {}).get("state") != "VERIFIED" for item in items):
            _check_reservations(directory, path, request, snapshot)
            _need(await gateway.verify_source(snapshot) is True, "SOURCE_CHANGED", "Source changed before transfer.")
        created = 0
        for item in items:
            key = _key(item)
            entry = entries.get(key)
            if entry is not None:
                _need(type(entry) is dict and entry.get("state") in ("VERIFIED", "INTENT", "UNCERTAIN"),
                      "JOURNAL_CORRUPT", "Unknown item state in the journal.")
                if entry["state"] == "VERIFIED":
                    _id(entry.get("target_id"))
                    continue
            _accounted(request, items, rows, entries, allow_new=entry is not None)
            parent = _parent(item, entries)
            if entry is None:
                entry = {"state": "INTENT", "baseline": [[r["kind"], str(r["id"])] for r in rows]}
                entries[key] = entry
                _persist(path, journal)
                target, hidden = _schedule(request, item)
                try:
                    returned_id = await gateway.create(request, deepcopy(item), target, hidden, parent)
                    entry["returned_id"] = _id(returned_id)
                    _persist(path, journal)
                except Exception:
                    # A timeout does not establish whether the provider committed.
                    entry["state"] = "UNCERTAIN"
                    _persist(path, journal)
                created += 1
                try:
                    read_one = getattr(gateway, "read_item", None)
                    if entry.get("returned_id") is not None and callable(read_one):
                        try:
                            row = await read_one(request, item, entry["returned_id"], parent)
                            _validate_rows(request, snapshot, [row])
                            _need(str(row["id"]) == entry["returned_id"] and _matches(request, item, row, parent),
                                  "READBACK_MISMATCH", "Created object did not match its expected content.")
                            _need(not any((r["kind"], str(r["id"])) == (row["kind"], str(row["id"])) for r in rows),
                                  "DUPLICATE_TARGET", "Provider returned an already existing destination ID.")
                            rows = [*rows, row]
                        except Exception:
                            rows = await _inventory(request, snapshot, gateway)
                    else:
                        rows = await _inventory(request, snapshot, gateway)
                except Exception:
                    entry["state"] = "UNCERTAIN"
                    _persist(path, journal)
                    return _summary(request, snapshot, "UNCERTAIN", journal, source_key=key,
                                    next_step="Read destination state again with the same request; do not recreate it.")
            baseline = entry.get("baseline")
            _need(type(baseline) is list and all(type(x) is list and len(x) == 2 for x in baseline),
                  "JOURNAL_CORRUPT", "Missing pre-write inventory in the journal.")
            old_ids = {tuple(x) for x in baseline}
            matches = [r for r in rows if (r["kind"], str(r["id"])) not in old_ids
                       and _matches(request, item, r, parent)
                       and ("returned_id" not in entry or str(r["id"]) == entry["returned_id"])]
            if len(matches) != 1:
                entry["state"] = "UNCERTAIN"
                _persist(path, journal)
                return _summary(request, snapshot, "UNCERTAIN", journal, source_key=key,
                                next_step="Reconcile the uncertain object with the provider; it will not be retried.")
            entry.update(state="VERIFIED", target_id=str(matches[0]["id"]))
            _persist(path, journal)
            _accounted(request, items, rows, entries)
        rows = await _inventory(request, snapshot, gateway)
        _accounted(request, items, rows, entries)
        _need(len(entries) == len(items) and all(e["state"] == "VERIFIED" for e in entries.values()),
              "INCOMPLETE", "Not every source object has a verified destination.")
        _need(await gateway.verify_source(snapshot) is True, "SOURCE_CHANGED", "Source preservation failed.")
        journal["state"] = "DONE_VERIFIED"
        _persist(path, journal)
        return _summary(request, snapshot, "DONE_VERIFIED", journal, create_calls_this_run=created,
                        next_step="Transfer complete; repeating this request performs readback only.")
