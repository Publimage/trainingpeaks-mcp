from scripts.ironman_jobs.chasing_strength_final_naming import TITLES,LIB,OLD_LIB,NEW_LIB

def test_final_names_only_and_unique():
    assert LIB==3894341 and OLD_LIB!=NEW_LIB
    assert len(TITLES)==7 and len({b for a,b in TITLES.values()})==7
    assert all(a.startswith("[DRAFT]") and not b.startswith("[DRAFT]") for a,b in TITLES.values())
