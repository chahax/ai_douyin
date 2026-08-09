"""
src/novel_promotion/publish_service.py — 发布与跨库同步服务

NovelPromotionPublishSyncService is the ONLY service that updates
fanqie_publish_records.douyin_video_id. Generic douyin-sync must not
directly modify fanqie closed-loop tables.

Cross-DB validation rules:
- account_key + video_id must match
- No account history → reject auto-association
- Multiple candidates → reject auto-association
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .models import (
    FanqiePublishRecord,
    FanqieDouyinAccount,
    PublishStatus,
    EventType,
)
from .repositories import (
    DouyinLegacyVideoRepository,
    DouyinAccountRepository,
    PublishRecordRepository,
    PromotionTaskRepository,
)

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


class NovelPromotionPublishSyncService:
    """Orchestrate douyin.db -> fanqie_publish_records sync with validation.

    This is the ONLY service authorized to update
    fanqie_publish_records.douyin_video_id.
    """

    def __init__(
        self,
        wisdom_db: Session,
        douyin_db_path: str = "data/douyin.db",
    ):
        self.wisdom_db = wisdom_db
        self.douyin_video_repo = DouyinLegacyVideoRepository(douyin_db_path)
        self.account_repo = DouyinAccountRepository(wisdom_db)
        self.publish_repo = PublishRecordRepository(wisdom_db)
        self.task_repo = PromotionTaskRepository(wisdom_db)

    def sync_by_account_and_video_id(
        self,
        account_key: str,
        douyin_video_id: str,
        *,
        actor_type: str = "sync_service",
    ) -> dict:
        """Validate and sync a douyin video to a fanqie publish record.

        Validation rules:
        1. Account must exist in fanqie_douyin_accounts
        2. Video must exist in douyin.db with matching account_key
        3. Only one candidate publish record → auto-associate
        4. No account → no auto-association
        5. Multiple candidates → manual_intervention

        Returns:
            dict with keys: success, action, publish_record_id, reason, event_id
        """
        # 1. Validate account exists
        account = self.account_repo.get_by_key(account_key)
        if not account:
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": f"Account '{account_key}' not found in fanqie_douyin_accounts",
                "publish_record_id": None,
                "event_id": None,
            }

        # 2. Validate video exists in douyin.db
        douyin_video = self.douyin_video_repo.get_by_video_id(douyin_video_id)
        if not douyin_video:
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": f"Video '{douyin_video_id}' not found in douyin.db",
                "publish_record_id": None,
                "event_id": None,
            }

        # 3. Check account_key on the douyin video
        video_account = douyin_video.get("account_key", "")
        if not video_account:
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": (
                    f"Video '{douyin_video_id}' has no account_key in douyin.db; "
                    "cannot auto-associate"
                ),
                "publish_record_id": None,
                "event_id": None,
            }
        if video_account != account_key:
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": (
                    f"Account mismatch: video account_key='{video_account}' "
                    f"!= requested account_key='{account_key}'"
                ),
                "publish_record_id": None,
                "event_id": None,
            }

        # 4. Check for existing publish record with this video_id
        existing = self.publish_repo.get_by_douyin_video_id(douyin_video_id)
        if existing:
            return {
                "success": True,
                "action": "already_synced",
                "reason": f"Video '{douyin_video_id}' already associated with publish_record {existing.id}",
                "publish_record_id": existing.id,
                "event_id": None,
            }

        # 5. Find candidate publish records (published or publish_pending_sync)
        candidates = (
            self.wisdom_db.query(FanqiePublishRecord)
            .filter(
                FanqiePublishRecord.douyin_account_id == account.id,
                FanqiePublishRecord.status.in_([
                    PublishStatus.PUBLISH_PENDING_SYNC,
                    PublishStatus.PUBLISHED,
                    PublishStatus.PUBLISHED_UNBOUND,
                ]),
                FanqiePublishRecord.douyin_video_id.is_(None),
            )
            .all()
        )

        if not candidates:
            # No candidate at all: create an event for manual review
            logger.warning(
                f"No pending publish record found for account_key='{account_key}', "
                f"video_id='{douyin_video_id}'"
            )
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": "No pending publish record found for this account",
                "publish_record_id": None,
                "event_id": None,
            }

        if len(candidates) > 1:
            logger.warning(
                f"Multiple ({len(candidates)}) publish records pending sync for "
                f"account_key='{account_key}': cannot auto-associate"
            )
            return {
                "success": False,
                "action": "manual_intervention",
                "reason": f"Multiple ({len(candidates)}) candidates; cannot auto-associate",
                "publish_record_id": None,
                "event_id": None,
            }

        # 6. Exactly one candidate → auto-associate
        record = candidates[0]
        douyin_video_url = douyin_video.get("cover_url", "")  # best available URL field
        # The douyin.db videos table doesn't have a direct video URL, but we can construct one
        if douyin_video_id:
            douyin_video_url = f"https://www.douyin.com/video/{douyin_video_id}"

        success = self.publish_repo.update_sync_info(
            record.id,
            douyin_video_id=douyin_video_id,
            douyin_video_url=douyin_video_url,
        )

        # Append sync event to the task
        if success and record.task_id:
            event = self.task_repo.append_event(
                record.task_id,
                EventType.PUBLISH_SYNC,
                from_status=record.status,
                to_status=PublishStatus.PUBLISHED,
                actor_type=actor_type,
                payload={
                    "douyin_video_id": douyin_video_id,
                    "douyin_video_url": douyin_video_url,
                    "account_key": account_key,
                },
            )
            self.wisdom_db.commit()
            return {
                "success": True,
                "action": "synced",
                "reason": f"Associated video '{douyin_video_id}' with publish_record {record.id}",
                "publish_record_id": record.id,
                "event_id": event.id,
            }

        self.wisdom_db.commit()
        return {
            "success": success,
            "action": "synced" if success else "failed",
            "reason": f"Update publish_record {record.id}",
            "publish_record_id": record.id,
            "event_id": None,
        }
