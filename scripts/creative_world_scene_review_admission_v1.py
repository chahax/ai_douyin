"""Separate new-scope admission from unchanged native v6 review decisions.

No provider, claim, budget mutation or grant creation. The coordinator must
verify the sealed USER_SCOPE file and consume real capacities under its lock.
This pure adapter retains even the old accepted=false/status verbatim.
"""
from copy import deepcopy
from pathlib import Path
import re

from src.content_factory import creative_full_review_protocol_v6 as full

VERSION = "creative_world_scene_review_admission/v1"
BUNDLE_VERSION = full.BUNDLE_VERSION
PART_TABLES = full.PART_TABLES
digest = full.digest
OLD_QUOTA_STOP = "halt_same_story_prior_allowance_exhausted"


def _require(condition, reason):
    if not condition: raise ValueError(reason)


def _sha(value): return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class ReviewAdmission:
    """An immutable original-scope identity, not a remaining-capacity flag."""
    VERSION = VERSION
    BUNDLE_VERSION = BUNDLE_VERSION
    PART_TABLES = PART_TABLES
    digest = staticmethod(digest)

    def __init__(self, user_scope, *, expected_user_scope_sha256, prior_story_scope,
                 expected_root, expected_inputs_sha256=None):
        _require(type(user_scope) is dict and digest(user_scope) == expected_user_scope_sha256,
            "sealed USER_SCOPE canonical identity differs")
        root = str(Path(expected_root).resolve())
        _require(type(user_scope.get("root")) is str and str(Path(user_scope["root"]).resolve()) == root,
            "new story scope belongs to a different run root")
        _require(type(user_scope.get("grant_id")) is str and bool(user_scope["grant_id"].strip()), "explicit new grant identity required")
        _require(user_scope.get("text_same_story_allowed") is True
            and type(user_scope.get("new_director_scope_limit")) is int and user_scope["new_director_scope_limit"] == 3,
            "explicit bounded same-story text/director authorization required")
        _require(type(prior_story_scope) is dict and user_scope.get("prior_scope_sha256") == digest(prior_story_scope),
            "original exhausted scope must be inherited exactly")
        _require(type(prior_story_scope.get("director_used")) is int and prior_story_scope["director_used"] > 0
            and type(prior_story_scope.get("director_limit")) is int and prior_story_scope["director_used"] == prior_story_scope["director_limit"]
            and prior_story_scope.get("director_remaining") == 0 and type(prior_story_scope.get("director_remaining")) is int,
            "historical exhausted director scope must remain unchanged")
        full._prior_scope({}, prior_story_scope)
        _require(_sha(user_scope.get("inputs_sha256")), "new grant must bind complete current inputs")
        if expected_inputs_sha256 is not None:
            _require(user_scope["inputs_sha256"] == expected_inputs_sha256, "new grant inputs identity differs")
        self._scope = deepcopy(user_scope)
        self._prior = deepcopy(prior_story_scope)
        self._scope_sha = expected_user_scope_sha256
        self._root = root

    def _scope_kwargs(self, options):
        value = deepcopy(options)
        if value.get("prior_story_scope") is not None:
            _require(value["prior_story_scope"] == self._prior, "review caller changed original prior scope")
        value["prior_story_scope"] = deepcopy(self._prior)
        return value

    def _decorate(self, result, native_semantic, script):
        underlying = deepcopy(result)
        settled_content = (underlying.get("valid") is True and underlying.get("findings") == []
            and underlying.get("uncertainties") == [])
        only_old_quota = False
        known_quota_identity = False
        identity_basis = None
        if (underlying.get("valid") is True and underlying.get("uncertainties") == []
                and underlying.get("status") == OLD_QUOTA_STOP and isinstance(native_semantic, dict)):
            relation = native_semantic.get("prior_story_relation", {}).get("relation")
            # Unknown remains a review stop, even if another identity check
            # could guess the answer. No other failure is silently reclassified.
            native_target = native_semantic.get("revision_target")
            if isinstance(underlying.get("part_results"), dict):
                targets = {row.get("revision_target") for row in underlying["part_results"].values()}
                native_target = "plan" if "plan" in targets else "script" if "script" in targets else "none"
            body = full.previous.checks.reviews.base.base.prior.story_body_digest
            exact = body(script) == body(self._prior["full_prior_script"])
            known_quota_identity = relation in ("same_story", "new_story") and (relation == "same_story" or exact)
            only_old_quota = settled_content and native_target == "none" and known_quota_identity
            if known_quota_identity: identity_basis = "native_same_story" if relation == "same_story" else "deterministic_identical_body"
        normal = settled_content and underlying.get("accepted") is True
        eligible = normal or only_old_quota
        known_failure = known_quota_identity and bool(underlying.get("findings"))
        revision = known_failure and native_target == "script"
        plan_revision = known_failure and native_target == "plan"
        # accepted/status/revision_dispatch_blocked are intentionally untouched.
        return {**deepcopy(result), "review_admission_version": VERSION, "underlying_v6_decision": underlying,
            "native_v6_review_accepted": underlying.get("accepted") is True,
            "content_checks_satisfied": eligible, "new_scope_admitted": eligible,
            "new_scope_revision_admitted": revision, "new_scope_requires_new_goal_plan": plan_revision,
            "requires_new_goal_plan": underlying.get("requires_new_goal_plan", False) or plan_revision,
            "admission_status": "content_checks_satisfied_under_new_story_scope" if only_old_quota else
                "whole_script_revision_under_new_story_scope" if revision else
                "new_complete_goal_required" if plan_revision else "native_content_checks_satisfied" if normal else "not_admitted",
            "old_quota_only_qualification": only_old_quota, "same_story_identity_basis": identity_basis,
            "admission_user_scope_sha256": self._scope_sha, "admission_root": self._root,
            "admission_inputs_sha256": self._scope["inputs_sha256"],
            "inherited_prior_scope_sha256": digest(self._prior), "new_director_scope_limit": 3,
            "capacity_consumed_here": False, "remaining_capacity_verified_here": False,
            "sealed_scope_file_verified_here": False, "native_review_response_rewritten": False,
            "old_budget_reset": False, "human_quality_approved": False, "creative_quality_passed": False}

    def _invalid(self, reason):
        return {"valid": False, "accepted": False, "status": "halt_review_admission_identity",
            "findings": [{"code": "NEW_STORY_SCOPE_IDENTITY_INVALID", "reason": reason}], "uncertainties": [],
            "review_admission_version": VERSION, "underlying_v6_decision": None,
            "content_checks_satisfied": False, "new_scope_admitted": False,
            "new_scope_revision_admitted": False, "new_scope_requires_new_goal_plan": False,
            "old_budget_reset": False, "human_quality_approved": False, "creative_quality_passed": False}

    def validate_part(self, document, part, script, brief, plan, legal_context, **options):
        try: options = self._scope_kwargs(options)
        except ValueError as exc: return self._invalid(str(exc))
        result = full.validate_part(document, part, script, brief, plan, legal_context, **options)
        return self._decorate(result, document if part == "semantic" else None, script)

    @staticmethod
    def build_review_bundle(native_semantic_review, native_physical_review):
        return full.build_review_bundle(native_semantic_review, native_physical_review)

    def validate_bundle(self, bundle, script, brief, plan, legal_context, **options):
        try: options = self._scope_kwargs(options)
        except ValueError as exc: return self._invalid(str(exc))
        result = full.validate_bundle(bundle, script, brief, plan, legal_context, **options)
        semantic = bundle.get("native_semantic_review") if isinstance(bundle, dict) else None
        # Native v6 bundle validity includes the complete physical report and
        # rechecking of both unchanged parts against the merged temporal proof.
        return self._decorate(result, semantic, script)

    def prepare_full_review_part_request(self, inputs, profile, native_script, views, part):
        _require(digest(inputs) == self._scope["inputs_sha256"], "review preparation changed granted current inputs")
        _require(inputs.get("production_preferences", {}).get("prior_story_scope") == self._prior,
            "review preparation omitted or changed historical scope")
        return full.prepare_full_review_part_request(inputs, profile, native_script, views, part)


def make_review_adapter(user_scope, *, expected_user_scope_sha256, prior_story_scope,
                        expected_root, expected_inputs_sha256=None):
    return ReviewAdmission(user_scope, expected_user_scope_sha256=expected_user_scope_sha256,
        prior_story_scope=prior_story_scope, expected_root=expected_root, expected_inputs_sha256=expected_inputs_sha256)
