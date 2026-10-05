"""Offline candidate: add previous-beat evidence to script review v6.

This wrapper does not change frozen v6 validation or any review conclusion.
It is not registered in a production workflow and supplies no semantic approval.
"""
from src.content_factory.creative_review_v6 import validate_review_v6
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "evidence_script_sources_v7"


def validate_review_v7(value: dict, context: dict) -> None:
    """Run unchanged v6 first, then require both script continuity sources."""
    validate_review_v6(value, context)
    if "shots" in context:
        return
    indexes = {beat["id"]: index
               for index, beat in enumerate(context.get("script", {}).get("beats", []))}
    for row_index, row in enumerate(value["coverage"]):
        index = indexes[row["id"]]
        check = row["checks"]["continuity"]
        if index == 0 or check["status"] not in ("pass", "fail"):
            continue
        # Existence, scalar leaf type and verbatim quotes were checked by v6.
        paths = [ref["path"] for ref in check["evidence_refs"]]
        required = [f"script.beats.{index}.", f"script.beats.{index - 1}."]
        missing = [prefix for prefix in required
                   if not any(path.startswith(prefix) for path in paths)]
        if missing:
            raise CreativeContractError(
                f"v7剧本连续性缺少前后拍正文证据: coverage.{row_index}.checks.continuity.evidence_refs 缺少"
                + ", ".join(missing))
