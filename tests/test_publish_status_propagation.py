from types import SimpleNamespace

from src.agent.registry import _publish_douyin_video
from src.platform_adapter import DouyinAdapter
from src.scheduler.models import TaskExecution, TaskStatus
from src.scheduler.queue import TaskQueue
from test_task_queue_claim import _sessions


def test_agent_publish_skill_preserves_pending_verification(monkeypatch):
    adapter = SimpleNamespace(
        publish_video=lambda request: SimpleNamespace(
            success=True,
            status="post_publish_verification_pending",
            post_id="post-1",
            publish_url="https://www.douyin.com/video/post-1",
            message="平台已接受提交，发布后检查待核验；禁止重复上传",
        ),
    )
    monkeypatch.setattr(
        DouyinAdapter,
        "for_account",
        classmethod(lambda cls, account_key: adapter),
    )

    result = _publish_douyin_video("candidate.mp4", "fixture")

    assert result["success"] is True
    assert result["status"] == "post_publish_verification_pending"
    assert result["finalized"] is False


def test_worker_keeps_pending_publish_out_of_completed_state(tmp_path):
    factory = _sessions(tmp_path)
    session = factory()
    queue = TaskQueue(session, owner_id="worker-a")
    execution = queue.claim_next()
    result = {
        "success": True,
        "code": "ok",
        "data": {
            "status": "post_publish_verification_pending",
            "finalized": False,
        },
    }

    queue.mark_awaiting_verification(execution, result)

    session.expire_all()
    saved = session.query(TaskExecution).one()
    assert saved.status == TaskStatus.AWAITING_VERIFICATION.value
    assert saved.result == result
    assert saved.completed_at is None
    assert queue.get_queue_stats()["awaiting_verification"] == 1
