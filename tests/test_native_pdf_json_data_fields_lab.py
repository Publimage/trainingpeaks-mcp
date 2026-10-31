from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_pdf_json_data_fields_lab.py"
def test_invalid_field_probe():
 s=P.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s and "OWNER=2116886" in s
 assert "684602" not in s and 'INVALID="not%%%valid%%%base64!!!"' in s
 assert "assert await read()==baseline" in s
 assert "if res.status_code!=400:" in s
