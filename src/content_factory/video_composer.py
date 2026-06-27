"""
video_composer.py — 视频拼接 + 音视频合成

流水线：
  1. 用 -stream_loop 循环视频片段 → 对齐配音时长
  2. 去除原声
  3. 替换为配音音频（单命令完成，无拼接中间文件）
"""

import os
import subprocess
import time

from src.shared.logger import logger


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _run_ffmpeg(cmd: list, timeout: int = 600) -> bool:
    """执行 ffmpeg 命令，返回是否成功"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",      # 替换无法解码的字符（Windows GBK 环境）
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"[FFmpeg Error]\n{result.stderr[-1000:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("[FFmpeg Error] 命令执行超时")
        return False
    except FileNotFoundError:
        logger.error("[FFmpeg Error] ffmpeg 未找到，请确认已安装并加入 PATH")
        return False


def get_duration(path: str) -> float:
    """读取文件/音视频时长（秒）"""
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


def _is_image_file(path: str) -> bool:
    """判断输入是否为静态图片，供 FFmpeg 使用 -loop 1。"""
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def _append_visual_input(cmd: list, path: str) -> None:
    """追加视频/图片输入；静态图片需要循环成视频流。"""
    if _is_image_file(path):
        cmd.extend(["-loop", "1", "-framerate", "24", "-i", path])
    else:
        cmd.extend(["-i", path])


def _normalize_active_speaker_timeline(timeline, total_duration: float) -> dict:
    """
    规范化主动说话角色时间轴。

    支持两种输入：
    - [{"speaker": "A", "start": 0, "end": 3.2}, ...]
    - [("A", 0, 3.2), ("B", 3.2, 6.0), ...]
    """
    segments = {"a": [], "b": []}
    if not timeline:
        return segments

    role_aliases = {
        "a": "a",
        "role_a": "a",
        "角色a": "a",
        "角色A": "a",
        "b": "b",
        "role_b": "b",
        "角色b": "b",
        "角色B": "b",
    }

    for item in timeline:
        if isinstance(item, dict):
            speaker = item.get("speaker") or item.get("role")
            start = item.get("start")
            end = item.get("end")
        else:
            if len(item) < 3:
                continue
            speaker, start, end = item[0], item[1], item[2]

        role = role_aliases.get(str(speaker).strip(), role_aliases.get(str(speaker).strip().lower()))
        if role not in segments:
            continue

        try:
            start_f = max(0.0, float(start))
            end_f = min(float(end), total_duration)
        except (TypeError, ValueError):
            continue

        if end_f > start_f:
            segments[role].append((start_f, end_f))

    return segments


def _active_enable_expr(segments: list) -> str:
    """生成 FFmpeg overlay enable 表达式。"""
    return "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in segments)


def _overlay_filter(base: str, layer: str, x, y, out: str, enable: str = None) -> str:
    """生成一段 overlay filter，enable 为空时全程显示。"""
    suffix = f":enable='{enable}'" if enable else ""
    return f"{base}{layer}overlay=x={x}:y={y}{suffix}{out}"


def compose_video(
    video_clip_path: str,
    audio_path: str,
    output_dir: str = "data/videos",
    output_name: str = None,
    audio_volume: float = 1.0,
    crf: int = 23,
) -> str:
    """
    完整流水线：循环拼接视频 + 替换音频

    单命令一次完成（-stream_loop 循环 + 音视频合并），无中间文件残留。

    Args:
        video_clip_path: 可灵/AI生成的原始视频片段
        audio_path:      TTS生成的配音音频（.wav / .mp3）
        output_dir:      输出目录
        output_name:     输出文件名（不含扩展名）
        audio_volume:    配音音量倍率（0.0-2.0）
        crf:             视频质量（0=无损，23=默认，28=更高压缩）

    Returns: 最终视频路径（成功） / 空字符串（失败）
    """
    os.makedirs(output_dir, exist_ok=True)

    audio_duration = get_duration(audio_path)
    if audio_duration <= 0:
        logger.error(f"[VideoComposer] 无法读取音频时长: {audio_path}")
        return ""

    clip_duration = get_duration(video_clip_path)
    if clip_duration <= 0:
        logger.error(f"[VideoComposer] 无法读取视频片段时长: {video_clip_path}")
        return ""

    repeat_count = max(1, int(audio_duration / clip_duration) + 1)

    if not output_name:
        output_name = f"final_{int(time.time() * 1000)}"
    final_path = os.path.join(output_dir, f"{output_name}.mp4")

    print(f"[VideoComposer] 视频片段 {clip_duration:.2f}s，配音 {audio_duration:.2f}s，循环 {repeat_count} 次")

    # 单命令：stream_loop 循环视频 + 注入音频
    cmd = [
        "ffmpeg", "-y",
        # 视频 loop，次数比需要的稍多（最后一帧会自然截断给 -shortest）
        "-stream_loop", str(repeat_count),
        "-i", video_clip_path,
        # 配音音频
        "-i", audio_path,
        # 视频：取 loop 后的视频流
        "-map", "0:v",
        # 音频：取配音（自动对齐 -shortest）
        "-map", "1:a",
        # 视频编码：H.264 重编码（stream_loop 需要重编码）
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        # 音频编码：AAC 192k
        "-c:a", "aac", "-b:a", "192k",
        # 音量调整
        "-af", f"volume={audio_volume}",
        # 以配音长度为总时长（自然截断 loop 视频）
        "-shortest",
        final_path,
    ]

    if _run_ffmpeg(cmd):
        actual = get_duration(final_path)
        print(f"[VideoComposer] 完成: {final_path}  (时长 {actual:.2f}s)")
        return final_path

    logger.error(f"[VideoComposer] 合成失败: {final_path}")
    return ""


def compose_dual_character_video(
    background_path: str,
    clip_a_path: str,
    clip_b_path: str,
    audio_a_path: str,
    audio_b_path: str,
    bgm_path: str = None,
    output_dir: str = "data/videos",
    output_name: str = None,
    portrait: bool = True,
    role_a_x: int = 0,
    role_a_y: int = 480,
    role_b_x: int = 540,
    role_b_y: int = 480,
    colorkey: bool = False,
    colorkey_color: str = "0x303030",
    colorkey_similarity: float = 0.25,
    colorkey_blend: float = 0.05,
    composite_a_path: str = None,
    composite_b_path: str = None,
    crf: int = 23,
    role_motion: bool = False,
    role_motion_px: int = 4,
) -> str:
    """
    双角色口型视频叠加到背景视频（竖屏 9:16）

    使用 FFmpeg filter_complex 实现：
    1. 背景视频循环对齐音频时长
    2. 角色通过 composite（预合成：身体PNG+头像）或 colorkey 或直接叠加
    3. 角色A音频 + 角色B音频顺序拼接（不重叠）
    4. 可选混入 BGM

    Args:
        background_path: 背景视频路径
        clip_a_path: SadTalker 输出的角色A口型视频（MP4）
        clip_b_path: SadTalker 输出的角色B口型视频（MP4）
        audio_a_path: 角色A的音频文件（已顺序拼接）
        audio_b_path: 角色B的音频文件（已顺序拼接）
        bgm_path: 背景音乐文件（可选）
        output_dir: 输出目录
        output_name: 输出文件名（不含扩展名）
        portrait: 是否竖屏（默认 True，1080x1920）
        role_a_x/y, role_b_x/y: 角色叠加位置
        colorkey: 是否对角色视频启用 colorkey 去背景
        colorkey_color: colorkey 颜色（默认 SadTalker 背景色 0x303030）
        colorkey_similarity: colorkey 相似度
        colorkey_blend: colorkey 混合值
        composite_a_path: 角色A的预合成图（GrabCut全身PNG + SadTalker头像叠加），直接叠加无需colorkey
        composite_b_path: 角色B的预合成图（同上）
        crf: 视频质量
        role_motion: 是否给最终角色层添加轻微漂浮动效
        role_motion_px: 角色上下浮动像素幅度

    Returns: 最终视频路径（成功） / 空字符串（失败）
    """
    os.makedirs(output_dir, exist_ok=True)

    for path, label in [(background_path, "背景视频"), (clip_a_path, "角色A视频"), (clip_b_path, "角色B视频")]:
        if not os.path.exists(path):
            logger.error(f"[VideoComposer] {label}不存在: {path}")
            return ""

    audio_a_dur = get_duration(audio_a_path)
    audio_b_dur = get_duration(audio_b_path)
    if audio_a_dur <= 0 or audio_b_dur <= 0:
        logger.error(
            f"[VideoComposer] 无法读取角色音频时长: audio_a={audio_a_path} ({audio_a_dur}s), "
            f"audio_b={audio_b_path} ({audio_b_dur}s)"
        )
        return ""

    # 音频滤镜使用 concat 顺序拼接 A/B，两段时长需要相加。
    total_dur = audio_a_dur + audio_b_dur

    if portrait:
        canvas_w, canvas_h = 1080, 1920
        role_w, role_h = 540, 960
    else:
        canvas_w, canvas_h = 1280, 720
        role_w, role_h = 320, 360

    bg_dur = get_duration(background_path)
    if bg_dur <= 0:
        logger.error(f"[VideoComposer] 无法读取背景视频时长: {background_path}")
        return ""
    repeat_count = max(1, int(total_dur / bg_dur) + 2)

    if not output_name:
        output_name = f"dual_portrait_{int(time.time() * 1000)}"
    final_path = os.path.join(output_dir, f"{output_name}.mp4")

    # composite 图：预合成的全身PNG+头像叠加，直接作为角色层
    use_composite_a = composite_a_path and os.path.exists(composite_a_path)
    use_composite_b = composite_b_path and os.path.exists(composite_b_path)
    use_composite = use_composite_a or use_composite_b

    ck_msg = f", colorkey={colorkey_color}" if colorkey else (" + composite" if use_composite else "")
    print(f"[VideoComposer] 竖屏合成: {canvas_w}x{canvas_h}, 背景循环 {repeat_count} 次, 时长 {total_dur:.2f}s{ck_msg}")

    # 构建 FFmpeg 命令（固定输入顺序）
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(repeat_count), "-i", background_path,  # [0]
        "-i", audio_a_path,   # [1]
        "-i", audio_b_path,   # [2]
    ]
    has_bgm = bgm_path and os.path.exists(bgm_path)
    if has_bgm:
        cmd.extend(["-i", bgm_path])  # [3] (optional)

    # composite PNG 用 -loop 1 确保连续帧；SadTalker 视频直接用
    if use_composite_a:
        _append_visual_input(cmd, composite_a_path)  # [4]
    else:
        cmd.extend(["-i", clip_a_path])  # [4]

    if use_composite_b:
        _append_visual_input(cmd, composite_b_path)  # [5]
    else:
        cmd.extend(["-i", clip_b_path])  # [5]

    # 动态索引：bg=0, audio_a=1, audio_b=2, bgm=3(if has), role_a=4(if no bgm), role_b=5(if no bgm)
    audio_a_idx, audio_b_idx = 1, 2
    bgm_idx = 3 if has_bgm else None
    role_a_idx = 3 + (1 if has_bgm else 0)
    role_b_idx = role_a_idx + 1

    # B 角色延迟（仅当 clip_b 是视频时生效，composite 图不需要延迟因为是静态全身）
    role_b_delay = "" if _is_image_file(clip_b_path) or use_composite_b else f"setpts=PTS+{audio_a_dur:.6f}/TB,"

    if role_motion and role_motion_px > 0:
        a_x = f"'{role_a_x}+2*sin(2*PI*t/5)'"
        a_y = f"'{role_a_y}+{role_motion_px}*sin(2*PI*t/3.8)'"
        b_x = f"'{role_b_x}+2*sin(2*PI*t/5+PI)'"
        b_y = f"'{role_b_y}+{role_motion_px}*sin(2*PI*t/4.2+PI)'"
    else:
        a_x, a_y = str(role_a_x), str(role_a_y)
        b_x, b_y = str(role_b_x), str(role_b_y)

    # 视频滤镜构建
    if use_composite_a:
        # 预合成图：直接缩放叠加（身体+头像已合并）
        role_a_filter = f"[{role_a_idx}:v]scale={role_w}:{role_h}[ra]"
        if use_composite_b:
            role_b_filter = f"[{role_b_idx}:v]{role_b_delay}scale={role_w}:{role_h}[rb]"
        else:
            role_b_filter = f"[{role_b_idx}:v]{role_b_delay}scale={role_w}:{role_h}[rb]"
        video_filter = (
            f"[0:v]scale={canvas_w}:{canvas_h}[bg];"
            f"{role_a_filter};"
            f"{role_b_filter};"
            f"[bg][ra]overlay=x={a_x}:y={a_y}[tmp1];"
            f"[tmp1][rb]overlay=x={b_x}:y={b_y}[outv]"
        )
    elif colorkey:
        role_a_filter = (
            f"[{role_a_idx}:v]colorkey={colorkey_color}:similarity={colorkey_similarity}:blend={colorkey_blend},"
            f"scale={role_w}:{role_h},format=rgba[ra]"
        )
        role_b_filter = (
            f"[{role_b_idx}:v]{role_b_delay}colorkey={colorkey_color}:similarity={colorkey_similarity}:blend={colorkey_blend},"
            f"scale={role_w}:{role_h},format=rgba[rb]"
        )
        video_filter = (
            f"[0:v]scale={canvas_w}:{canvas_h}[bg];"
            f"{role_a_filter};"
            f"{role_b_filter};"
            f"[bg][ra]overlay=x={a_x}:y={a_y}[tmp1];"
            f"[tmp1][rb]overlay=x={b_x}:y={b_y}[outv]"
        )
    else:
        video_filter = (
            f"[0:v]scale={canvas_w}:{canvas_h}[bg];"
            f"[{role_a_idx}:v]scale={role_w}:{role_h}[ra];"
            f"[{role_b_idx}:v]{role_b_delay}scale={role_w}:{role_h}[rb];"
            f"[bg][ra]overlay=x={a_x}:y={a_y}[tmp1];"
            f"[tmp1][rb]overlay=x={b_x}:y={b_y}[outv]"
        )

    # 音频滤镜
    if has_bgm:
        audio_filter = (
            f"[{audio_a_idx}:a][{audio_b_idx}:a]concat=n=2:v=0:a=1[a_diag];"
            f"[a_diag][{bgm_idx}:a]amix=inputs=2:duration=longest:weights=1 0.3[outa]"
        )
    else:
        audio_filter = f"[{audio_a_idx}:a][{audio_b_idx}:a]concat=n=2:v=0:a=1[outa]"

    cmd.extend([
        "-filter_complex", f"{video_filter};{audio_filter}",
        "-map", "[outv]", "-map", "[outa]",
    ])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(total_dur),
        final_path,
    ])

    if _run_ffmpeg(cmd):
        actual = get_duration(final_path)
        print(f"[VideoComposer] 完成: {final_path}  (时长 {actual:.2f}s)")
        return final_path

    logger.error(f"[VideoComposer] 合成失败: {final_path}")
    return ""


def compose_dual_character_sequence_video(
    background_path: str,
    role_a_sequence: str,
    role_b_sequence: str,
    audio_a_path: str,
    audio_b_path: str,
    bgm_path: str = None,
    output_dir: str = "data/videos",
    output_name: str = None,
    portrait: bool = True,
    role_a_x: int = 0,
    role_a_y: int = 480,
    role_b_x: int = 540,
    role_b_y: int = 480,
    crf: int = 23,
    active_speaker_timeline: list = None,
    active_scale: float = 1.05,
    active_brightness: float = 0.035,
    active_saturation: float = 1.08,
    active_y_offset: int = 18,
) -> str:
    """
    双角色 PNG 序列叠加到背景视频，输出最终合成视频。

    Args:
        background_path: 背景视频路径
        role_a_sequence: 角色A的PNG序列路径（包含 %06d.png）
        role_b_sequence: 角色B的PNG序列路径（包含 %06d.png）
        audio_a_path: 角色A的音频文件
        audio_b_path: 角色B的音频文件
        bgm_path: 背景音乐文件（可选）
        output_dir: 输出目录
        output_name: 输出文件名（不含扩展名）
        portrait: 是否竖屏（默认 True，1080x1920）
        role_a_x/y, role_b_x/y: 角色叠加位置
        crf: 视频质量
        active_speaker_timeline: 主动说话角色时间轴，示例 [("A", 0, 3.2), ("B", 3.2, 6.0)]
        active_scale: 说话角色放大倍率
        active_brightness: 说话角色亮度提升值
        active_saturation: 说话角色饱和度倍率
        active_y_offset: 说话角色额外上移像素

    Returns: 最终视频路径（成功） / 空字符串（失败）
    """
    os.makedirs(output_dir, exist_ok=True)

    audio_a_dur = get_duration(audio_a_path)
    audio_b_dur = get_duration(audio_b_path)
    if audio_a_dur <= 0 or audio_b_dur <= 0:
        logger.error(
            f"[VideoComposer] 无法读取角色音频时长: audio_a={audio_a_path} ({audio_a_dur}s), "
            f"audio_b={audio_b_path} ({audio_b_dur}s)"
        )
        return ""

    total_dur = audio_a_dur + audio_b_dur

    if portrait:
        canvas_w, canvas_h = 1080, 1920
        role_w, role_h = 540, 960
    else:
        canvas_w, canvas_h = 1280, 720
        role_w, role_h = 320, 360

    bg_dur = get_duration(background_path)
    if bg_dur <= 0:
        logger.error(f"[VideoComposer] 无法读取背景视频时长: {background_path}")
        return ""
    repeat_count = max(1, int(total_dur / bg_dur) + 2)

    if not output_name:
        output_name = f"dual_seq_{int(time.time() * 1000)}"
    final_path = os.path.join(output_dir, f"{output_name}.mp4")

    active_segments = _normalize_active_speaker_timeline(active_speaker_timeline, total_dur)
    has_active_speaker = bool(active_segments["a"] or active_segments["b"])
    active_msg = " + active speaker" if has_active_speaker else ""
    print(f"[VideoComposer] 序列合成: {canvas_w}x{canvas_h}, 背景循环 {repeat_count} 次, 时长 {total_dur:.2f}s{active_msg}")

    # PNG 序列天然带 alpha，直接用 -framerate 指定帧率
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(repeat_count), "-i", background_path,  # [0]
        "-framerate", "30", "-i", role_a_sequence,  # [1] PNG 序列
        "-framerate", "30", "-i", role_b_sequence,  # [2] PNG 序列
        "-i", audio_a_path,  # [3]
        "-i", audio_b_path,  # [4]
    ]
    has_bgm = bgm_path and os.path.exists(bgm_path)
    if has_bgm:
        cmd.extend(["-i", bgm_path])  # [5]

    if has_active_speaker:
        active_role_w = round(role_w * active_scale)
        active_role_h = round(role_h * active_scale)
        active_a_x = round(role_a_x - (active_role_w - role_w) / 2)
        active_b_x = round(role_b_x - (active_role_w - role_w) / 2)
        active_a_y = round(role_a_y - (active_role_h - role_h) / 2 - active_y_offset)
        active_b_y = round(role_b_y - (active_role_h - role_h) / 2 - active_y_offset)
        active_a_expr = _active_enable_expr(active_segments["a"])
        active_b_expr = _active_enable_expr(active_segments["b"])

        video_parts = [
            f"[0:v]scale={canvas_w}:{canvas_h}[bg]",
            f"[1:v]scale={role_w}:{role_h},format=rgba[ra_base]",
            f"[2:v]scale={role_w}:{role_h},format=rgba[rb_base]",
        ]
        if active_a_expr:
            video_parts.append(
                f"[1:v]scale={active_role_w}:{active_role_h},"
                f"eq=brightness={active_brightness}:saturation={active_saturation},format=rgba[ra_active]"
            )
        if active_b_expr:
            video_parts.append(
                f"[2:v]scale={active_role_w}:{active_role_h},"
                f"eq=brightness={active_brightness}:saturation={active_saturation},format=rgba[rb_active]"
            )

        current = "[bg]"
        step = 1

        def add_overlay(layer: str, x, y, enable: str = None) -> None:
            nonlocal current, step
            out = "[outv]" if layer.endswith("_last]") else f"[tmp_as_{step}]"
            clean_layer = layer.replace("_last", "")
            video_parts.append(_overlay_filter(current, clean_layer, x, y, out, enable))
            current = out
            step += 1

        add_overlay("[ra_base]", role_a_x, role_a_y, f"not({active_a_expr})" if active_a_expr else None)
        add_overlay("[rb_base]", role_b_x, role_b_y, f"not({active_b_expr})" if active_b_expr else None)
        if active_a_expr:
            add_overlay("[ra_active]", active_a_x, active_a_y, active_a_expr)
        if active_b_expr:
            add_overlay("[rb_active_last]", active_b_x, active_b_y, active_b_expr)
        else:
            video_parts[-1] = video_parts[-1].rsplit("[tmp_as_", 1)[0] + "[outv]"

        video_filter = ";".join(video_parts)
    else:
        video_filter = (
            f"[0:v]scale={canvas_w}:{canvas_h}[bg];"
            f"[1:v]scale={role_w}:{role_h}[ra];"
            f"[2:v]scale={role_w}:{role_h}[rb];"
            f"[bg][ra]overlay=x={role_a_x}:y={role_a_y}[tmp1];"
            f"[tmp1][rb]overlay=x={role_b_x}:y={role_b_y}[outv]"
        )

    # 音频滤镜
    if has_bgm:
        audio_filter = (
            f"[3:a][4:a]concat=n=2:v=0:a=1[a_diag];"
            f"[a_diag][5:a]amix=inputs=2:duration=longest:weights=1 0.3[outa]"
        )
    else:
        audio_filter = f"[3:a][4:a]concat=n=2:v=0:a=1[outa]"

    cmd.extend([
        "-filter_complex", f"{video_filter};{audio_filter}",
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(total_dur),
        "-pix_fmt", "yuv420p",
        final_path,
    ])

    if _run_ffmpeg(cmd):
        actual = get_duration(final_path)
        print(f"[VideoComposer] 完成: {final_path}  (时长 {actual:.2f}s)")
        return final_path

    logger.error(f"[VideoComposer] 合成失败: {final_path}")
    return ""


# ─── 快速测试 ────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python video_composer.py <视频片段> <配音音频> [输出目录]")
        sys.exit(1)

    clip = sys.argv[1]
    audio = sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "data/videos"

    final = compose_video(clip, audio, output_dir=out_dir)
    if final:
        print(f"\nSUCCESS: {final}")
    else:
        print("\nFAILED")
        sys.exit(1)
