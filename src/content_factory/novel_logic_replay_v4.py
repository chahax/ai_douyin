"""Read-only research replay of frozen v3 receipts; never migrate a run.

This module checks source/draft coverage and the existing evidence, not the
semantic correctness of a reviewer.  It deliberately exposes no execution API.
"""
from __future__ import annotations

import json
from pathlib import Path
import re


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _review(text):
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.I | re.S)
    return json.loads(fenced.group(1) if fenced else text)


def replay_saved_v3(run_dir):
    """Verify an existing v3 run and each saved full-draft/full-review pair.

    Existing v3 ``inspect`` verifies frozen code, request/receipt hashes, source,
    snapshots and accounting.  No call to prepare/execute or any service occurs.
    Old verdicts and the old stop are reported unchanged.  A replay is not a v4
    scene extraction, adjudication, production acceptance or new authorization.
    """
    from . import novel_plaintext_contracts_v3 as contracts
    from . import novel_plaintext_pipeline_v3 as v3

    run = Path(run_dir).resolve()
    view = v3.inspect(run)
    result = {
        "schema_version": "novel_logic_replay/v4",
        "run_dir": str(run), "mode": "read_only_research",
        "original_status": view.get("status"),
        "status": "evidence_invalid", "pairs": [], "errors": [],
        "new_provider_requests": 0, "new_media_requests": 0,
        "production_dispatch_allowed": False, "human_approved": False,
        "semantic_quality_validated": False, "v4_acceptance": False,
    }
    if view.get("status") in {"unprepared", "evidence_invalid", "incomplete_artifacts"}:
        result["errors"] = view.get("blockers") or ["Existing v3 evidence is unavailable"]
        return result
    binding = _read(run / "BINDING.json")
    result.update(
        original_calls=view["combined_calls_started"],
        original_reported_tokens=view["combined_known_reported_tokens"],
        original_pending_call=view["pending_call"],
        original_stop_reasons=view["blockers"],
    )
    if view["pending_call"] is not None:
        result["errors"].append("Existing request unresolved; do not redispatch")
        return result
    for request_path in sorted(run.glob("REQUEST_*.json")):
        request = _read(request_path)
        if request.get("stage") != "review_full":
            continue
        ordinal = request["ordinal"]
        response = _read(run / f"RESPONSE_{ordinal:03}.json")
        row = {"review_ordinal": ordinal, "errors": []}
        try:
            errors, tokens, body = contracts.response_evidence(
                response, {**binding["protocol"]["director"], "role": "director"})
            row["errors"].extend(errors)
            if body is None or errors:
                raise ValueError("Review native envelope incomplete")
            review = _review(body)
            row["errors"].extend(error["code"] for error in contracts.validate_review(review))
            if review != _read(run / f"REVIEW_{ordinal:03}.json"):
                row["errors"].append("REVIEW_DERIVATION_MISMATCH")
            payload = json.loads(request["messages"][-1]["content"])
            writer = request["input_bindings"]["writer_full"]
            writer_response = _read(writer["receipt"]["path"])
            writer_errors, writer_tokens, draft = contracts.response_evidence(
                writer_response, {**binding["protocol"]["writer"], "role": "writer"})
            row["errors"].extend(writer_errors)
            if writer_errors or not isinstance(draft, str):
                raise ValueError("Writer native envelope incomplete; do not substitute reasoning or partial text")
            if (payload.get("source") != binding["source"]
                    or payload.get("screenplay") != draft
                    or Path(writer["file"]["path"]).read_bytes() != draft.encode("utf-8")):
                row["errors"].append("FULL_SOURCE_OR_DRAFT_MISMATCH")
            row.update(
                writer_ordinal=writer_response["ordinal"],
                native_verdict=review["verdict"],
                reviewed_dimensions=len(review["checks"]),
                issue_count=sum(len(check["issues"]) for check in review["checks"]),
                writer_reported_tokens=writer_tokens, review_reported_tokens=tokens,
                source_characters=len(binding["source"]["text"]),
                draft_characters=len(draft),
                full_source_and_same_draft_verified=not row["errors"],
            )
        except (ValueError, TypeError, KeyError, OSError) as exc:
            row["errors"].append(str(exc))
        result["pairs"].append(row)
    result["errors"].extend(
        f"review {row['review_ordinal']}: {error}"
        for row in result["pairs"] for error in row["errors"])
    if not result["pairs"]:
        result["errors"].append("NO_SAVED_FULL_REVIEW")
    if not result["errors"]:
        result["status"] = "saved_evidence_verified"
    return result
