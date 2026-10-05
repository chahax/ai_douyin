"""One exclusive media submission; query never resubmits an uncertain task."""

from __future__ import annotations
import base64, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from .seedance_client import SeedanceReference, SeedanceAPIError
from .media_review_policy import (
    USER_MANUAL_REVIEW_POLICY_VERSION,
    mark_saved_candidate,
    validate_approved_tail,
)
from .creative_stage_contracts import persist, digest


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(p, v):
    Path(p).write_text(
        json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate(plan_path):
    p = Path(plan_path).resolve()
    plan = read(p)
    if plan.get("schema") != "creative_seedance_segment_plan/v1":
        raise ValueError("wrong plan schema")
    frame = Path(plan["first_frame"]["path"]).resolve()
    if sha(frame) != plan["first_frame"]["sha256"]:
        raise ValueError("frame changed")
    frame_source = plan.get("opening_frame_source") or plan.get("first_frame", {}).get(
        "source"
    )
    if frame_source == "preceding_approved_raw_tail":
        review = Path(plan["predecessor_review"]["path"]).resolve()
        if sha(review) != plan["predecessor_review"]["sha256"]:
            raise ValueError("predecessor review changed")
        approved = validate_approved_tail(review, expected_tail_path=frame)
        if plan.get("segment_order"):
            from src.content_factory.creative_media_workbench import (
                approved_predecessor,
            )

            approved_predecessor(plan["segment_order"], plan["segment_id"], review)
        if approved["sha256"] != plan["first_frame"]["sha256"]:
            raise ValueError("approved raw tail hash mismatch")
    else:
        review = Path(plan["first_frame_review"]["path"]).resolve()
        if sha(review) != plan["first_frame_review"]["sha256"]:
            raise ValueError("frame review changed")
        r = read(review)
        if not r.get("checks"):
            raise ValueError("first frame review has no explicit checks")
        if (
            plan.get("segment_order")
            and plan["segment_order"].index(plan["segment_id"]) > 0
        ):
            from .media_review_policy import validate_user_approved_candidate

            predecessor = plan.get("predecessor_review")
            if not predecessor or sha(predecessor["path"]) != predecessor["sha256"]:
                raise ValueError("cut predecessor approval changed")
            reviewed = validate_user_approved_candidate(predecessor["path"])
            order = plan["segment_order"]
            if (
                reviewed["candidate_identity"]["identifiers"].get("segment_id")
                != order[order.index(plan["segment_id"]) - 1]
            ):
                raise ValueError("cut predecessor is not adjacent")
        if (
            r.get("decision") != "passed"
            or r.get("first_frame_sha256") != plan["first_frame"]["sha256"]
            or any(v is not True for v in r.get("checks", {}).values())
        ):
            raise ValueError("first frame review incomplete")
    for item in plan["sources"].values():
        if sha(item["path"]) != item["sha256"]:
            raise ValueError("source changed")
    if plan.get("performance_run"):
        from src.content_factory.performance_revision_gate import (
            validate_performance_video_plan,
        )

        validate_performance_video_plan(plan)
    return p, plan, frame


def reference(frame):
    mime = "png" if frame.suffix.lower() == ".png" else "jpeg"
    return SeedanceReference(
        "image",
        f"data:image/{mime};base64,"
        + base64.b64encode(frame.read_bytes()).decode("ascii"),
        "first_frame",
    )


def payload(plan, frame, client):
    if plan.get("payload_template"):
        from copy import deepcopy

        if digest(plan["payload_template"]) != plan.get("payload_template_sha256"):
            raise ValueError("prepared request template changed")
        request = deepcopy(plan["payload_template"])
        request["content"] = [
            x if x.get("type") == "text" else reference(frame).to_content()
            for x in request["content"]
        ]
        request["seed"] = int(plan["seed"])
        return request
    return client.build_task_payload(
        plan["prompt"],
        duration=int(plan["duration_seconds"]),
        ratio=plan.get("ratio", "adaptive"),
        resolution=plan["resolution"],
        generate_audio=True,
        watermark=False,
        return_last_frame=True,
        seed=int(plan["seed"]),
        references=[reference(frame)],
        task_type="first_frame",
    )


def _execute_segment(plan_path, output_dir, operation, client, *, wait_timeout=1800):
    if operation not in ("preview", "submit", "query"):
        raise ValueError("unknown media operation")
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / "receipt.json"
    if operation == "query":
        if not receipt.exists():
            raise ValueError("no submission receipt; query cannot create a task")
        record = read(receipt)
        if not record.get("task_id"):
            raise ValueError(
                "submission outcome unknown without a task ID; reconcile with provider, never resubmit"
            )
        plan = record.get("plan_snapshot") or read(plan_path)
        # Query the original ID even after an upstream edit. Approval still checks lineage.
        if record.get("technical_status") == "succeeded":
            for path_key, hash_key in (
                ("video_path", "video_sha256"),
                ("last_frame", "last_frame_sha256"),
            ):
                if sha(record[path_key]) != record[hash_key]:
                    raise ValueError("saved provider file changed")
            return record
    else:
        plan_path, plan, frame = validate(plan_path)
        from .creative_state_store import check_media_dispatch
        check_media_dispatch(plan)
        run = plan.get("source_run")
        if run:
            control = Path(run) / ".creative_debug/control.json"
            if control.exists() and read(control).get("action") == "stop":
                raise ValueError("user stop blocks future media submission")
        request = payload(plan, frame, client)
        request_record = {k: v for k, v in request.items() if k != "content"}
        request_record["content"] = [
            {"type": "text", "text": plan["prompt"]},
            {
                "type": "image_url",
                "role": "first_frame",
                "image_url": {
                    "data_sha256": plan["first_frame"]["sha256"],
                    "mime": "image/png"
                    if frame.suffix.lower() == ".png"
                    else "image/jpeg",
                },
            },
        ]
        record = {
            "schema": "creative_seedance_segment_receipt/v1",
            "status": "previewed",
            "technical_status": "not_submitted",
            "content_status": "not_available",
            "review_policy_version": USER_MANUAL_REVIEW_POLICY_VERSION,
            "plan": str(plan_path),
            "plan_sha256": sha(plan_path),
            "plan_snapshot": plan,
            "segment_id": plan["segment_id"],
            "shot_id": plan.get("shot_id"),
            "provider": "ark_api",
            "model": plan.get("model"),
            "logical_task_id": plan.get("logical_task_id"),
            "source_bindings": {
                **plan.get("sources", {}),
                "first_frame_input": plan["first_frame"],
                **{
                    key: plan[key]
                    for key in ("first_frame_review", "predecessor_review")
                    if key in plan
                },
            },
            "request": request_record,
            "request_sha256": digest(request_record),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if operation == "preview":
            persist(out / "request.preview.json", record)
            return record
        record.update(status="submitting", technical_status="running")
        # Exclusive creation occurs before budget reservation or any external effect.
        try:
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
        except FileExistsError:
            raise ValueError("receipt exists; query instead of resubmitting") from None
        try:
            reserve_media_attempt(plan_path, plan, receipt)
            if plan.get("performance_run"):
                from .performance_revision_gate import reserve_performance_video

                reserve_performance_video(plan, receipt)
            check_media_dispatch(plan)
        except Exception as exc:
            record.update(
                status="blocked_before_submit",
                technical_status="not_submitted",
                task_created=False,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            persist(receipt, record)
            raise
        try:
            created = client.create_task(request)
            if not created.get("id"):
                raise ValueError("provider returned no task ID; outcome unknown")
        except Exception as exc:
            privacy = (
                isinstance(exc, SeedanceAPIError)
                and exc.status_code == 400
                and exc.error_code
                == "InputImageSensitiveContentDetected.PrivacyInformation"
            )
            record.update(
                status="rejected_pre_generation"
                if privacy
                else "submit_outcome_unknown",
                error_type=type(exc).__name__,
                error=str(exc),
                task_created=False if privacy else None,
                technical_status="failed" if privacy else "unknown",
            )
            persist(receipt, record)
            raise
        record.update(status="submitted", task_id=created["id"], created=created)
        persist(receipt, record)
    try:
        task = client.wait_for_task(record["task_id"], timeout_seconds=wait_timeout)
        video = client.download_video(task, out / (plan["segment_id"] + ".mp4"))
        last = client.download_last_frame(
            task, out / (plan["segment_id"] + ".last.png")
        )
        if (
            not Path(video).is_file()
            or Path(video).stat().st_size == 0
            or not Path(last).is_file()
            or Path(last).stat().st_size == 0
        ):
            raise ValueError("provider output file is incomplete")
        record.update(
            final=task,
            video_path=str(Path(video).resolve()),
            video_sha256=sha(video),
            last_frame=str(Path(last).resolve()),
            last_frame_sha256=sha(last),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        mark_saved_candidate(record)
        persist(receipt, record)
    except Exception as exc:
        record.update(status="task_query_pending", error=str(exc))
        persist(receipt, record)
        raise
    if plan.get("source_run"):
        from .creative_media_workbench import register_candidate

        try:
            register_candidate(
                plan["source_run"], receipt, expected_plan_sha256=record["plan_sha256"]
            )
        except ValueError as exc:
            record.update(
                workbench_status="source_lineage_stale", workbench_error=str(exc)
            )
            persist(receipt, record)
    return record


def execute_segment(plan_path, output_dir, operation, client, *, wait_timeout=1800):
    """Serialize receipt writers; a crash retains the lock for reconciliation."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".execution.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write("exclusive media receipt writer")
    try:
        return _execute_segment(
            plan_path, out, operation, client, wait_timeout=wait_timeout
        )
    finally:
        lock.unlink()


def media_reservation_root(plan):
    if plan.get("source_run"):
        return Path(plan["source_run"]).resolve() / ".creative_debug/media/submissions"
    root = Path(__file__).resolve().parents[2] / "data/creative_media_submissions"
    scope = plan.get("logical_task_id") or digest(plan.get("sources", {}))
    return root / digest(scope)


def reserve_media_attempt(plan_path, plan, receipt):
    """A changed output directory cannot bypass task identity or failure budget."""
    root = media_reservation_root(plan)
    root.mkdir(parents=True, exist_ok=True)
    dispatch_lock = root / ".dispatch.lock"
    with dispatch_lock.open("x", encoding="utf-8") as stream:
        stream.write("exclusive media budget reservation")
    try:
        limit = 10
        if plan.get("source_run"):
            limit = read(Path(plan["source_run"]) / "state.json").get(
                "video_failure_limit", 10
            )
        ledger_path = root / "budget.json"
        ledger = (
            read(ledger_path)
            if ledger_path.exists()
            else {
                "schema": "creative_media_budget/v1",
                "failure_limit": limit,
                "scope": "current_script",
                "budget_reset_supported": False,
            }
        )
        if (
            ledger["failure_limit"] != limit
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ValueError("same-script media failure budget cannot be changed")
        failures = 0
        for path in root.glob("*.reservation.json"):
            prior = read(path)
            saved = Path(prior["receipt"])
            if not saved.is_file():
                raise ValueError(
                    "prior media reservation has no receipt; reconcile before submitting"
                )
            candidate = read(saved)
            failures += int(
                candidate.get("technical_status") == "failed"
                or candidate.get("content_status") == "rejected"
            )
            if prior["segment_id"] == plan["segment_id"] and (
                candidate.get("technical_status") in ("running", "unknown")
                or candidate.get("content_status") == "awaiting_human_review"
            ):
                raise ValueError(
                    "prior segment submission or human review remains unresolved; query its original receipt"
                )
        ledger.update(
            confirmed_failed_current_script=failures,
            confirmed_failure_records=[str(p) for p in root.glob("*.reservation.json")],
            historical_other_script_failures="retained_in_original_script_ledgers; not charged to this script",
        )
        persist(ledger_path, ledger)
        if failures >= limit:
            raise ValueError(
                "current-script media failure budget exhausted; history retained"
            )
        binding = {
            "schema": "creative_media_reservation/v1",
            "plan_sha256": sha(plan_path),
            "segment_id": plan["segment_id"],
            "receipt": str(Path(receipt).resolve()),
            "source_run": plan.get("source_run"),
            "logical_task_id": plan.get("logical_task_id"),
        }
        target = root / (sha(plan_path) + ".reservation.json")
        with target.open("x", encoding="utf-8") as stream:
            json.dump(binding, stream, ensure_ascii=False, indent=2)
        ledger.update(
            confirmed_failed_current_script=failures,
            confirmed_failure_records=[str(p) for p in root.glob("*.reservation.json")],
            historical_other_script_failures="retained_in_original_script_ledgers; not charged to this script",
        )
        persist(ledger_path, ledger)
    finally:
        dispatch_lock.unlink()
