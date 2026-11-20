"""Render only verified ready natural-director text into a separate readable delivery."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _binding(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _json(path):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("交付记录存在重复字段：" + key)
            value[key] = item
        return value
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)


def _fenced(text):
    fence = "`" * max(3, 1 + max((len(value) for value in re.findall(r"`+", text)), default=0))
    return fence + "text\n" + text + ("" if text.endswith("\n") else "\n") + fence


def _review_summary(label, review):
    native = review["native"]
    lines = ["## " + label, "", "原生判词：" + native["verdict"], "", native["summary"], ""]
    checks = native.get("checks", {})
    for name, value in checks.items():
        lines.extend(["- " + name + "：" + str(value)])
    if native.get("issues"):
        lines.extend(["", "原生问题记录：", "", "```json", json.dumps(native["issues"], ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines)


def render(run_dir, output_dir):
    from src.content_factory import natural_director_pipeline_v10 as pipeline
    run, output = Path(run_dir).resolve(), Path(output_dir).resolve()
    report = pipeline.inspect(run)
    if (report.get("status") != "text_ready_for_production" or report.get("blockers") or report.get("pending_call")):
        raise ValueError("仅可导出inspect已核实ready且无未决请求/阻断的完整文本，不导出未通过稿为交付")
    if output == run or output.is_relative_to(run):
        raise ValueError("可读交付必须保存在原运行目录之外，不能改写原生文件")
    files = {name: run / name for name in ("BINDING.json", "OUTPUT_MANIFEST.json", "SCREENPLAY.md",
                                         "NATURAL_DIRECTOR.md", "VIDEO_REQUESTS.json", "PRODUCTION_HANDOFF.json")}
    bindings = {name: _binding(path) for name, path in files.items()}
    frozen = _json(files["BINDING.json"])
    handoff, requests = _json(files["PRODUCTION_HANDOFF.json"]), _json(files["VIDEO_REQUESTS.json"])
    pipeline.contracts.validate_handoff_for_dispatch(handoff)
    if handoff.get("video_requests") != requests:
        raise ValueError("完整可读交付请求与已审核交接不一致")
    writer = files["SCREENPLAY.md"].read_bytes().decode("utf-8")
    natural = files["NATURAL_DIRECTOR.md"].read_bytes().decode("utf-8")
    if natural != handoff.get("natural_director_text") or hashlib.sha256(writer.encode()).hexdigest() != handoff.get("draft_binding"):
        raise ValueError("完整稿或自然导演不是当前已核实的同一原文")
    title = frozen["source"].get("title") or "自然导演完整文本交付"
    total = sum(item["duration_seconds"] for item in requests["requests"])
    lines = ["# " + title, "", f"机器文本与全部实际请求已审核；共{len(requests['requests'])}段，计划总长{total}秒。", "",
             "视频尚未生成，实际视频内容由用户人工审核。", "", "## 完整编剧原文", "", writer,
             "", "## MiniMax完整自然导演原文", "", natural, "", "## 全部分段实际提示词", ""]
    for item in requests["requests"]:
        lines.extend([f"### {item['segment_id']} · {item['duration_seconds']}秒", "", _fenced(item["prompt"]), ""])
    lines.extend([_review_summary("DeepSeek忠实整理与全文审核", handoff["extract"]), "",
                  _review_summary("DeepSeek全部实际请求整包审核", handoff["final_review"]), ""])
    markdown = "\n".join(lines).encode("utf-8")
    request_bytes = files["VIDEO_REQUESTS.json"].read_bytes()
    contents = {"COMPLETE_TEXT_DELIVERY.md": markdown, "SDK_REQUESTS.json": request_bytes}
    manifest = {"schema": "natural_director_readable_delivery/v10", "status": "verified_text_delivery",
        "source_run": str(run), "source_files": bindings, "request_count": len(requests["requests"]),
        "estimated_duration_seconds": total, "original_native_content_modified": False,
        "media_generated": False, "human_approved": False,
        "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in contents.items()}}
    contents["DELIVERY_MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # Recheck every read source after rendering and before publishing any output.
    if bindings != {name: _binding(path) for name, path in files.items()}:
        raise ValueError("源文件在可读交付过程中变化，不发布交付副本")
    for name, data in contents.items():
        path = output / name
        if path.exists() and (not path.is_file() or path.read_bytes() != data):
            raise ValueError("目标已有不同交付文件，不覆盖：" + str(path))
    output.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        path = output / name
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(data)
    return {"status": "verified_text_delivery", "output_dir": str(output), "request_count": len(requests["requests"]),
            "estimated_duration_seconds": total, "files": {name: str(output / name) for name in contents},
            "automatic_media_submit": False, "human_approved": False}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = render(args.run_dir, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "delivery_rejected", "error": str(exc), "automatic_media_submit": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
