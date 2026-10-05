"""Approved delivery -> existing account-bound browser publish -> operations receipts."""

from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
from .creative_stage_contracts import digest, persist, read
from .creative_media_workbench import file_binding
from .media_review_policy import validate_user_approved_candidate
from src.platform_adapter.models import PublishRequest
from src.platform_adapter.publish_verification import declared_description, video_id


def prepare_delivery(
    run_dir,
    review_path,
    *,
    account_key,
    account_uuid,
    title,
    description="",
    fictional_story=True,
    assembly_chain=None,
):
    if not account_key or not account_uuid or not title.strip():
        raise ValueError("delivery requires an explicit account and title")
    review = validate_user_approved_candidate(review_path)
    if review["candidate_identity"]["identifiers"].get("segment_id") != "final":
        raise ValueError(
            "publishing requires the approved full-film candidate, not a segment"
        )
    if assembly_chain:
        for row in assembly_chain["segments"]:
            validate_user_approved_candidate(row["review"]["path"])
            if (
                file_binding(row["review"]["path"]) != row["review"]
                or file_binding(row["video"]["path"]) != row["video"]
            ):
                raise ValueError("approved assembly source changed")
    value = {
        "schema": "creative_delivery/v1",
        "source_run": str(Path(run_dir).resolve()),
        "review": file_binding(review_path),
        "video": file_binding(review["original_video"]),
        "account_key": account_key,
        "account_uuid": account_uuid,
        "title": title.strip(),
        "description": declared_description(description, fictional_story),
        "fictional_story": fictional_story,
        "ai_generated": True,
        "assembly_chain": assembly_chain,
        "automatic_publish": False,
    }
    path = Path(run_dir) / ".creative_debug/delivery" / digest(value) / "delivery.json"
    persist(path, value, immutable=True)
    return {"path": str(path.resolve()), "delivery": value}


def validate_delivery(path, adapter):
    delivery = read(path)
    validate_user_approved_candidate(delivery["review"]["path"])
    if (
        file_binding(delivery["review"]["path"]) != delivery["review"]
        or file_binding(delivery["video"]["path"]) != delivery["video"]
    ):
        raise ValueError("approved delivery changed")
    context = adapter.runtime_context
    if (
        context is None
        or context.account_key != delivery["account_key"]
        or context.account_uuid != delivery["account_uuid"]
    ):
        raise ValueError("browser account differs from approved delivery account")
    return delivery


def request_for(delivery):
    return PublishRequest(
        video_path=delivery["video"]["path"],
        title=delivery["title"],
        description=delivery["description"],
        ai_generated=True,
        fictional_story=delivery["fictional_story"],
        extra_metadata={
            "account_key": delivery["account_key"],
            "account_uuid": delivery["account_uuid"],
            "creative_delivery_sha256": digest(delivery),
        },
    )


def journal_evidence(adapter):
    path = getattr(adapter.publish_workflow, "_journal_path", None)
    if not path or not Path(path).is_file():
        return {
            "journal": None,
            "ai_selected": False,
            "ai_verified": False,
            "fiction_verified": False,
        }
    rows = [
        __import__("json").loads(x)
        for x in Path(path).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    declarations = [
        x
        for x in rows
        if x.get("stage") == "ai_declaration_verified"
        and x.get("evidence", {}).get("verified") is True
    ]
    screenshots = [
        file_binding(p)
        for x in rows
        for p in [x.get("evidence", {}).get("screenshot")]
        if p and Path(p).is_file()
    ]
    return {
        "journal": file_binding(path),
        "ai_selected": any(x.get("set_selected") is True for x in declarations),
        "ai_verified": bool(declarations),
        "post_verified": any(
            x.get("stage") == "post_publish_checked"
            and x.get("evidence", {}).get("verified") is True
            for x in rows
        ),
        "fiction_verified": any(
            x.get("stage") == "fiction_declaration_verified" for x in rows
        ),
        "screenshots": screenshots,
    }


def publish_delivery(path, adapter):
    delivery = validate_delivery(path, adapter)
    lock = Path(path).parent / "submission.json"
    # Retain this lock through unknown submission and pending post-verification.
    with lock.open("x", encoding="utf-8") as stream:
        __import__("json").dump(
            {
                "schema": "creative_publish_submission/v1",
                "delivery_sha256": digest(delivery),
                "status": "submission_started",
            },
            stream,
        )
    try:
        result = adapter.publish_video(request_for(delivery))
        evidence = journal_evidence(adapter)
        finished = (
            result.success is True
            and result.status == "published"
            and bool(result.post_id)
            and video_id(result.publish_url) == result.post_id
            and evidence["ai_verified"]
            and evidence["ai_selected"]
            and evidence.get("post_verified") is True
            and (not delivery["fictional_story"] or evidence["fiction_verified"])
        )
        value = {
            "schema": "creative_publish_receipt/v1",
            "delivery_sha256": digest(delivery),
            "account_key": delivery["account_key"],
            "account_uuid": delivery["account_uuid"],
            "result": asdict(result),
            "evidence": evidence,
            "status": "published_verified"
            if finished
            else "awaiting_publish_verification",
            "submission_lock_retained": True,
            "operations_status": "not_collected",
        }
        persist(Path(path).parent / "publish_receipt.json", value)
        return value
    except Exception as exc:
        persist(
            Path(path).parent / "publish_receipt.json",
            {
                "schema": "creative_publish_receipt/v1",
                "delivery_sha256": digest(delivery),
                "status": "submission_unknown",
                "error": str(exc),
                "submission_lock_retained": True,
                "operations_status": "not_collected",
            },
        )
        raise


def verify_delivery(path, adapter):
    delivery = validate_delivery(path, adapter)
    receipt_path = Path(path).parent / "publish_receipt.json"
    receipt = read(receipt_path)
    if receipt.get("delivery_sha256") != digest(delivery):
        raise ValueError("publish receipt differs from delivery")
    result = receipt.get("result", {})
    if (
        not result.get("post_id")
        or video_id(result.get("publish_url", "")) != result["post_id"]
    ):
        raise ValueError(
            "exact published work unknown; inspect existing submission, never upload again"
        )
    evidence = adapter.verify_published_video(
        request_for(delivery), result["post_id"], result["publish_url"]
    )
    prior = receipt.get("evidence", {})
    finished = (
        evidence.get("verified") is True
        and prior.get("ai_selected") is True
        and prior.get("ai_verified") is True
        and (not delivery["fictional_story"] or prior.get("fiction_verified") is True)
    )
    receipt.update(
        status="published_verified" if finished else "awaiting_publish_verification",
        post_verification=evidence,
    )
    persist(receipt_path, receipt)
    return receipt


def collect_operations(path, adapter, *, page_limit=5):
    delivery = validate_delivery(path, adapter)
    publish = read(Path(path).parent / "publish_receipt.json")
    if publish.get("status") != "published_verified":
        raise ValueError(
            "operations collection requires a verified exact published work"
        )
    result = adapter.sync_videos(page_limit=page_limit)
    expected = publish["result"]["post_id"]
    matches = [
        v
        for v in result.videos
        if v.video_id == expected and v.account_uuid == delivery["account_uuid"]
    ]
    if not result.success or len(matches) != 1:
        raise ValueError(
            "operations snapshot is missing or belongs to another account/work"
        )
    from src.services.content_performance import normalize_metrics, record_snapshot

    video = matches[0]
    record_snapshot(video)
    value = {
        "schema": "creative_operations_feedback/v1",
        "delivery_sha256": digest(delivery),
        "account_uuid": delivery["account_uuid"],
        "post_id": expected,
        "source_url": publish["result"]["publish_url"],
        "raw_metrics": video.creator_metrics,
        "metrics": normalize_metrics(video.creator_metrics or {}),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "causal_quality_claim": False,
        "next_action": "human_review_of_operations_evidence",
    }
    persist(
        Path(path).parent / "operations" / (digest(value) + ".json"),
        value,
        immutable=True,
    )
    publish["operations_status"] = "collected"
    persist(Path(path).parent / "publish_receipt.json", publish)
    return value
