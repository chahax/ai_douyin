"""Read-only historical response replay and offline modular fixture verification."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.creative_modular_contract import (
    build_direction_schema,build_local_schema,build_local_input,compile_complete,invalidation_scope)
from src.content_factory.creative_response_contract import response_failure,validation_failure
from src.content_factory.creative_stage_contracts import digest
from src.content_factory.creative_workflow_contract import CreativeContractError
from scripts.audit_creative_plan_offline import audit


def verify(fixture,run):
    context,direction,locals_=fixture["context"],fixture["direction"],fixture["locals"]
    before=digest(fixture)
    compiled=compile_complete(context,direction,locals_)
    cases=[]
    def check(name,expected,mutate):
        c,d,l=deepcopy((context,direction,locals_));mutate(c,d,l)
        try:
            compile_complete(c,d,l)
        except CreativeContractError as e:
            code=getattr(e,"detail",{}).get("code",str(e).split(":",1)[0])
            if code!=expected:raise AssertionError((name,expected,code)) from e
            cases.append({"case":name,"expected":expected,"observed":code,"passed":True})
        else:
            raise AssertionError(name+" should have failed")
    check("reaction_before_dialogue","MODULE_STIMULUS_REACTION_ORDER",
        lambda c,d,l:l[0]["performance_windows"][-1].update(anchor="PRE"))
    check("short_reaction_despite_tail_margin","MODULE_WINDOW_TOO_SHORT",
        lambda c,d,l:l[0]["groups"][-1].update(duration_seconds=0.5))
    check("cross_beat_take_without_transfer","PLAN_GROUP_PRECONDITION_INVALID",
        lambda c,d,l:l[1]["groups"][0]["operations"].append({"kind":"take","actor":"C01","target":"P01","value":"右手"}))
    check("text_revision_invalidates_following_input","MODULE_STALE_INPUT",
        lambda c,d,l:l[0].update(dialogue_performance="新的表演"))
    check("partial_is_not_delivery","MODULE_INCOMPLETE",lambda c,d,l:l.pop())
    assert before==digest(fixture)
    evidence=audit(run)
    original=json.loads((run/"AUTHORIZED_CONTINUATION_RESULT_24.json").read_text(encoding="utf-8"))
    response_cases=[]
    for call in original["calls"]:
        receipt=json.loads((run/call["receipt"]).read_text(encoding="utf-8"))
        f=response_failure(receipt.get("response_metadata",{}),receipt.get("response_text"),require_tool=True)
        if f is None and call["call_number"]==19:
            error=CreativeContractError(evidence["replays"]["call19_plan"]["error"])
            f=validation_failure(error)
        elif f is None and call["call_number"]==20:
            error=CreativeContractError("PLAN_SCHEMA_INVALID: "+str(evidence["replays"]["call20_schema_errors"]))
            f=validation_failure(error)
        response_cases.append({"call":call["call_number"],"receipt":call["receipt"],
            "sha256":hashlib.sha256((run/call["receipt"]).read_bytes()).hexdigest(),
            "classification":f,"historical_record_modified":False})
    return {
        "report":{"schema":"creative_response_modules_offline_verification/v1",
            "network_calls":0,"paid_calls":0,"production_state_modified":False,
            "production_quality_verified":False,"fixture_sha256":before,
            "module_cases":cases,"historical_response_cases":response_cases,
            "frozen_state":evidence["state"],
            "invalidation":[{"change":change,"scope":invalidation_scope(context,change)}
                for change in ("script","references","selected_assets","direction","compiler")]
                +[{"change":"local_performance","beat_id":b["id"],
                    "scope":invalidation_scope(context,"local_performance",beat_id=b["id"])}
                    for b in context["script"]["beats"]],
            "actual_reference_request_evidence":evidence["references"]},
        "compiled_fixture":compiled,
        "direction_schema":build_direction_schema(context),
        "local_schemas":{b["id"]:build_local_schema(context,direction,b["id"]) for b in context["script"]["beats"]},
        "local_inputs":[build_local_input(context,direction,locals_[:i]) for i in range(len(locals_))]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture",type=Path,required=True)
    parser.add_argument("--evidence-run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run=args.evidence_run.resolve();output=args.output.resolve()
    if output==run or run in output.parents:
        parser.error("output must be outside frozen production run")
    if args.fixture.resolve()==output or output in args.fixture.resolve().parents:
        parser.error("fixture must be outside output directory")
    fixture=json.loads(args.fixture.read_text(encoding="utf-8"))
    result=verify(fixture,run);output.mkdir(parents=True,exist_ok=True)
    for name,value in result.items():
        (output/(name+".json")).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Offline report saved; network/paid calls=0; fixture is not a production delivery.")


if __name__=="__main__":
    main()
