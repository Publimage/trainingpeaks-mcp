"""Offline diagnostic runner for organization tests. No provider access."""
from __future__ import annotations
import subprocess,sys

cmd=[sys.executable,"-m","pytest","-q","tests/test_tools/test_organization.py"]
p=subprocess.run(cmd,text=True,capture_output=True)
print("ORGANIZATION_PYTEST_EXIT",p.returncode,flush=True)
if p.stdout: print("STDOUT\n"+p.stdout[-12000:],flush=True)
if p.stderr: print("STDERR\n"+p.stderr[-12000:],flush=True)
print("provider_writes=0",flush=True)
raise SystemExit(p.returncode)
