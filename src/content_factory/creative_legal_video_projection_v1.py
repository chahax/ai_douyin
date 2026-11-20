"""Project complete legal performance rows; never clamp a shot into API time."""
from copy import deepcopy
import math

def select_complete_rows(compiled, source_refs, maximum_seconds=15):
    schedule=compiled["schedule"]
    indexes=[i for i,row in enumerate(schedule) if row["source_ref"] in source_refs]
    if not indexes or [schedule[i]["source_ref"] for i in indexes]!=source_refs:
        raise ValueError("source refs must match complete ordered rows")
    if indexes!=list(range(indexes[0],indexes[-1]+1)):
        raise ValueError("generation segment cannot skip a source row")
    rows=[deepcopy(schedule[i]) for i in indexes]
    if len({r["shot_id"] for r in rows})!=1:
        raise ValueError("this projection must stay within one observation shot")
    for i,row in enumerate(rows):
        if not row["start"]<=row["active_start"]<=row["active_end"]<=row["end"]:
            raise ValueError("invalid original performance timing")
        if i and rows[i-1]["end_state"]!=row["start_state"]:
            raise ValueError("cross-row state mismatch")
    if indexes[0] and schedule[indexes[0]-1]["end_state"]!=rows[0]["start_state"]:
        raise ValueError("preceding source end state mismatch")
    source_seconds=round(rows[-1]["end"]-rows[0]["start"],6)
    service_seconds=math.ceil(source_seconds)
    if not 4<=service_seconds<=maximum_seconds:
        raise ValueError("complete rows exceed service duration; split at a complete row boundary")
    return {"rows":rows,"source_seconds":source_seconds,"service_seconds":service_seconds,
            "rounding_seconds":round(service_seconds-source_seconds,6),
            "source_start":rows[0]["start"],"source_end":rows[-1]["end"],
            "start_state":rows[0]["start_state"],"end_state":rows[-1]["end_state"]}

