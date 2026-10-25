"""Read-only inspect of the live TrainingPeaks MCP systemd unit and restart permissions."""
import json, subprocess
def run(*a):
 p=subprocess.run(a,text=True,capture_output=True,timeout=10,check=False)
 return {"rc":p.returncode,"out":p.stdout[-12000:],"err":p.stderr[-4000:]}
print(json.dumps({
 "unit":run("systemctl","cat","ironman-trainingpeaks-tunnel.service"),
 "status":run("systemctl","status","ironman-trainingpeaks-tunnel.service","--no-pager"),
 "sudo_list":run("sudo","-n","-l"),
},ensure_ascii=False))
