"""Read-only inventory for Spaces uploader credential file; never reads contents."""
import json, os
from pathlib import Path

PATHS=[
 Path("/home/ironman/.config/ironman/spaces-uploader.json"),
 Path("/root/.config/ironman/spaces-uploader.json"),
]
def meta(p):
    if not p.exists():
        return {"path":str(p),"exists":False}
    st=p.stat()
    return {"path":str(p),"exists":True,"is_file":p.is_file(),"mode":oct(st.st_mode & 0o777),"uid":st.st_uid,"gid":st.st_gid,"size":st.st_size}
def main():
    print("SPACES_CONFIG_PATH_INVENTORY")
    print(json.dumps({"euid":os.geteuid(),"egid":os.getegid(),"paths":[meta(p) for p in PATHS]},sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
