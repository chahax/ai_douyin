"""Offline original-byte and decision-provenance tests; no visual approval."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_reference_compiler_v4 as compiler
from src.content_factory import creative_reference_intake_v5 as intake

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=")
NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
MODEL = "doubao-seedance-2-0-mini-260615"
ACCOUNT = "a" * 64
PROFILES = {"xiaolin": {"gender_presentation": "男性", "age_presentation": "二十多岁",
    "appearance": "东亚面孔，黑色短发，无胡须，自然五官", "wardrobe": "浅蓝长袖衬衫，深灰长裤，蓝色挂绳工牌"},
    "zhou": {"gender_presentation": "女性", "age_presentation": "四十岁左右",
    "appearance": "东亚面孔，黑色齐肩直发，自然妆容", "wardrobe": "米色西装外套，白色内搭，深色长裤"}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError("intake is strictly offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def manifest():
    return {"actors": [{"id": aid, "profile": {key: {"status": "known", "value": value}
        for key, value in profile.items()}} for aid, profile in PROFILES.items()],
        "scenes": [{"id": "meeting_room", "description": "灰色长桌与玻璃隔断"}]}


def fixture(tmp_path, *, segment_review=False, delegated=False, rejected=False):
    directory = tmp_path / "original"
    directory.mkdir()
    image = directory / "tail.png"
    image.write_bytes(PNG)
    sha = hashlib.sha256(PNG).hexdigest()
    service = {"id": "offline-original", "status": "succeeded", "model": MODEL,
        "created_at": int((NOW - timedelta(days=1)).timestamp()),
        "content": {"video_url": "https://offline.invalid/video?token=DO_NOT_INDEX",
            "last_frame_url": "https://offline.invalid/tail?token=DO_NOT_INDEX"}}
    raw = {"task_id": service["id"], "model": MODEL, "provider": "ark_api",
        "technical_status": "succeeded", "last_frame_source": "generation_service_original",
        "last_frame": str(image.resolve()), "last_frame_sha256": sha, "final": service,
        "provider_account_binding_sha256": ACCOUNT}
    receipt = save(directory / "receipt.json", raw)
    subjects = [{"subject_key": aid + "_visual", "entity_type": "actor", "entity_id": aid,
        "description": "合成测试角色 " + aid, "profile": deepcopy(profile)} for aid, profile in PROFILES.items()]
    subjects.append({"subject_key": "office", "entity_type": "scene", "entity_id": "meeting_room", "description": "合成测试会议室",
        "scene_spec": {"description": "灰色长桌与玻璃隔断"}})
    approval = {"schema": "creative_asset_subject_adoption/v1", "decision": "rejected" if rejected else "approved",
        "decision_source": "delegated_assistant_selection" if delegated else "explicit_user_statement",
        "user_statement": "离线测试模拟原图批准，不是实际采用。", "asset_id": "tail",
        "asset_sha256": sha, "original_task_id": service["id"], "original_receipt_sha256": receipt["sha256"],
        "all_visual_subjects_mapped": True, "contains_portrait": True, "subject_mappings": subjects}
    if delegated:
        approval["authorization"] = {"user_statement": "离线模拟委托选取，不是逐图采用"}
    if segment_review:
        approval = {"schema": "media_user_review/v1", "decision": "rejected" if rejected else "approved",
            "decision_source": "explicit_user_statement", "user_statement": "首段通过，使用原始尾帧继续",
            "source_receipt_sha256": "b" * 64,
            "raw_tail_sha256": sha, "candidate_identity": {"identifiers": {"task_id": service["id"]},
                "raw_tail_sha256": sha}}
    adoption = save(directory / "receipt.human_review.json", approval)
    candidate = {"asset_id": "tail", "kind": "image", "role": "reference_image", "mime_type": "image/png",
        "local_path": str(image.resolve()), "sha256": sha, "receipt": receipt, "adoption": adoption,
        "artifact_key": "last_frame"}
    return candidate, raw, approval


def inspect(candidate, tmp_path):
    return intake.inspect_candidate(candidate, manifest(), allowed_roots=[tmp_path], now=NOW)


def rewrite(candidate, field, value):
    candidate[field] = save(Path(candidate[field]["path"]), value)


def test_current_cast_matches_only_exact_four_attributes_and_subject_coverage(tmp_path):
    candidate, _, _ = fixture(tmp_path)
    result = inspect(candidate, tmp_path)
    assert result["status"] == "metadata_ready_for_compiler"
    assert result["cast_compatibility"] == "metadata_matches_current_manifest"
    assert result["adoption_category"] == "historical_explicit_asset_approved"
    assert result["new_generation_calls"] == 0 and not result["media_content_inspected"]
    assert "DO_NOT_INDEX" not in json.dumps(result)
    assert result["provider_portrait_eligibility"] == "not_checked"


@pytest.mark.parametrize("attribute", list(PROFILES["xiaolin"]))
def test_old_cast_wrong_gender_age_hair_or_clothing_is_rejected(tmp_path, attribute):
    candidate, _, approval = fixture(tmp_path)
    approval["subject_mappings"][0]["profile"][attribute] = "错误旧角色"
    rewrite(candidate, "adoption", approval)
    result = inspect(candidate, tmp_path)
    assert result["status"] == "rejected_for_current_source"
    assert "CURRENT_CAST_PROFILE_MISMATCH" in result["reasons"]


def test_segment_approval_is_not_reassigned_to_new_current_cast(tmp_path):
    candidate, _, _ = fixture(tmp_path, segment_review=True)
    result = inspect(candidate, tmp_path)
    assert result["status"] == "pending"
    assert result["adoption_category"] == "historical_segment_approved"
    assert result["cast_compatibility"] == "unknown"
    assert "CURRENT_SUBJECT_MAPPING_MISSING" in result["reasons"]
    assert result["current_receipt_differs_from_historical_review_snapshot"]


@pytest.mark.parametrize("segment", [True, False])
def test_rejected_old_batch_is_not_reused_even_if_names_match(tmp_path, segment):
    candidate, _, _ = fixture(tmp_path, segment_review=segment, rejected=True)
    result = inspect(candidate, tmp_path)
    assert result["status"] == "rejected_for_current_source"
    assert result["adoption_category"] == "historical_rejected"
    assert "ORIGINAL_ASSET_REJECTED" in result["reasons"]


def test_delegated_choice_kept_distinct_and_blocked_by_existing_v4(tmp_path):
    candidate, _, _ = fixture(tmp_path, delegated=True)
    result = inspect(candidate, tmp_path)
    assert result["status"] == "pending"
    assert result["adoption_category"] == "delegated_selection"
    with pytest.raises(intake.ReferenceIntakeError, match="SELECTED_REFERENCE_NOT_COMPATIBLE"):
        intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
            output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL)
    assert not (tmp_path / "normalized").exists()


@pytest.mark.parametrize("change,expected", [("bytes", "ORIGINAL_BYTES_CHANGED"),
    ("task", "ORIGINAL_TASK_BINDING_INVALID"), ("sha", "ORIGINAL_TASK_BINDING_INVALID"),
    ("source", "ORIGINAL_TASK_BINDING_INVALID"), ("adoption_task", "EXPLICIT_ADOPTION_BINDING_INVALID"),
    ("subject", "CURRENT_CAST_ENTITY_MISMATCH"), ("coverage", "COMPLETE_VISUAL_SUBJECT_COVERAGE_UNKNOWN"),
    ("portrait", "PORTRAIT_SUBJECT_COVERAGE_UNKNOWN")])
def test_evidence_and_subject_changes_fail_without_repair(tmp_path, change, expected):
    candidate, raw, approval = fixture(tmp_path)
    if change == "bytes":
        Path(candidate["local_path"]).write_bytes(PNG + b"changed")
    elif change in {"task", "sha", "source"}:
        raw[{"task": "task_id", "sha": "last_frame_sha256", "source": "last_frame_source"}[change]] = "wrong"
        rewrite(candidate, "receipt", raw)
    elif change == "adoption_task": approval["original_task_id"] = "other"
    elif change == "subject": approval["subject_mappings"][0]["entity_id"] = "zhou_old"
    elif change == "coverage": approval.pop("all_visual_subjects_mapped")
    elif change == "portrait": approval["contains_portrait"] = False
    if change in {"adoption_task", "subject", "coverage", "portrait"}: rewrite(candidate, "adoption", approval)
    result = inspect(candidate, tmp_path)
    assert result["status"] != "metadata_ready_for_compiler"
    assert expected in result["reasons"]


def test_missing_adoption_stays_pending_and_scene_not_invented(tmp_path):
    candidate, _, _ = fixture(tmp_path)
    candidate["adoption"] = None
    inventory = intake.build_inventory([candidate], manifest(), allowed_roots=[tmp_path])
    assert inventory["ready_asset_ids"] == []
    assert not inventory["complete_identity_assets_available"]
    assert all(row["status"] == "pending_original_compatible_reference" for row in inventory["required_entities"])


def test_full_image_cannot_be_silently_used_as_pure_office(tmp_path):
    candidate, _, approval = fixture(tmp_path)
    approval["subject_mappings"] = approval["subject_mappings"][2:]
    rewrite(candidate, "adoption", approval)
    result = inspect(candidate, tmp_path)
    assert "PORTRAIT_SUBJECT_COVERAGE_UNKNOWN" in result["reasons"]


def test_exact_explicit_original_is_normalized_without_changing_source_and_compiles(tmp_path):
    candidate, raw, approval = fixture(tmp_path)
    original = deepcopy(candidate)
    narrative = "周姐和小林在会议室隔桌对坐。"
    contract = intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
        output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL,
        input_account_binding_sha256=ACCOUNT, narrative_text=narrative, now=NOW)
    assert candidate == original
    assert json.loads(Path(candidate["receipt"]["path"]).read_text(encoding="utf-8")) == raw
    assert json.loads(Path(candidate["adoption"]["path"]).read_text(encoding="utf-8")) == approval
    normalized = json.loads(Path(contract["assets"][0]["original"]["path"]).read_text(encoding="utf-8"))
    assert normalized["intake_provenance"]["source_receipt"] == original["receipt"]
    get_body = save(tmp_path / "original_get.json", raw["final"])
    get = {"tail": {"method": "GET", "http_status": 200, "requested_task_id": raw["task_id"],
        "provider_id": "ark_api", "account_binding_sha256": ACCOUNT, "received_at": NOW.isoformat(), "response_body": get_body}}
    result = compiler.build_director_visual_messages([{"role": "user", "content": "original full script"}],
        contract, ["tail"], now=NOW, expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert result["coverage"]["ordered_images"][0]["asset_id"] == "tail"
    assert all(row["status"] == "unbound" for row in contract["voices"])
    with pytest.raises(FileExistsError):
        intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
            output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL)


def test_no_provider_get_is_fabricated_by_normalization(tmp_path):
    candidate, _, _ = fixture(tmp_path)
    contract = intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
        output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL,
        input_account_binding_sha256=ACCOUNT, now=NOW)
    with pytest.raises(compiler.ReferenceCompilerError, match="NATIVE_GET_EVIDENCE_MISSING"):
        compiler.build_director_visual_messages([{"role": "user", "content": "full script"}],
            contract, ["tail"], now=NOW, expected_account_binding_sha256=ACCOUNT)


def test_current_scene_spec_and_original_provider_must_match_before_writes(tmp_path):
    candidate, _, approval = fixture(tmp_path)
    approval["subject_mappings"][2]["scene_spec"] = {"description": "另一栋楼的办公室"}
    rewrite(candidate, "adoption", approval)
    assert "CURRENT_SCENE_SPEC_MISMATCH" in inspect(candidate, tmp_path)["reasons"]
    approval["subject_mappings"][2]["scene_spec"] = {"description": "灰色长桌与玻璃隔断"}
    rewrite(candidate, "adoption", approval)
    with pytest.raises(intake.ReferenceIntakeError, match="ORIGINAL_PROVIDER_MISMATCH"):
        intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
            output_dir=tmp_path / "not_created", allowed_roots=[tmp_path], provider_id="other", model=MODEL)
    assert not (tmp_path / "not_created").exists()


def test_ark_portrait_and_other_provider_nonportrait_scene_compile_actual_images(tmp_path):
    portrait, raw, adoption = fixture(tmp_path)
    # The actor picture has only the two explicitly mapped actor subjects.
    adoption["subject_mappings"] = adoption["subject_mappings"][:2]
    rewrite(portrait, "adoption", adoption)
    scene_path = tmp_path / "scene_original.png"
    scene_path.write_bytes(PNG)
    scene_sha = hashlib.sha256(PNG).hexdigest()
    scene_receipt = {"task_id": "offline-other-provider-scene", "model": "offline-scene-image-model",
        "provider_id": "other_image_provider", "status": "succeeded", "source": "generation_service_original",
        "artifacts": {"image": {"path": str(scene_path.resolve()), "sha256": scene_sha,
            "kind": "image", "mime_type": "image/png", "service_content_key": "image_url"}},
        "service_result": {"id": "offline-other-provider-scene", "status": "succeeded",
            "model": "offline-scene-image-model", "content": {"image_url": "https://offline.invalid/environment"}}}
    receipt_binding = save(tmp_path / "scene_original_receipt.json", scene_receipt)
    scene_adoption = {"schema": "creative_asset_subject_adoption/v1", "decision": "approved",
        "decision_source": "explicit_user_statement", "user_statement": "离线模拟原场景图片批准，无实际用户采用。",
        "asset_id": "office", "asset_sha256": scene_sha, "original_task_id": scene_receipt["task_id"],
        "original_receipt_sha256": receipt_binding["sha256"], "all_visual_subjects_mapped": True,
        "contains_portrait": False, "subject_mappings": [{"subject_key": "office_visual", "entity_type": "scene",
            "entity_id": "meeting_room", "description": "合成无人物会议室",
            "scene_spec": {"description": "灰色长桌与玻璃隔断"}}]}
    scene = {"asset_id": "office", "kind": "image", "role": "reference_image", "artifact_key": "image",
        "mime_type": "image/png", "local_path": str(scene_path.resolve()), "sha256": scene_sha,
        "receipt": receipt_binding, "adoption": save(tmp_path / "scene_adoption.json", scene_adoption)}
    contract = intake.build_binding_contract([portrait, scene], manifest(), selected_asset_ids=["tail", "office"],
        output_dir=tmp_path / "mixed_binding", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL,
        input_account_binding_sha256=ACCOUNT, now=NOW)
    assert contract["provider_id"] == "ark_api"
    assert contract["assets"][0]["original"]["provider_id"] == "ark_api"
    assert contract["assets"][1]["original"]["provider_id"] == "other_image_provider"
    normalized_scene = json.loads(Path(contract["assets"][1]["original"]["path"]).read_text(encoding="utf-8"))
    assert normalized_scene["provider_id"] == "other_image_provider"
    assert contract["assets"][1]["eligibility"]["route"] == "non_portrait"
    get_body = save(tmp_path / "actor_get.json", raw["final"])
    get = {"tail": {"method": "GET", "http_status": 200, "requested_task_id": raw["task_id"],
        "provider_id": "ark_api", "account_binding_sha256": ACCOUNT, "received_at": NOW.isoformat(), "response_body": get_body}}
    result = compiler.build_director_visual_messages([{"role": "user", "content": "保留整片正文和参考全文"}],
        contract, ["tail", "office"], now=NOW, expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert [row["asset_id"] for row in result["coverage"]["ordered_images"]] == ["tail", "office"]
    parts = result["messages"][-1]["content"]
    assert [row["type"] for row in parts] == ["text", "image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_other_provider_portrait_rejected_before_any_normalization_write(tmp_path):
    candidate, raw, adoption = fixture(tmp_path)
    raw["provider"] = "other_image_provider"
    rewrite(candidate, "receipt", raw)
    adoption["original_receipt_sha256"] = candidate["receipt"]["sha256"]
    rewrite(candidate, "adoption", adoption)
    assert inspect(candidate, tmp_path)["status"] == "metadata_ready_for_compiler"
    with pytest.raises(intake.ReferenceIntakeError, match="ORIGINAL_PROVIDER_MISMATCH"):
        intake.build_binding_contract([candidate], manifest(), selected_asset_ids=["tail"],
            output_dir=tmp_path / "cross_provider_portrait", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL)
    assert not (tmp_path / "cross_provider_portrait").exists()


def test_missing_original_path_is_a_typed_intake_rejection(tmp_path):
    candidate, _, _ = fixture(tmp_path)
    candidate["local_path"] = None
    assert inspect(candidate, tmp_path)["reasons"] == ["ORIGINAL_EVIDENCE_MISSING"]


def test_discovery_is_explicit_directory_only_and_does_not_scan_test_tree(tmp_path):
    candidate, _, _ = fixture(tmp_path, segment_review=True)
    found = intake.discover_legacy_tail_candidates([tmp_path / "original"], allowed_roots=[tmp_path])
    assert len(found) == 1 and found[0]["sha256"] == candidate["sha256"]
    assert "DO_NOT_INDEX" not in json.dumps(found)


def test_legacy_png_filename_with_jpeg_original_bytes_uses_actual_mime(tmp_path):
    candidate, raw, approval = fixture(tmp_path, segment_review=True)
    # Synthetic signature-only bytes; this is not a production JPEG or a visual
    # assessment.  Saved Ark tails may use .png while delivering JPEG bytes.
    jpeg = b"\xff\xd8\xff\xe0OFFLINE_SYNTHETIC_JPEG_SIGNATURE"
    Path(candidate["local_path"]).write_bytes(jpeg)
    sha = hashlib.sha256(jpeg).hexdigest()
    raw["last_frame_sha256"] = sha
    save(Path(candidate["receipt"]["path"]), raw)
    approval["raw_tail_sha256"] = sha
    approval["candidate_identity"]["raw_tail_sha256"] = sha
    save(Path(candidate["adoption"]["path"]), approval)
    found = intake.discover_legacy_tail_candidates([tmp_path / "original"], allowed_roots=[tmp_path])
    assert found[0]["mime_type"] == "image/jpeg"
    assert found[0]["local_path"].endswith(".png")
    result = inspect(found[0], tmp_path)
    assert result["original_bytes_verified"]
    assert result["adoption_category"] == "historical_segment_approved"
    assert result["status"] == "pending"


def test_outside_root_and_duplicate_candidate_fail(tmp_path):
    candidate, _, _ = fixture(tmp_path)
    result = intake.inspect_candidate(candidate, manifest(), allowed_roots=[tmp_path / "none"])
    assert result["reasons"] == ["EVIDENCE_OUTSIDE_ALLOWED_ROOT"]
    with pytest.raises(intake.ReferenceIntakeError, match="ASSET_ID_DUPLICATE"):
        intake.build_inventory([candidate, candidate], manifest(), allowed_roots=[tmp_path])
