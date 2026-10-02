---
schema_version: creative_quality_cost_report/v1
source_hash: e52cf3fc35b43305ebca71aa9daff9d92f47ac07134604101d722fe462f07ddc
created_at: 2026-09-28T13:54:12.499432+00:00
implementation_status: offline_infrastructure_only
---

# Quality and cost status

Implemented: offline scoped registry validation, rule conflict/lifecycle helpers, candidate fixture freezing, evaluation gates, and missing-aware cost reporting. Production integration is not enabled by this pack.

Inventory: 7 individually mapped rules, one explicit coarse exclusion record. This is not a repository-wide rule census. Semantic rules remain proposed; active deterministic rules are not proof of semantic coverage.

Dataset: 22 candidate cases, 0 approved gold cases, 0 approved holdout cases. R01-R03 derive from one story; conceptual correct variants are not separately validated complete plans. Required 80 independent approved cases / 40 holdouts are unmet. No benchmark model calls were executed.

Baseline: 4 actual historical requests. Provider token counts are recorded separately in baseline_metrics.json. Cache usage, invoice prices, currency and active human minutes are unavailable and remain null. No qualified handoff; cost per qualified handoff is undefined, not zero. No actual fee reduction claim is supported.

Quality, cost and latency targets remain blocked/unverified. See eval_config.json and eval_results.jsonl for executable thresholds and integer denominators.
