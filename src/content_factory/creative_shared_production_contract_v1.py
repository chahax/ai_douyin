"""Shared production declarations, independent of creative and dynamic state.

Pure/offline contract. It authenticates declared provenance and request coverage,
not pixels, semantic truth, call authorization or provider identity fidelity.
"""
from copy import deepcopy
import hashlib
import json

from jsonschema import Draft202012Validator
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_shared_production_contract/v1"
PROFILE_FIELDS = ("gender_presentation", "age_presentation", "appearance", "wardrobe")
SOURCE_KINDS = ("source_brief", "user_declaration", "user_asset_approval", "approved_asset_metadata", "provider_documentation", "source_script", "approved_frame_metadata")
REFERENCE_MODES = ("reference_image", "first_frame", "character_element", "trusted_generated_reference")
INPUT_MODES = (*REFERENCE_MODES, "text_to_video_bootstrap")
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
TEXT = {"type": "string", "minLength": 1}


def digest(value):
    return source.digest(value)


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum}


def _refs():
    return _arr(_obj({"source_id": TEXT, "quote": TEXT}))


def _fact(value_schema=TEXT):
    return _obj({"status": {"enum": ["known", "unknown"]},
        "value": {"anyOf": [value_schema, {"type": "null"}]}, "sources": _refs(), "reason": {"type": "string"}})


def unknown(reason="尚未确认，不根据姓名或未知像素推断"):
    return {"status": "unknown", "value": None, "sources": [], "reason": reason}


def known(value, source_refs):
    return {"status": "known", "value": deepcopy(value), "sources": deepcopy(source_refs), "reason": ""}


def _binding_schema():
    return _fact(_obj({"asset_id": TEXT, "subject_key": TEXT}))


def build_manifest_schema(script):
    actors = list(dict.fromkeys(x["speaker"] for x in source.catalog(script).values() if x["kind"] == "dialogue"))
    entity = _obj({"subject_key": TEXT, "entity_type": {"enum": ["actor", "scene"]}, "entity_id": TEXT,
        "mapping_status": {"enum": ["confirmed", "unknown"]}, "sources": _refs()})
    asset = _obj({"asset_id": TEXT, "kind": {"enum": ["image", "video", "element"]}, "path": TEXT, "sha256": SHA,
        "approval": _obj({"status": {"enum": ["approved", "pending", "rejected"]}, "sources": _refs()}),
        "subjects": _arr(entity, 1)})
    schema = _obj({"schema": {"const": VERSION}, "script_sha256": {"const": digest(script)}, "source_context_sha256": SHA,
        "provenance_catalog": _arr(_obj({"source_id": TEXT, "kind": {"enum": list(SOURCE_KINDS)}, "text": TEXT, "sha256": SHA}), 1),
        "actors": _arr(_obj({"id": {"enum": actors}, "name": TEXT,
            "profile": _obj({field: _fact() for field in PROFILE_FIELDS}), "asset_binding": _binding_schema(),
            "voice": _obj({"status": {"enum": ["bound", "unbound", "unknown"]},
                "voice_id": {"type": ["string", "null"]}, "sources": _refs(), "reason": {"type": "string"}})}), 1),
        "scenes": _arr(_obj({"id": TEXT, "setting": _fact(), "appearance": _fact(), "asset_binding": _binding_schema()}), 1),
        "props": _arr(_obj({"id": TEXT, "appearance": _fact(), "owner": _fact({"type": ["string", "null"]})})),
        "asset_catalog": _arr(asset),
        "scene_transition_permissions": _arr(_obj({"source_ref": TEXT, "from_scene_id": TEXT, "to_scene_id": TEXT, "sources": _refs()})),
        "provider_policy": _obj({"status": {"enum": ["verified", "unknown"]}, "provider_id": TEXT, "model": TEXT,
            "identity_reference_mode": {"enum": ["unverified", *INPUT_MODES]},
            "allows_actor_asset_mapping": {"type": ["boolean", "null"]}, "sources": _refs(), "reason": {"type": "string"}})})
    schema["properties"]["provider_policy"]["properties"]["allowed_reference_modes"] = {
        "type": "array", "items": {"enum": list(INPUT_MODES)}, "uniqueItems": True, "minItems": 1}
    return schema


def build_pending_manifest(script, scene_and_character_context, provider_policy, provenance_catalog=None):
    """Preserve declared names/setting; leave all unspecified identity/asset facts unknown."""
    context = deepcopy(scene_and_character_context)
    catalog = source.catalog(script)
    actors = list(dict.fromkeys(x["speaker"] for x in catalog.values() if x["kind"] == "dialogue"))
    declared = {x["id"]: x for x in context["characters"]}
    if set(declared) != set(actors):
        raise ValueError("source context cast must exactly cover source dialogue actors")
    context_text = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    provenance = deepcopy(provenance_catalog or [])
    context_id = "frozen_source_context"
    if any(x["source_id"] == context_id for x in provenance):
        raise ValueError("reserved source context provenance id")
    provenance.append({"source_id": context_id, "kind": "source_brief", "text": context_text, "sha256": text_sha256(context_text)})
    manifest = {"schema": VERSION, "script_sha256": digest(script), "source_context_sha256": digest(context), "provenance_catalog": provenance,
        "actors": [{"id": aid, "name": declared[aid]["name"], "profile": {k: unknown() for k in PROFILE_FIELDS},
            "asset_binding": unknown("人物到已批准素材中具体主体的映射未确认"),
            "voice": {"status": "unbound", "voice_id": None, "sources": [], "reason": "没有实际声线绑定；不能保证跨段同声线"}} for aid in actors],
        "scenes": [{"id": x["id"], "setting": known(x["description"], [{"source_id": context_id, "quote": context_text}]),
            "appearance": unknown("场景外观规格尚未确认"), "asset_binding": unknown("场景到已批准素材的映射未确认")} for x in context["scenes"]],
        "props": [{"id": x["id"], "appearance": unknown("道具外观规格尚未确认"), "owner": unknown("来源未指定道具所有权")} for x in context["initial_state"].get("prop_states", [])],
        "scene_transition_permissions": [], "provider_policy": deepcopy(provider_policy), "asset_catalog": []}
    validate_shared_manifest(manifest, script)
    return manifest


def _schema(script):
    return build_manifest_schema(script)


def _unique(rows, key, label):
    values = [x[key] for x in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return {x[key]: x for x in rows}


def _check_sources(refs, bank, required=False, allowed_kinds=None):
    if required and not refs:
        raise ValueError("known declaration needs provenance")
    for ref in refs:
        item = bank.get(ref["source_id"])
        if item is None or not ref["quote"] or ref["quote"] not in item["text"]:
            raise ValueError("provenance source/quote is not authentic")
        if allowed_kinds and item["kind"] not in allowed_kinds:
            raise ValueError("provenance kind cannot authorize this declaration")


def _check_fact(fact, bank, allow_null=False):
    if fact["status"] == "unknown":
        if fact["value"] is not None or fact["sources"] or not fact["reason"].strip():
            raise ValueError("unknown facts must remain null with an explicit reason")
        return
    if fact["value"] is None and not allow_null:
        raise ValueError("known fact cannot be null")
    _check_sources(fact["sources"], bank, True)
    if isinstance(fact["value"], str) and (not fact["value"].strip() or not any(fact["value"] in r["quote"] for r in fact["sources"])):
        raise ValueError("known text must be a declared source quote, not an inferred rewrite")


def validate_shared_manifest(manifest, script):
    Draft202012Validator(_schema(script)).validate(manifest)
    bank = _unique(manifest["provenance_catalog"], "source_id", "provenance id")
    for item in bank.values():
        if item["sha256"] != text_sha256(item["text"]):
            raise ValueError("provenance text hash changed")
    actors = _unique(manifest["actors"], "id", "actor id")
    expected = {x["speaker"] for x in source.catalog(script).values() if x["kind"] == "dialogue"}
    if set(actors) != expected:
        raise ValueError("shared cast must exactly cover source actors")
    scenes = _unique(manifest["scenes"], "id", "scene id")
    props = _unique(manifest["props"], "id", "prop id")
    assets = _unique(manifest["asset_catalog"], "asset_id", "asset id")
    for asset in assets.values():
        subjects = _unique(asset["subjects"], "subject_key", "asset subject key")
        _check_sources(asset["approval"]["sources"], bank, asset["approval"]["status"] == "approved", {"user_asset_approval"})
        for subject in subjects.values():
            entities = actors if subject["entity_type"] == "actor" else scenes
            if subject["entity_id"] not in entities:
                raise ValueError("asset mapping names an unknown entity")
            _check_sources(subject["sources"], bank, subject["mapping_status"] == "confirmed", {"user_asset_approval"})
    for actor in actors.values():
        for fact in actor["profile"].values():
            _check_fact(fact, bank)
        _check_fact(actor["asset_binding"], bank)
        voice = actor["voice"]
        if voice["status"] == "bound":
            if not voice["voice_id"] or not voice["voice_id"].strip():
                raise ValueError("bound voice needs an actual voice identity")
            _check_sources(voice["sources"], bank, True)
        elif voice["voice_id"] is not None or voice["sources"] or not voice["reason"].strip():
            raise ValueError("unbound/unknown voice must not claim a voice identity")
    for scene in scenes.values():
        for key in ("setting", "appearance", "asset_binding"):
            _check_fact(scene[key], bank)
    for prop in props.values():
        _check_fact(prop["appearance"], bank)
        _check_fact(prop["owner"], bank, True)
    for kind, rows in (("actor", actors), ("scene", scenes)):
        for eid, entity in rows.items():
            binding = entity["asset_binding"]
            if binding["status"] == "unknown":
                continue
            val = binding["value"]
            asset = assets.get(val["asset_id"])
            subject = None if asset is None else next((x for x in asset["subjects"] if x["subject_key"] == val["subject_key"]), None)
            if asset is None or subject is None or subject["entity_type"] != kind or subject["entity_id"] != eid:
                raise ValueError("approved asset binding does not match the declared entity")
            _check_sources(binding["sources"], bank, True, {"user_asset_approval"})
    policy = manifest["provider_policy"]
    _check_sources(policy["sources"], bank, policy["status"] == "verified", {"provider_documentation"})
    if policy["status"] == "unknown" and (policy["allows_actor_asset_mapping"] is not None or not policy["reason"].strip()):
        raise ValueError("unknown provider policy must not assert mapping capability")
    event_catalog = source.catalog(script)
    seen_edges = set()
    for permission in manifest["scene_transition_permissions"]:
        edge = (permission["source_ref"], permission["from_scene_id"], permission["to_scene_id"])
        if edge in seen_edges or permission["from_scene_id"] not in scenes or permission["to_scene_id"] not in scenes or permission["from_scene_id"] == permission["to_scene_id"]:
            raise ValueError("invalid/duplicate scene transition permission")
        seen_edges.add(edge)
        row = event_catalog.get(permission["source_ref"])
        if row is None or row["kind"] != "action":
            raise ValueError("scene transition must cite an actual source action")
        _check_sources(permission["sources"], bank, True, {"source_script", "source_brief", "user_declaration"})
        if not any(row["text"] in ref["quote"] for ref in permission["sources"]):
            raise ValueError("scene transition provenance must quote its actual source action")
    return {"status": "shared_manifest_valid", "global_manifest_sha256": digest(manifest), "script_sha256": digest(script),
        "declared_provenance_checked": True, "pixel_identity_verified": False, "human_approved_by_contract": False}


def production_gate(manifest, script):
    validate_shared_manifest(manifest, script)
    missing = []
    assets = {x["asset_id"]: x for x in manifest["asset_catalog"]}
    for actor in manifest["actors"]:
        for field in PROFILE_FIELDS:
            if actor["profile"][field]["status"] != "known":
                missing.append(f"actors.{actor['id']}.profile.{field}")
    for kind, rows in (("actors", manifest["actors"]), ("scenes", manifest["scenes"])):
        for entity in rows:
            binding = entity["asset_binding"]
            if binding["status"] != "known":
                missing.append(f"{kind}.{entity['id']}.asset_binding")
            else:
                asset = assets[binding["value"]["asset_id"]]
                subject = next(x for x in asset["subjects"] if x["subject_key"] == binding["value"]["subject_key"])
                if asset["approval"]["status"] != "approved" or subject["mapping_status"] != "confirmed":
                    missing.append(f"{kind}.{entity['id']}.approved_asset_mapping")
    for scene in manifest["scenes"]:
        for field in ("setting", "appearance"):
            if scene[field]["status"] != "known":
                missing.append(f"scenes.{scene['id']}.{field}")
    for prop in manifest["props"]:
        if prop["appearance"]["status"] != "known":
            missing.append(f"props.{prop['id']}.appearance")
    policy = manifest["provider_policy"]
    allowed = policy.get("allowed_reference_modes", [policy["identity_reference_mode"]])
    if policy["status"] != "verified" or not set(allowed).intersection(REFERENCE_MODES) or policy["allows_actor_asset_mapping"] is not True:
        missing.append("provider_policy.verified_actor_asset_mapping")
    unbound = [x["id"] for x in manifest["actors"] if x["voice"]["status"] != "bound"]
    return {"status": "shared_pending" if missing else "shared_ready", "missing": missing,
        "global_manifest_sha256": digest(manifest), "unbound_voice_actor_ids": unbound,
        "voice_bindings_declared": not unbound, "voice_inputs_bound": False, "voice_identity_guaranteed": False,
        "pixel_identity_verified": False, "model_fidelity_guaranteed": False, "calls_authorized": False}


def validate_casting_bootstrap(manifest, script):
    """Gate only a first text-to-video casting trial, never formal continuation."""
    validate_shared_manifest(manifest, script)
    missing = []
    bank = {x["source_id"]: x for x in manifest["provenance_catalog"]}
    for actor in manifest["actors"]:
        for field in PROFILE_FIELDS:
            fact = actor["profile"][field]
            if fact["status"] != "known":
                missing.append(f"actors.{actor['id']}.profile.{field}")
            else:
                _check_sources(fact["sources"], bank, True, {"source_brief", "user_declaration"})
    for scene in manifest["scenes"]:
        for field in ("setting", "appearance"):
            if scene[field]["status"] != "known":
                missing.append(f"scenes.{scene['id']}.{field}")
    for prop in manifest["props"]:
        if prop["appearance"]["status"] != "known":
            missing.append(f"props.{prop['id']}.appearance")
    policy = manifest["provider_policy"]
    if policy["status"] != "verified" or "text_to_video_bootstrap" not in policy.get("allowed_reference_modes", [policy["identity_reference_mode"]]):
        missing.append("provider_policy.text_to_video_bootstrap")
    return {"status": "casting_bootstrap_pending" if missing else "casting_bootstrap_ready", "missing": missing,
        "global_manifest_sha256": digest(manifest), "route": "bootstrap_casting", "max_initial_segments": 1,
        "visual_cast_approved": False, "asset_mapping_verified": False, "formal_continuation_allowed": False,
        "voice_identity_guaranteed": False, "calls_authorized": False, "media_status_after_save": "awaiting_human_review"}


def build_dynamic_state_schema(manifest):
    ids = [x["id"] for x in manifest["actors"]]
    support_value = _obj({"entity_type": {"enum": ["scene", "prop", "actor"]}, "entity_id": TEXT})
    return _obj({"global_manifest_sha256": {"const": digest(manifest)}, "scene_id": {"enum": [x["id"] for x in manifest["scenes"]]},
        "previous_scene_id": {"type": ["string", "null"]}, "completed_source_refs": _arr(TEXT),
        "actors": _arr(_obj({"id": {"enum": ids}, "pose": _fact(), "emotion": _fact()}), 1),
        "props": _arr(_obj({"id": TEXT, "holder": _fact({"enum": [*ids, None]}), "support": _fact(support_value), "orientation": _fact()}))})


def validate_dynamic_state(dynamic_state, manifest, script, source_refs, scene_transition=None):
    validate_shared_manifest(manifest, script)
    Draft202012Validator(build_dynamic_state_schema(manifest)).validate(dynamic_state)
    bank = {x["source_id"]: x for x in manifest["provenance_catalog"]}
    actor_rows = _unique(dynamic_state["actors"], "id", "dynamic actor")
    prop_rows = _unique(dynamic_state["props"], "id", "dynamic prop")
    if set(actor_rows) != {x["id"] for x in manifest["actors"]} or set(prop_rows) != {x["id"] for x in manifest["props"]}:
        raise ValueError("dynamic state must cover the same fixed actors and props")
    refs = list(source.catalog(script))
    completed = dynamic_state["completed_source_refs"]
    if completed != refs[:len(completed)] or not source_refs or source_refs != refs[len(completed):len(completed) + len(source_refs)]:
        raise ValueError("current scope must immediately follow the completed source prefix")
    pending = []
    nonblocking_unknown = []
    for actor in actor_rows.values():
        for field in ("pose", "emotion"):
            _check_fact(actor[field], bank)
            if actor[field]["status"] != "known":
                target = nonblocking_unknown if field == "emotion" else pending
                target.append(f"actors.{actor['id']}.{field}")
    entities = {"actor": set(actor_rows), "prop": set(prop_rows), "scene": {x["id"] for x in manifest["scenes"]}}
    for prop in prop_rows.values():
        for field in ("holder", "support", "orientation"):
            _check_fact(prop[field], bank, field in ("holder", "support"))
            if prop[field]["status"] != "known":
                target = nonblocking_unknown if field == "orientation" else pending
                target.append(f"props.{prop['id']}.{field}")
        support = prop["support"]["value"]
        if support is not None and support["entity_id"] not in entities[support["entity_type"]]:
            raise ValueError("unknown support entity")
    previous = dynamic_state["previous_scene_id"]
    current = dynamic_state["scene_id"]
    if previous is not None and previous not in entities["scene"]:
        raise ValueError("unknown previous scene")
    if previous is not None and previous != current:
        if scene_transition is None or scene_transition not in manifest["scene_transition_permissions"] or scene_transition["source_ref"] not in source_refs or scene_transition["from_scene_id"] != previous or scene_transition["to_scene_id"] != current:
            raise ValueError("scene change needs a frozen current source-event permission")
    elif scene_transition is not None:
        raise ValueError("scene transition supplied without an actual scene change")
    return {"status": "dynamic_pending" if pending else "dynamic_ready", "missing": pending,
        "nonblocking_unknown": nonblocking_unknown, "dynamic_state_sha256": digest(dynamic_state)}


def assert_creative_does_not_override(creative):
    """Reject structural identity edits; prose meaning still needs independent review."""
    forbidden = {"profile", *PROFILE_FIELDS, "asset_binding", "asset_catalog", "provider_policy", "voice_id", "owner"}
    def walk(value, path="creative"):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in forbidden:
                    raise ValueError(f"fixed production identity cannot be generated at {path}.{key}")
                walk(item, path + "." + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
    walk(creative)
    return {"status": "no_structural_identity_override", "prose_identity_semantics_verified": False}


def _media_binding(manifest, dynamic_state, bindings, media_binding, bootstrap):
    policy = manifest["provider_policy"]
    if media_binding is None:
        mode = "text_to_video_bootstrap" if bootstrap else policy["identity_reference_mode"]
        unique = {x["asset_id"]: {"asset_id": x["asset_id"], "sha256": x["asset_sha256"], "path": x["path"], "kind": x["kind"]} for x in bindings}
        media_binding = {"role": mode, "assets": [] if bootstrap else list(unique.values()), "tail_evidence": None}
    else:
        media_binding = deepcopy(media_binding)
    tail_schema = _obj({"path": TEXT, "sha256": SHA, "role": {"const": "first_frame"},
        "source": {"const": "generation_service_original"}, "source_task_id": TEXT, "source_segment_id": TEXT,
        "source_video_sha256": SHA, "human_review_path": TEXT, "human_review_sha256": SHA,
        "human_review_decision": {"const": "approved"}, "global_manifest_sha256": {"const": digest(manifest)},
        "actor_ids": {"const": [x["id"] for x in manifest["actors"]]}})
    media_schema = _obj({"role": {"enum": list(INPUT_MODES)}, "assets": _arr(_obj({"asset_id": TEXT, "sha256": SHA, "path": TEXT,
        "kind": {"enum": ["image", "video", "element"]}})), "tail_evidence": {"anyOf": [tail_schema, {"type": "null"}]}})
    Draft202012Validator(media_schema).validate(media_binding)
    mode = media_binding["role"]
    if mode not in policy.get("allowed_reference_modes", [policy["identity_reference_mode"]]):
        raise ValueError("segment input mode is outside frozen provider policy")
    rows = media_binding["assets"]
    _unique(rows, "asset_id", "segment asset")
    if bootstrap:
        if dynamic_state["completed_source_refs"] or mode != "text_to_video_bootstrap" or rows or media_binding["tail_evidence"] is not None:
            raise ValueError("casting bootstrap only starts the first segment without visual approval")
    elif mode == "first_frame":
        tail = media_binding["tail_evidence"]
        if not dynamic_state["completed_source_refs"] or tail is None or len(rows) != 1 or rows[0]["kind"] != "image" or rows[0]["sha256"] != tail["sha256"] or rows[0]["path"] != tail["path"]:
            raise ValueError("continuation first_frame must bind the actual approved original tail")
    else:
        if mode == "text_to_video_bootstrap" or media_binding["tail_evidence"] is not None:
            raise ValueError("formal production cannot use bootstrap or unsupported tail binding")
        expected = {(x["asset_id"], x["asset_sha256"], x["path"], x["kind"]) for x in bindings}
        actual = {(x["asset_id"], x["sha256"], x["path"], x["kind"]) for x in rows}
        if actual != expected:
            raise ValueError("reference inputs must cover the fixed approved baseline assets")
    return media_binding


def compile_segment_context(manifest, script, dynamic_state, source_refs, scene_transition=None, media_binding=None, bootstrap=False):
    gate = validate_casting_bootstrap(manifest, script) if bootstrap else production_gate(manifest, script)
    dynamic = validate_dynamic_state(dynamic_state, manifest, script, source_refs, scene_transition)
    if gate["status"] != ("casting_bootstrap_ready" if bootstrap else "shared_ready") or dynamic["status"] != "dynamic_ready":
        raise ValueError("shared/dynamic production facts are pending: " + ",".join(gate["missing"] + dynamic["missing"]))
    assets = {x["asset_id"]: x for x in manifest["asset_catalog"]}
    scene = next(x for x in manifest["scenes"] if x["id"] == dynamic_state["scene_id"])
    bindings = []
    for kind, rows in (("actor", manifest["actors"]), ("scene", [scene])):
        for entity in rows:
            value = entity["asset_binding"]["value"]
            if value is None and bootstrap:
                continue
            asset = assets[value["asset_id"]]
            bindings.append({"entity_type": kind, "entity_id": entity["id"], **deepcopy(value),
                "asset_sha256": asset["sha256"], "path": asset["path"], "kind": asset["kind"],
                "reference_mode": manifest["provider_policy"]["identity_reference_mode"]})
    media = _media_binding(manifest, dynamic_state, bindings, media_binding, bootstrap)
    paths = [f"actors.{a['id']}.profile.{field}" for a in manifest["actors"] for field in PROFILE_FIELDS]
    paths += [f"actors.{a['id']}.asset_binding" for a in manifest["actors"]]
    paths += [f"actors.{a['id']}.voice" for a in manifest["actors"]]
    paths += [f"scenes.{scene['id']}.{field}" for field in ("setting", "appearance", "asset_binding")]
    paths += [f"props.{p['id']}.{field}" for p in manifest["props"] for field in ("appearance", "owner")]
    projection = {"actors": deepcopy(manifest["actors"]), "scene": deepcopy(scene), "props": deepcopy(manifest["props"]),
        "provider_policy": deepcopy(manifest["provider_policy"]), "dynamic_state": deepcopy(dynamic_state), "scene_transition": deepcopy(scene_transition)}
    result = {"schema": VERSION + "/segment_context", "global_manifest_sha256": digest(manifest), "script_sha256": digest(script),
        "source_refs": deepcopy(source_refs), "dynamic_state_sha256": digest(dynamic_state), "projection": projection,
        "projection_sha256": digest(projection), "approved_asset_bindings": bindings,
        "media_binding": media, "media_binding_sha256": digest(media), "route": "bootstrap_casting" if bootstrap else "formal_production",
        "casting_bootstrap": bootstrap, "tail_approval_verification_is_runner_owned": True,
        "nonblocking_dynamic_unknown": deepcopy(dynamic["nonblocking_unknown"]),
        "coverage_proof": {"global_manifest_sha256": digest(manifest), "rendered_shared_paths": paths,
            "dynamic_state_sha256": digest(dynamic_state), "all_fixed_actor_profiles_projected": True,
            "actual_request_coverage_checked": False, "pixel_or_audio_quality_checked": False},
        "voice_identity_guaranteed": False, "model_fidelity_guaranteed": False, "media_status_after_save": "awaiting_human_review",
        "human_approved": False, "calls_authorized": False}
    result["prompt_fragment"] = _render(result)
    result["prompt_fragment_sha256"] = text_sha256(result["prompt_fragment"])
    return result


def _value(fact, unknown_text="未知，不推断"):
    if fact["status"] != "known":
        return unknown_text
    if fact["value"] is None:
        return "无人/无（已明确声明）"
    if isinstance(fact["value"], dict):
        return json.dumps(fact["value"], ensure_ascii=False, sort_keys=True)
    return str(fact["value"])


def _render(compiled):
    x = compiled["projection"]
    names = {a["id"]: a["name"] for a in x["actors"]}
    lines = ["共用制作规格（身份与场景固定，不能由当前演法改写）：", "闭合演员：" + "、".join(names.values()) + "；不得增加人物或分身。"]
    labels = {"gender_presentation": "性别呈现", "age_presentation": "年龄呈现", "appearance": "外貌", "wardrobe": "服装"}
    for a in x["actors"]:
        specs = "；".join(labels[k] + "：" + _value(a["profile"][k]) for k in PROFILE_FIELDS)
        binding = a["asset_binding"]["value"]
        if compiled["casting_bootstrap"]:
            mapping = "首段按上述创作选角建立人物；本段不输入人物视觉素材，生成身份与具体主体对应尚未批准，不能声称已验证视觉身份。"
        else:
            mapping = f"只对应已批准素材 {binding['asset_id']} 中已确认主体 {binding['subject_key']}，不可把另一主体当成本角色。"
        lines.append(f"角色 {a['id']}={a['name']}；{specs}；{mapping}")
        voice = a["voice"]
        lines.append(f"{a['name']}声线输入：" + ("已绑定 " + voice["voice_id"] if voice["status"] == "bound" else "unbound，没有实际声线绑定，跨段同声线未保证。"))
    scene = x["scene"]
    lines.append(f"当前固定场景 {scene['id']}：{_value(scene['setting'])}；外观：{_value(scene['appearance'])}；参考主体：{_value(scene['asset_binding'])}。")
    for p in x["props"]:
        owner = p["owner"]["value"]
        owner_label = names.get(owner, owner) if p["owner"]["status"] == "known" else "未知，不把位置或当前持有人当所有人"
        lines.append(f"道具 {p['id']}：{_value(p['appearance'])}；所有权：{owner_label}。")
    state = x["dynamic_state"]
    for a in state["actors"]:
        lines.append(f"{names[a['id']]}当前姿态：{_value(a['pose'])}；当前情绪：{_value(a['emotion'])}。")
    for p in state["props"]:
        lines.append(f"道具 {p['id']}当前持有人：{_value(p['holder'])}；当前承托/容纳位置：{_value(p['support'])}；朝向：{_value(p['orientation'])}。")
    policy = x["provider_policy"]
    lines.append(f"本段实际素材通道：{compiled['media_binding']['role']}；文字元数据不证明图中身份或成片质量。")
    if compiled["media_binding"]["role"] == "first_frame":
        lines.append("本段从经用户批准的上一段生成服务原始尾帧续接；尾帧是本次实际图像输入，固定角色基准仍是共用人物档案，不能用基准素材的哈希代替尾帧。")
    if x["scene_transition"]:
        t = x["scene_transition"]
        lines.append(f"本段仅按源事件 {t['source_ref']} 从 {t['from_scene_id']} 进入 {t['to_scene_id']}。")
    elif compiled["casting_bootstrap"]:
        lines.append("本次只建立首段人物与场景基准，尚无已批准视觉映射；生成后等待用户人工审核和角色对应确认，不能自动续段。")
    else:
        lines.append("本段不切换场景；空间布局由实际输入素材/已批准原始尾帧承接，不凭姓名或文字猜左右位置。")
    return "\n".join(lines)


def render_shared_context(compiled, manifest, script, dynamic_state, source_refs, scene_transition=None, media_binding=None, bootstrap=False):
    exact = compile_segment_context(manifest, script, dynamic_state, source_refs, scene_transition, media_binding, bootstrap)
    if exact != compiled:
        raise ValueError("shared manifest, state, source, projection or coverage changed")
    return compiled["prompt_fragment"]


def validate_provider_request_coverage(compiled, prompt, attached_assets, provider_id, model):
    """Check adapter's actual prompt/attachment metadata, not visual subject matching."""
    if digest(compiled["projection"]) != compiled["projection_sha256"] or digest(compiled["media_binding"]) != compiled["media_binding_sha256"]:
        raise ValueError("compiled projection/media binding integrity changed")
    if compiled["prompt_fragment"] != _render(compiled):
        raise ValueError("shared prompt no longer represents the compiled facts")
    if text_sha256(compiled["prompt_fragment"]) != compiled["prompt_fragment_sha256"] or prompt.count(compiled["prompt_fragment"]) != 1:
        raise ValueError("actual provider prompt must contain the complete shared projection once")
    policy = compiled["projection"]["provider_policy"]
    if provider_id != policy["provider_id"] or model != policy["model"]:
        raise ValueError("actual provider/model differs from frozen policy")
    expected = {(a["asset_id"], a["sha256"], compiled["media_binding"]["role"]) for a in compiled["media_binding"]["assets"]}
    actual = {(a["asset_id"], a["sha256"], a["reference_mode"]) for a in attached_assets}
    if actual != expected or len(attached_assets) != len(actual):
        raise ValueError("actual attachments do not cover exactly the approved asset bindings")
    return {"status": "shared_request_coverage_valid", "global_manifest_sha256": compiled["global_manifest_sha256"],
        "actual_prompt_sha256": text_sha256(prompt), "attached_asset_metadata_sha256": digest(attached_assets),
        "all_shared_fields_in_actual_text": True, "all_asset_metadata_attached": True,
        "pixel_subject_mapping_verified": False, "voice_identity_guaranteed": False, "media_status": "awaiting_human_review"}
