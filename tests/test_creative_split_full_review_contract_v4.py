"""Compact v4 native fake reports: provenance tests, never semantic gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from src.content_factory import creative_split_full_review_contract_v3 as frozen
from src.content_factory import creative_split_full_review_contract_v4 as split
from tests.test_creative_split_full_review_contract_v1 import fixture as original_fake_shape

CONTEXTS = {"semantic":"1"*64, "physical":"2"*64}
PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_16"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("compact review tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def judgement(ref):
    return {"status":"pass", "reason":"Synthetic source-binding judgment, not semantic gold",
        "required_revision":"", "evidence":[ref], "counterevidence":[]}


def synthetic_consistency(script, brief, plan, *, goal_contract=None):
    """Construct a NEW fake v4 report; never reads/converts old native output."""
    catalog = split.build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    beats = {}
    for beat in script["beats"]:
        ref = next(ref for ref,row in entries.items() if row["beat_id"] == beat["id"])
        beats[beat["id"]] = {"status":"pass", "counterexample_analysis":"Synthetic comparison only",
            "target_checks":{key:{**judgement(ref),"actual_reading":"Synthetic extraction, not interpretation proof"}
                for key,row in targets.items() if row["beat_id"] == beat["id"]}}
    dialogue = {}
    people = brief["constraints"]["allowed_character_ids"]
    for ref, actual in entries.items():
        if actual["kind"] != "dialogue": continue
        listener = next((x for x in people if x != actual["speaker"]),None)
        dialogue[ref] = {"status":"pass", "listener_id":listener,
            "listener_mode":"addressed" if listener else "self_talk",
            "quote_attribution":{"mode":"none","attributed_to":{"unspecified":None},"quote_fragment":None},
            "propositions":[{"quote":actual["quote"],"agents":[{"character_id":actual["speaker"]}],
                "patients":[],"referents":[],"negation":{"mode":"affirmed","scope_quote":None}}],
            "literal_meaning":"Synthetic literal extraction", "character_purpose":"Synthetic purpose",
            "checks":{key:judgement(ref) for key in ("referents","agent_patient","negation_scope","purpose_alignment")}}
    return {"beat_intent_checks":beats,"dialogue_role_checks":dialogue,"unresolved_issues":[]}


def fixture():
    case, opening, fake = original_fake_shape()
    reports = deepcopy(fake)
    for part in split.PART_TABLES:
        reports[part]["schema"] = split.VERSION
    reports["semantic"].update(synthetic_consistency(*case[:3]))
    return case, opening, reports


def schema(case,opening,part="semantic"):
    return split.build_part_schema(part,*case[:4],context_sha256=CONTEXTS[part],opening_setup=opening)


def validate(case,opening,reports,part="semantic"):
    return split.validate_part(reports[part],part,*case[:4],context_sha256=CONTEXTS[part],opening_setup=opening)


def bundle(case,opening,reports):
    return split.validate_bundle(split.build_review_bundle(reports["semantic"],reports["physical"]),
        *case[:4],semantic_context_sha256=CONTEXTS["semantic"],physical_context_sha256=CONTEXTS["physical"],opening_setup=opening)


def test_new_native_two_parts_preserve_all_duties_statuses_and_source_hashes_without_rewrite():
    case,opening,reports=fixture()
    before=deepcopy((case,opening,reports))
    for part in split.PART_TABLES:
        Draft202012Validator(schema(case,opening,part)).validate(reports[part])
        result=validate(case,opening,reports,part)
        assert result["valid"] and result["accepted"],result
        assert result["native_part_sha256"] == split.reviews.base.base.prior.digest(reports[part])
        assert result["reference_expansion_is_compiler_input"] and not result["native_response_rewritten"]
        assert set(split.part_table_contract(part,*case[:3])["required_tables"]) - {"unresolved_issues"} == set(frozen.part_table_contract(part,*case[:3])["required_tables"])
        assert split.part_table_contract(part,*case[:3])["coverage"] == frozen.part_table_contract(part,*case[:3])["coverage"]
        assert set(schema(case,opening,part)["properties"]) - {"unresolved_issues"} == set(frozen.build_part_schema(part,*case[:4],
            context_sha256=CONTEXTS[part],opening_setup=opening)["properties"])
    result=bundle(case,opening,reports)
    assert result["valid"] and result["accepted"] and result["status"]=="text_ready_for_director",result
    assert not result["human_quality_approved"] and not result["semantic_meaning_programmatically_verified"]
    assert not result["creative_quality_passed"] and not result["old_budget_reset"]
    assert (case,opening,reports)==before


def test_exact_ref_expansion_retains_every_native_judgment_and_entity_without_filling():
    case,opening,reports=fixture()
    raw=reports["semantic"]
    ref=next(iter(raw["dialogue_role_checks"]))
    role=raw["dialogue_role_checks"][ref]
    role["propositions"][0]["patients"]=[{"other_entity":"柜子"},{"unspecified":"原文未定"}]
    assert validate(case,opening,reports)["valid"]
    expanded=split._expand_semantic(raw,case[0],case[2])
    catalog=split.build_consistency_evidence_catalog(*case[:1],case[2])
    er=expanded["dialogue_role_checks"][ref]
    assert er["speaker_id"]==catalog["actual_steps"][ref]["speaker"]
    assert er["quote"]==catalog["actual_steps"][ref]["quote"]
    assert er["propositions"][0]["patients"]==[
        {"kind":"other_entity","character_id":None,"label":"柜子"},
        {"kind":"unspecified","character_id":None,"label":"原文未定"}]
    for key,child in role["checks"].items():
        old=er["checks"][key]
        assert all(old[x]==child[x] for x in ("status","reason","required_revision"))
        assert old["counterevidence"]==[]
        assert old["evidence"]==[{"source_ref":ref,"quote":catalog["actual_steps"][ref]["quote"]}]
    assert "reason" not in er and "evidence" not in er and "required_revision" not in er


@pytest.mark.parametrize("part",["semantic","physical"])
@pytest.mark.parametrize("field",[*split.SOURCE_HEADERS,"context_sha256","part","schema"])
def test_all_native_source_and_context_identities_reject_drift(part,field):
    case,opening,reports=fixture(); reports[part][field]="0"*64
    assert not validate(case,opening,reports,part)["valid"]
    assert not bundle(case,opening,reports)["accepted"]


@pytest.mark.parametrize("table",["dialogue_checks","beat_intent_checks","dialogue_role_checks","literal_events"])
@pytest.mark.parametrize("fault",["missing","empty","extra"])
def test_full_nonzero_coverage_cannot_be_dropped_or_supplemented(table,fault):
    case,opening,reports=fixture()
    if fault=="missing": reports["semantic"].pop(table)
    elif fault=="empty": reports["semantic"][table]={}
    else: reports["semantic"][table]["FOREIGN"]=deepcopy(next(iter(reports["semantic"][table].values())))
    assert not validate(case,opening,reports)["valid"]


@pytest.mark.parametrize("fault",["object_witness","foreign","target","duplicate","missing_own","counter_pass","empty_evidence","extra_speaker","extra_quote","bad_entity","multi_entity","bad_fragment","missing_fragment","negation_scope","attribution","child_aggregate"])
def test_native_ids_fragments_types_and_unresolved_counterproof_remain_strict(fault):
    case,opening,reports=fixture(); rows=reports["semantic"]["dialogue_role_checks"]
    ref=next(iter(rows)); row=rows[ref]; child=row["checks"]["agent_patient"]
    refs=list(split.reviews.base.base.prior.contract.evidence_catalog(case[0]))
    other=next(x for x in refs if x!=ref)
    if fault=="object_witness": child["evidence"]=[{"source_ref":ref,"quote":row["propositions"][0]["quote"]}]
    elif fault=="foreign": child["evidence"]=["E9999"]
    elif fault=="target": child["evidence"]=[next(iter(reports["semantic"]["beat_intent_checks"].values()))["target_checks"].keys().__iter__().__next__()]
    elif fault=="duplicate": child["evidence"]=[ref,ref]
    elif fault=="missing_own": child["evidence"]=[other]
    elif fault=="counter_pass": child["counterevidence"]=[other]
    elif fault=="empty_evidence": child["evidence"]=[]
    elif fault=="extra_speaker": row["speaker_id"]="FOREIGN"
    elif fault=="extra_quote": row["quote"]="Invented source"
    elif fault=="bad_entity": row["propositions"][0]["agents"]=[{"character_id":"FOREIGN"}]
    elif fault=="multi_entity": row["propositions"][0]["agents"]=[{"character_id":"worker","other_entity":"公司"}]
    elif fault=="bad_fragment": row["propositions"][0]["quote"]="Invented source"
    elif fault=="missing_fragment": row["propositions"][0]["quote"]=row["propositions"][0]["quote"][:1]
    elif fault=="negation_scope": row["propositions"][0]["negation"]={"mode":"negated","scope_quote":"FOREIGN"}
    elif fault=="attribution": row["quote_attribution"]={"mode":"direct_quote","attributed_to":{"other_entity":"公司"},"quote_fragment":"FOREIGN"}
    else: child["status"]="unknown"
    result=validate(case,opening,reports)
    assert not result["valid"] and not result["accepted"],result
    assert not bundle(case,opening,reports)["accepted"]


@pytest.mark.parametrize("status",["fail","unknown"])
def test_native_failure_unknown_and_counterproof_survive_without_inferred_status(status):
    case,opening,reports=fixture(); row=next(iter(reports["semantic"]["dialogue_role_checks"].values()))
    child=row["checks"]["purpose_alignment"]
    row["status"]=child["status"]=status
    child["required_revision"]="完整新稿修复人物目的" if status=="fail" else ""
    child["counterevidence"]=list(child["evidence"])
    reports["semantic"]["revision_target"]="script" if status=="fail" else "none"
    result=bundle(case,opening,reports)
    assert result["valid"] and not result["accepted"],result
    assert result["status"]==("needs_whole_revision" if status=="fail" else "halt_review_uncertain")
    assert result["part_results"]["semantic"]["findings" if status=="fail" else "uncertainties"][0]["finding"]["checks"]["purpose_alignment"]==child


@pytest.mark.parametrize("fault",["reaction_self","reaction_early","stimulus_self","stimulus_late"])
def test_temporal_candidates_and_reaction_field_are_unchanged(fault):
    case,opening,reports=fixture(); ref=next(iter(reports["semantic"]["dialogue_checks"]))
    entries=list(split.reviews.base.base.prior.contract.evidence_catalog(case[0])); idx=entries.index(ref)
    row=reports["semantic"]["dialogue_checks"][ref]
    if fault=="reaction_self": row["reaction_refs"]=[ref]
    elif fault=="reaction_early": row["reaction_refs"]=[entries[idx-1]]
    elif fault=="stimulus_self": row["stimulus_ref"]=ref
    else: row["stimulus_ref"]=entries[idx+1]
    assert not validate(case,opening,reports)["valid"]


def test_bounded_explanations_do_not_shorten_native_proposition_source_strings():
    case,opening,reports=fixture()
    child=next(iter(reports["semantic"]["dialogue_role_checks"].values()))["checks"]["referents"]
    child["reason"]="x"*split.EXPLANATION_LIMITS["reason"]
    assert validate(case,opening,reports)["accepted"]
    child["reason"]+="x"
    assert not validate(case,opening,reports)["valid"]


def test_old_native_parts_and_header_only_attack_are_never_adopted():
    case,opening,_=fixture()
    from tests.test_creative_split_full_review_contract_v3 import fixture as old_fake
    _,_,reports=old_fake()
    assert not validate(case,opening,reports)["valid"]
    reports["semantic"]["schema"]=split.VERSION
    assert not validate(case,opening,reports)["valid"]


def test_original601_truncated_tool_argument_stays_raw_rejected_and_unmodified():
    path=ACTUAL/"call_601_full_review_semantic_02.json"
    if not path.exists(): pytest.skip("actual601 read-only fixture absent")
    raw=path.read_bytes(); receipt=json.loads(raw.decode("utf-8-sig"))
    assert receipt["response_metadata"]["finish_reason"]=="length"
    assert receipt.get("output") is None
    # This does not close braces, parse prefixes into a report, or copy601.
    assert path.read_bytes()==raw


@pytest.mark.parametrize("status",["fail","unknown"])
def test_concrete_issues_cannot_be_hidden_behind_passing_native_tables(status):
    case,opening,reports=fixture()
    identifier=next(iter(reports["semantic"]["criteria"]))
    issue={"table":"criteria","item_id":identifier,"status":status,"reason":"Concrete unresolved feature",
        "required_revision":"Complete new script" if status=="fail" else ""}
    reports["semantic"]["unresolved_issues"]=[issue]
    assert not validate(case,opening,reports)["valid"]
    reports["semantic"]["criteria"][identifier].update(status=status,required_revision=issue["required_revision"])
    reports["semantic"]["revision_target"]="script" if status=="fail" else "none"
    result=bundle(case,opening,reports)
    assert result["valid"] and not result["accepted"],result


@pytest.mark.parametrize("fault",["pass","foreign_table","foreign_row","duplicate","missing"])
def test_explicit_issues_are_required_typed_and_exact(fault):
    case,opening,reports=fixture(); identifier=next(iter(reports["semantic"]["criteria"]))
    issue={"table":"criteria","item_id":identifier,"status":"unknown","reason":"Uncertain current item","required_revision":""}
    reports["semantic"]["criteria"][identifier]["status"]="unknown"
    reports["semantic"]["unresolved_issues"]=[issue]
    if fault=="pass": issue["status"]="pass"
    elif fault=="foreign_table": issue["table"]="review_limitations"
    elif fault=="foreign_row": issue["item_id"]="FOREIGN"
    elif fault=="duplicate": reports["semantic"]["unresolved_issues"].append({**issue,"reason":"Different reason"})
    else: reports["semantic"].pop("unresolved_issues")
    assert not validate(case,opening,reports)["valid"]


@pytest.mark.parametrize("atom,value",[("holder_character_id","hr"),("open",True),("support_entity_id","room")])
def test_physical_state_raw_native_atoms_and_exact_preconditions_are_not_relaxed(atom,value):
    case,opening,reports=fixture()
    reports["physical"]["action_checks"]["E0001"]["preconditions"]=[{"entity_id":"slip","state_key":atom,
        "actual_value":value,"expected_value":value,"established_by":"initial:prop:slip","quote":"没人持有"}]
    assert not validate(case,opening,reports,"physical")["valid"]


def test_later_beat_cannot_supply_performed_current_event_evidence():
    case,opening,reports=fixture()
    entries=split.build_consistency_evidence_catalog(case[0],case[2])["actual_steps"]
    beat=case[0]["beats"][0]["id"]
    later=next(ref for ref,row in entries.items() if row["beat_id"]!=beat)
    target=next(row for ref,row in reports["semantic"]["beat_intent_checks"][beat]["target_checks"].items() if ref.endswith("script.event"))
    target["evidence"]=[later]
    assert not validate(case,opening,reports)["valid"]


def test_literal_meaning_is_model_output_and_structure_does_not_prove_semantics():
    case,opening,reports=fixture()
    next(iter(reports["semantic"]["dialogue_role_checks"].values()))["literal_meaning"]="有意错误的合成解释，结构无力证明真假。"
    result=bundle(case,opening,reports)
    assert result["valid"] and result["accepted"] and not result["semantic_meaning_programmatically_verified"]
