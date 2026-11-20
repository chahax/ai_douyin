"""Fixed684 certificate alias projection; original v1 proof/native stay intact.

This preserves the already-verified SDK/SQL proof by pinned certificate and all
original source bytes. It does not repeat SDK replay or grant any capacity.
"""
from copy import deepcopy
from pathlib import Path
from scripts import creative_world_scene_invalid_comparison_spend_anchor_v1 as original

VERSION = "creative_world_scene_invalid_comparison_spend_anchor/v2"
ORIGINAL_PATH = original.session.base.PROJECT / "data/qa/creative_world_scene_live_v11_20261016/SETTLED684_SPEND_ANCHOR_v1.json"
ORIGINAL_SHA256 = "1b8021b610112b9e35846fb5d3dea452b8f8593afa020c9b36474320c8b4b348"
ORIGINAL_VERIFIER_SHA256 = "365395e077de655bd6bf56142e26e0e7c10802d0c2be0c85f867cfb2866b1307"
read, digest, sha, require = original.read, original.digest, original.sha, original.require


def project_aliases(anchor, reader):
    require(anchor.get("schema") == original.VERSION and digest(anchor) == ORIGINAL_SHA256
        and anchor.get("verifier_code_sha256") == ORIGINAL_VERIFIER_SHA256 and sha(original.__file__) == ORIGINAL_VERIFIER_SHA256,
        "fixed original684 certificate/verifier identity differs")
    refs = {name: anchor["accepted_observable_events_" + name] for name in ("receipt", "prepared_ref", "decision_ref")}
    require(all(anchor["source_files"].get(ref["path"]) == ref["file_sha256"] for ref in refs.values()), "accepted refs outside original verified source inventory")
    receipt, intent = reader.json(refs["receipt"]["path"]), reader.json(refs["prepared_ref"]["path"])
    prepared, decision = intent["prepared"], receipt["validation"]
    require(refs["prepared_ref"].get("json_pointer") == "/prepared" and refs["decision_ref"].get("json_pointer") == "/validation"
        and refs["decision_ref"]["path"] == refs["receipt"]["path"]
        and receipt.get("status") == "contract_valid" and decision.get("valid") is True and decision.get("ledger_usable") is True
        and digest(receipt["output"]) == refs["receipt"]["native_sha256"] and digest(decision) == refs["decision_ref"]["native_sha256"]
        and digest(prepared) == refs["prepared_ref"]["native_sha256"]
        and receipt["request"] == prepared["request"] and digest(prepared["request"]) == refs["receipt"]["request_sha256"] == refs["prepared_ref"]["request_sha256"]
        and prepared["context_sha256"] == refs["prepared_ref"]["context_sha256"]
        and digest(prepared["views"]["native_script"]) == anchor["current_valid_body_receipt"]["native_sha256"]
        and prepared["source_descriptor"]["native_script_sha256"] == anchor["current_valid_body_receipt"]["native_sha256"],
        "accepted683 request/native/decision/locator/source descriptor differs")
    return {**deepcopy(anchor), **{"latest_observable_events_" + name: deepcopy(ref) for name, ref in refs.items()}}


def build_anchor(root, *, expected_end):
    reader = original.evidence.Reader(); prior = reader.json(ORIGINAL_PATH)
    require(str(original.session.base._inside(root)) == prior["root"] and type(expected_end) is int
        and expected_end == prior["parent_identity"]["end_ordinal"], "fixed original684 root/end differs")
    for path, expected in prior["source_files"].items(): reader.verify(original.session.base._inside(path), expected)
    result = project_aliases(prior, reader)
    return {**result, "schema": VERSION, "verifier_code_sha256": sha(__file__), "original_anchor_path": str(ORIGINAL_PATH),
        "original_anchor_sha256": ORIGINAL_SHA256, "original_verifier_code_sha256": ORIGINAL_VERIFIER_SHA256,
        "source_files": {**prior["source_files"], str(ORIGINAL_PATH): sha(ORIGINAL_PATH), str(Path(__file__).resolve()): sha(__file__)},
        "alias_projection_basis": {"schema": VERSION + "/projection", "only_machine_latest_aliases_changed": True,
            "native_receipts_or_consumption_changed": False, "all_original_certificate_source_bytes_identical": True,
            "original_sdk_sql_replay_preserved_by_certificate_not_repeated": True}, "authorizes_dispatch": False}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "684 alias certificate identity differs")
    require(build_anchor(anchor["root"], expected_end=anchor["parent_identity"]["end_ordinal"]) == anchor, "original684 certificate/alias projection changed")
    return {"verified": True, "anchor": deepcopy(anchor), **{key: deepcopy(anchor[key]) for key in
        ("inherited", "source_files", "parent_identity", "creative_source_root", "current_inputs_path", "current_profile_path", "current_text_scope_accounting",
            "current_valid_body_receipt", "accepted_observable_events_receipt", "accepted_observable_events_prepared_ref", "accepted_observable_events_decision_ref")}, "authorizes_dispatch": False}
