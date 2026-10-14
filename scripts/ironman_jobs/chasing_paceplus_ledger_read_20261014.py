"""Read only the durable DO execution state from a NEW operator invocation.

Does not contact TrainingPeaks or change local/provider data.
"""
import json
from ironman_state_store_v1 import connect,read_snapshot,DB_PATH
from chasing_paceplus_ledger_seed_20261014 import JOB_ID

def main():
    db=connect(read_only=True)
    try: state=read_snapshot(db,JOB_ID)
    finally: db.close()
    assert state["plan"]==685173 and state["expected_items"]==9
    assert state["state"]=="DONE_VERIFIED" and state["event_count"]==1
    assert len(set(x["id"] for x in state["items"]))==9
    print(json.dumps({"stage":"DO_LEDGER_INDEPENDENT_READ_PASS",
      "path":str(DB_PATH),"job_id":state["job_id"],
      "state":state["state"],"verified_at":state["verified_at"],
      "target_plan":state["plan"],"items":state["items"],
      "evidence_digest":state["evidence_digest"],"events":state["event_count"],
      "provider_writes":0},sort_keys=True),flush=True)

if __name__=="__main__":main()
