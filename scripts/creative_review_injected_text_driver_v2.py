"""Explicit native review injection for a newly frozen text entry.

No client, claim, budget or automatic retry lives here.  Existing frozen drivers
are unchanged.  A session must still admit exact requests and verify original
SDK/TaskStore evidence before creating a production handoff.
"""
from copy import deepcopy

from scripts import creative_fresh_source_session_v1 as shared

VERSION = "creative_review_injected_text_driver/v2"


def review_gate(session, decision, folder, part, ordinal):
    """A malformed review never authorizes a new screenplay."""
    if (type(decision) is not dict or decision.get("valid") is not True
            or type(decision.get("accepted")) is not bool
            or type(decision.get("findings")) is not list
            or type(decision.get("uncertainties")) is not list
            or (decision["accepted"] and (decision.get("findings") or decision.get("uncertainties")))):
        raise shared.Halt("halt_full_review_contract_requires_pipeline_diagnosis",
            review_part=part, receipt_ordinal=ordinal, decision=decision)
    session._review_stop(decision, folder, part, ordinal)
    if not decision["accepted"] and not decision["findings"]:
        raise shared.Halt("halt_full_review_contract_requires_pipeline_diagnosis",
            review_part=part, receipt_ordinal=ordinal, decision=decision)


def body(session, runtime, inputs, goal, audit, setup, goal_ordinal, *, reviews):
    """Whole native revisions and both same-source reviews, explicitly injected.

    Review-part capacities and same-story revision consumption remain the
    session/runtime's responsibility; changing this driver grants no capacity.
    """
    wf = session.wf
    current = deepcopy(inputs)
    for index in (1, 2, 3):
        prepared = wf.prepare_script_request(current, session.profile, goal, audit,
            opening_setup=setup, **wf.origin_ids(inputs))
        views = prepared["views"]

        def validate(value):
            result = wf.validate_script_document(value, views, inputs["production_preferences"])
            if not result["necessary_conditions_only"]:
                error = ValueError("complete native revision required for necessary timing conditions")
                error.detail = result["diagnostic"]
                raise error
            return result

        receipt = session.invoke(runtime, f"complete_script_{index:02}", prepared, validate)
        native = session.known(receipt, "complete_script", require_valid=False)
        folder = session.root / "scripts" / f"version_{index:02}"
        shared.write(folder / "NATIVE_SCRIPT.json", native, True)
        try:
            compiled = shared.text.contract.compile_script(native, views["brief"])
            with (folder / "FULL_SCRIPT.md").open("x", encoding="utf-8") as out:
                out.write("完整模型原生正文；全文验收与人工质量分别记录。\n\n"
                    + shared.text.render_script(compiled, views["brief"]))
        except (ValueError, KeyError, TypeError):
            if receipt["status"] == "contract_valid":
                raise ValueError("accepted native script cannot be deterministically compiled")
            compiled = None
        if receipt["status"] != "contract_valid":
            current = {**deepcopy(inputs), "previous_complete_document": native,
                "revision_diagnostics": session._diagnosis(receipt)}
            continue

        documents, contexts, ordinals = {}, {}, {}
        legal, failed = None, None
        for part in ("semantic", "physical"):
            review = wf.prepare_full_review_part_request(inputs, session.profile, native, views, part)
            if review["request"]["input_provenance"].get("native_review_part_version") != reviews.VERSION:
                raise ValueError("request and explicitly injected review protocol differ")
            if legal is not None and legal != review["review_legal_context"]:
                raise ValueError("same-source review authority changed")
            legal, context = review["review_legal_context"], review["part_context_sha256"]
            reviewed = session.invoke(runtime, f"full_review_{part}_{index:02}", review,
                lambda value, p=part, c=context: reviews.validate_part(value, p, compiled,
                    views["brief"], views["plan"], legal, context_sha256=c,
                    goal_contract=goal, opening_setup=setup))
            document = session.known(reviewed, "full_review_" + part)
            decision = reviewed["validation"]
            shared.write(folder / ("NATIVE_" + part.upper() + "_REVIEW.json"), document, True)
            shared.write(folder / (part.upper() + "_DECISION.json"), decision, True)
            review_gate(session, decision, folder, part, reviewed["ordinal"])
            documents[part], contexts[part], ordinals[part] = document, context, reviewed["ordinal"]
            if not decision["accepted"]:
                failed = decision
                break
        if failed is not None:
            current = {**deepcopy(inputs), "previous_complete_document": native,
                "revision_diagnostics": {"complete_same_source_part_review": failed,
                    "native_part_reviews": documents, "native_review_ordinals": ordinals}}
            continue

        bundle = reviews.build_review_bundle(documents["semantic"], documents["physical"])
        decision = reviews.validate_bundle(bundle, compiled, views["brief"], views["plan"], legal,
            semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"],
            goal_contract=goal, opening_setup=setup)
        shared.write(folder / "NATIVE_REVIEW_BUNDLE.json", bundle, True)
        shared.write(folder / "DECISION.json", decision, True)
        review_gate(session, decision, folder, "bundle", ordinals)
        if decision["accepted"]:
            execution = session.execution_evidence(runtime, inputs, goal_ordinal, receipt["ordinal"],
                ordinals, views=views, compiled=compiled)
            shared.write(session.root / "TEXT_HANDOFF.json", {
                "schema": session.version + "/text_handoff", "driver_version": VERSION,
                "review_protocol_version": reviews.VERSION, "native_goal": goal,
                "native_goal_audit": audit, "native_opening_setup": setup, "native_script": native,
                "native_script_sha256": shared.digest(native), "compiled_script_sha256": shared.digest(compiled),
                "views": views, "native_full_review_bundle": bundle, "decision": decision,
                "execution_requirement_evidence": execution, "script_path": str(folder / "FULL_SCRIPT.md"),
                "script_ordinal": receipt["ordinal"], "review_ordinals": ordinals,
                "production_dispatch_eligible": False, "next_stage_requires_reconciled_director_lineage": True,
                "human_quality_approved": False, "creative_quality_passed": False, "media_authorized": False}, True)
            return session.state(runtime, "text_ready_for_director", text_ready_for_director=True,
                script_path=str(folder / "FULL_SCRIPT.md"), native_goal_ordinal=goal_ordinal,
                script_ordinal=receipt["ordinal"], review_ordinals=ordinals, decision=decision,
                execution_requirement_evidence=execution, review_protocol_version=reviews.VERSION)
        current = {**deepcopy(inputs), "previous_complete_document": native,
            "revision_diagnostics": {"complete_same_source_full_review_bundle": decision,
                "native_review_bundle": bundle, "native_review_ordinals": ordinals}}
    raise shared.Halt("halt_complete_script_capacity_exhausted")
