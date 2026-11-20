"""Native v3 temporal candidates; synthetic reports are not semantic gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from src.content_factory import creative_split_full_review_contract_v2 as frozen
from src.content_factory import creative_split_full_review_contract_v3 as split
from src.content_factory import creative_goal_context_workflow_v13 as old_workflow
from tests.test_creative_split_full_review_contract_v2 import fixture as synthetic_shape

CONTEXTS = {"semantic": "1" * 64, "physical": "2" * 64}
PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_13"


@pytest.fixture(autouse=True)
def no_dispatch(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("v3 schema verification may not contact providers or create clients")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def fixture():
    # New synthetic v3 reports, based on the shared fake source fixture only.
    # This never reads or converts a provider's previous native response.
    case, opening, shape = synthetic_shape()
    reports = {}
    for part in split.PART_TABLES:
        reports[part] = {key: deepcopy(value) for key, value in shape[part].items() if key != "schema"}
        reports[part]["schema"] = split.VERSION
    return case, opening, reports


def schema(case, opening, part="semantic"):
    return split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=opening)


def validate(case, opening, reports, part="semantic"):
    return split.validate_part(reports[part], part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=opening)


def bundle(case, opening, reports):
    return split.validate_bundle(split.build_review_bundle(reports["semantic"], reports["physical"]),
        *case[:4], semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["physical"],
        opening_setup=opening)


def test_new_native_part_and_bundle_acceptance_keeps_full_coverage_and_quality_boundaries():
    case, opening, reports = fixture()
    before = deepcopy((case, opening, reports))
    for part in split.PART_TABLES:
        Draft202012Validator(schema(case, opening, part)).validate(reports[part])
        result = validate(case, opening, reports, part)
        assert result["valid"] and result["accepted"], result
        assert result["split_review_contract_version"] == split.VERSION
        assert not result["semantic_meaning_programmatically_verified"] and not result["human_quality_approved"]
    result = bundle(case, opening, reports)
    assert result["valid"] and result["accepted"], result
    assert result["split_review_bundle_version"] == split.BUNDLE_VERSION
    assert not result["creative_quality_passed"] and not result["old_budget_reset"]
    assert (case, opening, reports) == before


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_schema_intersection_preserves_every_old_field_shared_definition_and_coverage(part):
    case, opening, _ = fixture()
    new = schema(case, opening, part)
    old = frozen.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=opening)
    assert set(new["properties"]) == set(old["properties"])
    assert new["required"] == old["required"]
    assert new.get("$defs") == old.get("$defs")
    restored = deepcopy(new)
    restored["properties"]["schema"] = old["properties"]["schema"]
    if part == "semantic":
        rows = restored["properties"]["dialogue_checks"]["properties"]
        for ref, item in rows.items():
            assert item["allOf"][0] == old["properties"]["dialogue_checks"]["properties"][ref]
            rows[ref] = item["allOf"][0]
    assert restored == old
    assert split.part_table_contract(part, *case[:3]) == frozen.part_table_contract(part, *case[:3])


def test_each_real_dialogue_has_exact_global_before_and_after_candidates_and_final_empty_rule():
    case, opening, reports = fixture()
    entries = split.reviews.base.base.prior.contract.evidence_catalog(case[0])
    refs = list(entries)
    rows = schema(case, opening)["properties"]["dialogue_checks"]["properties"]
    assert set(rows) == set(reports["semantic"]["dialogue_checks"])
    for ref, item in rows.items():
        bounds = item["allOf"][1]["properties"]
        index = refs.index(ref)
        assert bounds["stimulus_ref"]["enum"] == [None, *refs[:index]]
        reaction = bounds["reaction_refs"]
        assert reaction["minItems"] == 0 and reaction["uniqueItems"]
        assert reaction["maxItems"] == len(refs[index + 1:])
        assert reaction["items"] == ({"enum": refs[index + 1:]} if refs[index + 1:] else False)
    final = rows[refs[-1]]["allOf"][1]["properties"]["reaction_refs"]
    assert final["items"] is False and final["maxItems"] == 0


@pytest.mark.parametrize("field,mode", [("reaction_refs", "earlier"), ("reaction_refs", "self"),
    ("reaction_refs", "foreign"), ("reaction_refs", "duplicate"), ("stimulus_ref", "self"),
    ("stimulus_ref", "later"), ("stimulus_ref", "foreign")])
def test_wrong_temporal_or_foreign_reference_is_rejected_by_outbound_schema_and_native_validator(field, mode):
    case, opening, reports = fixture()
    ref = next(iter(reports["semantic"]["dialogue_checks"]))
    refs = list(split.reviews.base.base.prior.contract.evidence_catalog(case[0]))
    index = refs.index(ref)
    selected = {"earlier": refs[index - 1], "self": ref, "foreign": "E9999",
                "later": refs[index + 1], "duplicate": refs[index + 1]}[mode]
    reports["semantic"]["dialogue_checks"][ref][field] = ([selected, selected] if mode == "duplicate" else [selected]) if field == "reaction_refs" else selected
    with pytest.raises(ValidationError):
        Draft202012Validator(schema(case, opening)).validate(reports["semantic"])
    result = validate(case, opening, reports)
    assert not result["valid"] and not result["accepted"]
    assert result["findings"][0]["code"] == "SPLIT_REVIEW_SCHEMA_INVALID"
    assert not bundle(case, opening, reports)["accepted"]


def test_null_empty_and_cross_beat_later_references_remain_legal():
    case, opening, reports = fixture()
    refs = list(split.reviews.base.base.prior.contract.evidence_catalog(case[0]))
    rows = reports["semantic"]["dialogue_checks"]
    first = next(iter(rows))
    rows[first].update(stimulus_ref=None, reaction_refs=[refs[-1]])
    rows[refs[-1]].update(stimulus_ref=None, reaction_refs=[])
    assert validate(case, opening, reports)["accepted"]
    assert bundle(case, opening, reports)["accepted"]


def test_first_actual_step_dialogue_has_only_null_stimulus_candidate():
    case, opening, _ = fixture()
    case[0]["beats"][0]["steps"].reverse()  # Synthetic representation fixture only.
    entries = split.reviews.base.base.prior.contract.evidence_catalog(case[0])
    assert entries["E0001"]["kind"] == "dialogue"
    rows = schema(case, opening)["properties"]["dialogue_checks"]["properties"]
    assert rows["E0001"]["allOf"][1]["properties"]["stimulus_ref"] == {"enum": [None]}


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", [*split.SOURCE_HEADERS, "context_sha256", "part", "schema"])
def test_all_existing_native_source_and_part_identities_still_reject_cross_source(part, field):
    case, opening, reports = fixture()
    reports[part][field] = "0" * 64
    assert not validate(case, opening, reports, part)["valid"]
    assert not bundle(case, opening, reports)["accepted"]


@pytest.mark.parametrize("table", ["dialogue_checks", "beat_intent_checks", "dialogue_role_checks"])
@pytest.mark.parametrize("mutation", ["missing", "empty", "foreign"])
def test_nonzero_semantic_rows_and_reaction_field_cannot_be_dropped(table, mutation):
    case, opening, reports = fixture()
    if mutation == "missing": del reports["semantic"][table]
    elif mutation == "empty": reports["semantic"][table] = {}
    else: reports["semantic"][table]["FOREIGN"] = deepcopy(next(iter(reports["semantic"][table].values())))
    assert not validate(case, opening, reports)["valid"]


def test_reaction_field_is_still_required_even_when_no_reaction_is_selected():
    case, opening, reports = fixture()
    next(iter(reports["semantic"]["dialogue_checks"].values())).pop("reaction_refs")
    assert not validate(case, opening, reports)["valid"]


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_content_failure_unknown_and_child_counterevidence_checks_are_not_relaxed(status):
    case, opening, reports = fixture()
    row = next(iter(reports["semantic"]["dialogue_role_checks"].values()))
    child = row["checks"]["purpose_alignment"]
    for item in (row, child):
        item.update(status=status, required_revision="完整新稿修复。" if status == "fail" else "")
        item["counterevidence"] = deepcopy(item["evidence"])
    reports["semantic"]["revision_target"] = "script" if status == "fail" else "none"
    result = bundle(case, opening, reports)
    assert result["valid"] and not result["accepted"]
    assert result["status"] == ("needs_whole_revision" if status == "fail" else "halt_review_uncertain")


def actual_case():
    if not ACTUAL.exists(): pytest.skip("read-only historical round_13 fixture absent")
    read = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    inputs = read(ACTUAL / "INPUTS.json")
    goal = read(ACTUAL / "call_575_goal_plan_19.json")["output"]
    opening = read(ACTUAL / "call_578_opening_setup_01.json")["output"]
    native = read(ACTUAL / "call_579_complete_script_01.json")["output"]
    receipt = read(ACTUAL / "call_580_full_review_semantic_01.json")
    actual_payload = json.loads(receipt["request"]["messages"][1]["content"])
    views = old_workflow.compile_native_views(goal, opening, **old_workflow.origin_ids(inputs))
    script = old_workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
    return script, views["brief"], views["plan"], actual_payload["verified_legal_context"], goal, opening, receipt


def test_actual579_source_compiles_complete_v3_request_with_exact_original_native_identities():
    script, brief, plan, legal, goal, opening, receipt = actual_case()
    paths = [ACTUAL / name for name in ("call_579_complete_script_01.json", "call_580_full_review_semantic_01.json",
        "PRODUCTION_FREEZE.json", "STATE.json", "CALL_LEDGER.json")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    context = receipt["output"]["context_sha256"]
    schema_new = split.build_part_schema("semantic", script, brief, plan, legal, context_sha256=context,
        goal_contract=goal, opening_setup=opening)
    schema_old = frozen.build_part_schema("semantic", script, brief, plan, legal, context_sha256=context,
        goal_contract=goal, opening_setup=opening)
    assert schema_old == receipt["request"]["structured_schema"]
    assert schema_new["properties"]["schema"]["const"] == split.VERSION
    for field in split.SOURCE_HEADERS:
        assert schema_new["properties"][field] == schema_old["properties"][field]
    bound = schema_new["properties"]["dialogue_checks"]["properties"]["E0016"]["allOf"][1]["properties"]
    assert "E0015" not in bound["reaction_refs"]["items"]["enum"]
    assert "E0017" in bound["reaction_refs"]["items"]["enum"]
    assert "E0015" in bound["stimulus_ref"]["enum"]
    assert "E0016" not in bound["stimulus_ref"]["enum"]
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


@pytest.mark.parametrize("tamper_header", [False, True])
def test_original580_and_header_only_tamper_remain_rejected_never_promoted(tamper_header):
    script, brief, plan, legal, goal, opening, receipt = actual_case()
    path = ACTUAL / "call_580_full_review_semantic_01.json"
    raw = path.read_bytes()
    original = receipt["output"]
    assert original["schema"] == frozen.VERSION
    report = deepcopy(original)
    if tamper_header: report["schema"] = split.VERSION  # Rejection attack fixture only.
    result = split.validate_part(report, "semantic", script, brief, plan, legal,
        context_sha256=original["context_sha256"], goal_contract=goal, opening_setup=opening)
    assert not result["valid"] and not result["accepted"]
    assert result["findings"][0]["code"] == "SPLIT_REVIEW_SCHEMA_INVALID"
    if tamper_header:
        assert result["findings"][0]["path"] == "dialogue_checks/E0016/reaction_refs/0"
    assert path.read_bytes() == raw and receipt["output"] == original
