"""Provider-neutral contracts for candidate-video content understanding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from src.operations_accounts import AccountProfile
from src.trend_intelligence.models import VideoContentAnalysis


MediaAccessMode = Literal["metadata_only", "local_media_authorized"]


@dataclass(slots=True)
class ContentAnalysisRequest:
    item_id: str
    video_id: str
    title: str
    author: str
    account_profile: AccountProfile
    hashtags: list[str] = field(default_factory=list)
    raw_text: str = ""
    duration_seconds: float | None = None
    media_access_mode: MediaAccessMode = "metadata_only"
    local_video_path: str = ""
    qwen_analysis_path: str = ""
    transcript_path: str = ""
    scene_alignment_path: str = ""

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("item_id is required")
        if self.media_access_mode not in {"metadata_only", "local_media_authorized"}:
            raise ValueError("invalid media_access_mode")
        if self.media_access_mode == "metadata_only" and any(
            (
                self.local_video_path,
                self.qwen_analysis_path,
                self.transcript_path,
                self.scene_alignment_path,
            )
        ):
            raise ValueError("metadata_only requests cannot attach local media artifacts")

    def input_fingerprint(self) -> str:
        payload = {
            "item_id": self.item_id,
            "video_id": self.video_id,
            "title": self.title,
            "author": self.author,
            "hashtags": sorted(set(self.hashtags)),
            "raw_text": self.raw_text,
            "duration_seconds": self.duration_seconds,
            "media_access_mode": self.media_access_mode,
            "profile": {
                "account_uuid": self.account_profile.account_uuid,
                "profile_version": self.account_profile.profile_version,
                "domain_strategy_id": self.account_profile.domain_strategy_id,
                "strategy_version": self.account_profile.strategy_version,
            },
            "artifacts": {
                name: _file_fingerprint(value)
                for name, value in {
                    "video": self.local_video_path,
                    "qwen": self.qwen_analysis_path,
                    "transcript": self.transcript_path,
                    "scenes": self.scene_alignment_path,
                }.items()
                if value
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ContentAnalysisProvider(Protocol):
    provider_id: str
    provider_version: str
    max_parallelism: int

    def analyze(self, request: ContentAnalysisRequest) -> VideoContentAnalysis: ...


def stable_analysis_id(
    request: ContentAnalysisRequest,
    *,
    provider_id: str,
    provider_version: str,
) -> str:
    identity = "|".join(
        (
            request.item_id,
            request.account_profile.account_uuid,
            str(request.account_profile.profile_version),
            provider_id,
            provider_version,
            request.input_fingerprint(),
        )
    )
    return "analysis:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _file_fingerprint(value: str) -> str:
    path = Path(value).resolve()
    if not path.is_file():
        return f"missing:{path}"
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
