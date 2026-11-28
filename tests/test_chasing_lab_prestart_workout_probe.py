from scripts.ironman_jobs import chasing_lab_prestart_workout_probe as x

def test_lab_only():
 assert x.PLAN==684484 and x.ID==3995256662
 assert x.BEFORE_START=="2027-07-04" and x.START_DATE=="2027-07-05"
