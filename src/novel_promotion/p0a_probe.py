"""
P0-A: 番茄回填可行性现场调查探针

安全设计：
- 默认只读：不填假 URL、不点击提交、不实现真实提交
- 按表头名解析且兼容新旧 URL
- 证据自动脱敏：别名/书名/账号 → 脱敏值，仅保留状态、结构和稳定哈希
- 不使用 deprecated utcnow

核心结论（基于现有 list 页数据）：
- 4 条记录中 3 条强制失效、1 条审核不通过
- 均未填写（fill_status="未填写"）且无可点击回填入口
- 结论只能是 partially_verified；没有真实成功回填证据时绝不能 verified
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ── Known column headers for the promotion list table ──────────────────────────

# Current URL for the promotion list page
PROMOTION_LIST_URL = "https://kol.fanqieopen.com/page/promotion-list?tab_type=2&top_tab_genre=-1"

# Real 11-column table (Chinese headers as rendered in the browser DOM)
REAL_CHINESE_HEADERS = [
    "关键词",     # keyword / alias
    "书本信息",   # combined: book_name + book_id (must extract)
    "体裁",       # content_type (genre)
    "发文类型",   # publish_type
    "别名状态",   # alias_status
    "书籍状态",   # book_status
    "发文详情",   # fill detail — may contain URL or "未填写"
    "创建时间",   # created_at
    "有效期",     # valid_range
    "结算截止日", # settlement deadline (not used in P0-A)
    "操作",       # action buttons (not used in P0-A)
]

# English → Chinese header mapping (for current idealized dicts)
CURRENT_HEADERS = [
    "alias",           # 关键词
    "book_name",       # 书本信息 → book_name
    "book_id",         # 书本信息 → book_id  (extracted)
    "content_type",    # 体裁
    "publish_type",    # 发文类型
    "alias_status",    # 别名状态
    "book_status",     # 书籍状态
    "fill_status",     # 发文详情
    "has_fill_link",   # ← derived from 发文详情 cell metadata
    "created_at",      # 创建时间
    "valid_range",     # 有效期
]

# Legacy column names (aliased to current English)
LEGACY_HEADER_ALIASES = {
    "promotion_alias": "alias",
    "novel_name": "book_name",
    "novel_id": "book_id",
    "content": "content_type",
    "pub_type": "publish_type",
    "task_status": "alias_status",
    "novel_status": "book_status",
    "fill_url": "fill_status",
    "has_link": "has_fill_link",
    "apply_time": "created_at",
    "date_range": "valid_range",
    # Real Chinese headers → current English
    "关键词": "alias",
    "书本信息": "combined_book_info",  # special: needs parsing
    "体裁": "content_type",
    "发文类型": "publish_type",
    "别名状态": "alias_status",
    "书籍状态": "book_status",
    "发文详情": "fill_status",
    "创建时间": "created_at",
    "有效期": "valid_range",
    "结算截止日": "settlement_deadline",  # ignored
    "操作": "action_buttons",  # ignored
}

REQUIRED_COLUMNS = {"alias"}

# Legacy URLs (retained for backward compatibility)
LEGACY_PROMOTION_LIST_URLS = [
    "https://kol.fanqieopen.com/page/content?tab_type=2",
    "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1",
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def desensitize_text(text: str, kind: str = "alias") -> str:
    """Replace sensitive content with a stable hash-based placeholder.

    Args:
        text: The original text to desensitize.
        kind: Category for the placeholder prefix (alias, book_name, account).

    Returns:
        A desensitized placeholder like '<alias_a1b2c3>' or the original
        structural flag if it's a known status keyword.
    """
    if not text:
        return ""
    # Known status keywords that aren't sensitive
    if text in ("未填写", "生效中", "审核中", "审核不通过", "已失效",
                 "active", "under_review", "rejected", "expired"):
        return text
    # URLs are structural info, not personal data — but we still
    # desensitize them to be safe in case they contain tokens
    if text.startswith("http://") or text.startswith("https://"):
        h = hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"<url_{h}>"
    h = hashlib.sha256(text.encode()).hexdigest()[:6]
    return f"<{kind}_{h}>"


@dataclass
class FieldEvidence:
    """One row of desensitized field investigation evidence."""
    row_index: int
    alias: str              # desensitized
    book_name: str          # desensitized
    book_id_hash: str       # stable hash of book_id
    content_type: str       # structural
    publish_type: str       # structural
    alias_status: str       # structural (生效中/审核中/审核不通过/已失效)
    book_status: str        # structural
    fill_status: str        # "未填写" or desensitized URL "<url_...>"
    has_fill_link: bool     # whether there's a clickable "回填发文" link
    created_at: str         # structural (table column text)
    valid_range: str        # structural
    internal_status: str    # mapped: active/under_review/rejected/expired/unknown


@dataclass
class P0AReport:
    """P0-A field investigation report."""
    timestamp: str = field(default_factory=_now_utc)
    source_url: str = PROMOTION_LIST_URL
    total_scanned: int = 0
    entries: list[FieldEvidence] = field(default_factory=list)
    conclusion: str = "pending"
    conclusion_reason: str = ""
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "source_url": self.source_url,
            "total_scanned": self.total_scanned,
            "entries": [
                {
                    "row_index": e.row_index,
                    "alias": e.alias,
                    "book_name": e.book_name,
                    "book_id_hash": e.book_id_hash,
                    "content_type": e.content_type,
                    "publish_type": e.publish_type,
                    "alias_status": e.alias_status,
                    "book_status": e.book_status,
                    "fill_status": e.fill_status,
                    "has_fill_link": e.has_fill_link,
                    "created_at": e.created_at,
                    "valid_range": e.valid_range,
                    "internal_status": e.internal_status,
                }
                for e in self.entries
            ],
            "conclusion": self.conclusion,
            "conclusion_reason": self.conclusion_reason,
            "constraints": self.constraints,
        }


# Known alias statuses from the list page
ALIAS_STATUS_MAP = {
    "生效中": "active",
    "审核中": "under_review",
    "审核不通过": "rejected",
    "已失效": "expired",
}


def _normalize_headers(raw: dict) -> dict:
    """Map legacy and Chinese header names to current English header names.

    Handles:
    - Legacy English aliases (e.g. ``promotion_alias`` → ``alias``)
    - Real Chinese 11-column headers (e.g. ``关键词`` → ``alias``)
    - Combined ``书本信息`` column: parses book_name and book_id

    Returns a dict with only known current headers.
    Raises ValueError if required columns are missing.
    """
    result = {}
    for key, value in raw.items():
        # Step 1: Map to English target (Chinese → English, legacy → current)
        english = LEGACY_HEADER_ALIASES.get(key, key)

        # Skip non-P0-A columns
        if english in ("settlement_deadline", "action_buttons"):
            continue

        # Handle combined 书本信息 cell
        if english == "combined_book_info":
            book_name, book_id = _parse_combined_book_info(str(value) if value else "")
            result["book_name"] = book_name
            result["book_id"] = book_id
            continue

        # If English key is a known current header, store it
        if english in CURRENT_HEADERS:
            result[english] = value
        elif key in CURRENT_HEADERS:
            # Already an English header, keep it directly
            result[key] = value
        # else: unknown header — silently ignored

    # Check required columns — only when we have any data
    if result:
        missing = REQUIRED_COLUMNS - set(result.keys())
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    return result


def _parse_combined_book_info(cell_text: str) -> tuple[str, str]:
    """Extract book_name and book_id from a combined ``书本信息`` cell.

    Common formats:
    - ``"书名 (ID: 7577735918904151065)"``
    - ``"书名 7577735918904151065"``
    - Just a book name (no ID embedded)

    Returns ``(book_name, book_id)`` tuple.
    """
    import re
    if not cell_text:
        return "", ""
    # Pattern: "Name (ID: digits)" or "Name digits"
    m = re.match(r'^(.+?)\s*[\(（]\s*ID\s*[:：]\s*(\d{10,24})\s*[\)）]\s*$', cell_text)
    if m:
        return m.group(1).strip(), m.group(2)
    # Pattern: trailing digits at end
    m2 = re.match(r'^(.+?)\s+(\d{10,24})\s*$', cell_text)
    if m2:
        return m2.group(1).strip(), m2.group(2)
    # No ID found — return text as name, empty ID
    return cell_text.strip(), ""


def parse_row(row: dict, row_index: int) -> FieldEvidence:
    """Parse a single row dict into a desensitized FieldEvidence.

    Uses header-name-driven parsing:
    - Maps legacy/Chinese keys to current English names
    - Handles the real 11-Chinese-column contract (关键词, 书本信息, 体裁, …)
    - Extracts book_name/book_id from combined 书本信息 cell
    - Derives fill_status / has_fill_link from 发文详情 cell
    - Handles missing fields gracefully

    Raises ValueError for missing required columns (e.g. 别名, 书本信息).
    """
    # First pass: normalize headers (handles Chinese + legacy English)
    item = _normalize_headers(row)
    book_id = str(item.get("book_id", "")) if item.get("book_id") else ""

    # Derive fill_status + has_fill_link from 发文详情 cell or English "fill_status"
    fill_detail = item.get("fill_status", "")
    fill_status_raw = str(fill_detail) if fill_detail else ""
    has_fill_link = False

    # 发文详情 may carry metadata indicating a clickable 回填 link
    if isinstance(fill_detail, dict):
        fill_status_raw = str(fill_detail.get("text", "")) if fill_detail.get("text") else "未填写"
        has_fill_link = bool(fill_detail.get("has_fill_link", False))
    elif isinstance(fill_detail, str):
        has_fill_link = bool(item.get("has_fill_link", False))

    # Always desensitize fill_status if it looks like a URL — never leak
    if not fill_status_raw or "未填写" in fill_status_raw:
        fill_status = "未填写"
    elif fill_status_raw.startswith("http://") or fill_status_raw.startswith("https://"):
        fill_status = desensitize_text(fill_status_raw, "url")
    else:
        # Unknown non-empty value — desensitize
        fill_status = desensitize_text(fill_status_raw, "fill")

    return FieldEvidence(
        row_index=row_index,
        alias=desensitize_text(str(item.get("alias", "")), "alias"),
        book_name=desensitize_text(str(item.get("book_name", "")), "book_name"),
        book_id_hash=hashlib.sha256(
            (book_id or "").encode()
        ).hexdigest()[:12] if book_id else "",
        content_type=str(item.get("content_type", "")),
        publish_type=str(item.get("publish_type", "")),
        alias_status=str(item.get("alias_status", "")),
        book_status=str(item.get("book_status", "")),
        fill_status=fill_status,
        has_fill_link=has_fill_link,
        created_at=str(item.get("created_at", "")),
        valid_range=str(item.get("valid_range", "")),
        internal_status=ALIAS_STATUS_MAP.get(
            str(item.get("alias_status", "")), "unknown"
        ),
    )


def parse_list_items(raw_items: list[dict]) -> P0AReport:
    """Parse and desensitize raw promotion list items using header-driven parsing.

    This is the core probe logic. It takes raw output from the promotion list page
    and produces a desensitized evidence report.

    Args:
        raw_items: List of dicts from the promotion list page.

    Returns:
        P0AReport with desensitized evidence.
    """
    report = P0AReport()
    report.total_scanned = len(raw_items)

    for i, item in enumerate(raw_items):
        evidence = parse_row(item, i)
        report.entries.append(evidence)

    # Determine conclusion
    active_count = sum(1 for e in report.entries if e.internal_status == "active")
    has_any_fill_link = any(e.has_fill_link for e in report.entries)
    has_any_filled = any(
        e.fill_status and "未填写" not in (e.fill_status or "")
        for e in report.entries
    )

    report.constraints = [
        "P0-A 是只读探针：不填假 URL、不点击提交、不实现真实提交",
        "证据已自动脱敏：别名/书名 → <kind_hash>，book_id → SHA-256 前 12 位",
        "URL fill_status 脱敏为 <url_hash> 防止泄露",
        "仅保留状态、结构信息和稳定哈希",
        "结论基于 header-name 驱动的表头解析，兼容当前 11 列与旧列名",
    ]

    # No active tasks AND no fill link → partially_verified
    if active_count == 0 and not has_any_fill_link:
        report.conclusion = "partially_verified"
        report.conclusion_reason = (
            f"扫描 {report.total_scanned} 条记录：无 active 状态任务，"
            f"无可点击回填入口（has_fill_link=0），"
            f"均未填写（fill_status='未填写'）。"
            f"回填入口的存在性未得到正面确认，只能在有新 active 任务时重新验证。"
        )
    elif active_count > 0 and not has_any_fill_link:
        report.conclusion = "partially_verified"
        report.conclusion_reason = (
            f"有 {active_count} 条 active 任务但不显示回填入口。"
            f"需要操作人手动验证页面是否支持回填。"
        )
    elif has_any_fill_link and has_any_filled:
        # We see both a link AND a filled value → entry_observed, not verified
        report.conclusion = "partially_verified"
        report.conclusion_reason = (
            f"观察到回填入口和已填写值，但无真实成功提交证据。"
            f"回填功能存在性为 entry_observed，需通过实际 active 任务 + 真实作品 URL 验证。"
        )
    elif has_any_fill_link and not has_any_filled:
        report.conclusion = "partially_verified"
        report.conclusion_reason = (
            f"观察到回填入口但所有记录均未填写。"
            f"回填功能存在性为 entry_observed，需通过实际 active 任务验证提交。"
        )
    else:
        report.conclusion = "partially_verified"
        report.conclusion_reason = "数据不足以得出明确结论。"

    return report


def run_probe_from_raw_data(raw_items: list[dict]) -> str:
    """Run the probe and return JSON report string.

    Use this as the P0-A entry point. It only reads data, never writes.
    """
    report = parse_list_items(raw_items)
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def parse_table(headers: list[str], rows: list[list[str]]) -> str:
    """Table contract entry point accepting headers + row cell arrays.

    Maps cells by actual Chinese header names, tolerates reordering,
    and rejects missing required headers. Reuses ``parse_row`` after
    mapping each row to a dict keyed by English header names.

    Args:
        headers: List of Chinese column header strings (e.g. ``["关键词", "书本信息", …]``).
        rows: List of rows, each a list of cell strings in the same order as headers.

    Returns:
        JSON string of the P0AReport (conclusion always partially_verified).
    """
    # Validate required headers
    from .p0a_probe import REAL_CHINESE_HEADERS
    missing = sorted(REQUIRED_COLUMNS_CN - set(headers))
    if missing:
        report = P0AReport()
        report.conclusion = "partially_verified"
        report.conclusion_reason = f"Missing required headers: {', '.join(missing)}"
        report.constraints = [
            "Cannot parse table without required Chinese column headers.",
        ]
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)

    # Build Chinese → index map
    header_index = {h: i for i, h in enumerate(headers)}

    raw_items = []
    for row in rows:
        item = {}
        # Map Chinese headers → English dict for parse_row
        cn_to_en = {
            "关键词": "alias",
            "体裁": "content_type",
            "发文类型": "publish_type",
            "别名状态": "alias_status",
            "书籍状态": "book_status",
            "创建时间": "created_at",
            "有效期": "valid_range",
        }
        for cn_key, en_key in cn_to_en.items():
            if cn_key in header_index:
                idx = header_index[cn_key]
                if idx < len(row):
                    item[en_key] = row[idx]

        # Handle combined 书本信息 separately
        book_info_idx = header_index.get("书本信息")
        if book_info_idx is not None and book_info_idx < len(row):
            book_name, book_id = _parse_combined_book_info(str(row[book_info_idx]))
            item["book_name"] = book_name
            item["book_id"] = book_id

        # Handle 发文详情
        fill_idx = header_index.get("发文详情")
        if fill_idx is not None and fill_idx < len(row):
            item["fill_status"] = str(row[fill_idx]) if row[fill_idx] else "未填写"
        else:
            item["fill_status"] = "未填写"

        if item.get("alias"):
            raw_items.append(item)

    report = parse_list_items(raw_items)
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


# Chinese header names required for table contract
REQUIRED_COLUMNS_CN = {"关键词", "别名状态"}
