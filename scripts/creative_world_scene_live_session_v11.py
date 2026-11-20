"""Fixed source-bound native-payload continuation; no new creative capacity."""
import json
from scripts import creative_world_scene_fixed_remaining_entry_v1 as fixed

prior, base, mechanics = fixed.prior, fixed.base, fixed.mechanics
read, write, digest, sha, Config = prior.read, prior.write, prior.digest, prior.sha, prior.Config
VERSION = "creative_world_scene_live_session/v11"
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 2, "full_review": 6}
PARENT_LIMITS, PARENT_USED = prior.LIMITS, prior.PARENT_USED
TOTAL, BODY_VERSIONS, REF_KEYS = sum(LIMITS.values()), prior.BODY_VERSIONS, prior.REF_KEYS
SPEC = fixed.FixedEntry(VERSION, tuple(LIMITS.items()), tuple(PARENT_LIMITS.items()), tuple(PARENT_USED.items()),
    "scripts.creative_world_scene_source_bound_contract_spend_anchor_v1", "scripts.creative_world_scene_replanned_workflow_v7")
Runtime, Driver, Session = fixed.classes(SPEC)
POLICY = Session.POLICY


def verify_text_handoff(root): return mechanics.verify_handoff(Session.open(root), POLICY)


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("preview", "authorization", "prepare", "run", "verify")); p.add_argument("path")
    a = p.parse_args()
    if a.action == "verify": value = verify_text_handoff(a.path)
    else:
        s = Session.open(a.path) if a.action == "run" else Session(read(a.path))
        value = s.authorization_template(s.preview()) if a.action == "authorization" else getattr(s, a.action)()
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
