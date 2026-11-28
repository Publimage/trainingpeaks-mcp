from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_strength_move_recovery_readonly.py"
def test_recovery_reader_is_read_only():
 s=P.read_text();ast.parse(s)
 assert "SOURCE=3890637" in s and "TEMP=3902999" in s and "ITEM=330612" in s
 for bad in ("http.post(","http.put(","http.delete(","c._request("):
  assert bad not in s
 assert '"provider_writes":0' in s
