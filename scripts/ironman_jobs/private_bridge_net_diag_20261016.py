"""Read-only diagnosis of the private bridge listener and host firewall."""
from __future__ import annotations
import json, subprocess

def run(*argv):
    p=subprocess.run(argv,text=True,capture_output=True,timeout=15,check=False)
    return {"code":p.returncode,"out":p.stdout.strip(),"err":p.stderr.strip()}

def main():
    ss=run("ss","-ltnp")
    ufw=run("sudo","-n","ufw","status","numbered")
    ip=run("ip","-4","addr","show")
    print("PRIVATE_BRIDGE_NET_DIAG")
    print(json.dumps({"ss":ss,"ufw":ufw,"ip":ip,"trainingpeaks_writes":0}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
