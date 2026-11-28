"""Fast offline tests for the reviewed, reusable own-comment cleanup."""
import pytest

from scripts.ironman_jobs.reviewed_workout_comment_cleanup import (
    MARKER,
    OWNER,
    SafeStop,
    choose_comment,
    read_manifest,
    stable_fields,
)


def workout(owner=OWNER, has_comment=True, video=True, comment_body=None):
    url = "https://youtu.be/o0ffl059C1Q"
    d = "OBIETTIVO\nnuoto\nPugni chiusi: esercizio\nVideo:\n" + url + "\nAltra istruzione"
    if not video:
        d = d.replace("Video:\n" + url, "senza video")
    comments = [{
        "id": 322550499,
        "workoutId": 4081853605,
        "commenterPersonId": owner,
        "comment": comment_body or (MARKER + "\nPugni chiusi — " + url),
    }] if has_comment else []
    return {
        "workoutId": 4081853605,
        "description": d,
        "title": "Nuoto",
        "workoutComments": comments,
        "totalTimePlanned": 2400,
        "distancePlanned": 1200,
        "structure": {"structure": []},
    }


ENTRY = {
    "workout_id": 4081853605,
    "comment_id": 322550499,
    "expected_urls": ["https://youtu.be/o0ffl059C1Q"],
}


def test_manifest_has_only_reviewed_own_workout_comments():
    m = read_manifest()
    assert m["owner_id"] == OWNER and m["athlete_id"] == 6757136
    assert {(e["workout_id"], e["comment_id"]) for e in m["entries"]} == {
        (4081853605, 322550499),
        (4081855488, 322550505),
        (4081857186, 322550512),
        (4081858052, 322550519),
    }


def test_exact_own_comment_is_selected_for_reviewed_removal():
    assert choose_comment(workout(), ENTRY)["id"] == 322550499


def test_already_absent_idempotent():
    assert choose_comment(workout(has_comment=False), ENTRY) is None


@pytest.mark.parametrize("bad", [
    workout(owner=999),
    workout(video=False),
    workout(comment_body="Different unrelated coach feedback"),
])
def test_unapproved_or_mismatched_content_blocks_write(bad):
    with pytest.raises(SafeStop):
        choose_comment(bad, ENTRY)


def test_other_workout_fields_stable_comparison():
    before = workout()
    after = workout(has_comment=False)
    assert stable_fields(before) == stable_fields(after)
