"""Synthetic provider objects only: preflight and postflight never mutate TrainingPeaks."""
from copy import deepcopy
import pytest

from scripts.ironman_jobs.ironman_plan_mutation_gates import (
    MutationStop, digest, preview_new_plan, readback_new_plan,
    preview_delete_plan_workout, verify_plan_workout_absent,
)

OWNER = 2116886


def old_plans():
    return [
        {'planId': 501, 'title': 'Existing beginner', 'isPublic': False, 'price': None},
        {'planId': 612, 'title': 'Existing intermediate', 'isPublic': False, 'price': None},
    ]


def create_change(rows=None):
    rows = old_plans() if rows is None else rows
    return {
        'kind': 'plan.create',
        'target': {'provider': 'trainingpeaks', 'owner_id': OWNER,
                   'container_kind': 'training_plan', 'container_id': None,
                   'resource_id': None},
        'payload': {'title': 'New private plan', 'week_count': 12},
        'before_sha256': digest(rows),
    }


def new_plan_detail():
    return {'planId': 9001, 'title': 'New private plan', 'weekCount': 12,
            'startDate': '2026-10-26T00:00:00', 'isPublic': False, 'price': 0}


def test_create_new_private_plan_preflight_and_external_readback():
    before = old_plans()
    request = create_change(before)
    preview = preview_new_plan(request, before, coach_id=OWNER)
    assert preview['state'] == 'CREATE_PREFLIGHT_ONLY'
    assert preview['provider_writes'] == 0
    verified = readback_new_plan(request, before,
                                 before+[{'planId':9001,'title':'New private plan','isPublic':False,'price':None}],
                                 new_plan_detail(), coach_id=OWNER)
    assert verified['state'] == 'PROVIDER_READBACK_MATCH'
    assert verified['plan_id'] == 9001
    assert verified['writer_authorized_by_this_module'] is False


def test_create_requires_fresh_inventory_and_exact_owner():
    before = old_plans()
    request = create_change(before)
    with pytest.raises(MutationStop, match='COACH_OWNER_MISMATCH'):
        preview_new_plan(request, before, coach_id=999)
    with pytest.raises(MutationStop, match='PLAN_INVENTORY_DRIFT'):
        preview_new_plan(request, before+[{'planId':700,'title':'Other added'}], coach_id=OWNER)


def test_create_never_overwrites_same_title_or_uses_old_provider_id():
    before = old_plans() + [{'planId':888,'title':'new PRIVATE plan'}]
    with pytest.raises(MutationStop, match='PLAN_TITLE_ALREADY_EXISTS'):
        preview_new_plan(create_change(before), before, coach_id=OWNER)
    forged = create_change()
    forged['target']['container_id'] = 689369
    with pytest.raises(MutationStop, match='CREATE_TARGET_INVALID'):
        preview_new_plan(forged, old_plans(), coach_id=OWNER)


@pytest.mark.parametrize('field,value,code', [
    ('isPublic', True, 'CREATE_PRIVACY_DRIFT'),
    ('price', 199, 'CREATE_PRIVACY_DRIFT'),
    ('weekCount', 2, 'CREATE_WEEKS_DRIFT'),
    ('planId', 501, 'CREATE_DETAIL_IDENTITY_DRIFT'),
])
def test_create_readback_must_match_identity_privacy_and_calendar(field, value, code):
    detail = new_plan_detail()
    detail[field] = value
    rows = old_plans()
    with pytest.raises(MutationStop, match=code):
        readback_new_plan(create_change(rows), rows,
                          rows + [{'planId':9001,'title':'New private plan','isPublic':False,'price':None}],
                          detail, coach_id=OWNER)


def test_create_does_not_accept_new_resource_if_other_plan_changed():
    rows=old_plans()
    changed=deepcopy(rows)
    changed[0]['title']='Unexpected edit'
    changed.append({'planId':9001,'title':'New private plan','isPublic':False,'price':None})
    with pytest.raises(MutationStop, match='UNRELATED_PLAN_CHANGED'):
        readback_new_plan(create_change(rows), rows, changed,
                          new_plan_detail(), coach_id=OWNER)


def plan_detail():
    return {'planId':501, 'title':'Existing beginner',
            'isPublic':False,'price':None,'weekCount':8,
            'startDate':'2026-10-26T00:00:00'}


def plan_workouts():
    return [
        {'workoutId':301,'title':'Easy swim', 'week':1, 'day':1, 'workoutDay':'2026-10-26',
         'workoutTypeValueId':1,'description':'easy','totalTimePlanned':1,
         'structure':{'steps':[{'duration':600}]}},
        {'workoutId':302,'title':'Run threshold','week':1, 'day':2, 'workoutDay':'2026-10-27',
         'workoutTypeValueId':2,'description':'4x5','totalTimePlanned':1.2,
         'structure':{'steps':[{'duration':1200}]}},
        {'workoutId':303,'title':'Long bike','week':1, 'day':3, 'workoutDay':'2026-10-28',
         'workoutTypeValueId':3,'description':'easy','totalTimePlanned':2.5,
         'structure':None},
    ]


def notes():
    return [{'id':22,'title':'Coach notes','noteDate':'2026-10-26',
             'attachments':[{'id':111,'fileName':'guide.pdf','contentLength':4500}]}]


def delete_change():
    return {'kind':'plan.workout.delete',
            'target':{'provider':'trainingpeaks','owner_id':OWNER,
                      'container_kind':'training_plan',
                      'container_id':501,'resource_id':302},
            'payload':{'expected_title':'Run threshold', 'week':1, 'weekday':2},
            'before_sha256':digest({k:v for k,v in plan_workouts()[1].items()
                                    if k!='workoutDay'})}


def preview_delete():
    return preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                      owned_plans=old_plans(),plan=plan_detail(),
                                      workouts=plan_workouts(),notes=notes())


def test_delete_preview_and_external_readback_only_target_absent():
    preview=preview_delete()
    assert preview['state']=='DELETE_PREFLIGHT_ONLY'
    assert preview['provider_writes']==0
    assert preview['publication_enabled'] is False
    before=plan_workouts()
    after=[before[0],before[2]]
    verified=verify_plan_workout_absent(preview, plan=plan_detail(),
                                        workouts=after, notes=notes())
    assert verified['absent_workout_id']==302
    assert verified['unrelated_workouts_preserved']==2
    assert verified['native_notes_preserved']==1
    assert verified['writer_authorized_by_this_module'] is False


def test_delete_denies_cross_plan_or_athlete_calendar_target():
    change=delete_change()
    change['target']['container_id']=612
    with pytest.raises(MutationStop,match='DELETE_PLAN_ID_MISMATCH'):
        preview_delete_plan_workout(change,coach_id=OWNER,owned_plans=old_plans(),
                                    plan=plan_detail(),workouts=plan_workouts(),notes=notes())
    change=delete_change()
    change['target']['container_kind']='athlete_calendar'
    with pytest.raises(MutationStop,match='DELETE_TARGET_INVALID'):
        preview_delete_plan_workout(change,coach_id=OWNER,owned_plans=old_plans(),
                                    plan=plan_detail(),workouts=plan_workouts(),notes=notes())


def test_delete_denies_unowned_or_public_commercial_plan():
    with pytest.raises(MutationStop,match='PLAN_NOT_OWNED_BY_COACH'):
        preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                    owned_plans=old_plans()[1:], plan=plan_detail(),
                                    workouts=plan_workouts(),notes=notes())
    public=plan_detail()
    public['isPublic']=True
    owned=old_plans()
    owned[0]['isPublic']=True
    with pytest.raises(MutationStop,match='DELETE_PLAN_PUBLIC_OR_PRICED'):
        preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                    owned_plans=owned, plan=public,
                                    workouts=plan_workouts(),notes=notes())


def test_delete_denies_changed_workout_before_and_duplicate_provider_identity():
    changed=plan_workouts()
    changed[1]['description']='changed'
    with pytest.raises(MutationStop,match='PLAN_WORKOUT_PREIMAGE_DRIFT'):
        preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                    owned_plans=old_plans(),plan=plan_detail(),
                                    workouts=changed,notes=notes())
    duplicated=plan_workouts()
    duplicated.append(dict(duplicated[1]))
    with pytest.raises(MutationStop,match='PLAN_WORKOUT_ID_UNVERIFIABLE'):
        preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                    owned_plans=old_plans(),plan=plan_detail(),
                                    workouts=duplicated,notes=notes())


def test_delete_postflight_blocks_any_unrelated_workout_note_or_metadata_change():
    snapshot=preview_delete()
    remaining=[plan_workouts()[0],plan_workouts()[2]]
    extra=deepcopy(remaining)
    extra[0]['description']='unrelated change'
    with pytest.raises(MutationStop,match='OTHER_WORKOUTS_CHANGED'):
        verify_plan_workout_absent(snapshot, plan=plan_detail(),workouts=extra,notes=notes())
    other_notes=notes()
    other_notes[0]['title']='changed note'
    with pytest.raises(MutationStop,match='NATIVE_NOTES_CHANGED'):
        verify_plan_workout_absent(snapshot,plan=plan_detail(),workouts=remaining,notes=other_notes)
    other_plan=plan_detail()
    other_plan['weekCount']=12
    with pytest.raises(MutationStop,match='PLAN_METADATA_CHANGED'):
        verify_plan_workout_absent(snapshot,plan=other_plan,workouts=remaining,notes=notes())
    with pytest.raises(MutationStop,match='TARGET_STILL_PRESENT'):
        verify_plan_workout_absent(snapshot,plan=plan_detail(),workouts=plan_workouts(),notes=notes())


def test_unverified_mutation_module_exposes_no_network_writers():
    import scripts.ironman_jobs.ironman_plan_mutation_gates as module
    assert not hasattr(module,'delete_workout')
    assert not hasattr(module,'create_plan')
    assert not hasattr(module,'post_to_provider')


def test_delete_blocks_disagreement_between_plan_list_and_detail():
    inconsistent=plan_detail()
    inconsistent['isPublic']=True
    with pytest.raises(MutationStop,match='PLAN_INVENTORY_DETAIL_MISMATCH'):
        preview_delete_plan_workout(delete_change(),coach_id=OWNER,
                                    owned_plans=old_plans(), plan=inconsistent,
                                    workouts=plan_workouts(),notes=notes())


def test_plan_create_blocks_private_detail_if_inventory_row_is_public():
    before=old_plans()
    row={'planId':9001,'title':'New private plan','isPublic':True,'price':0}
    with pytest.raises(MutationStop,match='CREATE_INVENTORY_PRIVACY_DRIFT'):
        readback_new_plan(create_change(before),before,before+[row],
                          new_plan_detail(),coach_id=OWNER)


def test_training_plan_create_never_asks_for_calendar_dates():
    rows = old_plans()
    change = create_change(rows)
    assert 'start_date' not in change['payload']
    assert preview_new_plan(change, rows, coach_id=OWNER)['relative_weeks'] == 12
    legacy = deepcopy(change)
    legacy['payload']['start_date'] = '2026-10-26'
    with pytest.raises(MutationStop, match='CREATE_PAYLOAD_INVALID'):
        preview_new_plan(legacy, rows, coach_id=OWNER)
    detail = new_plan_detail()
    detail['startDate'] = None
    current = rows + [{'planId':9001,'title':'New private plan','isPublic':False,'price':None}]
    assert readback_new_plan(change, rows, current, detail,
                             coach_id=OWNER)['relative_weeks'] == 12
    detail['startDate'] = '2040-12-17T00:00:00'
    assert readback_new_plan(change, rows, current, detail,
                             coach_id=OWNER)['state'] == 'PROVIDER_READBACK_MATCH'


def test_delete_plan_workout_uses_only_relative_week_and_weekday():
    base = preview_delete()
    assert base['relative_week'] == 1
    assert base['relative_weekday'] == 2
    change = delete_change()
    change['payload']['weekday'] = 4
    with pytest.raises(MutationStop, match='PLAN_WORKOUT_RELATIVE_SLOT_MISMATCH'):
        preview_delete_plan_workout(change,coach_id=OWNER,
            owned_plans=old_plans(),plan=plan_detail(),workouts=plan_workouts(),notes=notes())
    bad = delete_change()
    bad['payload']['expected_date'] = '2026-10-27'
    with pytest.raises(MutationStop, match='DELETE_PAYLOAD_INVALID'):
        preview_delete_plan_workout(bad,coach_id=OWNER,
            owned_plans=old_plans(),plan=plan_detail(),workouts=plan_workouts(),notes=notes())


def test_provider_transport_date_may_shift_without_shifting_relative_slots():
    snapshot = preview_delete()
    after = deepcopy([plan_workouts()[0], plan_workouts()[2]])
    after[0]['workoutDay'] = '2038-02-15'
    after[1]['workoutDay'] = '2038-02-17'
    changed_notes = deepcopy(notes())
    changed_notes[0]['noteDate'] = '2038-02-15'
    changed_plan = deepcopy(plan_detail())
    changed_plan['startDate'] = '2038-02-15'
    verified = verify_plan_workout_absent(
        snapshot,plan=changed_plan,workouts=after,notes=changed_notes)
    assert verified['state'] == 'PROVIDER_POSTFLIGHT_MATCH'
    changed_slot = deepcopy(after)
    changed_slot[0]['day'] = 3
    with pytest.raises(MutationStop, match='OTHER_WORKOUTS_CHANGED'):
        verify_plan_workout_absent(
            snapshot,plan=changed_plan,workouts=changed_slot,notes=changed_notes)
