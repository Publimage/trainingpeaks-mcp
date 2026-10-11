from scripts.ironman_jobs.tp_frontend_strength_lib_route_audit import trusted,snippets

def test_allowlisted_hosts_only():
    assert trusted("https://app.trainingpeaks.com/a.js")
    assert trusted("https://cdn.trainingpeaks.com/b.js")
    assert not trusted("https://evil.example.com/trainingpeaks.com.js")

def test_public_snippet_search():
    s="let x={url:'/exerciselibrary/v1/libraries/55/items'}; function StrengthWorkout(){}"
    x=snippets(s)
    assert any("exerciselibrary" in y for y in x)
