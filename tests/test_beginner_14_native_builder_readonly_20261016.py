"""Static safety and scope tests for Beginner native audit."""
import ast
from pathlib import Path
P=Path("scripts/ironman_jobs/beginner_14_native_builder_readonly_20261016.py")
def test_readonly_beginner_audit_scoped():
    source=P.read_text(encoding="utf-8")
    tree=ast.parse(source)
    assert "P=679801" in source
    assert "OWNER=2116886" in source
    assert '"provider_writes":0' in source
    assert "isPublic" in source and "254" in source
    assert "polyline" in source and "targets" in source
    assert "BUILDER_TIME_MISMATCH" in source and "EMPTY_ACTIVE_TARGET" in source
    assert "RELATIVE_WEEK_DRIFT" in source
    assert "client.get(" in source
    for method in ('client.post(', 'client.put(', 'client.patch(', 'client.delete(', 'client._request('):
        assert method not in source
    expected=next(ast.literal_eval(node.value) for node in tree.body
      if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="EXPECTED" for t in node.targets))
    assert len(expected)==14
    assert len({z[1] for z in expected})==14
    assert {z[0] for z in expected}=={13,14,15,17,18,19,21}
    assert sum(z[2]==3 for z in expected)==7
    assert sum(z[2]==2 for z in expected)==7
