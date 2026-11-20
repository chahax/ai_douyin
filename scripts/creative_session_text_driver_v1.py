"""Explicit workflow-injected setup/body stages for independent text sessions.

The immutable v1 session cannot inject its module-global workflow. These small
drivers preserve its native whole-document revision and same-source review flow.
"""
from copy import deepcopy
from scripts import creative_fresh_source_session_v1 as shared


def opening(session, runtime, inputs, goal):
    wf=session.wf;current=deepcopy(inputs)
    for index in (1,2):
        prepared=wf.prepare_opening_setup_request(current,session.profile,goal)
        receipt=session.invoke(runtime,f"opening_setup_{index:02}",prepared,lambda value:{"valid":True,
            "native_setup_sha256":shared.digest(wf.validate_opening_setup_document(value,goal)),"state_fields_inferred":False})
        native=session.known(receipt,"opening_setup",require_valid=False)
        shared.write(session.root/"setup"/f"NATIVE_{index:02}.json",native,True)
        if receipt["status"]=="contract_valid":return native
        current={**deepcopy(inputs),"previous_opening_setup":native,"opening_setup_diagnostics":session._diagnosis(receipt)}
    raise shared.Halt("halt_opening_setup_capacity_exhausted")


def body(session, runtime, inputs, goal, audit, setup, goal_ordinal):
    wf=session.wf;current=deepcopy(inputs)
    for index in (1,2,3):
        prepared=wf.prepare_script_request(current,session.profile,goal,audit,opening_setup=setup,**wf.origin_ids(inputs));views=prepared["views"]
        def validate(value):
            result=wf.validate_script_document(value,views,inputs["production_preferences"])
            if not result["necessary_conditions_only"]:
                error=ValueError("complete native revision required for necessary timing conditions");error.detail=result["diagnostic"];raise error
            return result
        receipt=session.invoke(runtime,f"complete_script_{index:02}",prepared,validate)
        native=session.known(receipt,"complete_script",require_valid=False);folder=session.root/"scripts"/f"version_{index:02}"
        shared.write(folder/"NATIVE_SCRIPT.json",native,True)
        try:
            compiled=shared.text.contract.compile_script(native,views["brief"])
            with (folder/"FULL_SCRIPT.md").open("x",encoding="utf-8") as output:
                output.write("完整模型原生正文；结论见同目录DECISION和本次STATE，未获用户采用。\n\n"+shared.text.render_script(compiled,views["brief"]))
        except (ValueError,KeyError,TypeError):compiled=None
        if receipt["status"]!="contract_valid":
            current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":session._diagnosis(receipt)};continue
        documents,decisions,contexts,ordinals={}, {}, {}, {};legal=None;failed=None
        for part in ("semantic","physical"):
            review=wf.prepare_full_review_part_request(inputs,session.profile,native,views,part)
            if legal is not None and legal!=review["review_legal_context"]:raise ValueError("same-source review authority changed")
            legal=review["review_legal_context"];context=review["part_context_sha256"]
            reviewed=session.invoke(runtime,f"full_review_{part}_{index:02}",review,
                lambda value,p=part,c=context:shared.reviews.validate_part(value,p,compiled,views["brief"],views["plan"],legal,
                    context_sha256=c,goal_contract=goal,opening_setup=setup))
            documents[part]=session.known(reviewed,"full_review_"+part);decision=reviewed["validation"]
            shared.write(folder/("NATIVE_"+part.upper()+"_REVIEW.json"),documents[part],True)
            shared.write(folder/(part.upper()+"_DECISION.json"),decision,True)
            session._review_stop(decision,folder,part,reviewed["ordinal"])
            decisions[part],contexts[part],ordinals[part]=decision,context,reviewed["ordinal"]
            if not decision["accepted"]:failed=decision;break
        if failed is not None:
            current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":{
                "complete_same_source_part_review":failed,"native_part_reviews":documents,"native_review_ordinals":ordinals}};continue
        bundle=shared.reviews.build_review_bundle(documents["semantic"],documents["physical"])
        decision=shared.reviews.validate_bundle(bundle,compiled,views["brief"],views["plan"],legal,
            semantic_context_sha256=contexts["semantic"],physical_context_sha256=contexts["physical"],goal_contract=goal,opening_setup=setup)
        shared.write(folder/"NATIVE_REVIEW_BUNDLE.json",bundle,True);shared.write(folder/"DECISION.json",decision,True)
        session._review_stop(decision,folder,"bundle",ordinals)
        if decision.get("valid") is not True:raise shared.Halt("halt_full_review_bundle_contract_requires_pipeline_diagnosis")
        if decision["accepted"]:
            execution=session.execution_evidence(runtime,inputs,goal_ordinal,receipt["ordinal"],ordinals,views=views,compiled=compiled)
            shared.write(session.root/"TEXT_HANDOFF.json",{"schema":session.version+"/text_handoff","native_goal":goal,
                "native_goal_audit":audit,"native_opening_setup":setup,"native_script":native,"views":views,
                "native_full_review_bundle":bundle,"decision":decision,"execution_requirement_evidence":execution,
                "script_path":str(folder/"FULL_SCRIPT.md"),"script_ordinal":receipt["ordinal"],"review_ordinals":ordinals,
                "production_dispatch_eligible":False,"next_stage_requires_reconciled_director_lineage":True,"media_authorized":False},True)
            return session.state(runtime,"text_ready_for_director",text_ready_for_director=True,script_path=str(folder/"FULL_SCRIPT.md"),
                native_goal_ordinal=goal_ordinal,script_ordinal=receipt["ordinal"],review_ordinals=ordinals,decision=decision,
                execution_requirement_evidence=execution)
        current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":{
            "complete_same_source_full_review_bundle":decision,"native_review_bundle":bundle,"native_review_ordinals":ordinals}}
    raise shared.Halt("halt_complete_script_capacity_exhausted")
