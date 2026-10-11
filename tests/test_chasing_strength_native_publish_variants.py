"""Offline coverage QA for all Chasing native Strength variants."""
from scripts.ironman_jobs.chasing_strength_native_publish_common import blocks,verify,KNOWN,DEST
from scripts.ironman_jobs.chasing_strength_specs import SPECS
def test_variant_consistency():
    assert DEST==3894341 and len(SPECS)==4 and len(KNOWN)==6
    for key,s in SPECS.items():
        b=blocks(key)
        assert b[0]["type"]=="WarmUp"
        assert len(b)==len(s["ex"])+1
        assert len(set(z[0] for z in s["ex"]))==len(s["ex"])
def test_functional_groups():
    assert len(SPECS["M60"]["ex"])==7
    assert len(SPECS["D40"]["ex"])==6
    assert len(SPECS["M45"]["ex"])==6
    assert len(SPECS["M30"]["ex"])==5
