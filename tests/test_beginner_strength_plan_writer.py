from pathlib import Path
import ast


def test_beginner_strength_plan_tools_are_bounded():
    text = Path("src/tp_mcp/tools/beginner_strength_plan.py").read_text()
    ast.parse(text)
    assert "PLAN_ID = 679801" in text
    assert "OWNER_ID = 2116886" in text
    assert "SOURCE_IDS" in text
    assert "async def tp_batch_add_beginner_strength" in text
    assert "async def tp_batch_delete_beginner_classic_strength" in text
    assert "not 1 <= len(items) <= 8" in text
    assert 'plan.get("isPublic") is True' in text
    assert 'workouts/save' in text
    assert '_retry_on_401=False' in text
    assert "NATIVE_TWIN_NOT_EXACT" in text


def test_beginner_strength_tools_catalog_registration():
    init = Path("src/tp_mcp/tools/__init__.py").read_text()
    server = Path("src/tp_mcp/server.py").read_text()
    for name in (
        "tp_batch_add_beginner_strength",
        "tp_batch_delete_beginner_classic_strength",
    ):
        assert name in init
        assert f'name="{name}"' in server
        assert f'@_handler("{name}")' in server
