"""Secure one-time PDF relay from coach-private lab note to cloud server.

No provider writes. URL scoped to explicit OpenAI signed file domain, sha256
and byte count pinned. Never outputs the signed URL. Removes signed URL from
the downloaded filename; saved under local 0700 state directory with 0600.
"""
import asyncio,hashlib,os,tempfile
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from tp_mcp.client import TPClient

OWNER=2116886
LAB=684484
NOTE_TITLE="[MCP TEST] IRONMAN INTERMEDIATE V3 PDF TEMP TRANSFER"
EXPECTED_SHA256="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
EXPECTED_BYTES=396936
DEST=Path("/home/ironman/.local/state/ironman-operator/intermediate-guide-v3.pdf")

async def main():
 async with TPClient() as tp:
  me=await tp._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER,"Wrong authenticated coach"
  p=await tp.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data.get("title")=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  assert p.data.get("isPublic") is False and p.data.get("workoutCount")==1
  r=await tp.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
  assert not r.is_error and isinstance(r.data,list),"lab notes unavailable"
  found=[n for n in r.data if n.get("title")==NOTE_TITLE]
  assert len(found)==1 and len(r.data)==2, "Missing unique signed transfer note"
  d=found[0].get("description","")
  assert d.startswith("SIGNED_READ_URI=") and "\nSHA256="+EXPECTED_SHA256 in d
  uri=d.split("\n",1)[0].split("=",1)[1]
  print("STAGE_VALIDATED_NOTE",len(uri),flush=True)
  u=urlsplit(uri)
  assert u.scheme=="https" and u.hostname in {"sdmntprpolandcentral.oaiusercontent.com","sdmntprdenmarkeast.oaiusercontent.com"}
  print("STAGE_HOST_VALIDATED",flush=True)
  assert len(uri)<1000 and u.username is None and u.password is None
  async with httpx.AsyncClient(follow_redirects=False,timeout=45) as client:
   response=await client.get(uri)
   print("STAGE_HTTP",response.status_code,"bytes",len(response.content),flush=True)
   response.raise_for_status()
   assert response.status_code==200 and len(response.content)==EXPECTED_BYTES
   data=response.content
  assert data[:8]==b"%PDF-1.7" or data.startswith(b"%PDF-"),"Not PDF"
  assert hashlib.sha256(data).hexdigest()==EXPECTED_SHA256,"SHA256 mismatch"
  DEST.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  fd,temp=tempfile.mkstemp(prefix=".guide-v3-",suffix=".pdf",dir=str(DEST.parent))
  try:
   os.fchmod(fd,0o600)
   with os.fdopen(fd,"wb") as f:
    f.write(data);f.flush();os.fsync(f.fileno())
   os.replace(temp,DEST)
  finally:
   if os.path.exists(temp):os.unlink(temp)
  print("TRANSFER_VERIFIED", "bytes",len(data),"sha256",EXPECTED_SHA256,
        "stored_private",True,"trainingpeaks_writes",0,flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Exception as exc:
  print("STAGE_FAIL",type(exc).__name__,flush=True)
  raise SystemExit(2)
