"""Guarded library B60 creation checks."""
from scripts.ironman_jobs.native_chasing_b60_publish import B,EXPECT,spec,TARGET_LIB
def test_scope():
    assert TARGET_LIB==3894341
    assert len(spec())==9
    assert EXPECT==["165","579","520","516","616","6","79","5312"]
    assert B[0][0]=="WarmUp"

