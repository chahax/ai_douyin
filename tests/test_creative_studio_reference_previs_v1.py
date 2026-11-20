"""Explicit local geometry + original compiler fixtures, never media quality."""
import ast
from copy import deepcopy
import hashlib
import json
import math
import socket
from types import SimpleNamespace

import pytest

from src.content_factory import creative_studio_reference_previs_v1 as studio
from src.content_factory import creative_reference_compiler_v4 as refs
from tests.test_creative_reference_compiler_v4 import (
    ACCOUNT, NOW, NARRATIVE, MODEL, create_asset, first_frame_fixture, mixed_fixture,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("studio module must remain strictly offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def scene_fixture():
    """Complete assistant-authored synthetic geometry, explicitly provisional.

    The small manifest is an ID/provenance fixture, not a fully valid production
    shared manifest; validate_scene intentionally does not claim that gate.
    A production caller supplies the unchanged full existing shared manifest.
    """
    manifest = {"schema": studio.MANIFEST_SCHEMA, "script_sha256": "a" * 64,
                "actors": [{"id": "xiaolin"}, {"id": "zhou"}],
                "scenes": [{"id": "meeting_room"}],
                "props": [{"id": "table"}, {"id": "paper"}], "provenance_catalog": []}
    snapshot = {"units": "meters", "coordinate_system": "Z_UP_RIGHT_HANDED", "scene_id": "meeting_room",
        "bounds": {"min_m": [-3, -2, 0], "max_m": [3, 2, 3]},
        "entities": [
            {"entity_id": "xiaolin", "entity_type": "actor", "scene_id": "meeting_room",
             "pose": {"position_m": [-1, 0, 1], "rotation_deg": [0, 0, -90]},
             "proxy": {"shape": "capsule", "size_m": [0.5, 0.4, 1.5]}, "state": {"posture": "seated"}},
            {"entity_id": "zhou", "entity_type": "actor", "scene_id": "meeting_room",
             "pose": {"position_m": [1, 0, 1], "rotation_deg": [0, 0, 90]},
             "proxy": {"shape": "capsule", "size_m": [0.5, 0.4, 1.5]}, "state": {"posture": "seated"}},
            {"entity_id": "table", "entity_type": "prop", "scene_id": "meeting_room",
             "pose": {"position_m": [0, 0, 0.75], "rotation_deg": [0, 0, 0]},
             "proxy": {"shape": "box", "size_m": [1.5, 1, 0.05]},
             "state": {"holder_actor_id": None, "support": {"entity_type": "scene", "entity_id": "meeting_room"}}},
            {"entity_id": "paper", "entity_type": "prop", "scene_id": "meeting_room",
             "pose": {"position_m": [-0.4, 0, 0.78], "rotation_deg": [0, 0, 0]},
             "proxy": {"shape": "box", "size_m": [0.21, 0.297, 0.001]},
             "state": {"holder_actor_id": None, "support": {"entity_type": "prop", "entity_id": "table"}}},
        ], "camera": {"camera_id": "camera_M001", "position_m": [0, -1.9, 1.7],
                      "target_m": [0, 0, 1], "focal_length_mm": 24, "sensor_width_mm": 36,
                      "render_size_px": [640, 360]}}
    snapshot.update(segment_id="M001", time_seconds=0,
        structures=[{"structure_id": "env_door", "role": "door", "scene_id": "meeting_room",
            "pose": {"position_m": [2.1, 1.9, 1.1], "rotation_deg": [0, 0, 0]},
            "proxy": {"shape": "box", "size_m": [0.9, 0.1, 2.2]}}])
    for entity in snapshot["entities"]:
        entity["presence"] = "present"
    text = json.dumps({"snapshot": snapshot}, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    scene = {"schema": studio.SCENE_SCHEMA, "manifest_sha256": refs.digest(manifest),
             "script_sha256": manifest["script_sha256"], **deepcopy(snapshot),
             "source_state": {"status": "offline_fixture", "source_id": "offline_geometry", "source_pointer": "/snapshot", "source_sha256": sha},
             "geometry_provenance_catalog": [{"source_id": "offline_geometry", "origin": "offline_fixture",
                                               "author": "assistant", "text": text, "sha256": sha}]}
    return scene, manifest


def rebind_explicit_fixture(scene):
    snapshot = {key: deepcopy(scene[key]) for key in studio._SNAPSHOT_KEYS}
    text = json.dumps({"snapshot": snapshot}, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(text.encode()).hexdigest()
    scene["geometry_provenance_catalog"][0].update(text=text, sha256=sha)
    scene["source_state"]["source_sha256"] = sha


def test_explicit_geometry_is_deterministic_provisional_and_does_not_mutate_inputs():
    scene, manifest = scene_fixture()
    original = deepcopy((scene, manifest))
    bundle = studio.build_previs_bundle(scene, manifest)
    assert bundle == studio.build_previs_bundle(scene, manifest)
    assert (scene, manifest) == original
    assert bundle["validation"]["provisional"] is True
    assert bundle["validation"]["geometry_not_native_source"] is True
    assert bundle["validation"]["physics_simulated"] is False
    assert bundle["validation"]["director_desk_format_compatible"] is False
    assert not bundle["calls_authorized"] and bundle["new_paid_calls"] == 0
    assert bundle["renders_executed"] == 0
    ast.parse(bundle["blender_python"])
    assert hashlib.sha256(bundle["blender_python"].encode()).hexdigest() == bundle["blender_python_sha256"]
    assert json.loads(bundle["scene_json"]) == scene
    assert "bpy.data.scenes.new" in bundle["blender_python"]
    assert "bpy.ops.wm" not in bundle["blender_python"]
    assert "bpy.ops.render" not in bundle["blender_python"]
    assert "subprocess" not in bundle["blender_python"]
    assert "objects.remove" not in bundle["blender_python"]


def test_two_camera_exports_keep_contract_ids_when_blender_renames_objects():
    """Execute the export's identity loops with Blender-style name collisions.

    The fake provides object naming, properties and collection attachment only;
    this tests the emitted program, not Blender rendering or generated video.
    """
    _, manifest = scene_fixture()
    scenes = studio.build_offline_previs_example(manifest)["scenes"]
    sequence = studio.build_previs_sequence(scenes, manifest)
    objects = []

    class NamedProxy(dict):
        def __init__(self, name):
            self.data = SimpleNamespace(materials=[])
            self.users_collection = []
            self._name = None
            self.name = name
            objects.append(self)

        @property
        def name(self):
            return self._name

        @name.setter
        def name(self, requested):
            candidate, index = requested, 0
            while any(other is not self and other.name == candidate for other in objects):
                index += 1
                candidate = f"{requested}.{index:03d}"
            self._name = candidate

    attached = []
    collection = SimpleNamespace(objects=SimpleNamespace(link=attached.append))
    context = SimpleNamespace(object=None)

    def cube_add(**kwargs):
        context.object = NamedProxy("Cube")

    bpy = SimpleNamespace(context=context, ops=SimpleNamespace(mesh=SimpleNamespace(primitive_cube_add=cube_add)))
    exports = []
    for bundle in sequence["bundles"]:
        tree = ast.parse(bundle["blender_python"])
        # Use actual emitted DATA, bind_snapshot/attach and entity/structure loops.
        selected = [node for node in tree.body
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DATA" for t in node.targets)
                    or isinstance(node, ast.FunctionDef) and node.name in {"bind_snapshot", "attach"}
                    or isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id in {"entity", "structure"}]
        namespace = {"json": json, "math": math, "bpy": bpy, "collection": collection,
                     "white": object(), "capsule": lambda size: NamedProxy("creative_studio_actor_proxy")}
        start = len(objects)
        exec(compile(ast.Module(body=selected, type_ignores=[]), "<offline-export-id-test>", "exec"), namespace)
        exports.append(objects[start:])

    assert scenes[0]["camera"] != scenes[1]["camera"]
    for current, scene in zip(exports, scenes):
        expected_entities = {row["entity_id"] for row in scene["entities"] if row["presence"] == "present"}
        expected_structures = {row["structure_id"] for row in scene["structures"]}
        assert {obj["entity_id"] for obj in current if "entity_id" in obj} == expected_entities
        assert {obj["structure_id"] for obj in current if "structure_id" in obj} == expected_structures
        assert all(obj["scene_id"] == scene["scene_id"] and obj["segment_id"] == scene["segment_id"] for obj in current)
        assert all(("entity_id" in obj) != ("structure_id" in obj) for obj in current)
    # Both exports share stable IDs, despite globally unique display names.
    for first in exports[0]:
        key = "entity_id" if "entity_id" in first else "structure_id"
        second = next(obj for obj in exports[1] if obj.get(key) == first[key])
        assert second.name != first.name and second.name.endswith(".001")
        assert second[key] == first[key] and second["segment_id"] != first["segment_id"]


@pytest.mark.parametrize("change,code", [
    ("missing_pose", "SCENE_CONTRACT_INVALID"), ("missing_camera", "SCENE_CONTRACT_INVALID"),
    ("unknown_source", "SCENE_SOURCE_UNKNOWN"), ("units", "SCENE_SPACE_UNSUPPORTED"),
    ("axis", "SCENE_SPACE_UNSUPPORTED"), ("duplicate", "SCENE_DUPLICATE_ID"),
    ("wrong_actor", "SCENE_CAST_NOT_CLOSED"), ("another_room", "SCENE_SPACE_MIXED"),
    ("invalid_bounds", "SCENE_BOUNDS_INVALID"), ("outside", "SCENE_ENTITY_OUTSIDE_BOUNDS"),
    ("null_coordinate", "SCENE_NUMBER_INVALID"), ("bool_coordinate", "SCENE_NUMBER_INVALID"),
    ("nan_coordinate", "SCENE_NUMBER_INVALID"), ("negative_size", "SCENE_NUMBER_INVALID"),
    ("unknown_posture", "SCENE_POSE_UNKNOWN"), ("holder_is_prop", "SCENE_PROP_HOLDER_INVALID"),
    ("unknown_support", "SCENE_PROP_SUPPORT_INVALID"), ("support_cycle", "SCENE_PROP_SUPPORT_CYCLE"),
    ("camera_target", "SCENE_CAMERA_INVALID"), ("camera_lens", "SCENE_NUMBER_INVALID"),
    ("camera_size", "SCENE_CAMERA_INVALID"), ("proxy_script", "SCENE_PROXY_INVALID"),
    ("manifest", "SCENE_MANIFEST_MISMATCH"), ("script", "SCENE_MANIFEST_MISMATCH"),
])
def test_space_and_state_errors_are_blocked_without_completion(change, code):
    scene, manifest = scene_fixture()
    entity = scene["entities"][0]
    if change == "missing_pose": del entity["pose"]["position_m"]
    elif change == "missing_camera": del scene["camera"]
    elif change == "unknown_source": scene["source_state"]["status"] = "unknown"
    elif change == "units": scene["units"] = "centimeters"
    elif change == "axis": scene["coordinate_system"] = "Y_UP"
    elif change == "duplicate": scene["entities"].append(deepcopy(entity))
    elif change == "wrong_actor": entity["entity_id"] = "another_person"
    elif change == "another_room": entity["scene_id"] = "corridor"
    elif change == "invalid_bounds": scene["bounds"]["min_m"] = scene["bounds"]["max_m"]
    elif change == "outside": entity["pose"]["position_m"][0] = 9
    elif change == "null_coordinate": entity["pose"]["position_m"][0] = None
    elif change == "bool_coordinate": entity["pose"]["position_m"][0] = True
    elif change == "nan_coordinate": entity["pose"]["position_m"][0] = float("nan")
    elif change == "negative_size": entity["proxy"]["size_m"][0] = -1
    elif change == "unknown_posture": entity["state"]["posture"] = None
    elif change == "holder_is_prop": scene["entities"][3]["state"]["holder_actor_id"] = "table"
    elif change == "unknown_support": scene["entities"][3]["state"]["support"]["entity_id"] = "unknown_table"
    elif change == "support_cycle": scene["entities"][2]["state"]["support"] = {"entity_type": "prop", "entity_id": "paper"}
    elif change == "camera_target": scene["camera"]["target_m"] = scene["camera"]["position_m"]
    elif change == "camera_lens": scene["camera"]["focal_length_mm"] = 0
    elif change == "camera_size": scene["camera"]["render_size_px"] = [True, 360]
    elif change == "proxy_script": entity["proxy"]["shape"] = "python_eval"
    elif change == "manifest": manifest["actors"].append({"id": "new_actor"})
    elif change == "script": scene["script_sha256"] = "b" * 64
    with pytest.raises(studio.StudioReferencePrevisError, match=code):
        studio.build_previs_bundle(scene, manifest)


@pytest.mark.parametrize("change,code", [
    ("coordinate", "SCENE_GEOMETRY_SOURCE_MISMATCH"), ("state", "SCENE_GEOMETRY_SOURCE_MISMATCH"),
    ("source_text", "SCENE_SOURCE_CHANGED"), ("source_id", "SCENE_SOURCE_BINDING_INVALID"),
    ("source_hash", "SCENE_SOURCE_BINDING_INVALID"), ("pointer", "SCENE_SOURCE_POINTER_INVALID"),
    ("promote", "SCENE_SOURCE_ORIGIN_INVALID"), ("human", "SCENE_SOURCE_ORIGIN_INVALID"),
])
def test_geometry_provenance_is_exact_not_a_status_boolean(change, code):
    scene, manifest = scene_fixture()
    if change == "coordinate": scene["entities"][0]["pose"]["position_m"][0] += 0.1
    elif change == "state": scene["entities"][3]["state"]["holder_actor_id"] = "xiaolin"
    elif change == "source_text": scene["geometry_provenance_catalog"][0]["text"] += "changed"
    elif change == "source_id": scene["source_state"]["source_id"] = "missing"
    elif change == "source_hash": scene["source_state"]["source_sha256"] = "b" * 64
    elif change == "pointer": scene["source_state"]["source_pointer"] = "/not_present"
    elif change == "promote": scene["source_state"]["status"] = "known"
    elif change == "human": scene["geometry_provenance_catalog"][0]["author"] = "human"
    with pytest.raises(studio.StudioReferencePrevisError, match=code):
        studio.validate_scene(scene, manifest)


def test_known_geometry_needs_independent_manifest_source_and_never_pixel_approval():
    scene, manifest = scene_fixture()
    record = scene["geometry_provenance_catalog"][0]
    record.update(origin="explicit_geometry_declaration", author="human")
    scene["source_state"]["status"] = "known"
    with pytest.raises(studio.StudioReferencePrevisError, match="SCENE_INDEPENDENT_SOURCE_MISSING"):
        studio.validate_scene(scene, manifest)
    manifest["provenance_catalog"].append({"source_id": record["source_id"], "kind": "user_declaration",
                                          "text": record["text"], "sha256": record["sha256"]})
    scene["manifest_sha256"] = refs.digest(manifest)
    result = studio.validate_scene(scene, manifest)
    assert result["provisional"] is False
    assert result["assistant_pixel_identity_verified"] is False
    assert result["geometry_not_native_source"] is True
    assert result["production_adopted"] is False


def test_json_pointer_escaped_tokens_and_explicit_state_allow_ownership_distinction():
    scene, manifest = scene_fixture()
    scene["entities"][3]["state"]["holder_actor_id"] = "xiaolin"
    # Holder is independent of original declared ownership (not overwritten).
    manifest["props"][1]["owner"] = {"status": "known", "value": "company"}
    scene["manifest_sha256"] = refs.digest(manifest)
    record = scene["geometry_provenance_catalog"][0]
    text = json.dumps({"snap/shot~state": {key: scene[key] for key in studio._SNAPSHOT_KEYS}}, sort_keys=True)
    record.update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    scene["source_state"].update(source_pointer="/snap~1shot~0state", source_sha256=record["sha256"])
    assert studio.validate_scene(scene, manifest)["status"] == "scene_valid"
    assert manifest["props"][1]["owner"]["value"] == "company"


def test_media_projection_calls_real_compiler_once_and_numbers_selected_wire_order(tmp_path, monkeypatch):
    payload, contract, get = mixed_fixture(tmp_path)
    before = deepcopy((payload, contract))
    actual, calls = refs.compile_reference_request, []
    def spy(*args, **kwargs):
        calls.append(True)
        return actual(*args, **kwargs)
    monkeypatch.setattr(refs, "compile_reference_request", spy)
    result = studio.compile_reference_projection(contract, ["actor", "office", "voice"], mode="multimodal_reference",
        payload=payload, now=NOW, expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert calls == [True]
    assert (payload, contract) == before
    assert [row["reference_label"] for row in result["ordered_roles"]] == ["video1", "image1", "audio1"]
    assert [row["asset_id"] for row in result["ordered_roles"]] == ["actor", "office", "voice"]
    assert result["compiler_result"]["payload"]["content"][0]["text"].startswith(NARRATIVE)
    assert result["compiler_result"]["coverage"]["provider_input_acceptance"] == "unknown"
    assert result["media_status_after_save"] == "awaiting_human_review"
    assert not result["calls_authorized"] and result["new_paid_calls"] == 0


def director_fixture(tmp_path):
    scene, scene_map, _ = create_asset(tmp_path, "office", "image", "reference_image", "scene", "meeting_room")
    actor, actor_map, actor_get = create_asset(tmp_path, "portrait", "image", "reference_image", "actor", "xiaolin", native=True)
    # Native portrait eligibility needs an exact accepted original last frame.
    receipt = json.loads((tmp_path / "portrait.receipt.json").read_text(encoding="utf-8"))
    receipt["artifacts"]["last_frame"] = receipt["artifacts"].pop("image")
    receipt["artifacts"]["last_frame"]["service_content_key"] = "last_frame_url"
    receipt["service_result"]["content"]["last_frame_url"] = receipt["service_result"]["content"].pop("image_url")
    from tests.test_creative_reference_compiler_v4 import save
    origin = save(tmp_path / "portrait.receipt.json", receipt)
    actor["original"].update(origin, artifact_key="last_frame")
    review = json.loads((tmp_path / "portrait.approval.json").read_text(encoding="utf-8"))
    review["original_receipt_sha256"] = origin["sha256"]
    actor["approval"] = save(tmp_path / "portrait.approval.json", review)
    actor_get["response_body"] = save(tmp_path / "portrait.get.raw.json", receipt["service_result"])
    contract = {"schema": refs.BINDING_SCHEMA, "provider_id": "ark_api", "model": MODEL,
        "mode": "multimodal_reference", "input_account_binding_sha256": ACCOUNT,
        "assets": [scene, actor], "entity_bindings": [scene_map, actor_map], "voices": [],
        "required_entities": [{"entity_type": "actor", "entity_id": "xiaolin"}, {"entity_type": "scene", "entity_id": "meeting_room"}]}
    return [{"role": "user", "content": "完整原稿和教学参考，不能用文件名替代全文。"}], contract, {"portrait": actor_get}


def test_director_projection_real_original_image_bytes_and_source_messages(tmp_path, monkeypatch):
    messages, contract, get = director_fixture(tmp_path)
    before = deepcopy((messages, contract))
    actual, calls = refs.build_director_visual_messages, []
    def spy(*args, **kwargs):
        calls.append(True)
        return actual(*args, **kwargs)
    monkeypatch.setattr(refs, "build_director_visual_messages", spy)
    result = studio.compile_reference_projection(contract, ["portrait", "office"], mode="multimodal_reference",
        messages=messages, now=NOW, expected_account_binding_sha256=ACCOUNT, provider_get_evidence=get)
    assert calls == [True]
    assert (messages, contract) == before
    assert result["compiler_result"]["messages"][:-1] == messages
    assert [row["asset_id"] for row in result["ordered_roles"]] == ["portrait", "office"]
    assert result["ordered_roles"][0]["subjects"][0]["entity_id"] == "xiaolin"
    assert result["compiler_result"]["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result["geometry_used_as_identity_material"] is False


@pytest.mark.parametrize("change,code", [
    ("mode", "STUDIO_REFERENCE_MODE_MISMATCH"), ("mixed", "STUDIO_REFERENCE_MODE_MIXED"),
    ("both_channels", "STUDIO_REFERENCE_CHANNEL_INVALID"), ("no_channel", "STUDIO_REFERENCE_CHANNEL_INVALID"),
    ("duplicate", "STUDIO_REFERENCE_SELECTION_INVALID"), ("unknown", "STUDIO_REFERENCE_SELECTION_INVALID"),
    ("weaken", "STUDIO_REQUIRED_ENTITY_SCOPE_CHANGED"), ("missing_actor", "REQUIRED_ENTITY_BINDING_MISSING"),
    ("approval", "EXPLICIT_APPROVAL_INVALID"), ("no_native_account", "NATIVE_ACCOUNT_UNKNOWN"),
])
def test_reference_errors_cannot_be_fixed_by_geometry_or_filtering(tmp_path, change, code):
    messages, contract, get = director_fixture(tmp_path)
    mode, selected = "multimodal_reference", ["portrait", "office"]
    kwargs = {"messages": messages, "now": NOW, "expected_account_binding_sha256": ACCOUNT, "provider_get_evidence": get}
    if change == "mode": mode = "first_frame"
    elif change == "mixed": contract["assets"][0]["role"] = "first_frame"; selected = ["portrait"]
    elif change == "both_channels": kwargs["payload"] = {"model": MODEL, "content": [{"type": "text", "text": NARRATIVE}]}
    elif change == "no_channel": kwargs.pop("messages")
    elif change == "duplicate": selected.append("portrait")
    elif change == "unknown": selected.append("geometry_proxy")
    elif change == "weaken": kwargs["required_entities"] = [{"entity_type": "scene", "entity_id": "meeting_room"}]
    elif change == "missing_actor": selected = ["office"]
    elif change == "approval":
        approval = json.loads((tmp_path / "portrait.approval.json").read_text(encoding="utf-8"))
        approval["decision"] = "rejected"
        from tests.test_creative_reference_compiler_v4 import save
        contract["assets"][1]["approval"] = save(tmp_path / "portrait.approval.json", approval)
    elif change == "no_native_account": kwargs.pop("expected_account_binding_sha256")
    with pytest.raises((studio.StudioReferencePrevisError, refs.ReferenceCompilerError), match=code):
        studio.compile_reference_projection(contract, selected, mode=mode, **kwargs)


def test_formal_tail_current_source_required_and_old_identity_not_promoted(tmp_path):
    payload, contract, get = first_frame_fixture(tmp_path)
    kwargs = {"mode": "first_frame", "payload": payload, "now": NOW,
              "expected_account_binding_sha256": ACCOUNT, "provider_get_evidence": get}
    with pytest.raises(refs.ReferenceCompilerError, match="CURRENT_CONTINUATION_BINDING_UNKNOWN"):
        studio.compile_reference_projection(contract, ["tail"], **kwargs)
    current = deepcopy(contract["continuation"])
    result = studio.compile_reference_projection(contract, ["tail"], expected_continuation=current, **kwargs)
    assert result["ordered_roles"][0]["role"] == "first_frame"
    current["fixed_identity_sha256"] = "d" * 64
    with pytest.raises(refs.ReferenceCompilerError, match="CURRENT_CONTINUATION_BINDING_MISMATCH"):
        studio.compile_reference_projection(contract, ["tail"], expected_continuation=current, **kwargs)


def test_offline_example_shared_furniture_two_cameras_and_no_shared_manifest_mutation():
    _, manifest = scene_fixture()
    original = deepcopy(manifest)
    example = studio.build_offline_previs_example(manifest)
    assert manifest == original
    sequence = studio.build_previs_sequence(example["scenes"], manifest)
    assert sequence["validation"]["status"] == "scene_sequence_valid"
    assert sequence["validation"]["motion_validated"] is False
    assert sequence["validation"]["provisional"] is True
    first, second = example["scenes"]
    assert first["structures"] == second["structures"]
    assert first["camera"] != second["camera"]
    assert {row["role"] for row in first["structures"]} >= {"table", "chair", "wall", "door"}
    assert all("structure_id" in row for row in first["structures"])
    for bundle in sequence["bundles"]:
        ast.parse(bundle["blender_python"])
        assert 'DATA["structures"]' in bundle["blender_python"]
        assert "from_pydata" in bundle["blender_python"]
    assert sequence["renders_executed"] == 0


@pytest.mark.parametrize("change,code", [
    ("bounds", "SCENE_SEQUENCE_LAYOUT_CHANGED"), ("door", "SCENE_SEQUENCE_LAYOUT_CHANGED"),
    ("struct_missing", "SCENE_SEQUENCE_LAYOUT_CHANGED"), ("duplicate_segment", "SCENE_SEQUENCE_ORDER_INVALID"),
    ("same_time", "SCENE_SEQUENCE_ORDER_INVALID"), ("proxy", "SCENE_SEQUENCE_PROXY_CHANGED"),
    ("structure_actor_id", "SCENE_DUPLICATE_ID"), ("structure_other_space", "SCENE_SPACE_MIXED"),
    ("implicit_departure", "SCENE_CAST_NOT_CLOSED"), ("absent_pose", "SCENE_ABSENT_STATE_INVALID"),
])
def test_sequence_cannot_silently_change_space_cast_or_time(change, code):
    _, manifest = scene_fixture()
    scenes = studio.build_offline_previs_example(manifest)["scenes"]
    second = scenes[1]
    if change == "bounds": second["bounds"]["max_m"][0] += 0.1
    elif change == "door": second["structures"][3]["pose"]["position_m"][0] -= 0.1
    elif change == "struct_missing": second["structures"].pop()
    elif change == "duplicate_segment": second["segment_id"] = scenes[0]["segment_id"]
    elif change == "same_time": second["time_seconds"] = 0
    elif change == "proxy": second["entities"][0]["proxy"]["size_m"][0] += 0.1
    elif change == "structure_actor_id": second["structures"][0]["structure_id"] = "xiaolin"
    elif change == "structure_other_space": second["structures"][0]["scene_id"] = "corridor"
    elif change == "implicit_departure": second["entities"].pop(0)
    elif change == "absent_pose": second["entities"][0]["presence"] = "absent"
    rebind_explicit_fixture(second)
    with pytest.raises(studio.StudioReferencePrevisError, match=code):
        studio.build_previs_sequence(scenes, manifest)


def test_explicit_absence_preserves_identity_and_requires_no_held_prop():
    _, manifest = scene_fixture()
    scenes = studio.build_offline_previs_example(manifest)["scenes"]
    actor = scenes[1]["entities"][0]
    actor.update(presence="absent", pose=None, proxy=None, state={"posture": None})
    rebind_explicit_fixture(scenes[1])
    result = studio.build_previs_sequence(scenes, manifest)
    assert result["validation"]["status"] == "scene_sequence_valid"
    assert actor["entity_id"] in result["validation"]["snapshot_validations"][1]["entity_ids"]
    scenes[1]["entities"][-1]["state"]["holder_actor_id"] = actor["entity_id"]
    rebind_explicit_fixture(scenes[1])
    with pytest.raises(studio.StudioReferencePrevisError, match="SCENE_PROP_HOLDER_INVALID"):
        studio.validate_scene_sequence(scenes, manifest)


def test_duplicate_geometry_source_json_keys_are_rejected():
    scene, manifest = scene_fixture()
    record = scene["geometry_provenance_catalog"][0]
    record["text"] = '{"snapshot": {}, "snapshot": ' + json.dumps({key: scene[key] for key in studio._SNAPSHOT_KEYS}) + "}"
    record["sha256"] = hashlib.sha256(record["text"].encode()).hexdigest()
    scene["source_state"]["source_sha256"] = record["sha256"]
    with pytest.raises(studio.StudioReferencePrevisError, match="SCENE_SOURCE_JSON_INVALID"):
        studio.validate_scene(scene, manifest)


def test_generated_python_preserves_ids_named_like_template_tokens():
    scene, manifest = scene_fixture()
    manifest["actors"][0]["id"] = "PROVISIONAL_LITERAL"
    manifest["props"][1]["id"] = "SOURCE_HASH_LITERAL"
    scene["entities"][0]["entity_id"] = "PROVISIONAL_LITERAL"
    scene["entities"][3]["entity_id"] = "SOURCE_HASH_LITERAL"
    scene["manifest_sha256"] = refs.digest(manifest)
    rebind_explicit_fixture(scene)
    tree = ast.parse(studio.build_previs_bundle(scene, manifest)["blender_python"])
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "DATA")
    actual = json.loads(ast.literal_eval(assignment.value.args[0]))
    assert actual == {key: scene[key] for key in studio._SNAPSHOT_KEYS}
