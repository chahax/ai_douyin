"""Explicit v2-native / canonical-source bridge over frozen text stages.

Native reviewer v6 objects remain byte-for-byte values. Their historical
native_script_sha256 field identifies the canonical source actually reviewed;
the new outer descriptor separately binds the real provider-native v2 object.
"""
from copy import deepcopy
import json

from scripts import creative_world_scene_replanned_workflow_v2 as prior
from scripts import creative_world_scene_derived_context_script_v1 as contract
from src.content_factory import creative_full_review_protocol_v6 as full

VERSION = "creative_world_scene_replanned_workflow/v3"
REVIEW_BRIDGE_VERSION = VERSION + "/canonical_review_bridge"
base = prior.prior.base
digest = base.digest

_OLD_WORLD_LINK_RULE = (
    "场次ID唯一、按首次出现顺序登记；第一场previous_context_id=null且relation=opening，"
    "之后明确链接前一场；本拍所有action索引须存在且kind=action，并行dialogue索引须kind=dialogue。"
)
_NEW_WORLD_LINK_RULE = (
    "场次ID唯一、按首次出现顺序登记；原生v2不输出previous_context_id，前场链接由编译从场次顺序唯一派生。"
    "第一场relation=opening，之后不是opening；本拍所有action索引须存在且kind=action，并行dialogue索引须kind=dialogue。"
)
REVIEW_SOURCE_RULE = (
    "本请求native_script_document是由原生v2正文仅派生场次前置链接及合同版本所得的canonical-source，正文只送这一份。"
    "review_source_derivation绑定真实provider-native、canonical-source与compiled三份SHA；"
    "v6响应native_script_sha256按Schema精确填写canonical-source的SHA，不将它称为provider-native。"
    "创意内容无改写，原生v2另存。照常执行完整同源语义/物理审查，派生链接不证明动作完成或时间先后。"
)


class CanonicalReviewBridge:
    VERSION = REVIEW_BRIDGE_VERSION
    BUNDLE_VERSION = full.BUNDLE_VERSION
    PART_TABLES = full.PART_TABLES
    digest = staticmethod(digest)

    def __init__(self, delegate):
        self.delegate = delegate

    def __getattr__(self, key): return getattr(self.delegate, key)

    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        compiled = contract.compile_document(native, views["goal"], views["brief"])
        if views["compiled_script"] != compiled["script"]:
            raise ValueError("review compiled source differs from exact provider-native v2 derivation")
        prepared = self.delegate.prepare_full_review_part_request(inputs, profile, compiled["derived_script"], views, part)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        if payload["native_script_document"] != compiled["derived_script"]:
            raise ValueError("underlying full review changed the canonical creative source")
        descriptor = compiled["source_descriptor"]
        payload["review_source_derivation"] = deepcopy(descriptor)
        context_sha = digest(payload)
        policy = prepared["manifest"]["context_policy"]
        measure = base.workflow.contexts._measure(payload)
        if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
            raise ValueError("derived-source full review exceeds existing context policy; no source truncated")
        schema = full.build_part_schema(part, compiled["script"], views["brief"], views["plan"], prepared["review_legal_context"],
            context_sha256=context_sha, goal_contract=views["goal"], opening_setup=views["opening_setup"],
            prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
        prepared["request"]["structured_schema"] = schema
        prepared["request"]["messages"][0]["content"] += "\n" + REVIEW_SOURCE_RULE
        prepared["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        prepared["request"]["input_provenance"].update(context_sha256=context_sha,
            part_context_sha256=context_sha, review_source_descriptor_sha256=digest(descriptor),
            origin_native_script_sha256=descriptor["native_script_sha256"],
            derived_script_sha256=descriptor["derived_script_sha256"], canonical_review_bridge_version=REVIEW_BRIDGE_VERSION)
        prepared["manifest"].update(part_context_sha256=context_sha, context_sha256=context_sha,
            source_descriptor=deepcopy(descriptor), canonical_review_bridge_version=REVIEW_BRIDGE_VERSION,
            legacy_native_script_sha256_role=descriptor["legacy_review_native_script_sha256_role"],
            payload_identity=measure, payload_characters=len(prepared["request"]["messages"][1]["content"]),
            schema_characters=len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))))
        prepared.update(context_sha256=context_sha, part_context_sha256=context_sha,
            source_descriptor=deepcopy(descriptor), canonical_review_bridge_version=REVIEW_BRIDGE_VERSION)
        return base.workflow._mark(prepared, inputs)

    @staticmethod
    def _decorate(result, compiled):
        return {**deepcopy(result), "canonical_review_bridge_version": REVIEW_BRIDGE_VERSION,
            "source_descriptor": deepcopy(compiled["source_descriptor"]),
            "origin_native_script_sha256": compiled["source_descriptor"]["native_script_sha256"],
            "derived_script_sha256": compiled["source_descriptor"]["derived_script_sha256"],
            "legacy_native_script_sha256_role": compiled["source_descriptor"]["legacy_review_native_script_sha256_role"],
            "native_review_values_rewritten": False}

    @staticmethod
    def _invalid(exc):
        return {"valid": False, "accepted": False, "status": "halt_derived_source_identity",
            "findings": [{"code": "DERIVED_SCRIPT_IDENTITY_INVALID", "reason": str(exc)}],
            "uncertainties": [], "content_checks_satisfied": False, "new_scope_admitted": False,
            "new_scope_revision_admitted": False, "canonical_review_bridge_version": REVIEW_BRIDGE_VERSION}

    def validate_part(self, document, part, script, brief, plan, legal_context, **options):
        try: compiled = contract.recover_compiled(script, options["goal_contract"], brief)
        except (ValueError, KeyError, TypeError) as exc: return self._invalid(exc)
        result = self.delegate.validate_part(document, part, script, brief, plan, legal_context, **options)
        return self._decorate(result, compiled)

    def build_review_bundle(self, native_semantic_review, native_physical_review):
        return self.delegate.build_review_bundle(native_semantic_review, native_physical_review)

    def validate_bundle(self, bundle, script, brief, plan, legal_context, **options):
        try: compiled = contract.recover_compiled(script, options["goal_contract"], brief)
        except (ValueError, KeyError, TypeError) as exc: return self._invalid(exc)
        result = self.delegate.validate_bundle(bundle, script, brief, plan, legal_context, **options)
        return self._decorate(result, compiled)


class ReviewWorkflow(prior.ReviewWorkflow):
    def full_reviews(self):
        return CanonicalReviewBridge(self.adapter)

    def prepare_script_request(self, inputs, profile, goal, audit, **kwargs):
        result = super().prepare_script_request(inputs, profile, goal, audit, **kwargs)
        rule = result["request"]["messages"][0]["content"]
        old_relation = prior.prior.contract.RELATION_RULE
        if rule.count(_OLD_WORLD_LINK_RULE) != 1 or rule.count(old_relation) != 1:
            raise ValueError("inherited writer predecessor rules differ; cannot silently append contradictory native contract")
        rule = rule.replace(_OLD_WORLD_LINK_RULE, _NEW_WORLD_LINK_RULE).replace(old_relation, contract.RELATION_RULE)
        result["request"]["messages"][0]["content"] = rule
        representation = contract.prepare_schema(goal)
        result["request"]["structured_schema"] = representation["schema"]
        result["request"]["input_provenance"].update(native_script_contract_version=contract.NATIVE_VERSION,
            derived_context_script_version=contract.VERSION)
        result["manifest"].update(replanned_workflow_version=VERSION,
            native_contract_representation=deepcopy(representation["manifest"]),
            actual_wire_schema_sha256=digest(representation["schema"]),
            inherited_previous_context_output_rules_removed=True)
        # The inherited canonical/direct manifest remains clearly labelled as
        # ancestry; only this new representation describes actual v2 output.
        result["manifest"]["direct_wire_representation_role"] = "ancestry only; actual v2 contract is native_contract_representation"
        return self.base._mark(result, inputs)

    def validate_script_document(self, native, views, production_preferences=None):
        return contract.compile_document(native, views["goal"], views["brief"])

    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        self.base._verify_views(inputs, views)
        compiled = self.validate_script_document(native, views, inputs["production_preferences"])
        return self.full_reviews().prepare_full_review_part_request(inputs, profile, native,
            {**deepcopy(views), "compiled_script": compiled["script"]}, part)

    @staticmethod
    def render_script(native, goal): return contract.render_script(native, goal)

    @staticmethod
    def build_segment_context(goal, native, *args, **kwargs):
        result = contract.world.build_segment_context(goal, contract.derive(native, goal), *args, **kwargs)
        result["origin_native_script_sha256"] = digest(native)
        result["canonical_source_role"] = "derived canonical screenplay; legacy native_script_sha256 is canonical-source SHA"
        return result
