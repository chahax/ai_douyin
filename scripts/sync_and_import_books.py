import shutil
from pathlib import Path

from src.rag_engine.knowledge_importer import KnowledgeImporter
from src.shared.config import settings
from src.shared.logger import logger


def sync_books(source_dir: Path, target_dir: Path) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    supported = {".txt", ".epub", ".pdf"}

    for src in source_dir.glob("*"):
        if not src.is_file() or src.suffix.lower() not in supported:
            continue

        dst = target_dir / src.name

        # 如果目标不存在，或者源文件更新，则覆盖
        if (not dst.exists()) or (src.stat().st_mtime > dst.stat().st_mtime):
            shutil.copy2(src, dst)
            copied += 1
            logger.info(f"Synced: {src.name}")

    return copied


def main() -> None:
    source = Path("C:/data/books")
    target = Path(settings.BOOKS_DIR).resolve()

    if not source.exists():
        logger.warning(f"Source books dir not found: {source}")
    else:
        count = sync_books(source, target)
        logger.info(f"Sync completed. copied={count}")

    importer = KnowledgeImporter()
    importer.import_books(str(target))


if __name__ == "__main__":
    main()
