from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/stage_intermediate_pdf_secure.py"
def test_secure_source():
 t=P.read_text();ast.parse(t)
 assert "OWNER=2116886" in t and "LAB=684484" in t and "396936" in t
 assert "sdmntprpolandcentral.oaiusercontent.com" in t
 assert "EXPECTED_SHA256" in t and "os.fchmod(fd,0o600)" in t
 assert 'response=await client.get(uri)' in t
 assert '"PUT"' not in t and '"POST"' not in t and '"DELETE"' not in t
