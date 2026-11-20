"""Synthetic byte/evidence fixtures; no service requests or visual adoption."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import socket

import pytest

from src.content_factory import creative_reference_compiler_v4 as refs

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
MODEL = "doubao-seedance-2-0-mini-260615"
ACCOUNT = "a" * 64
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=")
NARRATIVE = "小林看清纸上写着个人原因，抬头问周姐。保持原对白与刺激反应。"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("reference compiler tests are strictly offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def create_asset(tmp_path, aid, kind, role, entity_type, entity_id, *, native=False):
    """A real tiny synthetic PNG; video/audio are explicitly nonplayable fixtures."""
    path = tmp_path / (aid + {"image": ".png", "video": ".mp4", "audio": ".wav"}[kind])
    path.write_bytes(PNG if kind == "image" else b"OFFLINE_SYNTHETIC_SERVICE_OUTPUT_NOT_PLAYABLE_" + aid.encode())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    mime = {"image": "image/png", "video": "video/mp4", "audio": "audio/wav"}[kind]
    artifact_key = "last_frame" if role == "first_frame" else kind
    content_key = artifact_key + "_url"
    url = "https://offline.invalid/original/" + aid
    subject = {"subject_key": aid + "_subject", "entity_type": entity_type,
        "entity_id": entity_id, "description": "明确合成夹具主体 " + entity_id}
    receipt = {"task_id": "offline-task-" + aid, "provider_id": "ark_api", "model": MODEL,
        "status": "succeeded", "source": "generation_service_original", "completed_at": (NOW - timedelta(days=1)).isoformat(),
        "provider_account_binding_sha256": ACCOUNT,
        "artifacts": {artifact_key: {"path": str(path), "sha256": sha, "kind": kind,
            "mime_type": mime, "service_content_key": content_key,
            "duration_seconds": 5 if kind == "video" else 3 if kind == "audio" else None}},
        "service_result": {"id": "offline-task-" + aid, "status": "succeeded", "model": MODEL,
            "created_at": int((NOW - timedelta(days=1)).timestamp()),
            "content": {content_key: url}}}
    origin = save(tmp_path / (aid + ".receipt.json"), receipt)
    origin.update(task_id=receipt["task_id"], artifact_key=artifact_key, provider_id="ark_api")
    review = {"decision": "approved", "decision_source": "explicit_user_statement",
        "user_statement": "离线模拟批准主体映射；不是实际用户采用或生产授权。",
        "asset_id": aid, "asset_sha256": sha, "original_task_id": receipt["task_id"],
        "original_receipt_sha256": origin["sha256"], "subject_mappings": [deepcopy(subject)]}
    approval = save(tmp_path / (aid + ".approval.json"), review)
    asset = {"asset_id": aid, "kind": kind, "role": role, "local_path": str(path), "sha256": sha,
        "mime_type": mime, "original": origin, "approval": approval, "subjects": [subject],
        "independent_image": kind == "image",
        "eligibility": {"route": "native_generated_portrait" if native else "non_portrait",
            "input_url_expires_at": (NOW + timedelta(hours=1)).isoformat()}}
    if kind != "image":
        asset["input_url"] = url
    get_body = save(tmp_path / (aid + ".get.raw.json"), receipt["service_result"])
    get_evidence = {"method": "GET", "http_status": 200, "requested_task_id": receipt["task_id"],
        "provider_id": "ark_api", "account_binding_sha256": ACCOUNT,
        "received_at": (NOW - timedelta(minutes=5)).isoformat(), "response_body": get_body}
    mapping = {"binding_id": "bind-" + aid, "entity_type": entity_type, "entity_id": entity_id,
        "asset_id": aid, "subject_key": subject["subject_key"]}
    return asset, mapping, get_evidence


def mixed_fixture(tmp_path):
    # Purposefully use a non-kind-sorted actual order: audio, image, video.
    audio, voice, audio_get = create_asset(tmp_path, "voice", "audio", "reference_audio", "voice", "xiaolin")
    scene, scene_map, scene_get = create_asset(tmp_path, "office", "image", "reference_image", "scene", "meeting_room")
    video, actor_map, actor_get = create_asset(tmp_path, "actor", "video", "reference_video", "actor", "xiaolin", native=True)
    contract = {"schema": refs.BINDING_SCHEMA, "provider_id": "ark_api", "model": MODEL,
        "mode": "multimodal_reference", "input_account_binding_sha256": ACCOUNT,
        "narrative_text_sha256": hashlib.sha256(NARRATIVE.encode()).hexdigest(),
        "assets": [audio, scene, video], "entity_bindings": [voice, scene_map, actor_map],
        "required_entities": [{"entity_type": row["entity_type"], "entity_id": row["entity_id"]}
            for row in [voice, scene_map, actor_map]],
        "voices": [{"actor_id": "xiaolin", "status": "bound", "binding_id": "bind-voice"}]}
    payload = {"model": MODEL, "content": [{"type": "text", "text": NARRATIVE}],
        "duration": 8, "resolution": "480p", "ratio": "9:16", "generate_audio": True,
        "return_last_frame": True, "watermark": False}
    return payload, contract, {"actor": actor_get}


def compile_mixed(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    compiled = refs.compile_reference_request(payload, contract, now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    return payload, contract, get, compiled


def first_frame_fixture(tmp_path):
    asset, mapping, get = create_asset(tmp_path, "tail", "image", "first_frame", "actor", "xiaolin", native=True)
    continuation = {"previous_task_id": asset["original"]["task_id"], "script_sha256": "b" * 64,
        "fixed_identity_sha256": "c" * 64, "completed_source_refs": ["B1.S01"]}
    receipt = json.loads((tmp_path / "tail.receipt.json").read_text(encoding="utf-8"))
    receipt["continuation_binding"] = continuation
    saved = save(tmp_path / "tail.receipt.json", receipt)
    asset["original"].update(saved)
    review = json.loads((tmp_path / "tail.approval.json").read_text(encoding="utf-8"))
    review.update(original_receipt_sha256=saved["sha256"], continuation_binding=continuation)
    asset["approval"] = save(tmp_path / "tail.approval.json", review)
    contract = {"schema": refs.BINDING_SCHEMA, "provider_id": "ark_api", "model": MODEL,
        "mode": "first_frame", "input_account_binding_sha256": ACCOUNT,
        "narrative_text_sha256": hashlib.sha256(NARRATIVE.encode()).hexdigest(),
        "assets": [asset], "entity_bindings": [mapping],
        "required_entities": [{"entity_type": "actor", "entity_id": "xiaolin"}],
        "voices": [], "continuation": continuation}
    return {"model": MODEL, "content": [{"type": "text", "text": NARRATIVE}],
        "duration": 8, "ratio": "9:16", "resolution": "480p"}, contract, {"tail": get}


def test_actual_content_order_derives_kind_numbering_and_covers_prompt(tmp_path):
    original, contract, get, result = compile_mixed(tmp_path)
    assert original["content"] == [{"type": "text", "text": NARRATIVE}]
    assert [row["reference_label"] for row in result["coverage"]["ordered_references"]] == ["audio1", "image1", "video1"]
    assert [row["content_index"] for row in result["coverage"]["ordered_references"]] == [1, 2, 3]
    assert result["payload"]["content"][0]["text"].startswith(NARRATIVE)
    assert result["coverage"]["actual_payload_sha256"] == refs.digest(result["payload"])
    assert result["coverage"]["voice_bindings"][0]["status"] == "bound"
    assert result["coverage"]["provider_input_acceptance"] == "unknown"
    assert not result["coverage"]["assistant_pixel_identity_verified"]
    assert not result["calls_authorized"] and result["new_paid_calls"] == 0
    assert refs.validate_actual_reference_request(result["payload"], contract, now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get) == result["coverage"]


@pytest.mark.parametrize("change,code", [
    ("order", "ACTUAL_REFERENCE_BINDING_MISMATCH"),
    ("url", "ACTUAL_REFERENCE_BINDING_MISMATCH"),
    ("image_bytes", "ACTUAL_REFERENCE_BINDING_MISMATCH"),
    ("drop_map_text", "ACTUAL_PROMPT_MAPPING_MISSING"),
    ("narrative", "ACTUAL_NARRATIVE_CHANGED"),
    ("model", "ACTUAL_MODEL_MISMATCH"),
    ("drop_ref", "ACTUAL_REFERENCE_COUNT_MISMATCH")])
def test_actual_payload_changes_fail_without_repair(tmp_path, change, code):
    _, contract, get, result = compile_mixed(tmp_path)
    payload = deepcopy(result["payload"])
    if change == "order": payload["content"][1], payload["content"][2] = payload["content"][2], payload["content"][1]
    elif change == "url": payload["content"][3]["video_url"]["url"] += "/edited"
    elif change == "image_bytes": payload["content"][2]["image_url"]["url"] = "data:image/png;base64," + base64.b64encode(PNG + b"EDITED").decode()
    elif change == "drop_map_text": payload["content"][0]["text"] = NARRATIVE
    elif change == "narrative": payload["content"][0]["text"] = "编辑原对白" + payload["content"][0]["text"]
    elif change == "model": payload["model"] = "other-model"
    elif change == "drop_ref": payload["content"].pop()
    with pytest.raises(refs.ReferenceCompilerError, match=code):
        refs.validate_actual_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


@pytest.mark.parametrize("change,code", [
    ("no_origin", "ORIGINAL_EVIDENCE_MISSING"),
    ("original_bytes", "ORIGINAL_BYTES_CHANGED"),
    ("approval_flag", "ORIGINAL_EVIDENCE_MISSING"),
    ("unapproved", "EXPLICIT_APPROVAL_INVALID"),
    ("subject", "SUBJECT_MAPPING_INVALID"),
    ("missing_required", "REQUIRED_ENTITY_BINDING_MISSING"),
    ("missing_required_contract", "REQUIRED_ENTITIES_MISSING"),
    ("voice_claim", "VOICE_INPUT_UNBOUND"),
    ("url_expiry", "INPUT_URL_EXPIRED"),
    ("get_absent", "NATIVE_GET_EVIDENCE_MISSING"),
    ("get_flag", "NATIVE_GET_EVIDENCE_INVALID"),
    ("get_task", "NATIVE_GET_TASK_MISMATCH"),
    ("get_stale", "NATIVE_GET_EVIDENCE_STALE"),
    ("account", "NATIVE_ACCOUNT_MISMATCH")])
def test_evidence_and_subject_failures_are_not_verified_booleans(tmp_path, change, code):
    payload, contract, get = mixed_fixture(tmp_path)
    actor = contract["assets"][2]
    if change == "no_origin": actor.pop("original")
    elif change == "original_bytes": (tmp_path / "actor.mp4").write_bytes(b"CHANGED")
    elif change == "approval_flag": actor["approval"] = {"verified": True, "decision": "approved"}
    elif change == "unapproved":
        review = json.loads((tmp_path / "actor.approval.json").read_text(encoding="utf-8"))
        review["decision"] = "pending"
        actor["approval"] = save(tmp_path / "actor.approval.json", review)
    elif change == "subject": contract["entity_bindings"][2]["entity_id"] = "zhou"
    elif change == "missing_required": contract["required_entities"].append({"entity_type": "actor", "entity_id": "zhou"})
    elif change == "missing_required_contract": contract.pop("required_entities")
    elif change == "voice_claim": contract["voices"][0]["binding_id"] = "fictional_voice_name"
    elif change == "url_expiry": actor["eligibility"]["input_url_expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif change == "get_absent": get = None
    elif change == "get_flag": get = {"actor": {"verified": True}}
    elif change == "get_task":
        body = {"id": "other-task", "status": "succeeded"}
        get["actor"]["response_body"] = save(tmp_path / "actor.get.raw.json", body)
    elif change == "get_stale": get["actor"]["received_at"] = (NOW - timedelta(hours=25)).isoformat()
    elif change == "account": contract["input_account_binding_sha256"] = "d" * 64
    with pytest.raises(refs.ReferenceCompilerError, match=code):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_formal_original_tail_has_source_and_identity_binding(tmp_path):
    payload, contract, get = first_frame_fixture(tmp_path)
    current = deepcopy(contract["continuation"])
    result = refs.compile_reference_request(payload, contract, now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get, expected_continuation=current)
    assert result["payload"]["content"][1]["role"] == "first_frame"
    assert result["coverage"]["input_mode"] == "first_frame"
    assert result["coverage"]["voice_bindings"][0]["status"] == "unbound"
    contract["continuation"]["completed_source_refs"] = ["B7.S01"]
    with pytest.raises(refs.ReferenceCompilerError, match="CURRENT_CONTINUATION_BINDING_MISMATCH"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get, expected_continuation=current)


@pytest.mark.parametrize("mode", ["first_frame", "multimodal_reference"])
def test_frame_modes_are_never_silently_mixed(tmp_path, mode):
    payload, contract, get = mixed_fixture(tmp_path)
    contract["mode"] = mode
    contract["assets"][1]["role"] = "first_frame"
    with pytest.raises(refs.ReferenceCompilerError, match="FRAME_REFERENCE_MODE_MIXED"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_native_trust_window_is_separate_from_active_url(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    actor = contract["assets"][2]
    receipt = json.loads((tmp_path / "actor.receipt.json").read_text(encoding="utf-8"))
    receipt["completed_at"] = (NOW - timedelta(days=31)).isoformat()
    receipt["service_result"]["created_at"] = int((NOW - timedelta(days=31)).timestamp())
    actor["original"].update(save(tmp_path / "actor.receipt.json", receipt))
    review = json.loads((tmp_path / "actor.approval.json").read_text(encoding="utf-8"))
    review["original_receipt_sha256"] = actor["original"]["sha256"]
    actor["approval"] = save(tmp_path / "actor.approval.json", review)
    get["actor"]["response_body"] = save(tmp_path / "actor.get.raw.json", receipt["service_result"])
    assert datetime.fromisoformat(actor["eligibility"]["input_url_expires_at"]) > NOW
    with pytest.raises(refs.ReferenceCompilerError, match="NATIVE_WINDOW_EXPIRED"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_director_receives_real_image_urls_without_replacing_fulltext(tmp_path):
    payload, contract, _ = mixed_fixture(tmp_path)
    # The visual feedback currently selects only the actual needed scene.
    messages = [{"role": "system", "content": "MiniMax导演合同"},
        {"role": "user", "content": json.dumps({"source_script": NARRATIVE,
            "reference_fulltext": "R01 完整参考教学全文，保留所有原文本。"}, ensure_ascii=False)}]
    result = refs.build_director_visual_messages(messages, contract, ["office"], now=NOW,
        required_entities=[{"entity_type": "scene", "entity_id": "meeting_room"}])
    assert result["messages"][:-1] == messages
    image = result["messages"][-1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(image.split(",", 1)[1]) == PNG
    assert result["coverage"]["actual_messages_sha256"] == refs.digest(result["messages"])
    assert result["coverage"]["original_messages_sha256"] == refs.digest(messages)
    assert result["coverage"]["entity_asset_mapping"][0]["reference_label"] == "image1"
    assert result["coverage"]["multimodal_message_index"] == 2
    assert not result["coverage"]["calls_authorized"]


def test_director_selected_images_cannot_drop_required_actor(tmp_path):
    _, contract, _ = mixed_fixture(tmp_path)
    with pytest.raises(refs.ReferenceCompilerError, match="REQUIRED_ENTITY_BINDING_MISSING"):
        refs.build_director_visual_messages([{"role": "user", "content": "原全文"}],
            contract, ["office"], now=NOW)


@pytest.mark.parametrize("entity_type", ["actor", "scene"])
def test_actor_and_scene_cannot_be_bound_to_audio(tmp_path, entity_type):
    payload, contract, get = mixed_fixture(tmp_path)
    audio = contract["assets"][0]
    audio["subjects"][0]["entity_type"] = entity_type
    contract["entity_bindings"][0]["entity_type"] = entity_type
    review = json.loads((tmp_path / "voice.approval.json").read_text(encoding="utf-8"))
    review["subject_mappings"] = deepcopy(audio["subjects"])
    audio["approval"] = save(tmp_path / "voice.approval.json", review)
    with pytest.raises(refs.ReferenceCompilerError, match="VISUAL_SUBJECT_INPUT_INVALID"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_empty_subjects_cannot_claim_ready_material(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    contract["assets"][1]["subjects"] = []
    with pytest.raises(refs.ReferenceCompilerError, match="SUBJECT_MAPPING_INVALID"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_director_rejects_whole_reference_board_declaration(tmp_path):
    _, contract, _ = mixed_fixture(tmp_path)
    contract["assets"][1]["independent_image"] = False
    with pytest.raises(refs.ReferenceCompilerError, match="DIRECTOR_SELECTION_INVALID"):
        refs.build_director_visual_messages([{"role": "user", "content": "全文"}], contract,
            ["office"], now=NOW, required_entities=[{"entity_type": "scene", "entity_id": "meeting_room"}])


def test_compile_does_not_replace_existing_adapter_references(tmp_path):
    payload, contract, get, compiled = compile_mixed(tmp_path)
    with pytest.raises(refs.ReferenceCompilerError, match="ACTUAL_CONTENT_INVALID"):
        refs.compile_reference_request(compiled["payload"], contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_native_model_prefix_or_seedream_name_does_not_grant_eligibility(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    actor = contract["assets"][2]
    receipt = json.loads((tmp_path / "actor.receipt.json").read_text(encoding="utf-8"))
    receipt["model"] = "doubao-seedance-2-0-unregistered-guessed-name"
    receipt["service_result"]["model"] = receipt["model"]
    actor["original"].update(save(tmp_path / "actor.receipt.json", receipt))
    review = json.loads((tmp_path / "actor.approval.json").read_text(encoding="utf-8"))
    review["original_receipt_sha256"] = actor["original"]["sha256"]
    actor["approval"] = save(tmp_path / "actor.approval.json", review)
    with pytest.raises(refs.ReferenceCompilerError, match="NATIVE_MODEL_UNSUPPORTED"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


def test_renewed_url_comes_from_same_original_task_get(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    actor = contract["assets"][2]
    body = json.loads((tmp_path / "actor.get.raw.json").read_text(encoding="utf-8"))
    body["content"]["video_url"] = "https://offline.invalid/renewed-by-original-task/actor"
    get["actor"]["response_body"] = save(tmp_path / "actor.get.raw.json", body)
    actor["input_url"] = body["content"]["video_url"]
    result = refs.compile_reference_request(payload, contract, now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert result["payload"]["content"][3]["video_url"]["url"] == actor["input_url"]
    assert result["coverage"]["ordered_references"][2]["provider_input_acceptance"] == "unknown"


def test_director_actual_face_tail_and_scene_inputs_preserve_selected_order(tmp_path):
    _, contract, get = first_frame_fixture(tmp_path)
    contract["mode"] = "multimodal_reference"
    contract["assets"][0]["role"] = "reference_image"
    scene, mapping, _ = create_asset(tmp_path, "office", "image", "reference_image", "scene", "meeting_room")
    contract["assets"].append(scene)
    contract["entity_bindings"].append(mapping)
    contract["required_entities"].append({"entity_type": "scene", "entity_id": "meeting_room"})
    messages = [{"role": "system", "content": "导演合同"}, {"role": "user", "content": "R01完整参考全文与完整正文"}]
    result = refs.build_director_visual_messages(messages, contract, ["office", "tail"], now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert [row["asset_id"] for row in result["coverage"]["ordered_images"]] == ["office", "tail"]
    mapped = {row["entity_id"]: row for row in result["coverage"]["entity_asset_mapping"]}
    assert mapped["meeting_room"]["reference_label"] == "image1"
    assert mapped["xiaolin"]["reference_label"] == "image2"
    assert result["messages"][:2] == messages
    assert result["coverage"]["provider_input_acceptance"] == "unknown"


def test_non_portrait_scene_can_reuse_another_image_provider_original(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    scene = contract["assets"][1]
    receipt = json.loads((tmp_path / "office.receipt.json").read_text(encoding="utf-8"))
    receipt["provider_id"] = "approved_existing_image_provider"
    receipt["model"] = "existing_image_model"
    scene["original"].update(save(tmp_path / "office.receipt.json", receipt))
    scene["original"]["provider_id"] = receipt["provider_id"]
    review = json.loads((tmp_path / "office.approval.json").read_text(encoding="utf-8"))
    review["original_receipt_sha256"] = scene["original"]["sha256"]
    scene["approval"] = save(tmp_path / "office.approval.json", review)
    result = refs.compile_reference_request(payload, contract, now=NOW,
        expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert result["coverage"]["ordered_references"][1]["native_metadata_qualification"] == "not_applicable"


def test_local_completion_time_cannot_renew_service_origin_window(tmp_path):
    payload, contract, get = mixed_fixture(tmp_path)
    actor = contract["assets"][2]
    receipt = json.loads((tmp_path / "actor.receipt.json").read_text(encoding="utf-8"))
    receipt["completed_at"] = NOW.isoformat()
    receipt["service_result"]["created_at"] = int((NOW - timedelta(days=31)).timestamp())
    actor["original"].update(save(tmp_path / "actor.receipt.json", receipt))
    review = json.loads((tmp_path / "actor.approval.json").read_text(encoding="utf-8"))
    review["original_receipt_sha256"] = actor["original"]["sha256"]
    actor["approval"] = save(tmp_path / "actor.approval.json", review)
    get["actor"]["response_body"] = save(tmp_path / "actor.get.raw.json", receipt["service_result"])
    with pytest.raises(refs.ReferenceCompilerError, match="NATIVE_WINDOW_EXPIRED"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)


@pytest.mark.parametrize("changed", ["script_sha256", "fixed_identity_sha256", "completed_source_refs", "previous_task_id"])
def test_first_frame_rejects_old_self_consistent_evidence_for_different_current_source(tmp_path, changed):
    payload, contract, get = first_frame_fixture(tmp_path)
    current = deepcopy(contract["continuation"])
    current[changed] = ["B9.S09"] if changed == "completed_source_refs" else "d" * 64
    # Even a new narrative with its own matching hash cannot renew old source.
    payload["content"][0]["text"] = "另一新剧情的完整段落"
    contract["narrative_text_sha256"] = hashlib.sha256(payload["content"][0]["text"].encode()).hexdigest()
    with pytest.raises(refs.ReferenceCompilerError, match="CURRENT_CONTINUATION_BINDING_MISMATCH"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get, expected_continuation=current)


def test_first_frame_requires_independent_current_source_input(tmp_path):
    payload, contract, get = first_frame_fixture(tmp_path)
    with pytest.raises(refs.ReferenceCompilerError, match="CURRENT_CONTINUATION_BINDING_UNKNOWN"):
        refs.compile_reference_request(payload, contract, now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
