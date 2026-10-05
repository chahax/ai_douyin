"""Candidate quality cases and explicit human gold; no automatic quality claims."""

from pathlib import Path
from datetime import datetime, timezone
from .creative_stage_contracts import digest, persist, read
from .creative_media_workbench import file_binding
from .creative_evaluation import (
    DEFAULT_CONFIG,
    validate_dataset,
    normalize_call,
    summarize_cost,
    score_review_runs,
    score_production_runs,
)


def collect_case(
    run_dir,
    stage_id,
    *,
    category,
    source_family,
    independence_group,
    split="development",
):
    if split not in ("development", "holdout"):
        raise ValueError("invalid case split")
    if (
        category not in DEFAULT_CONFIG["dataset"]["categories"]
        or not source_family
        or not independence_group
    ):
        raise ValueError(
            "case needs category, source family and independent story group"
        )
    from .creative_stage_debug import CreativeStageCommandService

    root = Path(run_dir).resolve()
    stage = next(
        (
            x
            for x in CreativeStageCommandService(root).inspect()["stages"]
            if x["stage_id"] == stage_id
        ),
        None,
    )
    if stage is None or not stage["artifact_verified"]:
        raise ValueError("quality candidate needs a verified stage artifact")
    snapshot = file_binding(root / (stage_id + ".json"))
    # Copy a frozen source rather than binding a mutable current-stage filename.
    case_id = digest(
        {
            "stage": stage_id,
            "output": stage["output_sha256"],
            "input": stage["input_sha256"],
            "family": source_family,
            "independence_group": independence_group,
            "category": category,
            "split": split,
        }
    )
    source_path = root / ".creative_debug/quality/sources" / (case_id + ".json")
    persist(source_path, read(snapshot["path"]), immutable=True)
    value = {
        "case_id": case_id,
        "stage_id": stage_id,
        "stage_output_sha256": stage["output_sha256"],
        "category": category,
        "source_family": source_family,
        "independence_group": independence_group,
        "source": file_binding(source_path),
        "case_kind": "unlabelled",
        "label_status": "candidate",
        "split": split,
        "used_for_prompt_tuning": split == "development",
        "expected_issues": [],
        "adjudication": None,
        "quality_rubric": [
            "story_causality",
            "emotion_timing",
            "readable_reaction",
            "shot_execution",
            "ending_resolution",
        ],
    }
    persist(
        root / ".creative_debug/quality/cases" / (case_id + ".json"),
        value,
        immutable=True,
    )
    return value


def annotate_case(case_path, annotation):
    case = read(case_path)
    if (
        annotation.get("decision_source") != "explicit_human_gold"
        or not annotation.get("approved_by")
        or not annotation.get("user_statement")
        or annotation.get("case_id") != case["case_id"]
        or annotation.get("source_sha256") != case["source"]["sha256"]
    ):
        raise ValueError(
            "gold label needs an explicit human and exact frozen source binding"
        )
    if file_binding(case["source"]["path"]) != case["source"]:
        raise ValueError("gold source changed")
    if annotation.get("case_kind") not in ("error", "correct") or annotation.get(
        "split"
    ) not in ("development", "holdout"):
        raise ValueError("invalid gold label kind or split")
    if annotation["split"] == "holdout" and case["used_for_prompt_tuning"]:
        raise ValueError("a development/tuning case cannot be promoted to holdout")
    issues = annotation.get("expected_issues", [])
    if (annotation["case_kind"] == "error" and not issues) or (
        annotation["case_kind"] == "correct" and issues
    ):
        raise ValueError("gold issue list conflicts with label kind")
    if len({issue.get("issue_id") for issue in issues}) != len(issues):
        raise ValueError("gold issue IDs must be unique")
    for issue in issues:
        if (
            not issue.get("issue_id")
            or issue.get("severity") not in ("minor", "major", "blocking")
            or not issue.get("evidence")
        ):
            raise ValueError("gold issues require ID, severity and source evidence")
    gold = {
        **case,
        "label_status": "approved",
        "case_kind": annotation["case_kind"],
        "split": annotation["split"],
        "expected_issues": issues,
        "adjudication": {
            **annotation,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    target = Path(case_path).with_name(Path(case_path).stem + ".gold.json")
    if target.exists():
        old = read(target)
        if old["adjudication"]["user_statement"] != annotation["user_statement"] or any(
            old.get(k) != gold[k] for k in ("case_kind", "split", "expected_issues")
        ):
            raise ValueError(
                "gold labels are immutable; adjudicate a new version explicitly"
            )
        return old
    persist(target, gold, immutable=True)
    return gold


def freeze_dataset(case_paths, output):
    cases = [read(p) for p in case_paths]
    for case in cases:
        if file_binding(case["source"]["path"]) != case["source"]:
            raise ValueError("frozen quality source changed")
    result = validate_dataset(cases)
    value = {
        "schema_version": "creative_quality_dataset/v1",
        "cases": cases,
        "config_sha256": digest(DEFAULT_CONFIG),
        "readiness": result,
        "automatic_gold_labels": False,
        "quality_improvement_verified": False,
    }
    persist(output, value, immutable=True)
    return value


def quality_report(run_dir, *, dataset_path=None, runs_path=None, production_path=None):
    root = Path(run_dir)
    calls, bindings = [], []
    for path in sorted(root.glob("*.json")):
        record = read(path)
        if isinstance(record, dict) and (
            record.get("response_metadata") is not None
            or record.get("request", {}).get("messages")
        ):
            calls.append(
                normalize_call(
                    {
                        **record,
                        "response_metadata": record.get("response_metadata") or {},
                    },
                    path,
                )
            )
            bindings.append(file_binding(path))
    cases = read(dataset_path)["cases"] if dataset_path else []
    runs = (
        [
            __import__("json").loads(x)
            for x in Path(runs_path).read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        if runs_path
        else []
    )
    production = (
        read(production_path) if production_path else {"normal": [], "boundary": []}
    )
    report = {
        "schema": "creative_quality_evidence_report/v1",
        "call_sources": bindings,
        "dataset_source": file_binding(dataset_path) if dataset_path else None,
        "runs_source": file_binding(runs_path) if runs_path else None,
        "production_source": file_binding(production_path) if production_path else None,
        "evaluation": score_review_runs(cases, runs),
        "production": score_production_runs(
            production["normal"], production["boundary"]
        ),
        "cost": summarize_cost(calls, [], 0),
        "media_review_performed": False,
        "quality_improvement_verified": False,
        "automatic_paid_execution": False,
    }
    persist(
        root / ".creative_debug/quality/reports" / (digest(report) + ".json"),
        report,
        immutable=True,
    )
    return report
