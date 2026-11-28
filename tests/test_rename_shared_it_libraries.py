from scripts.ironman_jobs.rename_shared_it_libraries import NAMES,OWNER
def test_library_rename_scope():
 assert OWNER==2116886
 assert len(NAMES)==5
 assert set(NAMES)=={3891872,3892601,3892602,3891875,3892900}
 assert all(old!=new and new.startswith("ALBERTO FAZI ENDURANCE | ") and new.endswith(" | IT") for old,new in NAMES.values())
 assert len({n for _,n in NAMES.values()})==5
