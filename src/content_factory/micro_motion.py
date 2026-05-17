"""
micro_motion.py — 人物微动作生成器（方案A: 每眼独立patch + 确定性眨眼事件）

功能：眨眼（每只眼睛独立patch）+ 胸口阴影呼吸
输入：分层 PNG 素材
输出：PNG 序列帧

文档：docs/IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md
修复：docs/DUAL_V12_EYE_POSITION_FIX_PLAN_2026-05-10.md
"""

import os
import random
import math
from dataclasses import dataclass
from typing import Optional, List
from PIL import Image
import numpy as np


# ─── 角色素材坐标（源图 1728x2304）───────────────────────────

@dataclass(frozen=True)
class EyePatch:
    """单只眼睛的闭眼贴片"""
    file_name: str
    offset: tuple[int, int]  # (x, y) 左上角在源图画布上的位置


# na1 男角色：双眼 patch + 胸口阴影
NA1_EYE_PATCHES: List[EyePatch] = [
    EyePatch("viewer_left_eye_closed.png",  (567, 245)),
    EyePatch("viewer_right_eye_closed.png", (876, 267)),
]
NA1_CHEST_OFFSET = (664, 750)

# n3 女角色：双眼 patch + 胸口阴影
N3_EYE_PATCHES: List[EyePatch] = [
    EyePatch("viewer_left_eye_closed.png",  (569, 253)),
    EyePatch("viewer_right_eye_closed.png", (929, 242)),
]
N3_CHEST_OFFSET = (664, 750)


# ─── 配置 dataclass ──────────────────────────────────────────────

@dataclass
class MotionConfig:
    fps: int = 30
    duration: float = 31.5
    blink_interval_min: float = 3.0   # 眨眼最小间隔（秒）
    blink_interval_max: float = 5.0   # 眨眼最大间隔（秒）
    blink_duration_frames: int = 5    # 每次眨眼持续帧数
    breath_period: float = 5.2        # 呼吸周期（秒）
    breath_opacity_min: float = 0.85  # 呼吸阴影最小透明度
    breath_opacity_max: float = 1.0   # 呼吸阴影最大透明度（=无阴影）
    breath_enabled: bool = True        # 是否启用呼吸
    blink_enabled: bool = True        # 是否启用眨眼
    first_blink_min: float = 2.0      # 第一次眨眼最早时间
    first_blink_max: float = 4.0      # 第一次眨眼最晚时间
    seed: int = 1                    # 随机种子（确保可复现）


# ─── 核心函数 ──────────────────────────────────────────────

def _load_asset(asset_dir: str, name: str) -> Optional[Image.Image]:
    path = os.path.join(asset_dir, name)
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    return None


def _paste(base: Image.Image, overlay: Image.Image, offset: tuple) -> Image.Image:
    """把 overlay 贴到 base 的 offset 位置（alpha 作为 mask）"""
    result = base.copy()
    x, y = offset
    ow, oh = overlay.size
    bx, by = result.size
    if x >= bx or y >= by:
        return result
    cw = min(ow, bx - x)
    ch = min(oh, by - y)
    if cw <= 0 or ch <= 0:
        return result
    result.paste(overlay.crop((0, 0, cw, ch)), (x, y), overlay.crop((0, 0, cw, ch)))
    return result


def _blend_alpha(overlay: Image.Image, alpha: float) -> Image.Image:
    """按比例调整 overlay 的 alpha 通道"""
    arr = np.array(overlay)
    arr[:, :, 3] = (arr[:, :, 3] * alpha).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _compute_breath_strength(t: float, config: MotionConfig) -> float:
    """呼吸阴影透明度，周期正弦变化。0.85=最强阴影，1.0=无阴影"""
    breath_phase = 2 * math.pi * t / config.breath_period
    normalized = 0.5 + 0.5 * math.sin(breath_phase)
    return config.breath_opacity_min + \
        (config.breath_opacity_max - config.breath_opacity_min) * normalized


def build_blink_events(
    duration: float,
    fps: int,
    seed: int,
    interval_min: float,
    interval_max: float,
    duration_frames: int,
    first_min: float,
    first_max: float,
) -> List[tuple[int, int]]:
    """
    预生成确定性眨眼事件列表。

    Returns:
        [(start_frame, end_frame), ...] 闭眼窗口列表
    """
    rng = random.Random(seed)
    events = []
    t = rng.uniform(first_min, first_max)
    while t < duration:
        start = int(round(t * fps))
        end = start + duration_frames
        events.append((start, end))
        t += rng.uniform(interval_min, interval_max)
    return events


def render_micro_motion_character(
    asset_dir: str,
    output_dir: str,
    eye_patches: List[EyePatch],
    config: Optional[MotionConfig] = None,
    chest_offset: tuple = None,
    chest_asset_name: str = "chest_shadow.png",
    character_name: str = "character",
    output_debug: bool = False,
) -> str:
    """
    生成单个角色的微动作 PNG 序列。

    Args:
        asset_dir: 分层素材目录
        output_dir: 输出帧目录
        eye_patches: 每只眼睛的 patch 列表
        config: 动作配置
        chest_offset: 胸口 patch 偏移
        chest_asset_name: 胸口素材文件名
        character_name: 日志角色名
        output_debug: 是否输出调试图（闭眼帧+睁眼帧）

    Returns:
        输出帧目录路径
    """
    if config is None:
        config = MotionConfig()

    os.makedirs(output_dir, exist_ok=True)

    # 加载素材
    body = _load_asset(asset_dir, "body.png")
    chest_shadow = _load_asset(asset_dir, chest_asset_name) if config.breath_enabled else None
    loaded_patches = []
    for ep in eye_patches:
        img = _load_asset(asset_dir, ep.file_name)
        if img is not None:
            loaded_patches.append((ep.offset, img))

    if body is None:
        raise FileNotFoundError(f"body.png not found in {asset_dir}")

    total_frames = int(config.duration * config.fps)
    print(f"[{character_name}] 微动作序列: {config.duration}s, {total_frames} 帧, fps={config.fps}")
    print(f"  eye_patches: {[(ep.file_name, ep.offset) for ep in eye_patches]}")
    print(f"  chest_offset: {chest_offset}, breath: {config.breath_enabled}, blink: {config.blink_enabled}")

    # 预生成眨眼事件（确定性）
    blink_events = []
    if config.blink_enabled:
        blink_events = build_blink_events(
            duration=config.duration,
            fps=config.fps,
            seed=config.seed,
            interval_min=config.blink_interval_min,
            interval_max=config.blink_interval_max,
            duration_frames=config.blink_duration_frames,
            first_min=config.first_blink_min,
            first_max=config.first_blink_max,
        )
        print(f"  blink_events: {len(blink_events)} 次")

    # 输出调试帧
    debug_frame_dir = None
    if output_debug:
        debug_frame_dir = os.path.join(output_dir, "_debug_frames")
        os.makedirs(debug_frame_dir, exist_ok=True)

    for frame_idx in range(total_frames):
        t = frame_idx / config.fps

        # 1. 从 body 开始
        frame = body.copy()

        # 2. 眨眼：帧号落在任一闭眼窗口内
        is_blink = any(start <= frame_idx < end for start, end in blink_events)
        if is_blink:
            for offset, patch_img in loaded_patches:
                frame = _paste(frame, patch_img, offset)

        # 3. 呼吸：胸口阴影透明度变化
        if chest_shadow is not None and chest_offset is not None:
            strength = _compute_breath_strength(t, config)
            chest_adjusted = _blend_alpha(chest_shadow, strength)
            frame = _paste(frame, chest_adjusted, chest_offset)

        # 4. 保存帧
        frame_path = os.path.join(output_dir, f"{frame_idx + 1:06d}.png")
        frame.save(frame_path, optimize=False)

        # 5. 调试帧：保存闭眼瞬间和睁眼瞬间
        if output_debug and debug_frame_dir and frame_idx in {0, 1, 2, 100, 150}:
            dbg_path = os.path.join(debug_frame_dir, f"frame_{frame_idx+1:06d}.png")
            frame.save(dbg_path)

        if frame_idx % 200 == 0 and frame_idx > 0:
            print(f"  进度: {frame_idx}/{total_frames} 帧")

    print(f"  完成: {output_dir}")
    return output_dir


def generate_dual_character_sequence(
    asset_a_dir: str,
    asset_b_dir: str,
    output_dir: str,
    config: MotionConfig,
) -> tuple[str, str]:
    """
    生成双角色微动作序列（版本化输出目录）。

    Returns:
        (role_a_frames_dir, role_b_frames_dir)
    """
    os.makedirs(output_dir, exist_ok=True)

    seq_a = os.path.join(output_dir, "na1")
    seq_b = os.path.join(output_dir, "n3")

    # 角色 B 复用相同配置，但 seed 不同 + blink_offset（已由 build_blink_events 预生成事件）
    import copy
    config_a = copy.copy(config)
    config_b = copy.copy(config)
    config_b.seed = config.seed + 100  # 不同 seed = 不同眨眼时间

    import threading
    result = {}

    def thread_a():
        result["a"] = render_micro_motion_character(
            asset_dir=asset_a_dir,
            output_dir=seq_a,
            eye_patches=NA1_EYE_PATCHES,
            config=config_a,
            chest_offset=NA1_CHEST_OFFSET,
            character_name="na1",
        )

    def thread_b():
        result["b"] = render_micro_motion_character(
            asset_dir=asset_b_dir,
            output_dir=seq_b,
            eye_patches=N3_EYE_PATCHES,
            config=config_b,
            chest_offset=N3_CHEST_OFFSET,
            character_name="n3",
        )

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    return result["a"], result["b"]


# ─── 调试预览图生成 ────────────────────────────────────────────

def save_debug_preview(
    frame_dir: str,
    character_name: str,
    output_path: str,
    frame_indices: tuple = (1, 2, 105, 110),
):
    """从序列帧目录中抽取指定帧，拼接成一张预览图"""
    frames = []
    for idx in frame_indices:
        path = os.path.join(frame_dir, f"{idx:06d}.png")
        if os.path.exists(path):
            frames.append(Image.open(path).convert("RGB"))
    if not frames:
        return
    # 缩放到宽度 540 后拼接
    w = 540
    resized = [f.resize((w, int(w * f.height / f.width)), Image.LANCZOS) for f in frames]
    total_h = sum(r.height for r in resized)
    canvas = Image.new("RGB", (w, total_h), (0, 0, 0))
    y = 0
    for r in resized:
        canvas.paste(r, (0, y))
        y += r.height
    canvas.save(output_path)
    print(f"  调试预览: {output_path}")


if __name__ == "__main__":
    import sys
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

    config = MotionConfig(duration=duration, fps=30, seed=1, breath_enabled=False)

    print("=== 调试：生成 na1 眨眼预览（仅眨眼，无呼吸）===")
    out = render_micro_motion_character(
        asset_dir="data/motion_assets/na1",
        output_dir="data/videos/characters/v13_na1_test",
        eye_patches=NA1_EYE_PATCHES,
        config=config,
        chest_offset=NA1_CHEST_OFFSET,
        character_name="na1_debug",
        output_debug=True,
    )

    save_debug_preview(
        frame_dir=os.path.join(out, "_debug_frames"),
        character_name="na1",
        output_path="data/diagnostics/v13_na1_debug.png",
        frame_indices=(1, 2, 105, 110),
    )
    print("Done")
