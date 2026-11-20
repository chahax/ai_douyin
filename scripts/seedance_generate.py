#!/usr/bin/env python3
"""Submit one analysis prompt-pack segment to the selected Seedance provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from dataclasses import replace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.content_factory.seedance_client import (  # noqa: E402
    SeedanceClient,
    SeedanceConfig,
    SeedanceReference,
    load_prompt_pack_segment,
)
from src.content_factory.dreamina_cli import (  # noqa: E402
    DreaminaCLIClient,
    DreaminaCLIConfig,
    dreamina_report_status,
    dreamina_submit_id,
)
from src.shared.config import settings  # noqa: E402
from src.content_factory.seedance_models import load_catalog, TASK_TYPES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="读取分析提示词包中的一个分段并提交给所选 Seedance 渠道。默认只生成请求预览，不产生费用。"
    )
    parser.add_argument("prompt_pack", nargs='?', help="analysis_video_prompt_pack/v1 JSON 文件")
    parser.add_argument("--segment", help="分段 ID，例如 S01 或 segment-S01")
    parser.add_argument('--list-models',action='store_true',help='列出已登记型号，不调用生成接口')
    parser.add_argument('--model',help='本次调用的模型 ID；不修改首选模型')
    parser.add_argument('--task-type',choices=sorted(TASK_TYPES),default='auto')
    parser.add_argument('--output-format',choices=['mp4','mov'])
    parser.add_argument('--first-frame',help='首帧图片 URL、Base64 或 asset:// ID')
    parser.add_argument('--last-frame',help='尾帧图片 URL、Base64 或 asset:// ID')
    parser.add_argument(
        "--provider",
        choices=("dreamina_cli", "byteplus_api", "ark_api"),
        default=settings.SEEDANCE_PROVIDER,
        help="生成渠道；默认读取 SEEDANCE_PROVIDER",
    )
    parser.add_argument(
        "--output-dir",
        default="data/video_generation/seedance",
        help="请求记录、任务状态和下载视频的输出目录",
    )
    parser.add_argument("--duration", type=int, help="覆盖生成时长；方舟 2.0 Mini 为 4–15 秒，即梦/BytePlus 2.5 为 4–30 秒")
    parser.add_argument("--ratio", default=settings.SEEDANCE_DEFAULT_RATIO)
    parser.add_argument(
        "--resolution",
        choices=("480p", "720p", "1080p", "4k"),
        default=settings.SEEDANCE_DEFAULT_RESOLUTION,
    )
    parser.add_argument("--session", type=int, default=0, help="即梦 CLI 会话 ID")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--watermark", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--reference-image", action="append", default=[])
    parser.add_argument("--reference-video", action="append", default=[])
    parser.add_argument("--reference-audio", action="append", default=[])
    parser.add_argument("--callback-url")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="实际提交付费任务；不传时只输出并保存请求预览",
    )
    parser.add_argument("--wait", action="store_true", help="等待任务完成")
    parser.add_argument("--download", action="store_true", help="成功后下载 MP4；必须同时传 --wait")
    parser.add_argument("--wait-timeout", type=float, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_models:
        print(json.dumps(load_catalog(),ensure_ascii=False,indent=2))
        return 0
    if not args.prompt_pack or not args.segment:
        raise SystemExit('prompt_pack and --segment are required unless using --list-models')
    if args.wait and not args.submit:
        raise SystemExit("--wait requires --submit")
    if args.download and not args.wait:
        raise SystemExit("--download requires --wait and --submit")

    pack_path = Path(args.prompt_pack).resolve()
    pack = json.loads(pack_path.read_text(encoding="utf-8-sig"))
    segment, prompt, inferred_duration = load_prompt_pack_segment(pack, args.segment)
    duration = args.duration if args.duration is not None else inferred_duration
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_segment_id = str(segment["id"]).replace("/", "-").replace("\\", "-")

    if args.provider == "dreamina_cli":
        if args.model or args.task_type!='auto' or args.output_format or args.first_frame or args.last_frame:
            raise SystemExit('These model/task controls belong to the Ark API entry; use its provider')
        return _run_dreamina(
            args,
            pack_path=pack_path,
            segment=segment,
            prompt=prompt,
            duration=duration,
            output_dir=output_dir,
            safe_segment_id=safe_segment_id,
        )

    references = _references(args)

    # A placeholder key is sufficient to validate and preview the request. A
    # real key is loaded only when the user explicitly passes --submit.
    config = SeedanceConfig.from_env(args.provider,require_key=args.submit)
    if args.model:config=replace(config,model=args.model)
    with SeedanceClient(config) as client:
        payload = client.build_task_payload(
            prompt,
            duration=duration,
            ratio=args.ratio,
            resolution=args.resolution,
            generate_audio=not args.no_audio,
            watermark=args.watermark,
            return_last_frame=True,
            seed=args.seed,
            references=references,
            callback_url=args.callback_url,
            task_type=args.task_type,
            output_format=args.output_format,
        )
        report: dict[str, Any] = {
            "schema": "seedance_generation_report/v1",
            "provider": args.provider,
            "mode": "submit" if args.submit else "dry-run",
            "prompt_pack": str(pack_path),
            "segment_id": segment["id"],
            "request": payload,
        }
        report_path = output_dir / f"{safe_segment_id}.seedance.json"
        if report_path.exists():
            previous=json.loads(report_path.read_text(encoding='utf-8'))
            if previous.get('mode')=='submit':
                raise RuntimeError('Submission receipt already exists; query the saved task instead of resubmitting')
        if not args.submit:
            _write_json(report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        from datetime import datetime, timezone
        report.update(created_at=datetime.now(timezone.utc).isoformat(),status='submit_outcome_unknown')
        _write_json(report_path,report)
        created = client.create_task(payload)
        report["created"] = created
        report['status']='submitted'
        _write_json(report_path, report)
        print(json.dumps({"status": "submitted", "task_id": created["id"]}, ensure_ascii=False))

        if not args.wait:
            return 0

        def record_update(task):
            report.update(final=task,updated_at=datetime.now(timezone.utc).isoformat())
            _write_json(report_path,report)
            print(json.dumps({'task_id':task.get('id'),'status':task.get('status')},ensure_ascii=False))

        final = client.wait_for_task(
            created["id"],
            timeout_seconds=args.wait_timeout,
            on_update=record_update,
        )
        report["final"] = final
        if args.download:
            video_path = client.download_video(final, output_dir / f"{safe_segment_id}.{args.output_format or 'mp4'}")
            report["video_path"] = str(video_path)
        _write_json(report_path, report)
        print(
            json.dumps(
                {
                    "status": final["status"],
                    "task_id": final["id"],
                    "video_path": report.get("video_path"),
                    "report_path": str(report_path),
                },
                ensure_ascii=False,
            )
        )
    return 0


def _run_dreamina(
    args: argparse.Namespace,
    *,
    pack_path: Path,
    segment: dict[str, Any],
    prompt: str,
    duration: int,
    output_dir: Path,
    safe_segment_id: str,
) -> int:
    unsupported: list[str] = []
    if args.no_audio:
        unsupported.append("--no-audio")
    if args.watermark:
        unsupported.append("--watermark")
    if args.seed is not None:
        unsupported.append("--seed")
    if args.callback_url:
        unsupported.append("--callback-url")
    if unsupported:
        raise SystemExit(
            "Dreamina CLI does not expose these options: " + ", ".join(unsupported)
        )

    client = DreaminaCLIClient(DreaminaCLIConfig.from_settings())
    arguments = client.build_video_arguments(
        prompt,
        duration=duration,
        ratio=args.ratio,
        resolution=args.resolution,
        session=args.session,
        reference_images=args.reference_image,
        reference_videos=args.reference_video,
        reference_audio=args.reference_audio,
        poll_seconds=0,
    )
    request = {
        "model": client.config.model_version,
        "resolution": args.resolution,
        "ratio": args.ratio,
        "duration": duration,
        "generate_audio": True,
        "content": [{"type": "text", "text": prompt}],
        "cli": {
            "subcommand": arguments[0],
            "arguments": arguments[1:],
            "session": args.session,
        },
    }
    report: dict[str, Any] = {
        "schema": "seedance_generation_report/v1",
        "provider": "dreamina_cli",
        "mode": "submit" if args.submit else "dry-run",
        "prompt_pack": str(pack_path),
        "segment_id": segment["id"],
        "request": request,
    }
    report_path = output_dir / f"{safe_segment_id}.seedance.json"
    if not args.submit:
        _write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    created_payload = client.submit_video(arguments)
    submit_id = dreamina_submit_id(created_payload)
    if not submit_id:
        raise RuntimeError("Dreamina CLI response did not contain submit_id")
    report["created"] = {
        "id": submit_id,
        "status": dreamina_report_status(created_payload),
        "provider_response": created_payload,
    }
    _write_json(report_path, report)
    print(json.dumps({"status": "submitted", "task_id": submit_id}, ensure_ascii=False))
    if not args.wait:
        return 0

    final_payload = client.wait_for_result(
        submit_id,
        initial=created_payload,
        timeout_seconds=args.wait_timeout,
        on_update=lambda task: print(
            json.dumps(
                {
                    "task_id": dreamina_submit_id(task) or submit_id,
                    "status": dreamina_report_status(task),
                },
                ensure_ascii=False,
            )
        ),
    )
    if args.download:
        final_payload = client.query_result(submit_id, download_dir=output_dir)
        report["video_path"] = _find_downloaded_video(final_payload, output_dir)
    report["final"] = {
        "id": submit_id,
        "model": client.config.model_version,
        "status": dreamina_report_status(final_payload),
        "resolution": args.resolution,
        "ratio": args.ratio,
        "duration": duration,
        "generate_audio": True,
        "provider_response": final_payload,
    }
    _write_json(report_path, report)
    print(
        json.dumps(
            {
                "status": report["final"]["status"],
                "task_id": submit_id,
                "video_path": report.get("video_path"),
                "report_path": str(report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _find_downloaded_video(payload: dict[str, Any], output_dir: Path) -> str:
    candidates: list[Path] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.lower().endswith(".mp4"):
            path = Path(value)
            candidates.append(path if path.is_absolute() else output_dir / path)

    visit(payload)
    candidates.extend(sorted(output_dir.glob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True))
    for path in candidates:
        if path.is_file():
            return str(path.resolve())
    return ""


def _references(args: argparse.Namespace) -> list[SeedanceReference]:
    result: list[SeedanceReference] = []
    if args.first_frame:result.append(SeedanceReference('image',args.first_frame,'first_frame'))
    if args.last_frame:result.append(SeedanceReference('image',args.last_frame,'last_frame'))
    result.extend(
        SeedanceReference("image", source, "reference_image")
        for source in args.reference_image
    )
    result.extend(
        SeedanceReference("video", source, "reference_video")
        for source in args.reference_video
    )
    result.extend(
        SeedanceReference("audio", source, "reference_audio")
        for source in args.reference_audio
    )
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
