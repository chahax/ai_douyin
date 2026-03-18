import os
import re
import shutil
from datetime import datetime
from src.shared.logger import logger


def _slugify_topic(topic: str) -> str:
    base = (topic or "").strip()
    if not base:
        return "untitled"
    base = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9_]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        return "untitled"
    return base[:20]


def _build_unique_path(output_dir: str, base_name: str, ext: str) -> str:
    candidate = os.path.join(output_dir, f"{base_name}{ext}")
    if not os.path.exists(candidate):
        return candidate
    index = 1
    while True:
        candidate = os.path.join(output_dir, f"{base_name}_{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1


def finalize_output(source_path: str, output_dir: str = None, topic: str = "", provider: str = "", keep_temp: bool = False) -> str:
    if not source_path:
        return None
    source_abs = os.path.abspath(source_path)
    if not os.path.exists(source_abs):
        logger.error(f"Source output not found: {source_abs}")
        return None
    if not output_dir:
        return source_abs

    target_dir = os.path.abspath(output_dir)
    os.makedirs(target_dir, exist_ok=True)

    _, ext = os.path.splitext(source_abs)
    if not ext:
        ext = ".mp3"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify_topic(topic)
    provider_name = (provider or "tts").strip() or "tts"
    file_base = f"{timestamp}_{slug}_{provider_name}"
    target_abs = _build_unique_path(target_dir, file_base, ext)

    if keep_temp:
        shutil.copy2(source_abs, target_abs)
        logger.info(f"Output copied to archive: {target_abs}")
        return target_abs

    try:
        shutil.move(source_abs, target_abs)
        logger.info(f"Output moved to archive: {target_abs}")
        return target_abs
    except Exception as e:
        logger.warning(f"Move failed: {e}. Falling back to copy.")
        try:
            shutil.copy2(source_abs, target_abs)
            logger.info(f"Output copied to archive: {target_abs}")
            return target_abs
        except Exception as copy_err:
            logger.error(f"Copy fallback failed: {copy_err}")
            return source_abs
