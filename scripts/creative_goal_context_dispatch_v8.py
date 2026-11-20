"""Independent source-v3 output allowance; all other stage gates stay frozen."""
from copy import deepcopy

from jsonschema import Draft202012Validator

from scripts.creative_goal_context_dispatch_v7 import GoalContextRuntime as PriorRuntime
from scripts import creative_deepseek_strict_role_clients_v2 as strict_clients

SOURCE_VERSION = "creative_goal_legal_usage_source_audit/v3"


class GoalContextRuntime(PriorRuntime):
    def _request_gate(self, request):
        schema = request.get("structured_schema", {})
        compact = schema.get("properties", {}).get("schema", {}).get("const") == SOURCE_VERSION
        if not compact:
            return super()._request_gate(request)
        policy = self.profile.get("source_strict", {})
        if (request.get("role") != "director" or request.get("stage") != "goal_audit"
                or request.get("model") != self.models["director"]["model"]
                or request.get("model") != strict_clients.REVIEW_MODEL
                or policy.get("enabled") is not True or policy.get("role") != "director"
                or policy.get("stage") != "goal_audit" or policy.get("schema_version") != SOURCE_VERSION
                or policy.get("base_url") != strict_clients.REVIEW_BASE_URL
                or policy.get("function_strict") is not True
                or policy.get("other_deepseek_stages_strict") is not False
                or type(policy.get("max_completion_tokens")) is not int
                or policy["max_completion_tokens"] != 24000
                or type(policy.get("max_wire_utf8_bytes")) is not int
                or not 0 < policy["max_wire_utf8_bytes"] <= 600000
                or type(policy.get("sdk_max_retries")) is not int or policy["sdk_max_retries"] != 0
                or policy.get("http_follow_redirects") is not False):
            raise RuntimeError("exact compact source-v3-only strict policy required")
        expected = deepcopy(self.profile["director"]["parameters"])
        override = self.profile.get("stage_parameters", {}).get("goal_audit", {})
        if set(override) - {"max_completion_tokens"}:
            raise RuntimeError("stage profile can only override output allowance")
        expected.update(override)
        expected["max_completion_tokens"] = 24000
        if request.get("parameters") != expected:
            raise RuntimeError("compact source request differs from exact selected source profile")
        strict_clients.expected_wire_request(request)
        binding = strict_clients.protocol_binding(request, review_base_url=policy["base_url"])
        if request.get("input_provenance", {}).get("source_protocol_binding") != binding:
            raise RuntimeError("compact source protocol binding absent or changed")
        Draft202012Validator.check_schema(schema)

    def _policy(self):
        value = super()._policy()
        value.update(schema="creative_goal_context_dispatch/v8/policy",
                     source_only_output_allowance=24000,
                     source_only_schema_version=SOURCE_VERSION,
                     original_other_stage_parameters_preserved=True)
        return value
