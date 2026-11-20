"""Fixed text-version selection, including native v5 proof; no flag fallback."""
from copy import deepcopy
from pathlib import Path

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_world_scene_text_handoff_verifier_v1 as legacy

VERSION = "creative_world_scene_text_handoff_verifier/v2"
PROJECT = Path(__file__).resolve().parents[1]
V5_STATE = "creative_world_scene_live_session/v5/state"
V6_STATE = "creative_world_scene_live_session/v6/state"
V7_STATE = "creative_world_scene_live_session/v7/state"
V8_STATE = "creative_world_scene_live_session/v8/state"
V9_STATE = "creative_world_scene_live_session/v9/state"
V10_STATE = "creative_world_scene_live_session/v10/state"
V11_STATE = "creative_world_scene_live_session/v11/state"
V12_STATE = "creative_world_scene_live_session/v12/state"


def _verify_v5(root):
    # This is a fixed project import, never a configuration-selected module.
    from scripts import creative_world_scene_live_session_v5 as native_v5
    return native_v5.verify_text_handoff(root)


def _verify_v6(root):
    from scripts import creative_world_scene_live_session_v6 as native_v6
    return native_v6.verify_text_handoff(root)


def _verify_v7(root):
    from scripts import creative_world_scene_live_session_v7 as native_v7
    return native_v7.verify_text_handoff(root)


def _verify_v8(root):
    from scripts import creative_world_scene_live_session_v8 as native_v8
    return native_v8.verify_text_handoff(root)


def _verify_v9(root):
    from scripts import creative_world_scene_live_session_v9 as native_v9
    return native_v9.verify_text_handoff(root)


def _verify_v10(root):
    from scripts import creative_world_scene_live_session_v10 as native_v10
    return native_v10.verify_text_handoff(root)


def _verify_v11(root):
    from scripts import creative_world_scene_live_session_v11 as native_v11
    return native_v11.verify_text_handoff(root)


def _verify_v12(root):
    from scripts import creative_world_scene_live_session_v12 as native_v12
    return native_v12.verify_text_handoff(root)


def verify_text_handoff(root):
    root = Path(root).resolve()
    if not root.is_relative_to(PROJECT) or root == PROJECT:
        raise ValueError("original text root must stay inside project")
    state = io.strict_json((root / "STATE.json").read_text("utf-8-sig"))
    schema = state.get("schema")
    if schema not in (V5_STATE, V6_STATE, V7_STATE, V8_STATE, V9_STATE, V10_STATE, V11_STATE, V12_STATE) and schema not in legacy.VERIFIERS:
        raise ValueError("unsupported original text session version; no fallback")
    if state.get("status") != "text_ready_for_director":
        raise ValueError("original text session is not text ready")
    checked = (_verify_v5(root) if schema == V5_STATE else _verify_v6(root) if schema == V6_STATE
        else _verify_v7(root) if schema == V7_STATE else _verify_v8(root) if schema == V8_STATE
        else _verify_v9(root) if schema == V9_STATE
        else _verify_v10(root) if schema == V10_STATE
        else _verify_v11(root) if schema == V11_STATE
        else _verify_v12(root) if schema == V12_STATE
        else legacy.verify_text_handoff(root))
    if not (checked.get("valid") is True and checked.get("accepted") is True
            and checked.get("status") == "text_ready_for_director"
            and Path(checked["root"]).resolve() == root and Path(checked["source_root"]).resolve() == root
            and all(type(checked.get(k)) is dict and bool(checked[k])
                for k in ("paths", "identity", "inherited", "parent_identity", "source_files"))):
        raise ValueError("fixed original text verifier did not accept complete native proof")
    result = deepcopy(checked)
    files = result["source_files"]
    for path in (Path(__file__).resolve(), Path(legacy.__file__).resolve()):
        files[str(path)] = io.sha_file(path)
    result["verifier_entry"] = {"schema": VERSION + "/entry", "native_state_schema": schema,
        "registry_path": str(Path(__file__).resolve()), "registry_file_sha256": io.sha_file(__file__),
        "native_verifier_always_executed": True, "ready_flag_is_not_proof": True}
    return result
