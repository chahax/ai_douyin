"""
framepack_pipeline.py — FramePack 输出后处理 + 双人视频合成

流程：
  1. 抽帧（MP4 -> PNG 序列）
  2. chromakey 抠图（绿幕 -> RGBA PNG）
  3. 帧循环（短片段 -> 配音时长）
  4. 合成最终视频

用法（FramePack 手动生成 MP4 后）：
  python src/content_factory/framepack_pipeline.py --video na1_idle_v1
  python src/content_factory/framepack_pipeline.py --video na1_idle_v1 --role a
"""

import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path

# ─── 路径配置 ─────────────────────────────────────────────────

BASE = Path("data/framepack")
RAW = BASE / "raw_frames"
ALPHA = BASE / "frames_alpha"
LOOPED = BASE / "frames_looped"
OUTPUT = Path("data/videos")
FPS = 30

# ─── FFmpeg 辅助 ────────────────────────────────────────────────

def run_ffmpeg(cmd: list, timeout: int = 300) -> bool:
    """执行 ffmpeg 命令"""
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode != 0:
            print(f"[FFmpeg] 失败:\n{result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("[FFmpeg] 超时")
        return False
    except FileNotFoundError:
        print("[FFmpeg] 未找到 ffmpeg")
        return False


def get_frame_count(frames_dir: Path) -> int:
    """统计帧目录里的 PNG 数量"""
    if not frames_dir.exists():
        return 0
    return len(list(frames_dir.glob("*.png")))


# ─── Step 1: 抽帧 ───────────────────────────────────────────────

def extract_frames(video_name: str) -> tuple[Path, int]:
    """
    MP4 -> PNG 序列
    Returns: (frames_dir, frame_count)
    """
    video_path = BASE / "output" / f"{video_name}.mp4"
    frames_dir = RAW / video_name
    frames_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"视频不存在: {video_path}")

    # 先清空旧帧
    for f in frames_dir.glob("*.png"):
        f.unlink()

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps={FPS}",
        str(frames_dir / "%06d.png"),
    ]

    print(f"[抽帧] {video_path} -> {frames_dir}")
    if not run_ffmpeg(cmd):
        raise RuntimeError("抽帧失败")

    count = get_frame_count(frames_dir)
    print(f"  抽帧完成: {count} 帧")
    return frames_dir, count


# ─── Step 2: chromakey 抠图 ─────────────────────────────────────

def chromakey_frames(video_name: str, similarity: float = 0.18, blend: float = 0.08) -> Path:
    """
    绿幕视频帧 -> RGBA PNG 序列
    """
    src_dir = RAW / video_name
    out_dir = ALPHA / video_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清空旧帧
    for f in out_dir.glob("*.png"):
        f.unlink()

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_dir / "%06d.png"),
        "-vf", f"chromakey=0x00ff00:{similarity}:{blend},format=rgba",
        str(out_dir / "%06d.png"),
    ]

    print(f"[抠图] {src_dir} -> {out_dir}  (similarity={similarity})")
    if not run_ffmpeg(cmd):
        raise RuntimeError("抠图失败")

    count = get_frame_count(out_dir)
    print(f"  抠图完成: {count} 帧")
    return out_dir


# ─── Step 3: 循环帧 ─────────────────────────────────────────────

def loop_frames(video_name: str, target_duration: float, audio_path: str = None) -> Path:
    """
    短片段循环到目标时长
    如果提供 audio_path，时长从音频读取
    """
    src_dir = ALPHA / video_name
    out_dir = LOOPED / video_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清空旧帧
    for f in out_dir.glob("*.png"):
        f.unlink()

    if audio_path and os.path.exists(audio_path):
        audio_dur = get_audio_duration(audio_path)
        if audio_dur > 0:
            target_duration = audio_dur
            print(f"[循环] 音频时长 {audio_dur:.2f}s")

    src_count = get_frame_count(src_dir)
    if src_count == 0:
        raise RuntimeError(f"源帧为空: {src_dir}")

    target_frames = int(target_duration * FPS)
    print(f"[循环] {src_count} 帧 -> {target_frames} 帧 (目标 {target_duration:.2f}s)")

    # 用 FFmpeg loop + concat 延长
    # 先把原始帧复制一份，然后用 loop
    # 注意：FFmpeg 的 loop_input 对图片序列不太好用，改用 -stream_loop 全局 + 次数
    repeat_count = (target_frames // src_count) + 2  # 多循环几次保险

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(repeat_count),
        "-framerate", str(FPS),
        "-i", str(src_dir / "%06d.png"),
        "-vframes", str(target_frames),
        "-c:v", "png",
        str(out_dir / "%06d.png"),
    ]

    if not run_ffmpeg(cmd):
        raise RuntimeError("循环失败")

    count = get_frame_count(out_dir)
    print(f"  循环完成: {count} 帧")
    return out_dir


def get_audio_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        return float(subprocess.check_output(cmd, text=True, timeout=10).strip())
    except Exception:
        return 0.0


# ─── Step 4: 合成最终视频 ──────────────────────────────────────

def compose_final_video(
    role_a_frames: str,
    role_b_frames: str,
    background_path: str,
    audio_a_path: str,
    audio_b_path: str,
    output_name: str,
    role_a_x: int = 0,
    role_a_y: int = 480,
    role_b_x: int = 540,
    role_b_y: int = 480,
    active_speaker_timeline: list = None,
) -> str:
    """调用 video_composer 合成最终视频"""
    from src.content_factory.video_composer import compose_dual_character_sequence_video
    return compose_dual_character_sequence_video(
        background_path=background_path,
        role_a_sequence=role_a_frames,
        role_b_sequence=role_b_frames,
        audio_a_path=audio_a_path,
        audio_b_path=audio_b_path,
        output_dir=str(OUTPUT),
        output_name=output_name,
        portrait=True,
        role_a_x=role_a_x,
        role_a_y=role_a_y,
        role_b_x=role_b_x,
        role_b_y=role_b_y,
        active_speaker_timeline=active_speaker_timeline,
    )


# ─── 完整流水线 ───────────────────────────────────────────────

def run_pipeline(
    video_name: str,
    audio_a_path: str = None,
    audio_b_path: str = None,
    background_path: str = "data/videos/bg_loop.mp4",
    target_duration: float = 31.5,
    chromakey_similarity: float = 0.18,
    chromakey_blend: float = 0.08,
    output_name: str = "dual_v14_framepack_idle",
    role_a_x: int = 0,
    role_a_y: int = 480,
    role_b_x: int = 540,
    role_b_y: int = 480,
) -> str:
    """
    完整流水线：抽帧 -> 抠图 -> 循环 -> 合成
    """
    print(f"\n{'='*50}")
    print(f"FramePack 流水线: {video_name}")
    print(f"{'='*50}")

    # Step 1: 抽帧
    frames_dir, frame_count = extract_frames(video_name)

    # Step 2: chromakey 抠图
    alpha_dir = chromakey_frames(video_name, chromakey_similarity, chromakey_blend)

    # Step 3: 循环（时长从音频读取，如果没有则用 target_duration）
    looped_dir = loop_frames(video_name, target_duration, audio_a_path)

    print(f"\n[完成] 处理后帧目录: {looped_dir}")
    return str(looped_dir)


# ─── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FramePack 后处理流水线")
    parser.add_argument("--video", required=True, help="视频名（不含 .mp4），如 na1_idle_v1")
    parser.add_argument("--role", choices=["a", "b", "dual"], default="a", help="处理角色")
    parser.add_argument("--audio-a", default="data/ref_audio/role_a.wav", help="角色A音频")
    parser.add_argument("--audio-b", default="data/ref_audio/role_b.wav", help="角色B音频")
    parser.add_argument("--bg", default="data/videos/bg_loop.mp4", help="背景视频")
    parser.add_argument("--similarity", type=float, default=0.18, help="chromakey 相似度")
    parser.add_argument("--blend", type=float, default=0.08, help="chromakey 边缘混合")
    parser.add_argument("--duration", type=float, default=31.5, help="目标时长（秒）")
    parser.add_argument("--active-speaker", action="store_true", help="双角色合成时启用谁说话谁轻微放大/高亮")
    args = parser.parse_args()

    if args.role == "a":
        result = run_pipeline(
            video_name=args.video,
            audio_a_path=args.audio_a,
            target_duration=args.duration,
            chromakey_similarity=args.similarity,
            chromakey_blend=args.blend,
        )
        print(f"\n角色A处理完成: {result}")

    elif args.role == "b":
        result = run_pipeline(
            video_name=args.video,
            audio_a_path=args.audio_b,
            target_duration=args.duration,
            chromakey_similarity=args.similarity,
            chromakey_blend=args.blend,
        )
        print(f"\n角色B处理完成: {result}")

    else:
        # dual: 假设 video_name 是角色A，女角色自动用 n3
        video_name_a = args.video
        video_name_b = args.video.replace("na1", "n3")

        print(f"\n>>> 处理角色A: {video_name_a}")
        looped_a = run_pipeline(
            video_name=video_name_a,
            audio_a_path=args.audio_a,
            target_duration=args.duration,
            chromakey_similarity=args.similarity,
            chromakey_blend=args.blend,
        )

        print(f"\n>>> 处理角色B: {video_name_b}")
        looped_b = run_pipeline(
            video_name=video_name_b,
            audio_a_path=args.audio_b,
            target_duration=args.duration,
            chromakey_similarity=args.similarity,
            chromakey_blend=args.blend,
        )

        # Step 4: 合成
        print(f"\n>>> 合成最终视频...")
        active_timeline = None
        if args.active_speaker:
            audio_a_dur = get_audio_duration(args.audio_a)
            audio_b_dur = get_audio_duration(args.audio_b)
            if audio_a_dur > 0 and audio_b_dur > 0:
                active_timeline = [
                    ("A", 0, audio_a_dur),
                    ("B", audio_a_dur, audio_a_dur + audio_b_dur),
                ]
        final = compose_final_video(
            role_a_frames=str(looped_a) + "/%06d.png",
            role_b_frames=str(looped_b) + "/%06d.png",
            background_path=args.bg,
            audio_a_path=args.audio_a,
            audio_b_path=args.audio_b,
            output_name="dual_v14_framepack_idle",
            role_a_x=0,
            role_a_y=480,
            role_b_x=540,
            role_b_y=480,
            active_speaker_timeline=active_timeline,
        )
        print(f"\n=== 全部完成: {final} ===")


if __name__ == "__main__":
    main()
