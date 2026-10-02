"""MiniMax-backed reconstruction-script refinement from local video evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence


SCHEMA = "video_script_refinement/v1"
DEFAULT_MODEL = "Minimax-M2.7"
REQUIRED_EVIDENCE_FILES = (
    "qwen_analysis.json",
    "qwen_shot_reconstruction.json",
    "scene_transcript_alignment.json",
    "transcript_raw.json",
)


class VideoScriptRefinementError(RuntimeError):
    """Raised when evidence, model configuration, or output is invalid."""


class TrackedLLM(Protocol):
    provider_name: str

    @property
    def model_name(self) -> str: ...

    def chat_completion_tracked(
        self,
        messages: Sequence[dict[str, str]],
        *,
        caller: str,
        temperature: float,
        json_mode: bool,
        use_cache: bool,
    ) -> str | None: ...


@dataclass(frozen=True)
class VideoScriptRefinementRequest:
    evidence_dir: Path
    model: str = DEFAULT_MODEL
    temperature: float = 0.2

    def load_evidence(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not self.evidence_dir.is_dir():
            raise FileNotFoundError(self.evidence_dir)

        bundle: dict[str, Any] = {}
        inventory: list[dict[str, Any]] = []
        for name in REQUIRED_EVIDENCE_FILES:
            path = (self.evidence_dir / name).resolve()
            if not path.is_file():
                raise VideoScriptRefinementError(f"missing required evidence file: {path}")
            raw = path.read_bytes()
            try:
                value = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VideoScriptRefinementError(
                    f"invalid JSON evidence file: {path}"
                ) from exc
            bundle[name] = _normalise_evidence(value)
            inventory.append(
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(raw).hexdigest().upper(),
                    "bytes": len(raw),
                }
            )
        return bundle, inventory


class VideoScriptRefiner:
    """Ask the configured MiniMax model to turn evidence into a script document."""

    def __init__(self, client: TrackedLLM, request: VideoScriptRefinementRequest) -> None:
        self.client = client
        self.request = request
        if client.model_name.lower() != request.model.lower():
            raise VideoScriptRefinementError(
                "video script model mismatch: "
                f"configured refiner expects {request.model}, LLM client uses {client.model_name}"
            )

    def build_messages(self) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        evidence, inventory = self.request.load_evidence()
        system_prompt = (
            "你是短视频内容理解、编剧和逐镜头复刻专家。只依据提供的视觉分析、ASR、"
            "镜头边界和可见字幕整理复刻级剧本，不虚构画面外事实，不猜测人物真实身份。"
            "输出必须是中文 Markdown，不能输出代码围栏、JSON、分析过程或免责声明。\n\n"
            "文档必须依次包含：\n"
            "1. 一级标题：视频标题加“复刻级剧本”；\n"
            "2. `## 视频内容总结`，下设核心冲突、剧情推进、主要情绪、表现形式、完播动力；\n"
            "3. `## 内容复刻建议`，说明钩子、升级、反差、情绪回报和尾钩；\n"
            "4. `## 画面复刻建议`，说明角色连续性、构图、机位、表情、动作、道具、声音和节奏；\n"
            "5. `## 角色` Markdown 表格；\n"
            "6. `## 表情、动作与表演节拍` Markdown 表格；\n"
            "7. `## 场景和关键道具`；\n"
            "8. 最后一节必须是 `## 逐镜头复刻表`，列严格为"
            "`镜头|时间|画面与机位|台词/字幕|叙事作用`。\n\n"
            "逐镜头表必须覆盖输入中的全部镜头边界；台词优先使用硬字幕和带时间戳 ASR，"
            "不确定内容标记 `[疑似]`。每行写清景别、机位、角色表情、视线、身体动作、"
            "手部动作、关键道具和镜头叙事功能。不要添加“改成法律版”等题外改编建议。"
        )
        user_payload = {
            "task": "根据证据整理可用于复刻类似视频的详细剧本",
            "source": str(self.request.evidence_dir.resolve()),
            "evidence": evidence,
        }
        return (
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            inventory,
        )

    def refine(
        self,
        output_path: str | Path,
        *,
        overwrite: bool = False,
        use_cache: bool = False,
    ) -> dict[str, Any]:
        destination = Path(output_path).resolve()
        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"output already exists; pass overwrite=True to replace it: {destination}"
            )
        messages, inventory = self.build_messages()
        response = self.client.chat_completion_tracked(
            messages,
            caller="video_script_refine",
            temperature=self.request.temperature,
            json_mode=False,
            use_cache=use_cache,
        )
        document = _normalise_markdown(response or "")
        _validate_document(document)

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8")
        metadata_path = destination.with_suffix(destination.suffix + ".meta.json")
        metadata = {
            "schema": SCHEMA,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": self.client.provider_name,
            "model": self.client.model_name,
            "temperature": self.request.temperature,
            "caller": "video_script_refine",
            "inputs": inventory,
            "output": {
                "path": str(destination),
                "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest().upper(),
                "characters": len(document),
            },
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {**metadata, "metadata_path": str(metadata_path)}


def build_refinement_preview(request: VideoScriptRefinementRequest) -> dict[str, Any]:
    """Build a no-network request preview suitable for review and tests."""

    evidence, inventory = request.load_evidence()
    return {
        "schema": "video_script_refinement_preview/v1",
        "model": request.model,
        "temperature": request.temperature,
        "evidence_dir": str(request.evidence_dir.resolve()),
        "inputs": inventory,
        "evidence_keys": sorted(evidence),
        "network_called": False,
    }


def _normalise_evidence(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    answer = result.get("answer")
    if isinstance(answer, str):
        try:
            result["answer"] = json.loads(answer)
        except json.JSONDecodeError:
            pass
    return result


def _normalise_markdown(value: str) -> str:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 : -3].strip()
    return text.rstrip() + "\n" if text else ""


def _validate_document(document: str) -> None:
    required = (
        "## 视频内容总结",
        "## 内容复刻建议",
        "## 画面复刻建议",
        "## 角色",
        "## 表情、动作与表演节拍",
        "## 场景和关键道具",
        "## 逐镜头复刻表",
    )
    missing = [heading for heading in required if heading not in document]
    if missing:
        raise VideoScriptRefinementError(
            "MiniMax output is missing required sections: " + ", ".join(missing)
        )
    if not document.lstrip().startswith("# "):
        raise VideoScriptRefinementError("MiniMax output must start with a Markdown title")
    if document.rfind("## 逐镜头复刻表") < max(document.rfind(item) for item in required[:-1]):
        raise VideoScriptRefinementError("逐镜头复刻表 must be the final required section")
    table_header = "| 镜头 | 时间 | 画面与机位 | 台词/字幕 | 叙事作用 |"
    if table_header not in document:
        raise VideoScriptRefinementError(
            "MiniMax output is missing the required shot-table columns"
        )
