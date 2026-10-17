import pytest
from unittest.mock import AsyncMock, patch
from tp_mcp.client.models import APIResponse
from tp_mcp.tools.organization import (
    tp_list_plan_folders, tp_create_plan_folder, tp_rename_plan_folder,
    tp_move_training_plans, tp_rename_training_plan,
)

def _patch(client):
    p=patch("tp_mcp.tools.organization.TPClient")
    cls=p.start()
    cls.return_value.__aenter__.return_value=client
    return p

@pytest.mark.asyncio
async def test_list_plan_folders_includes_virtual_my_plans():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"folderId":"uuid-1","folderName":"Test","planIds":[1]}]),
        APIResponse(success=True,data=[{"planId":1,"title":"A"},{"planId":2,"title":"B"}]),
    ])
    p=_patch(c)
    try:r=await tp_list_plan_folders()
    finally:p.stop()
    assert r["folders"][0]["folder_id"]=="uuid-1"
    assert r["my_plans"]["plan_ids"]==[2]

@pytest.mark.asyncio
async def test_create_folder_idempotent_without_post():
    c=AsyncMock()
    c.get=AsyncMock(return_value=APIResponse(success=True,data=[
        {"folderId":"u","folderName":"Archive","planIds":[]}
    ]))
    c._request=AsyncMock()
    p=_patch(c)
    try:r=await tp_create_plan_folder("Archive")
    finally:p.stop()
    assert r["verified"] and r["created"] is False
    c._request.assert_not_called()

@pytest.mark.asyncio
async def test_create_folder_post_once_then_readback():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[]),
        APIResponse(success=True,data=[{"folderId":"u","folderName":"Archive","planIds":[]}]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_create_plan_folder("Archive")
    finally:p.stop()
    assert r["verified"] and r["folder"]["folder_id"]=="u"
    assert c._request.await_count==1
    assert c._request.call_args.kwargs["_retry_on_401"] is False

@pytest.mark.asyncio
async def test_rename_folder_readback():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"folderId":"u","folderName":"Old","planIds":[]}]),
        APIResponse(success=True,data=[{"folderId":"u","folderName":"New","planIds":[]}]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_rename_plan_folder("u","New")
    finally:p.stop()
    assert r["verified"] and r["old_name"]=="Old"
    assert c._request.call_args.args[:2]==("PUT","/planfolder/v1/folder/u/name")

@pytest.mark.asyncio
async def test_assign_unfiled_plan_to_custom_folder():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"planId":1,"title":"A"}]),
        APIResponse(success=True,data=[{"folderId":"u","folderName":"Archive","planIds":[]}]),
        APIResponse(success=True,data=[{"folderId":"u","folderName":"Archive","planIds":[1]}]),
        APIResponse(success=True,data=[{"folderId":"u","folderName":"Archive","planIds":[1]}]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_move_training_plans([1],"u")
    finally:p.stop()
    assert r["verified"]
    assert c._request.call_args.args[:2]==("POST","/planfolder/v1/command/assignplanstofolder")
    assert c._request.call_args.kwargs["json"]=={"folderId":"u","planIds":[1]}

@pytest.mark.asyncio
async def test_move_between_custom_folders():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"planId":1,"title":"A"}]),
        APIResponse(success=True,data=[
            {"folderId":"a","folderName":"A","planIds":[1]},
            {"folderId":"b","folderName":"B","planIds":[]},
        ]),
        APIResponse(success=True,data=[
            {"folderId":"a","folderName":"A","planIds":[]},
            {"folderId":"b","folderName":"B","planIds":[1]},
        ]),
        APIResponse(success=True,data=[
            {"folderId":"a","folderName":"A","planIds":[]},
            {"folderId":"b","folderName":"B","planIds":[1]},
        ]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_move_training_plans([1],"b")
    finally:p.stop()
    assert r["verified"]
    assert c._request.call_args.kwargs["json"]=={"fromFolder":"a","toFolder":"b","planIds":[1]}

@pytest.mark.asyncio
async def test_move_to_my_plans_uses_remove_command():
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"planId":1,"title":"A"}]),
        APIResponse(success=True,data=[{"folderId":"a","folderName":"A","planIds":[1]}]),
        APIResponse(success=True,data=[{"folderId":"a","folderName":"A","planIds":[]}]),
        APIResponse(success=True,data=[{"folderId":"a","folderName":"A","planIds":[]}]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_move_training_plans([1],"my_plans")
    finally:p.stop()
    assert r["verified"]
    assert c._request.call_args.args[:2]==("POST","/planfolder/v1/command/removeplansfromfolder")

@pytest.mark.asyncio
async def test_plan_rename_changes_title_only_and_reads_back():
    before={"planId":1,"title":"Old","workoutCount":5,"isPublic":False}
    after={**before,"title":"New"}
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[APIResponse(success=True,data=before),APIResponse(success=True,data=after)])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_rename_training_plan(1,"New")
    finally:p.stop()
    assert r["verified"]
    assert c._request.call_args.kwargs["json"]=={"planId":1,"title":"New"}
    assert c._request.call_args.kwargs["_retry_on_401"] is False
