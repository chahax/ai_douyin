"""Bounded, resumable synthesis of full-video evidence.

This module performs no model/network calls itself. Its caller owns inference.
All raw evidence survives in the final expression; intermediate claims are
model candidates, and their citations are checked against the exact input of
that stage. Structural validation never grants semantic approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .artifacts import read_json, sha256, validate_expression, write_json

VERSION = "source-hierarchical-synthesis-v1"
DEFAULT_MAX_INPUT_CHARS = 11000

SEGMENT_PROMPT = """你分析的是原视频一个连续时间范围内的媒体证据，不是完整视频。仅保留本范围最重要的具体表达事实，供后续合并。
ASR可能错词，不证明声线、语气、口型；静帧中的主画面、画中画、字幕属于不同层，不得把画中画的手或物件归给主画面人物。
保持担忧、假设、条件、否定以及动作先后，不把可能发生写成已发生，不合并不同对象为因果。看不清、转写不确定时如实留疑问。
区分夸张、反问、气话与实际事件，例如‘我死都不同意’不能变成死亡后的法律问题。不能把人物明确要求、拒绝、威逼或逃避责任中和成‘双方沟通协商’，也不能给其添加未表达的目标。
优先保留：本范围开头引入的具体问题，物件实际展示步骤，人物目标及阻碍，冲突转折，本范围末尾已展示的结果/最后结论或仍未解决的状态。开头和末尾信息都要保留，不能只摘中间知识句；没有结果证据时不得补结局。保留尚未回答的问题，不能自行给知识答案。
只输出JSON：{"claims":[{"text":"具体的候选归纳，最多120字","evidence_ids":["真实证据ID"]}],"uncertainties":["本范围未能确定的信息"]}。
最多6条claims，每条最多3个不同evidence_ids；所有ID必须来自本次给出的原始证据。不要输出evidence原文副本，不要给整片起标题。"""

MERGE_PROMPT = """合并下面同一原视频相邻时间范围的候选归纳。每段是模型候选而非事实判定，下面同时提供其引用的原始证据。
保持全片发生顺序和不同人物/画中画/字幕的区别，保留核心问题、实际示范步骤、阻碍、转折、结果及未解决的问题。不能用前一段的原因解释后一段的结果，除非原始证据明确表达该联系。
不能丢掉担忧、假设、否定和条件，不自行补充知识结论。对不相容说法保留疑问。
夸张、反问和气话不等于已发生事件，不将带‘死’的情绪说法改成死亡法律问题；人物明确要求、拒绝、威逼或推卸责任必须保留其对立目标，不能中和成‘双方协商’。
必须保留合并范围最初提出的问题，以及最末范围已经展示的结局/结果或仍未解决状态；不能让早期示范细节挤掉结尾事实。结尾没有答案就如实保留问题，不能生成一个答案。
只输出JSON：{"claims":[{"text":"具体候选归纳，最多120字","evidence_ids":["本次原始证据中的ID"]}],"uncertainties":["本范围未能确定的信息"]}。
最多6条claims，每条最多3个不同evidence_ids。不要复述格式说明或输出原始evidence副本。"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _references(value: object) -> set[str]:
    if isinstance(value, dict):
        own = set(value.get("evidence_ids") or [])
        for key, child in value.items():
            if key != "evidence":
                own.update(_references(child))
        return own
    if isinstance(value, list):
        return set().union(*(_references(child) for child in value)) if value else set()
    return set()


def _visual_result(result: dict, frames: list[dict]) -> None:
    rows = result.get("observations")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("visual checkpoint needs an observations list")
    ids = [str(row.get("frame_id") or "") for row in rows]
    expected = [str(frame["id"]) for frame in frames]
    if len(set(expected)) != len(expected) or len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise ValueError("visual checkpoint must observe every frame exactly once")
    if any(not str(row.get("event") or "").strip() for row in rows):
        raise ValueError("visual checkpoint contains an empty observation")


class VisualBatchCheckpoint:
    """Reuse completed image batches only under unchanged input identity."""

    def __init__(self, directory: str | Path, *, binding: dict):
        self.directory = Path(directory)
        self.binding = {"helper_version": VERSION, **binding}

    def _identity(self, frames: list[dict]) -> dict:
        for frame in frames:
            if sha256(frame["path"]) != frame["sha256"]:
                raise ValueError("checkpoint input frame bytes changed")
        # A resumed attempt may copy the identical decoded frames elsewhere.
        # Verify the current path's bytes, but identify content and sampling
        # facts rather than that incidental filesystem location.
        bound_frames = [{key: frame[key] for key in
                         ("id", "sha256", "time_seconds", "decoded_frame_index", "sampling_reason")
                         if key in frame} for frame in frames]
        return {"binding": self.binding, "frames": bound_frames}

    def load(self, frames: list[dict]) -> dict | None:
        identity = self._identity(frames)
        path = self.directory / f"visual_{_digest(identity)}.json"
        if not path.is_file():
            return None
        value = read_json(path)
        if (value.get("schema") != "local_visual_batch_checkpoint/v1" or
                value.get("identity") != identity or value.get("result_sha256") != _digest(value.get("result"))):
            raise ValueError("visual checkpoint identity or result hash changed")
        _visual_result(value["result"], frames)
        return value["result"]

    def save(self, frames: list[dict], result: dict) -> None:
        _visual_result(result, frames)
        identity = self._identity(frames)
        write_json(self.directory / f"visual_{_digest(identity)}.json", {
            "schema": "local_visual_batch_checkpoint/v1", "identity": identity,
            "result": result, "result_sha256": _digest(result),
        })


def _validate_summary(value: dict, known: set[str], *, max_claim_refs: int = 3,
                      max_claim_chars: int = 120, max_claims: int = 6) -> dict:
    if type(max_claims) is not int or not 1 <= max_claims <= 12:
        raise ValueError("max_claims must be an integer from 1 to 12")
    if type(max_claim_chars) is not int or max_claim_chars < 1:
        raise ValueError("max_claim_chars must be a positive integer")
    claims = value.get("claims")
    if not isinstance(claims, list) or not 1 <= len(claims) <= max_claims:
        raise ValueError(f"summary needs 1 to {max_claims} claims")
    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError("summary claim must be an object")
        text = claim.get("text")
        refs = claim.get("evidence_ids")
        if not isinstance(text, str) or not text.strip() or len(text) > max_claim_chars:
            raise ValueError(f"summary claim text must contain 1 to {max_claim_chars} characters")
        if (not isinstance(refs, list) or not 1 <= len(refs) <= max_claim_refs or
                any(not isinstance(ref, str) for ref in refs) or
                len(set(refs)) != len(refs) or not set(refs) <= known):
            count = len(refs) if isinstance(refs, list) else "invalid"
            raise ValueError("summary cites missing/duplicate evidence or too many references: "
                             f"claim {claim_index} has {count}; maximum {max_claim_refs} distinct supplied IDs")
    uncertainties = value.get("uncertainties") or []
    if (not isinstance(uncertainties, list) or len(uncertainties) > 6 or
            any(not isinstance(item, str) or len(item) > 160 for item in uncertainties)):
        raise ValueError("summary uncertainties exceed bounded format")
    # Reject extra data rather than silently retaining an unbounded evidence copy.
    if set(value) - {"claims", "uncertainties"}:
        raise ValueError("summary may only contain claims and uncertainties")
    return value


def _split_rows(rows: list[dict], budget: int) -> list[list[dict]]:
    if budget < 1000:
        raise ValueError("synthesis prompt leaves insufficient evidence budget")
    result, current = [], []
    size = 2
    for row in rows:
        length = len(_json(row)) + 1
        if length + 2 > budget:
            raise ValueError("single evidence item exceeds bounded synthesis input; split at real ASR timestamps upstream")
        if current and size + length > budget:
            result.append(current)
            current, size = [], 2
        current.append(row)
        size += length
    if current:
        result.append(current)
    return result


def synthesize_expression(
    evidence: list[dict], duration: float, *, infer: Callable[[list[dict]], dict],
    synthesis_prompt: str, checkpoint_dir: str | Path, binding: dict,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS, allow_final_repair: bool = True,
    max_claim_refs: int = 3, max_claim_chars: int = 120, max_claims: int = 6,
    feedback_text: str = "",
) -> tuple[dict, dict]:
    """Run bounded chronological map/reduce only when full evidence will not fit.

    ``infer`` accepts the analyzer's ``[{type: text, text: ...}]`` content API.
    Root code should additionally count actual tokenizer tokens before inference.
    Every stage has at most one schema repair, with a compact error instruction.
    Checkpoints store exact stage inputs, output hashes, and semantic-unreviewed
    status; callers must include model/prompt/source identities in ``binding``.
    """
    if not evidence or len({row.get("id") for row in evidence}) != len(evidence):
        raise ValueError("synthesis needs unique nonempty evidence")
    if type(max_claim_refs) is not int or not 1 <= max_claim_refs <= 32:
        raise ValueError("max_claim_refs must be an integer from 1 to 32")
    if type(max_claim_chars) is not int or max_claim_chars < 1:
        raise ValueError("max_claim_chars must be a positive integer")
    if type(max_claims) is not int or not 1 <= max_claims <= 12:
        raise ValueError("max_claims must be an integer from 1 to 12")
    if not isinstance(feedback_text, str):
        raise ValueError("synthesis feedback must be text")
    known = {row["id"]: row for row in evidence}
    evidence = sorted(evidence, key=lambda row: (row["start_seconds"], row["end_seconds"], row["id"]))
    checkpoint_dir = Path(checkpoint_dir)
    run_binding = {"helper_version": VERSION, "caller": binding, "evidence_sha256": _digest(evidence),
                   "synthesis_prompt": synthesis_prompt, "max_input_chars": max_input_chars,
                   "max_claim_refs": max_claim_refs, "max_claim_chars": max_claim_chars,
                   "max_claims": max_claims}
    feedback = ""
    if feedback_text.strip():
        run_binding["feedback_text"] = feedback_text
        feedback = ("\n独立证据复核反馈（纠正要求不是新的媒体证据）：\n" + feedback_text
                    + "\n本阶段只处理本次提供的原始证据，反馈提到但未在本阶段原始证据中出现的ID不得引用，"
                    "不得据反馈补造本段事实。仍按本阶段上文规定的JSON结构输出；"
                    "分段/合并阶段只输出claims和uncertainties，不输出最终整片结构。\n")
    segment_prompt = (SEGMENT_PROMPT.replace("最多3个不同evidence_ids", f"最多{max_claim_refs}个不同evidence_ids")
                      .replace("最多120字", f"最多{max_claim_chars}字")
                      .replace("最多6条claims", f"最多{max_claims}条claims")) + feedback
    merge_prompt = (MERGE_PROMPT.replace("最多3个不同evidence_ids", f"最多{max_claim_refs}个不同evidence_ids")
                    .replace("最多120字", f"最多{max_claim_chars}字")
                    .replace("最多6条claims", f"最多{max_claims}条claims")) + feedback
    final_task_prompt = synthesis_prompt + feedback
    stages = []

    def stage(prompt: str, allowed: set[str], label: str, *, final: bool = False) -> dict:
        if len(prompt) > max_input_chars:
            raise ValueError("synthesis input exceeds configured character budget")
        identity = {"binding": run_binding, "prompt": prompt, "stage": label,
                    "allowed_evidence_ids": sorted(allowed)}
        path = checkpoint_dir / f"{label}_{_digest(identity)}.json"

        def validate(value: dict) -> dict:
            if not _references(value) <= allowed:
                raise ValueError("stage invented a citation that was not in its input")
            if final:
                return validate_expression(value, evidence, duration)
            return _validate_summary(value, allowed, max_claim_refs=max_claim_refs,
                                     max_claim_chars=max_claim_chars, max_claims=max_claims)

        reused = path.is_file()
        if reused:
            cache = read_json(path)
            if (cache.get("schema") != "local_synthesis_checkpoint/v1" or
                    cache.get("identity") != identity or cache.get("result_sha256") != _digest(cache.get("result"))):
                raise ValueError("synthesis checkpoint identity or result hash changed")
            result = validate(cache["result"])
        else:
            try:
                result = validate(infer([{"type": "text", "text": prompt}]))
            except (ValueError, TypeError, KeyError) as exc:
                if final and not allow_final_repair:
                    raise
                # Do not append a potentially huge malformed answer; repeat the
                # original evidence and a bounded schema correction once only.
                correction = "\n上一次输出校验失败：" + str(exc)[:180] + "。按原格式重写，只用本次证据ID；未知字段空串和空引用。"
                if len(prompt) + len(correction) > max_input_chars:
                    raise ValueError("synthesis repair exceeds input budget") from exc
                result = validate(infer([{"type": "text", "text": prompt + correction}]))
            write_json(path, {"schema": "local_synthesis_checkpoint/v1", "identity": identity,
                              "semantic_status": "model_candidate_unreviewed", "result": result,
                              "result_sha256": _digest(result)})
        stages.append({"stage": label, "checkpoint_path": str(path.resolve()), "checkpoint_sha256": sha256(path),
                       "input_characters": len(prompt), "input_evidence_ids": sorted(allowed),
                       "reused": reused})
        return result

    direct = final_task_prompt + "\n媒体证据：\n" + _json(evidence)
    # Reserve room for a bounded validation correction without increasing size.
    capacity = max_input_chars - 500
    if len(direct) <= capacity:
        expression = stage(direct, set(known), "final", final=True)
        return expression, {"schema": "local_synthesis_provenance/v1", "strategy": "direct",
                            "raw_evidence_count": len(evidence), "stages": stages}

    def node_payload(nodes: list[dict]) -> dict:
        refs = set().union(*(_references(node["summary"]) for node in nodes))
        return {"candidate_summaries": [{"range_seconds": node["range_seconds"], "summary": node["summary"]}
                                        for node in nodes],
                "raw_evidence": [row for row in evidence if row["id"] in refs]}

    chunks = _split_rows(evidence, capacity - len(segment_prompt) - 30)
    nodes = []
    for index, chunk in enumerate(chunks):
        prompt = segment_prompt + "\n原始媒体证据：\n" + _json(chunk)
        summary = stage(prompt, {row["id"] for row in chunk}, f"leaf_{index:04d}")
        nodes.append({"summary": summary, "covered_evidence_ids": [row["id"] for row in chunk],
                      "range_seconds": [min(row["start_seconds"] for row in chunk),
                                        max(row["end_seconds"] for row in chunk)]})
    leaf_count, level = len(nodes), 0
    final_prefix = (final_task_prompt + "\n以下为覆盖全片的分段候选归纳及其引用的原始证据。"
                    "分段归纳本身不是新证据，只能引用raw_evidence中的真实ID；保持假设/条件/未解决问题。"
                    "其他完整逐帧观察和ASR仍保存在工件中，分层归纳可能遗漏细节，不能称为人工审核。\n")
    while True:
        combined = node_payload(nodes)
        final_prompt = final_prefix + _json(combined)
        if len(final_prompt) <= capacity:
            expression = stage(final_prompt, {row["id"] for row in combined["raw_evidence"]}, "final", final=True)
            break
        if len(nodes) == 1 or level >= 12:
            raise ValueError("hierarchical synthesis cannot fit without dropping raw citation evidence")
        groups, current = [], []
        for node in nodes:
            proposed = current + [node]
            if len(merge_prompt + _json(node_payload(proposed))) > capacity:
                if not current:
                    raise ValueError("one summary and its raw citations exceed merge budget")
                groups.append(current)
                current = [node]
            else:
                current = proposed
        if current:
            groups.append(current)
        if len(groups) >= len(nodes):
            raise ValueError("bounded summary merging made no progress; reduce per-claim citation size upstream")
        next_nodes = []
        for index, group in enumerate(groups):
            if len(group) == 1:
                next_nodes.extend(group)
                continue
            payload = node_payload(group)
            summary = stage(merge_prompt + _json(payload), {row["id"] for row in payload["raw_evidence"]},
                            f"merge_{level:02d}_{index:04d}")
            next_nodes.append({"summary": summary,
                               "covered_evidence_ids": [item for node in group for item in node["covered_evidence_ids"]],
                               "range_seconds": [min(node["range_seconds"][0] for node in group),
                                                 max(node["range_seconds"][1] for node in group)]})
        nodes, level = next_nodes, level + 1
    covered = [item for node in nodes for item in node["covered_evidence_ids"]]
    if len(covered) != len(evidence) or set(covered) != set(known):
        raise ValueError("hierarchical synthesis did not preserve complete leaf coverage")
    expression["uncertainties"] = list(dict.fromkeys([*(expression.get("uncertainties") or []),
        "长片采用覆盖全部原始证据的分层模型归纳，合并可能遗漏细节；核心与引用仍需独立语义核对。",
    ]))
    return expression, {"schema": "local_synthesis_provenance/v1", "strategy": "chronological_hierarchical",
                        "raw_evidence_count": len(evidence), "leaf_count": leaf_count, "merge_levels": level,
                        "leaf_covered_evidence_ids": covered, "stages": stages}
