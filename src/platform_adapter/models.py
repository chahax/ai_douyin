from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


@dataclass
class BrowserSessionConfig:
    base_url: str
    home_url: str
    storage_state_path: str
    user_data_dir: str
    browser_channel: str = ""
    headless: bool = False
    slow_mo_ms: int = 0
    timeout_ms: int = 30000


@dataclass
class SessionState:
    active: bool
    authenticated: bool
    base_url: str
    storage_state_path: str
    user_data_dir: str


@dataclass
class PublishRequest:
    video_path: str
    title: str
    description: str = ""
    hashtags: List[str] = field(default_factory=list)
    cover_path: Optional[str] = None
    scheduled_at: Optional[str] = None
    extra_metadata: Dict[str, str] = field(default_factory=dict)
    visibility: str = "public"  # "public" | "private" | "friends"

    def normalized_hashtags(self) -> List[str]:
        normalized: List[str] = []
        for item in self.hashtags:
            value = item.strip().lstrip("#")
            if value:
                normalized.append(value)
        return normalized


@dataclass
class PublishResult:
    success: bool
    status: str
    platform: str = "douyin"
    post_id: str = ""
    publish_url: str = ""
    message: str = ""


@dataclass
class CommentQuery:
    post_id: str = ""
    post_url: str = ""
    page: int = 1
    page_size: int = 20


@dataclass
class CommentRecord:
    comment_id: str
    author_name: str
    content: str
    created_at: str = ""
    reply_to_comment_id: str = ""


@dataclass
class CommentSyncResult:
    success: bool
    status: str
    comments: List[CommentRecord] = field(default_factory=list)
    message: str = ""


class VideoStatus(str, Enum):
    PENDING = "pending_review"     # 审核中
    PUBLISHED = "published"        # 已发布
    FAILED = "failed"              # 发布失败
    UNKNOWN = "unknown"            # 未知状态


@dataclass
class VideoStats:
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int = 0


@dataclass
class VideoItem:
    id: Optional[int] = None                    # 数据库自增主键，sync 后才有值
    local_id: Optional[str] = None             # 本地生成的唯一标识（publish 时 UUID）
    video_id: Optional[str] = None              # 抖音视频 ID，sync 后补上
    title: str = ""
    description: str = ""
    status: VideoStatus = VideoStatus.UNKNOWN
    publish_time: Optional[str] = None
    cover_url: Optional[str] = None
    stats: Optional[VideoStats] = None


@dataclass
class SyncResult:
    success: bool
    status: str
    videos: List[VideoItem] = field(default_factory=list)
    message: str = ""
