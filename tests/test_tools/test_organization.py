import pytest
from unittest.mock import AsyncMock, patch
from tp_mcp.client.http import APIResponse
from tp_mcp.tools.organization import (
    tp_list_plan_folders, tp_create_plan_folder, tp_rename_plan_folder,
    tp_move_training_plans, tp_rename_training_plan,
    tp_copy_training_plan, tp_delete_training_plan,
    tp_rename_library, tp_move_library_items, tp_delete_library_items,
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


@pytest.mark.asyncio
async def test_copy_training_plan_native_command_status_and_readback():
    import tp_mcp.tools.organization as org
    source_row={"planId":1,"title":"Source","weekCount":2,"workoutCount":3,"isPublic":False,"price":0}
    source_detail={**source_row,"dayCount":14,"description":"x"}
    copied_detail={**source_detail,"planId":99,"title":"Copy"}
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[source_row]),             # inventory before
        APIResponse(success=True,data=source_detail),           # source detail
        APIResponse(success=True,data={"status":1}),             # copy status
        APIResponse(success=True,data={"status":2}),             # copy status
        APIResponse(success=True,data=copied_detail),            # copied detail
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={"planId":99}))
    p=_patch(c)
    with patch.object(org.asyncio,"sleep",AsyncMock()):
        try:r=await tp_copy_training_plan(1,"Copy")
        finally:p.stop()
    assert r["verified"] and r["plan_id"]==99
    assert r["copy_status_seen"]==[1,2]
    assert c._request.call_args.args[:2]==("POST","/plans/v1/commands/copyplan")
    assert c._request.call_args.kwargs["_retry_on_401"] is False
    assert c._request.call_args.kwargs["json"]["planId"]==1
    assert c._request.call_args.kwargs["json"]["title"]=="Copy"
    assert c._request.call_args.kwargs["json"]["planData"]==source_detail


@pytest.mark.asyncio
async def test_delete_training_plan_private_unpriced_uses_inventory_readback():
    before={"planId":1,"title":"Disposable","weekCount":1,"workoutCount":0,"isPublic":False,"price":0}
    c=AsyncMock()
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[before]),
        APIResponse(success=True,data=[]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_delete_training_plan(1,"Disposable")
    finally:p.stop()
    assert r["verified"] and r["deleted"] is True
    assert c._request.call_args.args[:2]==("DELETE","/plans/v1/plans/1")
    assert c._request.call_args.kwargs["_retry_on_401"] is False


@pytest.mark.asyncio
async def test_delete_training_plan_blocks_public_plan_without_mutation():
    before={"planId":1,"title":"Commercial","isPublic":True,"price":179.0}
    c=AsyncMock()
    c.get=AsyncMock(return_value=APIResponse(success=True,data=[before]))
    c._request=AsyncMock()
    p=_patch(c)
    try:r=await tp_delete_training_plan(1,"Commercial")
    finally:p.stop()
    assert r["isError"] and r["error_code"]=="FORBIDDEN"
    c._request.assert_not_called()


@pytest.mark.asyncio
async def test_rename_library_uses_name_route_and_readback():
    c=AsyncMock()
    c._get_user_data=AsyncMock(return_value={"personId":2116886})
    c.get=AsyncMock(side_effect=[
        APIResponse(success=True,data=[{"exerciseLibraryId":10,"libraryName":"Old","ownerId":2116886,"isDefaultContent":False}]),
        APIResponse(success=True,data=[{"exerciseLibraryId":10,"libraryName":"New","ownerId":2116886,"isDefaultContent":False}]),
    ])
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    p=_patch(c)
    try:r=await tp_rename_library(10,"New")
    finally:p.stop()
    assert r["verified"] and r["name"]=="New"
    assert c._request.call_args.args[:2]==("PUT","/exerciselibrary/v1/libraries/10/name")
    assert c._request.call_args.kwargs["json"]=={"value":"New"}
    assert c._request.call_args.kwargs["_retry_on_401"] is False


@pytest.mark.asyncio
async def test_classic_move_library_item_preserves_same_id_and_content():
    import tp_mcp.tools.organization as org
    c=AsyncMock()
    c._get_user_data=AsyncMock(return_value={"personId":2116886})
    c.get=AsyncMock(return_value=APIResponse(success=True,data=[
        {"exerciseLibraryId":1,"libraryName":"A","ownerId":2116886,"isDefaultContent":False},
        {"exerciseLibraryId":2,"libraryName":"B","ownerId":2116886,"isDefaultContent":False},
    ]))
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    fake_http=AsyncMock()
    fake_http.aclose=AsyncMock()
    source={"exerciseLibraryItemId":101,"exerciseLibraryId":1,"itemName":"Tempo","structure":{"structure":[{"type":"step"}]}}
    destination={**source,"exerciseLibraryId":2}
    p=_patch(c)
    with patch.object(org,"_native_session",AsyncMock(return_value=(fake_http,{"h":"x"},None))),          patch.object(org,"_read_classic_items",AsyncMock(side_effect=[
             ([source],None),   # resolve source
             ([],None),         # source readback after move
             ([destination],None), # destination readback
         ])),          patch.object(org,"_read_native_items_http",AsyncMock(return_value=([],None))):
        try:r=await tp_move_library_items(1,2,[101])
        finally:p.stop()
    assert r["verified"]
    assert r["moved"]==[{"item_id":101,"kind":"classic","verified":True}]
    assert c._request.call_args.args[:2]==("PUT","/exerciselibrary/v1/libraries/2/items/101")
    assert c._request.call_args.kwargs["_retry_on_401"] is False


@pytest.mark.asyncio
async def test_classic_delete_library_item_is_convergent_and_read_back():
    import tp_mcp.tools.organization as org
    c=AsyncMock()
    c._get_user_data=AsyncMock(return_value={"personId":2116886})
    c.get=AsyncMock(return_value=APIResponse(success=True,data=[
        {"exerciseLibraryId":1,"libraryName":"A","ownerId":2116886,"isDefaultContent":False}
    ]))
    c._request=AsyncMock(return_value=APIResponse(success=True,data={}))
    fake_http=AsyncMock(); fake_http.aclose=AsyncMock()
    source={"exerciseLibraryItemId":101,"exerciseLibraryId":1,"itemName":"Tempo"}
    p=_patch(c)
    with patch.object(org,"_native_session",AsyncMock(return_value=(fake_http,{"h":"x"},None))),          patch.object(org,"_read_classic_items",AsyncMock(side_effect=[
             ([source],None),([],None),
         ])),          patch.object(org,"_read_native_items_http",AsyncMock(return_value=([],None))):
        try:r=await tp_delete_library_items(1,[101])
        finally:p.stop()
    assert r["verified"]
    assert r["deleted"][0]["item_id"]==101
    assert c._request.call_args.args[:2]==("DELETE","/exerciselibrary/v1/libraries/1/items/101")
    assert c._request.call_args.kwargs["_retry_on_401"] is False


def test_native_semantic_ignores_runtime_metadata_but_keeps_prescriptions():
    from tp_mcp.tools.organization import _native_semantic
    base={
        "id":"330612","libraryId":1,"title":"Strength",
        "workoutLibraryItemType":"ActivityWorkoutTemplate",
        "workout":{"workoutType":"StructuredStrength","instructions":"x",
                   "lastUpdatedAt":"A",
                   "blocks":[{"prescriptions":[{"sets":[1]}]}]},
    }
    moved={
        **base,"libraryId":2,
        "workout":{**base["workout"],"lastUpdatedAt":"B"},
    }
    assert _native_semantic(base)==_native_semantic(moved)
