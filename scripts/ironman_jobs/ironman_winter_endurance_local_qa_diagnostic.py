"""READ ONLY local diagnostic for existing approved Winter endurance pytest, no provider connections."""
import json
import subprocess
def main():
    res=subprocess.run(["python","-m","pytest","-xq","tests/test_ironman_winter_endurance_native_publish.py"],
        capture_output=True,text=True,timeout=55,check=False)
    print(json.dumps({"stage":"WINTER_ENDURANCE_TEST_DIAGNOSTIC","exit":res.returncode,
       "stdout":res.stdout[-11000:],"stderr":res.stderr[-4500:],"provider_writes":0},
       ensure_ascii=False),flush=True)
    return 0
if __name__=="__main__":raise SystemExit(main())
