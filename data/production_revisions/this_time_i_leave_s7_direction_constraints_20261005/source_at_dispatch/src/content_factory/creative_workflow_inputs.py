"""Versioned source intake for the creative-story drivers.

The legacy novel_highlight/reference_video switch is intentionally not reused:
it always required a novel, while this module has independent story sources.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DRIVERS = ("novel", "reference_video", "original")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"材料不是文件: {resolved}")
    digest = hashlib.sha256()
    size = 0
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if not size:
        raise ValueError(f"材料为空: {resolved}")
    return {"path": str(resolved), "sha256": digest.hexdigest(), "bytes": size}


def verify_binding(binding: dict[str, Any]) -> Path:
    path = Path(binding["path"])
    if not path.is_absolute() or file_binding(path)["sha256"] != binding["sha256"]:
        raise ValueError(f"材料版本已改变: {path}")
    return path


def _read_text(path: Path) -> str:
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise ValueError(f"文本材料为空: {path}")
    return value


def _reference_text(path: Path) -> str:
    text = _read_text(path)
    if path.suffix.lower() != ".json":
        return text
    value = json.loads(text)
    if not isinstance(value, (list, dict)):
        raise ValueError(f"参考分析 JSON 应为对象或数组: {path}")
    return json.dumps(value, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class MaterialBundle:
    source_driver: str
    title: str
    source_text: str
    metadata: dict[str, Any]
    references: tuple[dict[str, str], ...]
    manifest: dict[str, Any]

    def input_payload(self) -> dict[str, Any]:
        return {
            "source_driver": self.source_driver,
            "title": self.title,
            "story_source": self.source_text,
            "metadata": self.metadata,
            "reference_pack": list(self.references),
            "source_scope": self.manifest["scope"],
            "rule": (
                "Only story_source may supply characters, plot and dialogue. "
                "Reference_pack may supply expression and film grammar, never story facts."
            ),
        }


def load_materials(
    *,
    source_driver: str,
    title: str,
    novel_path: Path | None = None,
    metadata_path: Path | None = None,
    video_path: Path | None = None,
    analysis_path: Path | None = None,
    analysis_end_heading: str = "",
    reference_paths: list[Path] | None = None,
    brief_path: Path | None = None,
    asset_library_path: Path | None = None,
) -> MaterialBundle:
    if source_driver not in DRIVERS:
        raise ValueError(f"未知业务驱动: {source_driver}")
    title = title.strip()
    if not title:
        raise ValueError("标题不能为空")
    files: dict[str, Any] = {}
    metadata: dict[str, Any] = {}

    creative_brief = None
    if brief_path is not None:
        from .creative_brief import load_brief
        creative_brief = load_brief(brief_path)
        files["creative_brief"] = file_binding(brief_path)
    if source_driver == "original":
        if creative_brief is None or any(x is not None for x in (novel_path, video_path, analysis_path, metadata_path)):
            raise ValueError("原创简报驱动需要 --brief，不能混入其他故事来源")
        source_text = json.dumps(creative_brief, ensure_ascii=False, sort_keys=True)
        scope = {"claim": "按用户创作简报创作原创故事；空白项由编剧导演提出", "characters": len(source_text)}
    elif source_driver == "novel":
        if novel_path is None or video_path is not None or analysis_path is not None:
            raise ValueError("小说驱动需要正文，原视频及其分析不能作为故事来源")
        novel_path = Path(novel_path)
        files["story_source"] = file_binding(novel_path)
        source_text = _read_text(novel_path)
        if len(source_text) < 200:
            raise ValueError("小说正文不足 200 字")
        if metadata_path is not None:
            metadata_path = Path(metadata_path)
            files["metadata"] = file_binding(metadata_path)
            metadata = json.loads(_read_text(metadata_path))
            if not isinstance(metadata, dict):
                raise ValueError("书籍元数据应为 JSON 对象")
        chapter_markers = re.findall(r"(?m)^第[一二三四五六七八九十百千万零〇\d]+[章回][^\r\n]*", source_text)
        scope = {
            "claim": "已获取正文范围；不代表整书",
            "characters": len(source_text),
            "chapter_markers": chapter_markers[:200],
            "chapter_marker_count": len(chapter_markers),
        }
    else:
        if novel_path is not None or video_path is None or analysis_path is None:
            raise ValueError("视频驱动需要原视频和对应分析，不需要小说")
        video_path, analysis_path = Path(video_path), Path(analysis_path)
        files["story_video"] = file_binding(video_path)
        files["story_analysis"] = file_binding(analysis_path)
        full_analysis = _reference_text(analysis_path)
        source_text = full_analysis
        analysis_end_heading = (analysis_end_heading or "").strip()
        if analysis_end_heading:
            if full_analysis.count(analysis_end_heading) != 1:
                raise ValueError("视频分析范围终点标题必须在分析中唯一出现")
            source_text = full_analysis.split(analysis_end_heading, 1)[0].strip()
            if len(source_text) < 100:
                raise ValueError("所选视频分析范围过短")
        video_name = video_path.name
        video_digest = files["story_video"]["sha256"]
        if video_digest.lower() in source_text.lower():
            pairing = "sha256_claim_in_analysis"
        elif video_name.lower() in source_text.lower():
            pairing = "filename_claim_in_analysis_only"
        else:
            raise ValueError("视频分析未标明原视频文件名或 SHA256，不能确认对应材料")
        scope = {
            "claim": "基于提供的视频分析创作新故事；分析未核验的音画判断不得当事实",
            "characters": len(source_text),
            "video_sha256": files["story_video"]["sha256"],
            "analysis_pairing": pairing,
            "analysis_scope_end_heading": analysis_end_heading or None,
            "full_analysis_sha256": sha256_bytes(full_analysis.encode("utf-8")),
        }

    if creative_brief is not None:
        metadata["creative_brief"] = creative_brief
        scope["creative_brief"] = creative_brief
    if creative_brief is not None and asset_library_path is not None and Path(asset_library_path).is_file():
        from .reusable_production import asset_catalog
        files["asset_library"] = file_binding(Path(asset_library_path))
        metadata["asset_catalog"] = asset_catalog(Path(asset_library_path))
    references: list[dict[str, str]] = []
    reference_adaptation: list[dict[str, Any]] = []
    for index, path in enumerate(reference_paths or [], 1):
        path = Path(path)
        binding = file_binding(path)
        files[f"reference_{index}"] = binding
        reference_text = _reference_text(path)
        references.append(
            {"id": f"R{index:02}", "path": str(path.resolve()), "text": reference_text}
        )
        source_units = 1
        source_format = "text"
        if path.suffix.lower() == ".json":
            source_format = "json"
            parsed = json.loads(_read_text(path))
            source_units = len(parsed) if isinstance(parsed, (list, dict)) else 0
        reference_adaptation.append({
            "id": f"R{index:02}",
            "path": str(path.resolve()),
            "format": source_format,
            "characters_read": len(reference_text),
            "items_read": source_units,
            "items_effective": source_units,
            "items_excluded": 0,
            "exclusion_reasons": [],
            "text_sha256": sha256_bytes(reference_text.encode("utf-8")),
        })

    manifest = {
        "schema": "creative_material_manifest/v1",
        "source_driver": source_driver,
        "title": title,
        "files": files,
        "scope": scope,
        "reference_count": len(references),
        "reference_adaptation": reference_adaptation,
        "unread_or_unverified": (
            ["原视频的像素、声音和口型未由本次文本入口重新审查"]
            if source_driver == "reference_video"
            else ["简报仅确定创作意图，实际生成效果待检查"] if source_driver == "original"
            else ["未提供的后续章节不在本次理解范围"]
        ),
    }
    return MaterialBundle(
        source_driver=source_driver,
        title=title,
        source_text=source_text,
        metadata=metadata,
        references=tuple(references),
        manifest=manifest,
    )


def verify_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "creative_material_manifest/v1":
        raise ValueError("材料清单版本不受支持")
    for binding in manifest["files"].values():
        verify_binding(binding)
