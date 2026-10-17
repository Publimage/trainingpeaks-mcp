"""Generic TrainingPeaks account organization primitives.

Provider-native organization only. No title-prefix simulation of folders.

Training Plan folders (current TP web provider contract):
  GET  /planfolder/v1/folder/all
  POST /planfolder/v1/folder
  PUT  /planfolder/v1/folder/{folderId}/name
  POST /planfolder/v1/command/assignplanstofolder
  POST /planfolder/v1/command/moveplansbetweenfolders
  POST /planfolder/v1/command/removeplansfromfolder

Every writer uses explicit provider readback and disables blind 401 retry on
the mutation request. Destructive folder deletion is intentionally NOT exposed
here because the TP UI contract deletes every plan inside the folder.
"""
from __future__ import annotations

from typing import Any
import copy

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

_PLAN_FOLDER_LIST = "/planfolder/v1/folder/all"
_PLAN_FOLDER_CREATE = "/planfolder/v1/folder"
_PLAN_FOLDER_RENAME = "/planfolder/v1/folder/{folder_id}/name"
_PLAN_FOLDER_ASSIGN = "/planfolder/v1/command/assignplanstofolder"
_PLAN_FOLDER_MOVE = "/planfolder/v1/command/moveplansbetweenfolders"
_PLAN_FOLDER_REMOVE = "/planfolder/v1/command/removeplansfromfolder"


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"isError": True, "error_code": code, "message": message, **extra}


def _folder_id(row: dict[str, Any]) -> str | None:
    value = row.get("folderId", row.get("id"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _folder_name(row: dict[str, Any]) -> str:
    return str(row.get("folderName") or row.get("title") or row.get("name") or "")


def _folder_plan_ids(row: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for value in row.get("planIds") or []:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


async def _read_folders(client: TPClient) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    response = await client.get(_PLAN_FOLDER_LIST)
    if response.is_error or not isinstance(response.data, list):
        return None, _error("API_ERROR", "Could not read Training Plan folders.")
    return [x for x in response.data if isinstance(x, dict)], None


async def _read_plans(client: TPClient) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    response = await client.get("/plans/v1/plans")
    if response.is_error or not isinstance(response.data, list):
        return None, _error("API_ERROR", "Could not read Training Plans.")
    return [x for x in response.data if isinstance(x, dict)], None


def _slim_folder(row: dict[str, Any], plans: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    ids = _folder_plan_ids(row)
    result: dict[str, Any] = {
        "folder_id": _folder_id(row),
        "name": _folder_name(row),
        "plan_ids": ids,
        "plan_count": len(ids),
    }
    if plans is not None:
        result["plans"] = [
            {"plan_id": pid, "title": plans.get(pid, {}).get("title")}
            for pid in ids
        ]
    return result


async def tp_list_plan_folders(include_plans: bool = True) -> dict[str, Any]:
    """List native Training Plan folders plus the virtual unfiled My Plans bucket."""
    async with TPClient() as client:
        folders, err = await _read_folders(client)
        if err:
            return err
        plans, err = await _read_plans(client)
        if err:
            return err
        by_id = {int(p["planId"]): p for p in plans if p.get("planId") is not None}
        folder_rows = [_slim_folder(x, by_id if include_plans else None) for x in folders]
        assigned = {pid for row in folder_rows for pid in row["plan_ids"]}
        my_ids = sorted(set(by_id) - assigned)
        my_plans: dict[str, Any] = {
            "folder_id": "my_plans",
            "name": "My Plans",
            "virtual": True,
            "plan_ids": my_ids,
            "plan_count": len(my_ids),
        }
        if include_plans:
            my_plans["plans"] = [{"plan_id": pid, "title": by_id[pid].get("title")} for pid in my_ids]
        return {
            "folders": folder_rows,
            "my_plans": my_plans,
            "folder_count": len(folder_rows),
            "total_plan_count": len(by_id),
        }


async def tp_create_plan_folder(name: str) -> dict[str, Any]:
    """Create one native Training Plan folder, idempotent by exact folder name."""
    name = (name or "").strip()
    if not name:
        return _error("VALIDATION_ERROR", "Folder name must not be empty.")
    async with TPClient() as client:
        before, err = await _read_folders(client)
        if err:
            return err
        matches = [x for x in before if _folder_name(x) == name]
        if len(matches) > 1:
            return _error("AMBIGUOUS_TARGET", f"More than one folder is named {name!r}.")
        if len(matches) == 1:
            row = _slim_folder(matches[0])
            return {"verified": True, "created": False, "folder": row}

        try:
            response = await client._request(
                "POST", _PLAN_FOLDER_CREATE,
                json={"folderName": name}, _retry_on_401=False,
            )
        except Exception:
            after, read_err = await _read_folders(client)
            if read_err:
                return _error("AMBIGUOUS_WRITE", "Folder create outcome is ambiguous; readback failed.")
            matches = [x for x in after if _folder_name(x) == name]
            if len(matches) == 1:
                return {"verified": True, "created": True, "recovered_from_ambiguous_response": True,
                        "folder": _slim_folder(matches[0])}
            return _error("AMBIGUOUS_WRITE", "Folder create outcome could not be verified; do not retry blindly.")

        after, read_err = await _read_folders(client)
        if read_err:
            return _error("READBACK_FAILED", "Folder create returned but provider readback failed.")
        matches = [x for x in after if _folder_name(x) == name]
        if len(matches) != 1:
            return _error("READBACK_FAILED", "Created folder was not uniquely present on provider readback.")
        if response.is_error:
            return {"verified": True, "created": True, "provider_response_error": True,
                    "folder": _slim_folder(matches[0])}
        return {"verified": True, "created": True, "folder": _slim_folder(matches[0])}


async def tp_rename_plan_folder(folder_id: str, name: str) -> dict[str, Any]:
    """Rename a native Training Plan folder and verify by provider readback."""
    fid = str(folder_id or "").strip()
    name = (name or "").strip()
    if not fid or fid == "my_plans":
        return _error("VALIDATION_ERROR", "A real custom folder_id is required.")
    if not name:
        return _error("VALIDATION_ERROR", "Folder name must not be empty.")
    async with TPClient() as client:
        before, err = await _read_folders(client)
        if err:
            return err
        source = next((x for x in before if _folder_id(x) == fid), None)
        if source is None:
            return _error("NOT_FOUND", f"No Training Plan folder {fid}.")
        if any(_folder_name(x) == name and _folder_id(x) != fid for x in before):
            return _error("ALREADY_EXISTS", f"Another Training Plan folder is already named {name!r}.")
        old = _folder_name(source)
        if old == name:
            return {"verified": True, "changed": False, "folder": _slim_folder(source)}
        try:
            response = await client._request(
                "PUT", _PLAN_FOLDER_RENAME.format(folder_id=fid),
                json={"folderName": name}, _retry_on_401=False,
            )
        except Exception:
            response = None
        after, read_err = await _read_folders(client)
        if read_err:
            return _error("READBACK_FAILED", "Folder rename outcome could not be read back; do not retry blindly.")
        updated = next((x for x in after if _folder_id(x) == fid), None)
        if updated is None or _folder_name(updated) != name:
            code = "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED"
            return _error(code, "Folder rename was not verified; do not retry blindly.")
        return {"verified": True, "changed": True, "old_name": old, "folder": _slim_folder(updated)}


async def tp_move_training_plans(plan_ids: list[int], to_folder_id: str) -> dict[str, Any]:
    """Move exact Training Plans to a custom folder or to virtual my_plans."""
    if not isinstance(plan_ids, list) or not plan_ids:
        return _error("VALIDATION_ERROR", "plan_ids must be a non-empty list.")
    try:
        ids = sorted(set(int(x) for x in plan_ids))
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "Every plan_id must be numeric.")
    destination = str(to_folder_id or "").strip()
    if not destination:
        return _error("VALIDATION_ERROR", "to_folder_id is required; use 'my_plans' for the root bucket.")

    async with TPClient() as client:
        plans, err = await _read_plans(client)
        if err:
            return err
        by_id = {int(p["planId"]): p for p in plans if p.get("planId") is not None}
        missing = [pid for pid in ids if pid not in by_id]
        if missing:
            return _error("NOT_FOUND", f"Unknown Training Plan IDs: {missing}.", missing_plan_ids=missing)

        folders, err = await _read_folders(client)
        if err:
            return err
        by_folder = {_folder_id(x): x for x in folders if _folder_id(x)}
        if destination != "my_plans" and destination not in by_folder:
            return _error("NOT_FOUND", f"No Training Plan folder {destination}.")

        current_for: dict[int, str | None] = {}
        for pid in ids:
            memberships = [fid for fid, row in by_folder.items() if pid in _folder_plan_ids(row)]
            if len(memberships) > 1:
                return _error("PROVIDER_DRIFT", f"Plan {pid} appears in multiple folders.", plan_id=pid)
            current_for[pid] = memberships[0] if memberships else None

        mutations: list[dict[str, Any]] = []

        async def provider_membership() -> dict[int, str | None] | None:
            rb, read_err = await _read_folders(client)
            if read_err:
                return None
            mapping: dict[int, str | None] = {pid: None for pid in ids}
            for row in rb:
                fid = _folder_id(row)
                for pid in _folder_plan_ids(row):
                    if pid in mapping:
                        if mapping[pid] is not None and mapping[pid] != fid:
                            return None
                        mapping[pid] = fid
            return mapping

        async def mutate(method_path: str, payload: dict[str, Any],
                         expected: dict[int, str | None], label: str) -> dict[str, Any] | None:
            try:
                response = await client._request(
                    "POST", method_path, json=payload, _retry_on_401=False,
                )
            except Exception:
                response = None
            observed = await provider_membership()
            if observed is None:
                return _error("AMBIGUOUS_WRITE", f"{label} outcome could not be read back; do not retry blindly.")
            if any(observed.get(pid) != target for pid, target in expected.items()):
                code = "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED"
                return _error(code, f"{label} was not verified; do not retry blindly.",
                              observed={str(k): v for k, v in observed.items()})
            mutations.append({"operation": label, "plan_ids": sorted(expected), "verified": True})
            return None

        expected_dest = None if destination == "my_plans" else destination
        if destination == "my_plans":
            sources = sorted({fid for fid in current_for.values() if fid is not None})
            for source in sources:
                moving = [pid for pid, fid in current_for.items() if fid == source]
                err_result = await mutate(
                    _PLAN_FOLDER_REMOVE,
                    {"folderId": source, "planIds": moving},
                    {pid: None for pid in moving},
                    "remove_plans_from_folder",
                )
                if err_result:
                    return err_result
        else:
            unfiled = [pid for pid, fid in current_for.items() if fid is None]
            if unfiled:
                err_result = await mutate(
                    _PLAN_FOLDER_ASSIGN,
                    {"folderId": destination, "planIds": unfiled},
                    {pid: destination for pid in unfiled},
                    "assign_plans_to_folder",
                )
                if err_result:
                    return err_result
            sources = sorted({fid for fid in current_for.values()
                              if fid is not None and fid != destination})
            for source in sources:
                moving = [pid for pid, fid in current_for.items() if fid == source]
                err_result = await mutate(
                    _PLAN_FOLDER_MOVE,
                    {"fromFolder": source, "toFolder": destination, "planIds": moving},
                    {pid: destination for pid in moving},
                    "move_plans_between_folders",
                )
                if err_result:
                    return err_result

        final = await provider_membership()
        if final is None:
            return _error("READBACK_FAILED", "Final folder membership readback failed.")
        if any(final.get(pid) != expected_dest for pid in ids):
            return _error("READBACK_FAILED", "Final Training Plan folder membership is not exact.")
        return {
            "verified": True,
            "plan_ids": ids,
            "destination_folder_id": destination,
            "mutations": mutations,
            "no_op_plan_ids": sorted(pid for pid, fid in current_for.items()
                                     if fid == expected_dest),
        }


async def tp_rename_training_plan(plan_id: int | str, title: str) -> dict[str, Any]:
    """Rename one Training Plan with title-only provider PUT and full detail readback."""
    try:
        pid = int(plan_id)
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "plan_id must be numeric.")
    title = (title or "").strip()
    if not title:
        return _error("VALIDATION_ERROR", "title must not be empty.")
    async with TPClient() as client:
        before = await client.get(f"/plans/v1/plans/{pid}")
        if before.is_error or not isinstance(before.data, dict):
            return _error("NOT_FOUND", f"Training Plan {pid} was not found.")
        original = before.data
        old_title = str(original.get("title") or "")
        if old_title == title:
            return {"verified": True, "changed": False, "plan_id": pid, "title": title}
        baseline = {k: v for k, v in original.items() if k != "title"}
        try:
            response = await client._request(
                "PUT", f"/plans/v1/plans/{pid}",
                json={"planId": pid, "title": title}, _retry_on_401=False,
            )
        except Exception:
            response = None
        after = await client.get(f"/plans/v1/plans/{pid}")
        if after.is_error or not isinstance(after.data, dict):
            return _error("AMBIGUOUS_WRITE", "Training Plan rename outcome could not be read back; do not retry blindly.")
        if after.data.get("title") != title:
            code = "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED"
            return _error(code, "Training Plan rename was not verified; do not retry blindly.")
        if {k: v for k, v in after.data.items() if k != "title"} != baseline:
            return _error("PROVIDER_DRIFT", "Training Plan metadata changed beyond the requested title.")
        return {"verified": True, "changed": True, "plan_id": pid,
                "old_title": old_title, "title": title}


async def tp_move_athletes_between_groups(
    from_group_id: str,
    to_group_id: str,
    athlete_ids: list[int],
) -> dict[str, Any]:
    """Move athletes between TP coach tags: add+verify destination, then remove+verify source."""
    try:
        source_id = int(from_group_id)
        dest_id = int(to_group_id)
        ids = sorted(set(int(x) for x in athlete_ids))
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "Group and athlete IDs must be numeric.")
    if not ids:
        return _error("VALIDATION_ERROR", "athlete_ids must be non-empty.")
    if source_id == dest_id:
        return _error("VALIDATION_ERROR", "Source and destination groups must differ.")

    async with TPClient() as client:
        user = await client._get_user_data()
        if not user or not user.get("personId"):
            return _error("AUTH_INVALID", "Could not resolve coach account.")
        coach_id = int(user["personId"])
        read_path = f"/coaches/v2/coaches/{coach_id}/tags"

        async def tags():
            r = await client.get(read_path)
            if r.is_error or not isinstance(r.data, list):
                return None
            return [x for x in r.data if isinstance(x, dict)]

        before = await tags()
        if before is None:
            return _error("API_ERROR", "Could not read athlete groups.")
        source = next((x for x in before if x.get("id") == source_id), None)
        dest = next((x for x in before if x.get("id") == dest_id), None)
        if source is None or dest is None:
            return _error("NOT_FOUND", "Source or destination athlete group was not found.")
        if source.get("isDefault") or dest.get("isDefault"):
            return _error("FORBIDDEN", "Moving membership to/from the default group is not supported.")
        source_members = {int(x) for x in source.get("athleteIds") or []}
        missing_source = sorted(set(ids) - source_members)
        if missing_source:
            return _error("PRECONDITION_FAILED", "Some athletes are not in the source group.",
                          missing_from_source=missing_source)

        added_now: list[int] = []
        dest_members = {int(x) for x in dest.get("athleteIds") or []}
        for aid in ids:
            if aid in dest_members:
                continue
            try:
                resp = await client._request(
                    "POST", f"/coaches/v1/coaches/{coach_id}/tags/{dest_id}/athletes",
                    json={"Value": aid}, _retry_on_401=False,
                )
            except Exception:
                resp = None
            rb = await tags()
            current_dest = next((x for x in rb or [] if x.get("id") == dest_id), None)
            verified = current_dest is not None and aid in {int(x) for x in current_dest.get("athleteIds") or []}
            if not verified:
                return _error("AMBIGUOUS_WRITE" if resp is None else "READBACK_FAILED",
                              f"Destination membership for athlete {aid} was not verified; source was not changed.")
            added_now.append(aid)

        removed: list[int] = []
        for aid in ids:
            try:
                resp = await client._request(
                    "DELETE",
                    f"/coaches/v1/coaches/{coach_id}/tags/{source_id}/athletes/{aid}",
                    _retry_on_401=False,
                )
            except Exception:
                resp = None
            rb = await tags()
            current_source = next((x for x in rb or [] if x.get("id") == source_id), None)
            gone = current_source is not None and aid not in {int(x) for x in current_source.get("athleteIds") or []}
            if not gone:
                return _error("AMBIGUOUS_WRITE" if resp is None else "READBACK_FAILED",
                              f"Source removal for athlete {aid} was not verified.",
                              destination_membership_already_verified=True)
            removed.append(aid)

        final = await tags()
        fs = next((x for x in final or [] if x.get("id") == source_id), None)
        fd = next((x for x in final or [] if x.get("id") == dest_id), None)
        if fs is None or fd is None:
            return _error("READBACK_FAILED", "Final athlete-group readback failed.")
        sm = {int(x) for x in fs.get("athleteIds") or []}
        dm = {int(x) for x in fd.get("athleteIds") or []}
        if any(a in sm or a not in dm for a in ids):
            return _error("READBACK_FAILED", "Final athlete-group membership is not exact.")
        return {"verified": True, "athlete_ids": ids,
                "from_group_id": source_id, "to_group_id": dest_id,
                "added_to_destination": added_now, "removed_from_source": removed}


# ---------------------------------------------------------------------------
# Workout Library organization
# ---------------------------------------------------------------------------

_CLASSIC_LIBS = "/exerciselibrary/v2/libraries"
_CLASSIC_ITEMS_READ = "/exerciselibrary/v2/libraries/{library_id}/items"
_CLASSIC_LIBRARY_NAME = "/exerciselibrary/v1/libraries/{library_id}/name"
_CLASSIC_ITEM = "/exerciselibrary/v1/libraries/{library_id}/items/{item_id}"
_CLASSIC_ITEMS_CREATE = "/exerciselibrary/v1/libraries/{library_id}/items"

_NATIVE_READ = "/rx/activity/v1/libraryContent/workoutLibrary/{library_id}"
_NATIVE_COPY = "/rx/activity/v1/LibraryContent/workoutLibrary/items/copy"
_NATIVE_SAVE = "/rx/activity/v1/libraryContent/workoutLibrary/save"
_NATIVE_DELETE = "/rx/activity/v1/libraryContent/workoutLibrary/items/{item_id}"


def _library_id(row: dict[str, Any]) -> int | None:
    value = row.get("exerciseLibraryId", row.get("id"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classic_item_id(row: dict[str, Any]) -> int | None:
    value = row.get("exerciseLibraryItemId", row.get("id"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _native_item_id(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("id"))
    except (TypeError, ValueError):
        return None


def _native_items(raw: Any) -> list[dict[str, Any]]:
    data = raw.get("data") if isinstance(raw, dict) else raw
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _native_semantic(item: dict[str, Any]) -> dict[str, Any]:
    workout = item.get("workout") if isinstance(item.get("workout"), dict) else {}
    blocks = workout.get("blocks") or []
    return {
        "id": _native_item_id(item),
        "title": item.get("title"),
        "workoutLibraryItemType": item.get("workoutLibraryItemType"),
        "workoutType": workout.get("workoutType"),
        "instructions": workout.get("instructions"),
        "blocks": blocks,
        "block_prescription_counts": [
            len(block.get("prescriptions") or [])
            for block in blocks
            if isinstance(block, dict)
        ],
    }


async def _read_library_inventory(
    client: TPClient,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    response = await client.get(_CLASSIC_LIBS)
    if response.is_error or not isinstance(response.data, list):
        return None, _error("API_ERROR", "Could not read Workout Libraries.")
    return [x for x in response.data if isinstance(x, dict)], None


def _owned_library(
    libraries: list[dict[str, Any]],
    library_id: int,
    owner_id: int,
) -> dict[str, Any] | None:
    return next(
        (
            x for x in libraries
            if _library_id(x) == library_id
            and x.get("ownerId") == owner_id
            and not x.get("isDefaultContent", False)
        ),
        None,
    )


async def _read_classic_items(
    client: TPClient,
    library_id: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    response = await client.get(_CLASSIC_ITEMS_READ.format(library_id=library_id))
    if response.is_error or not isinstance(response.data, list):
        return None, _error("API_ERROR", f"Could not read Workout Library {library_id}.")
    return [x for x in response.data if isinstance(x, dict)], None


async def tp_rename_library(library_id: int | str, name: str) -> dict[str, Any]:
    """Rename one coach-owned Workout Library with provider readback."""
    try:
        lid = int(library_id)
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "library_id must be numeric.")
    name = (name or "").strip()
    if not name:
        return _error("VALIDATION_ERROR", "Library name must not be empty.")

    async with TPClient() as client:
        user = await client._get_user_data()
        if not user or not user.get("personId"):
            return _error("AUTH_INVALID", "Could not resolve coach account.")
        owner = int(user["personId"])
        libraries, err = await _read_library_inventory(client)
        if err:
            return err
        source = _owned_library(libraries, lid, owner)
        if source is None:
            return _error("FORBIDDEN_OR_NOT_FOUND", "Library is not a mutable coach-owned library.")
        old = str(source.get("libraryName") or "")
        if old == name:
            return {"verified": True, "changed": False, "library_id": lid, "name": name}
        if any(
            x.get("ownerId") == owner
            and _library_id(x) != lid
            and str(x.get("libraryName") or "") == name
            for x in libraries
        ):
            return _error("ALREADY_EXISTS", f"Another coach-owned library is already named {name!r}.")

        try:
            response = await client._request(
                "PUT",
                _CLASSIC_LIBRARY_NAME.format(library_id=lid),
                json={"value": name},
                _retry_on_401=False,
            )
        except Exception:
            response = None

        after, read_err = await _read_library_inventory(client)
        if read_err:
            return _error("AMBIGUOUS_WRITE", "Library rename outcome could not be read back; do not retry blindly.")
        updated = next((x for x in after if _library_id(x) == lid), None)
        if updated is None or str(updated.get("libraryName") or "") != name:
            return _error(
                "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                "Library rename was not verified; do not retry blindly.",
            )
        return {"verified": True, "changed": True, "library_id": lid, "old_name": old, "name": name}


async def _native_session(
    client: TPClient,
) -> tuple[httpx.AsyncClient | None, dict[str, str] | None, dict[str, Any] | None]:
    _, token, error = await _access(client)
    if error or not token:
        return None, None, _error("AUTH_INVALID", "Could not authenticate the native Strength library service.")
    http = httpx.AsyncClient(timeout=25, follow_redirects=False)
    return http, _headers(token), None


async def _read_native_items_http(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    library_id: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    try:
        response = await http.get(
            STRENGTH_API_BASE + _NATIVE_READ.format(library_id=library_id),
            headers=headers,
        )
    except httpx.RequestError:
        return None, _error("NETWORK_ERROR", f"Could not read native Strength library {library_id}.")
    if response.status_code != 200:
        return None, _error(
            "API_ERROR",
            f"Native Strength library read failed with HTTP {response.status_code}.",
        )
    try:
        return _native_items(response.json()), None
    except ValueError:
        return None, _error("API_ERROR", "Native Strength library returned invalid JSON.")


async def _resolve_library_item(
    client: TPClient,
    http: httpx.AsyncClient,
    headers: dict[str, str],
    library_id: int,
    item_id: int,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    classic, err = await _read_classic_items(client, library_id)
    if err:
        return None, None, err
    classic_matches = [x for x in classic if _classic_item_id(x) == item_id]

    native, native_err = await _read_native_items_http(http, headers, library_id)
    if native_err:
        return None, None, native_err
    native_matches = [x for x in native if _native_item_id(x) == item_id]

    if classic_matches and native_matches:
        return None, None, _error("PROVIDER_DRIFT", f"Item {item_id} appears as both classic and native.")
    if len(classic_matches) == 1:
        return "classic", classic_matches[0], None
    if len(native_matches) == 1:
        return "native_strength", native_matches[0], None
    if len(classic_matches) > 1 or len(native_matches) > 1:
        return None, None, _error("PROVIDER_DRIFT", f"Item {item_id} is duplicated in library {library_id}.")
    return None, None, _error("NOT_FOUND", f"Item {item_id} was not found in library {library_id}.")


def _classic_copy_payload(
    source: dict[str, Any],
    destination_library_id: int,
    title: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload.pop("exerciseLibraryItemId", None)
    payload.pop("id", None)
    payload["exerciseLibraryId"] = destination_library_id
    if "itemName" in payload or "title" not in payload:
        payload["itemName"] = title
    if "title" in payload:
        payload["title"] = title
    return payload


def _classic_move_payload(
    source: dict[str, Any],
    destination_library_id: int,
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["exerciseLibraryId"] = destination_library_id
    return payload


def _classic_semantic(
    item: dict[str, Any],
    *,
    ignore_library: bool = False,
    ignore_id: bool = False,
    ignore_title: bool = False,
) -> dict[str, Any]:
    value = copy.deepcopy(item)
    for key in ("loaded", "shared", "selected", "expanded"):
        value.pop(key, None)
    if ignore_library:
        value.pop("exerciseLibraryId", None)
    if ignore_id:
        value.pop("exerciseLibraryItemId", None)
        value.pop("id", None)
    if ignore_title:
        value.pop("itemName", None)
        value.pop("title", None)
    return value


async def tp_copy_library_items(
    source_library_id: int | str,
    to_library_id: int | str,
    item_ids: list[int],
) -> dict[str, Any]:
    """Copy classic or native StructuredStrength templates between coach-owned libraries.

    Item type is discovered provider-side. Classic items use the classic
    exerciselibrary POST; ActivityWorkoutTemplate/StructuredStrength uses the
    native Activity Builder copy endpoint. Existing title collisions fail
    closed to keep retries idempotent.
    """
    try:
        source_id = int(source_library_id)
        destination_id = int(to_library_id)
        ids = [int(x) for x in item_ids]
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "Library and item IDs must be numeric.")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return _error("VALIDATION_ERROR", "item_ids must be non-empty.")
    if source_id == destination_id:
        return _error("VALIDATION_ERROR", "Source and destination libraries must differ.")

    async with TPClient() as client:
        user = await client._get_user_data()
        if not user or not user.get("personId"):
            return _error("AUTH_INVALID", "Could not resolve coach account.")
        owner = int(user["personId"])
        libraries, err = await _read_library_inventory(client)
        if err:
            return err
        if _owned_library(libraries, source_id, owner) is None or _owned_library(libraries, destination_id, owner) is None:
            return _error("FORBIDDEN_OR_NOT_FOUND", "Both libraries must be mutable coach-owned libraries.")

        http, headers, native_err = await _native_session(client)
        if native_err or http is None or headers is None:
            return native_err or _error("AUTH_INVALID", "Native library session unavailable.")
        results: list[dict[str, Any]] = []
        try:
            for iid in ids:
                kind, source, resolve_err = await _resolve_library_item(
                    client, http, headers, source_id, iid
                )
                if resolve_err or source is None or kind is None:
                    return resolve_err or _error("NOT_FOUND", f"Item {iid} not found.")

                if kind == "classic":
                    title = str(source.get("itemName") or source.get("title") or "")
                    destination_items, read_err = await _read_classic_items(client, destination_id)
                    if read_err:
                        return read_err
                    collisions = [x for x in destination_items if str(x.get("itemName") or x.get("title") or "") == title]
                    if collisions:
                        return _error("ALREADY_EXISTS", f"Destination already contains a classic item titled {title!r}.")
                    payload = _classic_copy_payload(source, destination_id, title)
                    try:
                        response = await client._request(
                            "POST",
                            _CLASSIC_ITEMS_CREATE.format(library_id=destination_id),
                            json=payload,
                            _retry_on_401=False,
                        )
                    except Exception:
                        response = None
                    after, rb_err = await _read_classic_items(client, destination_id)
                    if rb_err:
                        return _error("AMBIGUOUS_WRITE", "Classic copy readback failed; do not retry blindly.")
                    matches = [x for x in after if str(x.get("itemName") or x.get("title") or "") == title]
                    if len(matches) != 1:
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Classic copy of item {iid} was not uniquely verified; do not retry blindly.",
                        )
                    copied = matches[0]
                    if _classic_semantic(copied, ignore_library=True, ignore_id=True, ignore_title=True) != _classic_semantic(
                        source, ignore_library=True, ignore_id=True, ignore_title=True
                    ):
                        return _error("PROVIDER_DRIFT", f"Classic copy of item {iid} changed workout content.")
                    results.append({
                        "source_item_id": iid,
                        "copied_item_id": _classic_item_id(copied),
                        "kind": kind,
                        "verified": True,
                    })
                else:
                    title = str(source.get("title") or "")
                    destination_items, rb_err = await _read_native_items_http(http, headers, destination_id)
                    if rb_err:
                        return rb_err
                    if any(str(x.get("title") or "") == title for x in destination_items):
                        return _error("ALREADY_EXISTS", f"Destination already contains a native item titled {title!r}.")
                    try:
                        response = await http.post(
                            STRENGTH_API_BASE + _NATIVE_COPY,
                            json={
                                "libraryId": destination_id,
                                "workoutLibraryItemId": iid,
                                "title": title,
                            },
                            headers=headers,
                        )
                    except httpx.RequestError:
                        response = None
                    after, rb_err = await _read_native_items_http(http, headers, destination_id)
                    if rb_err:
                        return _error("AMBIGUOUS_WRITE", "Native copy readback failed; do not retry blindly.")
                    matches = [x for x in after if str(x.get("title") or "") == title]
                    if len(matches) != 1:
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Native copy of item {iid} was not uniquely verified; do not retry blindly.",
                        )
                    copied = matches[0]
                    source_sem = _native_semantic(source)
                    copied_sem = _native_semantic(copied)
                    for key in ("id", "title"):
                        source_sem.pop(key, None)
                        copied_sem.pop(key, None)
                    if copied_sem != source_sem:
                        return _error("PROVIDER_DRIFT", f"Native StructuredStrength copy of item {iid} changed prescribed structure.")
                    results.append({
                        "source_item_id": iid,
                        "copied_item_id": _native_item_id(copied),
                        "kind": kind,
                        "verified": True,
                    })
            return {
                "verified": True,
                "source_library_id": source_id,
                "destination_library_id": destination_id,
                "items": results,
            }
        finally:
            await http.aclose()


async def tp_move_library_items(
    source_library_id: int | str,
    to_library_id: int | str,
    item_ids: list[int],
) -> dict[str, Any]:
    """Move classic or native StructuredStrength templates without recreating them."""
    try:
        source_id = int(source_library_id)
        destination_id = int(to_library_id)
        ids = [int(x) for x in item_ids]
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "Library and item IDs must be numeric.")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return _error("VALIDATION_ERROR", "item_ids must be non-empty.")
    if source_id == destination_id:
        return {"verified": True, "moved": [], "no_op_item_ids": ids}

    async with TPClient() as client:
        user = await client._get_user_data()
        if not user or not user.get("personId"):
            return _error("AUTH_INVALID", "Could not resolve coach account.")
        owner = int(user["personId"])
        libraries, err = await _read_library_inventory(client)
        if err:
            return err
        if _owned_library(libraries, source_id, owner) is None or _owned_library(libraries, destination_id, owner) is None:
            return _error("FORBIDDEN_OR_NOT_FOUND", "Both libraries must be mutable coach-owned libraries.")

        http, headers, native_err = await _native_session(client)
        if native_err or http is None or headers is None:
            return native_err or _error("AUTH_INVALID", "Native library session unavailable.")
        moved: list[dict[str, Any]] = []
        try:
            for iid in ids:
                kind, source, resolve_err = await _resolve_library_item(
                    client, http, headers, source_id, iid
                )
                if resolve_err or source is None or kind is None:
                    # Idempotent retry support: if no longer in source but already
                    # exists with same ID in destination, treat it as verified no-op.
                    dest_kind, dest_item, _ = await _resolve_library_item(
                        client, http, headers, destination_id, iid
                    )
                    if dest_item is not None and dest_kind is not None:
                        moved.append({"item_id": iid, "kind": dest_kind, "verified": True, "already_moved": True})
                        continue
                    return resolve_err or _error("NOT_FOUND", f"Item {iid} not found.")

                if kind == "classic":
                    baseline = _classic_semantic(source, ignore_library=True)
                    payload = _classic_move_payload(source, destination_id)
                    try:
                        response = await client._request(
                            "PUT",
                            _CLASSIC_ITEM.format(library_id=destination_id, item_id=iid),
                            json=payload,
                            _retry_on_401=False,
                        )
                    except Exception:
                        response = None
                    source_after, source_err = await _read_classic_items(client, source_id)
                    dest_after, dest_err = await _read_classic_items(client, destination_id)
                    if source_err or dest_err:
                        return _error("AMBIGUOUS_WRITE", "Classic move readback failed; do not retry blindly.")
                    still_source = [x for x in source_after if _classic_item_id(x) == iid]
                    destination = [x for x in dest_after if _classic_item_id(x) == iid]
                    if still_source or len(destination) != 1:
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Classic move of item {iid} was not verified; do not retry blindly.",
                        )
                    if _classic_semantic(destination[0], ignore_library=True) != baseline:
                        return _error("PROVIDER_DRIFT", f"Classic move of item {iid} changed workout content.")
                    moved.append({"item_id": iid, "kind": kind, "verified": True})
                else:
                    baseline = _native_semantic(source)
                    payload = {
                        "id": source["id"],
                        "libraryId": destination_id,
                        "title": source["title"],
                        "workout": source["workout"],
                        "workoutLibraryItemType": source["workoutLibraryItemType"],
                    }
                    try:
                        response = await http.post(
                            STRENGTH_API_BASE + _NATIVE_SAVE,
                            json=payload,
                            headers=headers,
                        )
                    except httpx.RequestError:
                        response = None
                    source_after, source_err = await _read_native_items_http(http, headers, source_id)
                    dest_after, dest_err = await _read_native_items_http(http, headers, destination_id)
                    if source_err or dest_err:
                        return _error("AMBIGUOUS_WRITE", "Native move readback failed; do not retry blindly.")
                    still_source = [x for x in source_after if _native_item_id(x) == iid]
                    destination = [x for x in dest_after if _native_item_id(x) == iid]
                    if still_source or len(destination) != 1:
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Native move of item {iid} was not verified; do not retry blindly.",
                        )
                    if _native_semantic(destination[0]) != baseline:
                        return _error("PROVIDER_DRIFT", f"Native move of item {iid} changed prescribed structure.")
                    moved.append({"item_id": iid, "kind": kind, "verified": True})
            return {
                "verified": True,
                "source_library_id": source_id,
                "destination_library_id": destination_id,
                "moved": moved,
            }
        finally:
            await http.aclose()


async def tp_delete_library_items(
    library_id: int | str,
    item_ids: list[int],
) -> dict[str, Any]:
    """Delete exact classic or native StructuredStrength library items, with readback.

    This deletes reusable templates only, never athlete calendar workouts.
    """
    try:
        lid = int(library_id)
        ids = [int(x) for x in item_ids]
    except (TypeError, ValueError):
        return _error("VALIDATION_ERROR", "Library and item IDs must be numeric.")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return _error("VALIDATION_ERROR", "item_ids must be non-empty.")

    async with TPClient() as client:
        user = await client._get_user_data()
        if not user or not user.get("personId"):
            return _error("AUTH_INVALID", "Could not resolve coach account.")
        owner = int(user["personId"])
        libraries, err = await _read_library_inventory(client)
        if err:
            return err
        if _owned_library(libraries, lid, owner) is None:
            return _error("FORBIDDEN_OR_NOT_FOUND", "Library is not a mutable coach-owned library.")

        http, headers, native_err = await _native_session(client)
        if native_err or http is None or headers is None:
            return native_err or _error("AUTH_INVALID", "Native library session unavailable.")
        deleted: list[dict[str, Any]] = []
        try:
            for iid in ids:
                kind, source, resolve_err = await _resolve_library_item(client, http, headers, lid, iid)
                if resolve_err or source is None or kind is None:
                    # Deletion is convergent: absent item is already at target state.
                    if resolve_err and resolve_err.get("error_code") == "NOT_FOUND":
                        deleted.append({"item_id": iid, "verified": True, "already_absent": True})
                        continue
                    return resolve_err or _error("NOT_FOUND", f"Item {iid} not found.")

                if kind == "classic":
                    try:
                        response = await client._request(
                            "DELETE",
                            _CLASSIC_ITEM.format(library_id=lid, item_id=iid),
                            _retry_on_401=False,
                        )
                    except Exception:
                        response = None
                    after, rb_err = await _read_classic_items(client, lid)
                    if rb_err:
                        return _error("AMBIGUOUS_WRITE", "Classic delete readback failed; do not retry blindly.")
                    if any(_classic_item_id(x) == iid for x in after):
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Classic deletion of item {iid} was not verified; do not retry blindly.",
                        )
                else:
                    try:
                        response = await http.delete(
                            STRENGTH_API_BASE + _NATIVE_DELETE.format(item_id=iid),
                            headers=headers,
                        )
                    except httpx.RequestError:
                        response = None
                    after, rb_err = await _read_native_items_http(http, headers, lid)
                    if rb_err:
                        return _error("AMBIGUOUS_WRITE", "Native delete readback failed; do not retry blindly.")
                    if any(_native_item_id(x) == iid for x in after):
                        return _error(
                            "AMBIGUOUS_WRITE" if response is None else "READBACK_FAILED",
                            f"Native deletion of item {iid} was not verified; do not retry blindly.",
                        )
                deleted.append({"item_id": iid, "kind": kind, "verified": True})
            return {"verified": True, "library_id": lid, "deleted": deleted}
        finally:
            await http.aclose()
