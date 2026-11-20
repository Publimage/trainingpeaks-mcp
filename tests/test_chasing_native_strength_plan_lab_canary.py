from scripts.ironman_jobs import chasing_native_strength_plan_lab_canary as m

def test_scope():
 assert m.PLAN==684543 and m.NEW.startswith('[MCP TEST]')
