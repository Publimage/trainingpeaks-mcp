"""Offline QA for native A60: 8 working exercises and separate WarmUp."""
from scripts.ironman_jobs.native_chasing_a60_lab_save import (
    LIB,ITEM,SOURCE,IDS,TITLE,INFO,blocks_to_builder
)

def test_scope_and_counts():
    assert LIB==3890637 and ITEM=="330612"
    assert TITLE.startswith("[MCP TEST]")
    assert len(SOURCE)==9 and len(IDS)==8
    assert SOURCE[0][0]=="WarmUp"
    assert "EXTRA" in INFO and "60'" in INFO

def test_provider_block_validation():
    blocks=blocks_to_builder()
    assert len(blocks)==9
    assert len(blocks[0]["exercises"])==3
    assert [b["exercises"][0]["id"] for b in blocks[1:]]==IDS
