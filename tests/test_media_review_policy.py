from src.content_factory.media_review_policy import (
    AWAITING_HUMAN_REVIEW,
    USER_MANUAL_REVIEW_POLICY_VERSION,
    mark_saved_candidate,
)


def test_saved_candidate_separates_technical_success_from_content_review():
    record = {"status": "submitted", "content_status": "not_available"}

    returned = mark_saved_candidate(record)

    assert returned is record
    assert record["status"] == "succeeded_awaiting_human_review"
    assert record["technical_status"] == "succeeded"
    assert record["content_status"] == AWAITING_HUMAN_REVIEW
    assert record["review_policy_version"] == USER_MANUAL_REVIEW_POLICY_VERSION
    assert record["user_decision_source"] is None
    assert "passed" not in record.values()


def test_legacy_downloaded_status_can_be_retained_without_approving_content():
    record = {}

    mark_saved_candidate(record, status="downloaded")

    assert record["status"] == "downloaded"
    assert record["technical_status"] == "succeeded"
    assert record["content_status"] == "awaiting_human_review"
