from pathlib import Path
import ast


def test_beginner_strength_writer_source_is_bounded():
    text = Path("src/tp_mcp/tools/strength.py").read_text()
    ast.parse(text)
    assert "async def tp_batch_add_beginner_strength" in text
    assert "plan_id = 679801" in text
    assert "BEGINNER_STRENGTH_SOURCE_IDS" in text
    assert "len(items) <= 8" in text
    assert 'plan.get("isPublic") is not True' in text
    assert 'plan.get("ownerPersonId") != 2116886' in text
    assert 'workoutTypeValueId") != 9' in text
    assert 'workouts/save' in text
    assert "videos_verified" in text
    assert "tp_batch_add_beginner_strength" not in text.split("async def tp_batch_add_intermediate_strength", 1)[0]


def test_beginner_strength_writer_catalog_registration():
    init = Path("src/tp_mcp/tools/__init__.py").read_text()
    server = Path("src/tp_mcp/server.py").read_text()
    assert "tp_batch_add_beginner_strength" in init
    assert 'name="tp_batch_add_beginner_strength"' in server
    assert '@_handler("tp_batch_add_beginner_strength")' in server
    assert '"tp_batch_add_beginner_strength"' in server
