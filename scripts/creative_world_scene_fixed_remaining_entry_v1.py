"""Restricted code-bound continuation classes; configuration cannot select a flow."""
from copy import deepcopy
from dataclasses import dataclass
import importlib

from scripts import creative_world_scene_live_session_v10 as prior
from scripts import creative_world_scene_live_session_v5 as body_flow

base, mechanics = prior.base, prior.mechanics
read, digest, sha = prior.read, prior.digest, prior.sha


@dataclass(frozen=True)
class FixedEntry:
    version: str
    stage_pairs: tuple
    parent_stage_pairs: tuple
    parent_used_pairs: tuple
    parent_verifier_module: str
    workflow_module: str


def classes(spec):
    """Only a Python entry supplies spec; it is never read from Config or JSON."""
    if not isinstance(spec, FixedEntry) or any(type(pairs) is not tuple or len(pairs) != 4
            or any(type(pair) is not tuple or len(pair) != 2 for pair in pairs)
            for pairs in (spec.stage_pairs, spec.parent_stage_pairs, spec.parent_used_pairs)):
        raise TypeError("immutable code-bound entry required")
    limits, parent_limits, used = map(dict, (spec.stage_pairs, spec.parent_stage_pairs, spec.parent_used_pairs))
    if (tuple(limits) != tuple(prior.LIMITS) or tuple(parent_limits) != tuple(limits) or tuple(used) != tuple(limits)
            or any(type(x) is not int or x < 0 for d in (limits, parent_limits, used) for x in d.values())
            or {k: parent_limits[k] - used[k] for k in limits} != limits
            or limits["goal_plan"] != 0 or limits["goal_audit"] != 0 or limits["complete_script"] != 2):
        raise ValueError("exact nonnegative original body/review remainder required")
    policy = mechanics.FixedPolicy(spec.version, spec.stage_pairs, prior.POLICY.label_pattern)

    class Runtime(prior.Runtime):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.stage_limits = deepcopy(limits)

        def _policy(self):
            value = super()._policy()
            value.update(schema=spec.version + "/runtime_policy", total_new_calls_limit=policy.total,
                parent_scope_stage_limits=deepcopy(parent_limits), parent_scope_stage_calls=deepcopy(used), parent_scope_remaining=deepcopy(limits),
                parent_scope_calls_used=sum(used.values()), parent_scope_calls_remaining=policy.total,
                source_bound_native_payload=True)
            return value

    class Driver(prior.Driver):
        def reserve_complete_chain(self, label):
            if not label.startswith("complete_script_"): return
            remaining = limits["full_review"] - sum(not r["label"].startswith("complete_script_") for r in self.calls)
            if remaining < 4:
                spent = {r["label"] for r in self.calls}
                raise base.Halt("halt_review_capacity_for_complete_chain", remaining_reviews=remaining, required_reviews=4,
                    unused_body_versions=[v for v in prior.BODY_VERSIONS if f"complete_script_{v:02}" not in spent],
                    original_body_capacity_preserved=True)

        def invoke(self, label, prepared, validator):
            self.reserve_complete_chain(label)
            return mechanics.dispatch(self, policy, label, prepared, validator)

        def _focused(self, native, views, label):
            accepted, packet, decision = super()._focused(native, views, label)
            packet["coordinator_packet_schema"] = spec.version + "/two_native_report_packet"
            return accepted, packet, decision

    class Session(prior.Session):
        SPEC, POLICY, driver_type = spec, policy, Driver

        def _parent(self):
            anchor = read(self.config.parent_anchor_path)
            verifier = self.parent_verifier or importlib.import_module(spec.parent_verifier_module).verify_anchor
            checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
            account = anchor.get("current_text_scope_accounting", {})
            if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                    or checked.get("inherited") != anchor.get("inherited") or account.get("limits") != parent_limits
                    or account.get("consumed") != used or account.get("remaining") != limits
                    or account.get("calls_used") != sum(used.values()) or account.get("calls_remaining") != policy.total
                    or account.get("body_used") != 0 or account.get("body_limit") != 2
                    or anchor.get("current_body_versions_unused") != prior.BODY_VERSIONS
                    or anchor.get("unused_capacity_is_original_grant_balance_only") is not True
                    or anchor.get("creative_body_capacity_regranted") is not False
                    or not anchor.get("continuation_of_original_grant")):
                raise ValueError("settled fixed parent and exact unused original capacity required")
            prior.source_refs.creative_root(anchor)
            for key in ("inputs", "profile"):
                path = base._inside(anchor["current_" + key + "_path"])
                if sha(path) != anchor["current_" + key + "_file_sha256"] or digest(read(path)) != anchor["current_" + key + "_sha256"]:
                    raise ValueError("current original authority changed")
            return anchor, checked

        def _workflow(self):
            adapter = self._reviews(read(self.root / "USER_SCOPE.json")) if (self.root / "USER_SCOPE.json").exists() else self.injected_review_adapter
            return importlib.import_module(spec.workflow_module).ReviewWorkflow(base.workflow, adapter)

        def authorization_template(self, preview):
            value = super().authorization_template(preview)
            value.update(schema=spec.version + "/remaining_capacity_authorization", stage_limits=deepcopy(limits),
                total_new_calls_limit=policy.total, parent_scope_stage_limits=deepcopy(parent_limits), parent_scope_stage_calls=deepcopy(used),
                parent_scope_remaining=deepcopy(limits), parent_scope_calls_used=sum(used.values()), parent_scope_calls_remaining=policy.total,
                source_bound_native_payload=True,
                new_authority="continue only frozen original body/review remainder; local source metadata is compiled, no new capacity/source/goal/media")
            return value

        def _binding(self, parent):
            value = super()._binding(parent)
            value.update(schema=spec.version + "/successor_claim", remaining_original_capacity=deepcopy(limits), source_bound_native_payload=True)
            return value

        def preview(self): return mechanics.preview(self, policy)
        def prepare(self): return mechanics.prepare(self, policy)
        def _guard(self): return mechanics.guard(self, policy)
        def _admit(self, label, request, ledger): return mechanics.admit(self, policy, label, request, ledger)

        def runtime(self):
            freeze = read(self.root / "PRODUCTION_FREEZE.json")
            return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
                inherited_guard=self._guard, admission=self._admit, shared_lock=base.PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock",
                quota_state=None, client_factory_builder=self.client_factory_builder)

        def _replay(self, ledger, label=None, *, verify_validations=False):
            owner, rows = self, ledger["calls"]
            class Replay(Driver):
                def invoke(self, current, prepared, validator):
                    self.reserve_complete_chain(current)
                    if self.position == len(rows):
                        if current != label: raise ValueError("code-bound continuation sequence differs")
                        raise body_flow.NextRequest(prepared)
                    row = rows[self.position]; self.position += 1
                    path = owner.root / row["receipt"]; receipt = read(path)
                    if current != row["label"] or sha(path) != row["receipt_sha256"] or receipt["request"] != prepared["request"]:
                        raise ValueError("original bound payload prerequisite differs")
                    native, decision = prior.native_proof.known_native(receipt), base._decision(receipt)
                    if verify_validations and receipt["status"] == "contract_valid" and validator(native) != decision:
                        raise ValueError("source-bound payload validation changed")
                    self.calls.append(row)
                    return native, decision, row
            replay = Replay(self, None, read(self.root / "INPUTS.json"), self._workflow()); replay.position = 0
            try: result = replay.flow()
            except body_flow.NextRequest as found:
                if label is None: raise ValueError("source-bound handoff flow unfinished")
                return found.prepared
            if label is not None or replay.position != len(rows): raise ValueError("terminal flow or extra bound receipts")
            return result

        def state_metadata(self):
            value = super().state_metadata()
            value.update(parent_scope_stage_calls=deepcopy(used), parent_scope_remaining=deepcopy(limits), source_bound_native_payload=True)
            return value

        def state(self, runtime, status, **details): return mechanics.state(self, policy, runtime, status, **details)
        def _save_text(self, result, driver, runtime): return mechanics.save_text(self, policy, result, driver, runtime)
        def run(self): return mechanics.run(self, policy)

    return Runtime, Driver, Session
