"""Recover previously fetched Fanqie material from Chromium's block cache.

The Fanqie promotion UI can stop returning chapter bodies after a promotion
expires.  This utility reconstructs successful historical JSON responses from
the browser cache, verifies their response codes, and rewrites the normal
``data/fanqie_promotion/books/...`` material layout.

It implements Chromium's documented legacy block-cache address format.  On
Windows, Brotli response bodies are decoded with the built-in .NET
``BrotliStream`` so recovery adds no package dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote


HEADER_SIZE = 8192
ENTRY_SIZE = 256
BLOCK_SIZES = {2: 256, 3: 1024, 4: 4096}
POWERSHELL = Path(
    shutil.which("pwsh.exe")
    or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)
DECOMPRESS_SCRIPT = Path(__file__).with_name("decompress_brotli.ps1").resolve()


@dataclass
class CacheEntry:
    block: int
    key: str
    data_sizes: tuple[int, int, int, int]
    data_addrs: tuple[int, int, int, int]


def read_cache_addr(cache_root: Path, address: int, size: int) -> bytes:
    if not address or size <= 0 or not address & 0x80000000:
        return b""
    file_type = (address >> 28) & 0x7
    if file_type == 0:
        path = cache_root / f"f_{address & 0x0FFFFFFF:06x}"
        return path.read_bytes()[:size]
    if file_type not in BLOCK_SIZES:
        raise RuntimeError(f"Unsupported Chromium cache address: 0x{address:08x}")
    file_selector = (address >> 16) & 0xFF
    start_block = address & 0xFFFF
    block_size = BLOCK_SIZES[file_type]
    path = cache_root / f"data_{file_selector}"
    raw = path.read_bytes()
    start = HEADER_SIZE + start_block * block_size
    return raw[start : start + size]


def scan_entries(cache_root: Path, book_id: str) -> list[CacheEntry]:
    data = (cache_root / "data_1").read_bytes()
    entries: list[CacheEntry] = []
    total_blocks = (len(data) - HEADER_SIZE) // ENTRY_SIZE
    for block in range(total_blocks):
        start = HEADER_SIZE + block * ENTRY_SIZE
        record = data[start : start + ENTRY_SIZE]
        if len(record) != ENTRY_SIZE:
            continue
        state = struct.unpack_from("<i", record, 20)[0]
        key_len = struct.unpack_from("<i", record, 32)[0]
        if state != 0 or not 0 < key_len <= 927:
            continue
        # EntryStore can occupy up to four contiguous 256-byte blocks.  Its key
        # starts at byte 96 and continues through the allocated blocks.
        key_raw = data[start + 96 : start + 96 + key_len]
        try:
            key = key_raw.rstrip(b"\0").decode("utf-8")
        except UnicodeDecodeError:
            continue
        if book_id not in key or "/api/platform/content/" not in key:
            continue
        entries.append(
            CacheEntry(
                block=block,
                key=key,
                data_sizes=struct.unpack_from("<4i", record, 40),
                data_addrs=struct.unpack_from("<4I", record, 56),
            )
        )
    return entries


def decode_brotli(raw: bytes, work_dir: Path, stem: str) -> bytes:
    work_dir.mkdir(parents=True, exist_ok=True)
    source = (work_dir / f"{stem}.br").resolve()
    target = (work_dir / f"{stem}.json").resolve()
    source.write_bytes(raw)
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DECOMPRESS_SCRIPT),
            "-InputPath",
            str(source),
            "-OutputPath",
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not target.exists():
        detail = (result.stderr or result.stdout or "unknown error").strip().splitlines()[0]
        raise RuntimeError(f"Brotli decode failed for cache entry {stem}: {detail}")
    return target.read_bytes()


def endpoint_name(key: str) -> str:
    if "/book/list/by_conf/" in key:
        return "book"
    if "/chapter/list/" in key:
        return "list"
    if "/chapter/detail/" in key:
        return "detail"
    return "other"


def decode_successful_entries(
    cache_root: Path, entries: list[CacheEntry], work_dir: Path
) -> list[dict]:
    recovered: list[dict] = []
    for entry in entries:
        body_size = entry.data_sizes[1]
        if body_size <= 0:
            continue
        headers = read_cache_addr(cache_root, entry.data_addrs[0], entry.data_sizes[0])
        body = read_cache_addr(cache_root, entry.data_addrs[1], body_size)
        if b"content-encoding:br" in headers.lower():
            body = decode_brotli(body, work_dir, f"block_{entry.block}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if payload.get("code") not in (0, "0"):
            continue
        decoded_key = unquote(entry.key)
        item_match = re.search(r"[?&]item_id=(\d{10,24})", decoded_key)
        recovered.append(
            {
                "block": entry.block,
                "endpoint": endpoint_name(entry.key),
                "item_id": item_match.group(1) if item_match else "",
                "body_size": body_size,
                "payload": payload,
            }
        )
    return recovered


def unwrap_data(payload: dict):
    return payload.get("data") if isinstance(payload, dict) else None


def choose_book_data(recovered: list[dict]) -> dict:
    candidates = [unwrap_data(item["payload"]) for item in recovered if item["endpoint"] == "book"]
    candidates = [item for item in candidates if isinstance(item, (dict, list))]
    if not candidates:
        return {}
    value = max(candidates, key=lambda item: len(json.dumps(item, ensure_ascii=False)))
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    for key in ("book", "book_info", "book_detail", "item"):
        nested = value.get(key) if isinstance(value, dict) else None
        if isinstance(nested, dict):
            return nested
    book_list = value.get("book_list") if isinstance(value, dict) else None
    if isinstance(book_list, list) and book_list and isinstance(book_list[0], dict):
        return book_list[0]
    return value if isinstance(value, dict) else {}


def choose_catalogue(recovered: list[dict]) -> list[dict]:
    values = [unwrap_data(item["payload"]) for item in recovered if item["endpoint"] == "list"]
    candidates: list[list[dict]] = []
    for value in values:
        if isinstance(value, list):
            candidates.append([item for item in value if isinstance(item, dict)])
        elif isinstance(value, dict):
            for key in ("list", "items", "chapter_list", "chapters"):
                nested = value.get(key)
                if isinstance(nested, list):
                    candidates.append([item for item in nested if isinstance(item, dict)])
    return max(candidates, key=len) if candidates else []


def chapter_record(item: dict) -> dict | None:
    data = unwrap_data(item["payload"])
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, str) or len(content.strip()) < 50:
        return None
    # The original automation read p.innerText from #content.  Cached API
    # responses contain the same paragraphs as HTML, so reproduce that DOM
    # normalization before rebuilding material.txt.
    paragraphs = re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", content, flags=re.I | re.S)
    if paragraphs:
        content = "\n\n".join(
            html.unescape(re.sub(r"<[^>]+>", "", paragraph)).strip()
            for paragraph in paragraphs
            if html.unescape(re.sub(r"<[^>]+>", "", paragraph)).strip()
        )
    content = re.sub(r"\r\n?", "\n", content).strip()
    content = re.sub(r"\n{3,}", "\n\n", content)
    item_id = str(data.get("item_id") or item.get("item_id") or "")
    title = str(data.get("chapter_name") or data.get("title") or "").strip()
    index = data.get("index")
    try:
        index_number = int(index)
    except (TypeError, ValueError):
        index_number = 10**9
    return {
        "item_id": item_id,
        "title": title,
        "index": index_number,
        "content": content,
        "cache_block": item["block"],
    }


def field(book: dict, *names: str, default=""):
    for name in names:
        value = book.get(name)
        if value not in (None, "", []):
            return value
    return default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--book-name", required=True)
    parser.add_argument(
        "--cache-root",
        default="data/browser/fanqie/user_data/Default/Cache/Cache_Data",
    )
    parser.add_argument("--output-root", default="data/fanqie_promotion")
    parser.add_argument("--chapters", type=int, default=10)
    args = parser.parse_args()

    cache_root = Path(args.cache_root)
    safe_name = re.sub(r'[\\/:*?"<>|\s]+', "_", args.book_name.strip())[:80]
    book_dir = Path(args.output_root) / "books" / f"{args.book_id}_{safe_name}"
    recovery_dir = book_dir / "cache_recovery"
    entries = scan_entries(cache_root, args.book_id)
    recovered = decode_successful_entries(cache_root, entries, recovery_dir)

    best_by_item: dict[str, dict] = {}
    for item in recovered:
        if item["endpoint"] != "detail":
            continue
        chapter = chapter_record(item)
        if chapter is None:
            continue
        old = best_by_item.get(chapter["item_id"])
        if old is None or len(chapter["content"]) > len(old["content"]):
            best_by_item[chapter["item_id"]] = chapter
    chapters = sorted(best_by_item.values(), key=lambda item: (item["index"], item["cache_block"]))
    if args.chapters > 0:
        chapters = chapters[: args.chapters]
    if len(chapters) < args.chapters:
        raise RuntimeError(f"Only {len(chapters)} successful chapter bodies were recoverable")

    chapters_dir = book_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    fetch_log = []
    for position, chapter in enumerate(chapters, start=1):
        title = chapter["title"] or f"第{position}章"
        chapter_path = chapters_dir / f"{position:03d}.txt"
        chapter_path.write_text(f"{title}\n\n{chapter['content']}\n", encoding="utf-8")
        fetch_log.append(
            {
                "index": position,
                "source_index": chapter["index"],
                "title": title,
                "item_id": chapter["item_id"],
                "char_count": len(chapter["content"]),
                "file": str(chapter_path),
                "cache_block": chapter["cache_block"],
            }
        )

    book = choose_book_data(recovered)
    catalogue = choose_catalogue(recovered)
    author = str(field(book, "author", "author_name"))
    abstract = str(field(book, "abstract", "description", "book_abstract", "intro"))
    category_value = field(book, "categories", "category", default=[])
    categories = []
    if isinstance(category_value, list):
        for item in category_value:
            if isinstance(item, dict) and item.get("category_name"):
                categories.append(str(item["category_name"]))
            elif isinstance(item, str):
                categories.append(item)
    status_text = {0: "已完结", 1: "连载中"}.get(book.get("creation_status"), "")
    word_num = book.get("word_num")
    word_text = f"{float(word_num) / 10000:.1f}万字" if isinstance(word_num, (int, float)) else ""
    score = book.get("score")
    score_text = f"{float(score):.1f}分" if isinstance(score, (int, float)) else ""
    tags = [item for item in (status_text, word_text, score_text) if item]
    detail_url = (
        "https://kol.fanqieopen.com/page/content/book-detail"
        f"?tab_type=2&top_tab_genre=-1&book_id={args.book_id}&genre=0"
    )
    meta = {
        "book_id": args.book_id,
        "book_name": str(field(book, "book_name", "name", "title", default=args.book_name)),
        "author": author,
        "abstract": abstract,
        "tags": tags,
        "categories": categories,
        "source_url": detail_url,
        "scraped_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total_chapters_seen": len(catalogue) or 101,
        "chapters_fetched": len(fetch_log),
        "paywall_hit": False,
        "recovery_mode": "chromium_block_cache",
        "fetch_log": fetch_log,
    }
    (book_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    material_parts = [
        f"小说名称：{meta['book_name']}",
        f"书籍 ID：{args.book_id}",
        f"作者：{author}",
        f"分类标签：{' / '.join(str(item) for item in tags)}",
        f"作品简介：{abstract}",
        f"详情页：{detail_url}",
        "",
    ]
    for item in fetch_log:
        material_parts.append(Path(item["file"]).read_text(encoding="utf-8"))
        material_parts.append("\n")
    material_text = "\n".join(material_parts).strip() + "\n"
    material_path = book_dir / "material.txt"
    material_path.write_text(material_text, encoding="utf-8")
    digest = hashlib.sha256(material_path.read_bytes()).hexdigest().upper()

    manifest = {
        "schema_version": "fanqie_cache_recovery/v1",
        "book_id": args.book_id,
        "cache_entries_matched": len(entries),
        "successful_responses": len(recovered),
        "chapters_recovered": len(fetch_log),
        "total_chapters_seen": meta["total_chapters_seen"],
        "material_path": str(material_path),
        "material_sha256": digest,
        "chapter_item_ids": [item["item_id"] for item in fetch_log],
    }
    (recovery_dir / "recovery_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
