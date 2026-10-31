"""Read-only inventory of the live MCP runtime/process manager on ironman-tp-mcp."""
import json, os, subprocess
from pathlib import Path

def run(*a):
    p=subprocess.run(a,text=True,capture_output=True,timeout=10,check=False)
    return {"rc":p.returncode,"out":p.stdout[-6000:],"err":p.stderr[-2000:]}

def main():
    data={
      "hostname":os.uname().nodename,
      "pid":os.getpid(),
      "ppid":os.getppid(),
      "cwd":os.getcwd(),
      "proc_self_cgroup":Path("/proc/self/cgroup").read_text() if Path("/proc/self/cgroup").exists() else "",
      "ps":run("ps","-eo","pid,ppid,user,comm,args"),
      "systemd_user":run("systemctl","--user","list-units","--type=service","--all","--no-pager"),
      "systemd_system":run("systemctl","list-units","--type=service","--all","--no-pager"),
    }
    print(json.dumps(data,ensure_ascii=False))
if __name__=="__main__": main()
