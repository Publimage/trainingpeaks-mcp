"""Read-only inventory for Spaces uploader credential file; never reads contents."""
import json, os
from pathlib import Path

TARGET=Path("/home/ironman/.config/ironman/spaces-uploader.json")
PARENT=TARGET.parent

def safe_meta(p):
    try:
        st=p.stat()
        return {"path":str(p),"exists":True,"is_file":p.is_file(),"is_dir":p.is_dir(),"mode":oct(st.st_mode & 0o777),"uid":st.st_uid,"gid":st.st_gid,"size":st.st_size}
    except FileNotFoundError:
        return {"path":str(p),"exists":False}
    except PermissionError:
        return {"path":str(p),"exists":"PERMISSION_DENIED"}

def main():
    print("SPACES_CONFIG_PATH_INVENTORY")
    print(json.dumps({"euid":os.geteuid(),"egid":os.getegid(),"parent":safe_meta(PARENT),"target":safe_meta(TARGET)},sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(main())
