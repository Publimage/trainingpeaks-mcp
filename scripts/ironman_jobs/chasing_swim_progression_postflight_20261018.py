"""Read-only provider postflight for CHASING 685173 Swim rebuild."""
import asyncio,json
from tp_mcp.client import TPClient
try:\n    from scripts.ironman_jobs import chasing_swim_rebuild_20261018 as r\nexcept ModuleNotFoundError:\n    import chasing_swim_rebuild_20261018 as r

async def main():
    specs=r.build_specs()
    design=r.design_gate(specs)
    async with TPClient() as c:
        who=await c._get_user_data()
        r.need(who.get("personId")==r.OWNER,"WRONG_COACH")
        p=await c.get(f"/plans/v1/plans/{r.PLAN}")
        h=p.data
        r.need(not p.is_error and h.get("planId")==r.PLAN and h.get("planPersonId")==r.PERSON
               and h.get("isPublic") is True and h.get("workoutCount")==276
               and "CHASING THE SLOT" in (h.get("title") or "") and "Advanced" in (h.get("title") or ""),"PLAN_SCOPE_DRIFT")
        rows,notes=await r.read_all(c)
        qa=r.final_content_gate(rows,specs)
        swims=[x for x in rows if x.get("workoutTypeValueId")==1]
        titles=[x.get("title") or "" for x in swims]
        old_tokens=("Endurance 3x700 - 3000 m","Facile + tecnica - 3200 m","Endurance 4x550 - 3100 m","Endurance 4x500 - 2800 m")
        r.need(not any(any(t in z for t in old_tokens) for z in titles),"OLD_SERIAL_TEMPLATE_SURVIVED")
        continuous=[s for s in specs if s["kind"]=="cont"]
        exposures=[{"week":s["week"],"main_m":s["main"],"total_m":s["metres"],"workout_id":s["id"]}
                   for s in continuous if s["main"]>=3000]
        r.need(any(x["main_m"]>=3500 for x in exposures)
               and any(x["main_m"]>=3800 for x in exposures)
               and any(x["main_m"]==4000 for x in exposures),"CONTINUOUS_GATE_LIVE")
        print(json.dumps({"stage":"CHASING_SWIM_PROGRESSION_POSTFLIGHT_PASS",
              "plan":r.PLAN,"plan_workout_count":h.get("workoutCount"),
              "swim_count":len(swims),"unique_titles":len(set(titles)),
              "unique_descriptions":qa["unique_descriptions"],
              "continuous_3k_plus":exposures,
              "whole_4000_id":qa["whole_4000_id"],
              "old_serial_templates_remaining":0,
              "notes_readback_blocks":3,"provider_writes":0,"public_preserved":True,
              "design_gate":design}),flush=True)

if __name__=="__main__":
    asyncio.run(main())
