"""Local-only novel selection from an immutable account opportunity snapshot.

Discovery is deliberately not authorization. No model, browser or platform call
is performed here; every selected source must carry explicit text-use evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.domain.novel import NovelPromotionStrategy

_GENERIC = {"小说", "小说推文", "推文", "小说推广", "阅读", "书荒", "番茄小说"}
_CHAPTER = re.compile(r"(?m)^第[0-9零一二三四五六七八九十百千万两]+[章节回卷][^\r\n]*")


def _snapshot(value: Any) -> dict:
    if is_dataclass(value):
        return copy.deepcopy(asdict(value))
    if isinstance(value, dict):
        return copy.deepcopy(value)
    raise ValueError("account and opportunity must be dataclasses or mappings")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict:
    return _json_bytes(path.read_bytes(), path)


def _json_bytes(raw: bytes, path: Path) -> dict:
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _path(raw: Any, parent: Path) -> Path:
    value = Path(str(raw))
    return (value if value.is_absolute() else parent / value).resolve()


def discover_books(books_root: Path) -> list[dict]:
    """Read native ``meta.json`` books; retain unavailable candidates as evidence."""
    root = Path(books_root).resolve()
    if not root.exists():
        return []
    books = []
    for metadata_path in sorted(root.rglob("meta.json")):
        candidate = {"metadata_path": str(metadata_path.resolve()),
                     "material_path": str((metadata_path.parent / "material.txt").resolve()),
                     "authorization": None}
        try:
            metadata_raw = metadata_path.read_bytes()
            metadata = _json_bytes(metadata_raw, metadata_path)
            candidate.update(book_id=str(metadata.get("book_id", "")),
                             book_name=str(metadata.get("book_name", "")),
                             metadata_sha256=_sha(metadata_raw))
            if metadata.get("material_path"):
                candidate["material_path"] = str(_path(metadata["material_path"], metadata_path.parent))
            material = Path(candidate["material_path"])
            if material.is_file():
                candidate["source_sha256"] = _sha(material.read_bytes())
            authorization_path = metadata_path.parent / "text_authorization.json"
            if authorization_path.exists():
                candidate["authorization_path"] = str(authorization_path.resolve())
                authorization_raw = authorization_path.read_bytes()
                candidate["authorization_sha256"] = _sha(authorization_raw)
                candidate["authorization"] = _json_bytes(authorization_raw, authorization_path)
        except (ValueError, OSError) as exc:
            candidate["discovery_error"] = str(exc)
        books.append(candidate)
    return books


def _instant(value: Any, name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include timezone")
    return parsed.astimezone(timezone.utc)


def _validate_context(account: dict, opportunity: dict, now: Any) -> dict:
    if type(account.get("profile_version")) is not int or type(opportunity.get("profile_version")) is not int:
        raise ValueError("profile_version must be an integer")
    try:
        profile = AccountProfile(**account)
        config = NovelPromotionStrategy().validate_profile(profile)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid novel account: {exc}") from exc
    if profile.status != "active":
        raise ValueError("novel account is not active")
    for key in ("account_uuid", "account_key", "profile_version", "domain_strategy_id", "strategy_version"):
        if opportunity.get(key) != account.get(key):
            raise ValueError(f"opportunity {key} does not match account snapshot")
    if not str(opportunity.get("opportunity_id", "")).strip():
        raise ValueError("missing opportunity_id")
    if opportunity.get("status") not in {"candidate", "approved"}:
        raise ValueError("opportunity is rejected, expired, used or unavailable")
    start = _instant(opportunity.get("valid_from"), "valid_from")
    end = _instant(opportunity.get("valid_until"), "valid_until")
    current = _instant(now if now is not None else datetime.now(timezone.utc), "now")
    if end <= start or current < start or current >= end:
        raise ValueError("opportunity is future, expired or has invalid validity range")
    return config


def _terms(values: Any, *, drop_generic: bool = True) -> list[str]:
    if isinstance(values, str):
        values = [values]
    result = []
    for raw in values or []:
        text = str(raw).strip().casefold()
        if text and (not drop_generic or text not in _GENERIC) and text not in result:
            result.append(text)
    return result


def _body(text: str, metadata: dict) -> tuple[str, dict, list[dict]]:
    """Strip only recognized collector preambles; never infer arbitrary prose."""
    collector_format = text.lstrip("\ufeff").startswith("小说名称：") and "作品简介：" in text
    search_start = 0
    if collector_format:
        footer = re.search(r"(?m)^详情页[：:][^\r\n]*(?:\r?\n|$)", text)
        if not footer:
            raise ValueError("collector material has no unambiguous preamble boundary")
        search_start = footer.end()
    matches = list(_CHAPTER.finditer(text, search_start))
    if collector_format and not matches:
        raise ValueError("collector material has no verifiable chapter body")
    start = matches[0].start() if collector_format else 0
    body = text[start:]
    if not body.strip():
        raise ValueError("empty source body")
    chapters = [{"title": match.group().strip(), "start": match.start(),
                 "end": matches[index + 1].start() if index + 1 < len(matches) else len(text)}
                for index, match in enumerate(matches) if match.start() >= start]
    return body, {"start": start, "end": len(text), "unit": "unicode_codepoints",
                  "kind": "collector_chapter_body" if collector_format else "whole_plain_text",
                  "sha256": _sha(body.encode("utf-8"))}, chapters


def _bind(candidate: dict) -> dict:
    if candidate.get("discovery_error"):
        raise ValueError("discovery_error: " + str(candidate["discovery_error"]))
    if not candidate.get("book_id") or not candidate.get("metadata_path") or not candidate.get("material_path"):
        raise ValueError("missing book identity or material/metadata path")
    metadata_path = Path(candidate["metadata_path"]).resolve()
    material_path = _path(candidate["material_path"], metadata_path.parent)
    metadata_raw = metadata_path.read_bytes()
    metadata = _json_bytes(metadata_raw, metadata_path)
    source_raw = material_path.read_bytes()
    metadata_sha = _sha(metadata_raw)
    source_sha = _sha(source_raw)
    if str(metadata.get("book_id", "")) != str(candidate["book_id"]):
        raise ValueError("metadata book_id mismatch")
    if not metadata.get("book_name"):
        raise ValueError("missing metadata book_name")
    for key in ("tags", "categories"):
        values = metadata.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"metadata {key} must be a list of strings")
    if candidate.get("book_name") and candidate["book_name"] != metadata["book_name"]:
        raise ValueError("metadata book_name mismatch")
    for key, actual in (("metadata_sha256", metadata_sha), ("source_sha256", source_sha), ("material_sha256", source_sha)):
        if candidate.get(key) and candidate[key] != actual:
            raise ValueError(f"{key} mismatch")
    authorization = candidate.get("authorization")
    authorization_path = candidate.get("authorization_path")
    authorization_sha = None
    if authorization_path:
        authorization_path = _path(authorization_path, metadata_path.parent)
        authorization_raw = authorization_path.read_bytes()
        authorization_sha = _sha(authorization_raw)
        loaded = _json_bytes(authorization_raw, authorization_path)
        if authorization is not None and authorization != loaded:
            raise ValueError("authorization file differs from supplied authorization")
        if candidate.get("authorization_sha256") and candidate["authorization_sha256"] != authorization_sha:
            raise ValueError("authorization_sha256 mismatch")
        authorization = loaded
    if not isinstance(authorization, dict):
        raise ValueError("missing explicit text authorization")
    if str(authorization.get("book_id", "")) != str(candidate["book_id"]):
        raise ValueError("authorization book_id mismatch")
    if authorization.get("source_sha256") != source_sha:
        raise ValueError("authorization source_sha256 mismatch")
    if authorization.get("allow_text_adaptation") is not True or authorization.get("allow_model_input") is not True:
        raise ValueError("authorization does not allow text adaptation and model input")
    if not isinstance(authorization.get("reference"), str) or not authorization["reference"].strip():
        raise ValueError("missing authorization reference")
    text = source_raw.decode("utf-8-sig")
    body, span, chapters = _body(text, metadata)
    # Collector identity in the preamble is independent evidence, not story text.
    header_id = re.search(r"(?m)^书籍\s*ID[：:]\s*(\S+)", text[:span["start"]])
    if header_id and header_id.group(1) != str(candidate["book_id"]):
        raise ValueError("collector book_id mismatch")
    return {"book_id": str(candidate["book_id"]), "book_name": metadata["book_name"],
            "metadata_path": str(metadata_path), "material_path": str(material_path),
            "metadata_sha256": metadata_sha, "source_sha256": source_sha,
            "material_sha256": source_sha, "metadata": metadata,
            "authorization": copy.deepcopy(authorization),
            "authorization_path": str(authorization_path) if authorization_path else None,
            "authorization_sha256": authorization_sha, "source_text": body, "source_span": span,
            "chapters": chapters, "acquisition_scope": {
                "observed_chapters": len(chapters), "chapters_fetched_reported": metadata.get("chapters_fetched"),
                "total_chapters_seen": metadata.get("total_chapters_seen"),
                "paywall_hit": metadata.get("paywall_hit"), "source_url": metadata.get("source_url", ""),
                "scraped_at": metadata.get("scraped_at", ""),
                "partial_source": True, "scope_note": "Only bound source body is available; whole-book completeness is unverified."}}


def select_target_novel(profile, opportunity, candidates, *, now=None, target_book_id=None) -> dict:
    """Return a deterministic selection, with every rejected candidate explained."""
    account, chance = _snapshot(profile), _snapshot(opportunity)
    config = _validate_context(account, chance, now)
    candidates = [copy.deepcopy(item) for item in candidates]
    account_terms = _terms([*account.get("seed_keywords", []), *account.get("service_scope", []), *config["genres"]])
    opportunity_terms = _terms([*chance.get("topic_labels", []), chance.get("title", "")])
    chance_text = " ".join(opportunity_terms)
    account_terms_in_chance = [term for term in account_terms if term in chance_text]
    negative_terms = _terms(account.get("negative_keywords", []), drop_generic=False)
    duplicate_ids = {book_id for book_id, count in Counter(str(item.get("book_id", "")) for item in candidates).items() if count > 1}
    # Identical duplicate observations may be deduplicated. Different source,
    # metadata or authorization bindings for one ID must all remain rejected.
    conflicting = set()
    for book_id in duplicate_ids:
        signatures = {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in candidates if str(item.get("book_id", "")) == book_id}
        if len(signatures) > 1:
            conflicting.add(book_id)
    rankings, bound_books, seen = [], {}, set()
    for candidate in candidates:
        book_id = str(candidate.get("book_id", ""))
        signature = json.dumps(candidate, sort_keys=True, ensure_ascii=False, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        row = {"book_id": book_id, "book_name": candidate.get("book_name", ""), "score": 0,
               "eligible": False, "matched_account_terms": [], "matched_opportunity_terms": [], "exclusion_reasons": []}
        if book_id in conflicting:
            row["exclusion_reasons"].append("conflicting_book_id")
        try:
            book = _bind(candidate)
        except (OSError, ValueError, TypeError) as exc:
            row["exclusion_reasons"].append(str(exc))
            rankings.append(row)
            continue
        metadata = book["metadata"]
        text = " ".join(str(metadata.get(key, "")) for key in ("book_name", "abstract", "tags", "categories", "genre", "genres")).casefold()
        categories = _terms([*metadata.get("tags", []), *metadata.get("categories", [])])
        row["matched_account_terms"] = [term for term in account_terms if term in text]
        opportunity_matches = [term for term in opportunity_terms + account_terms_in_chance if term in text]
        opportunity_matches += [term for term in categories if term in chance_text]
        row["matched_opportunity_terms"] = list(dict.fromkeys(opportunity_matches))
        excluded = [term for term in negative_terms if term in text]
        if excluded:
            row["exclusion_reasons"].append("negative_keywords: " + ", ".join(excluded))
        if account_terms and not row["matched_account_terms"]:
            row["exclusion_reasons"].append("no_account_match")
        if not row["matched_opportunity_terms"]:
            row["exclusion_reasons"].append("no_opportunity_match")
        if target_book_id is not None and book_id != str(target_book_id):
            row["exclusion_reasons"].append("not_requested_book")
        row["score"] = 2 * len(row["matched_account_terms"]) + 3 * len(row["matched_opportunity_terms"])
        row["eligible"] = not row["exclusion_reasons"]
        row["book_name"] = book["book_name"]
        if row["eligible"]:
            bound_books[book_id] = book
        rankings.append(row)
    rankings.sort(key=lambda row: (not row["eligible"], -row["score"], row["book_id"]))
    selected = next((bound_books[row["book_id"]] for row in rankings if row["eligible"]), None)
    material_missing = not candidates or any(any(reason not in {"no_account_match", "no_opportunity_match", "not_requested_book"} and not reason.startswith("negative_keywords:") for reason in row["exclusion_reasons"]) for row in rankings)
    return {"schema": "account_novel_selection/v1", "account": account, "opportunity": chance,
            "rankings": rankings, "selected_book": selected,
            "status": "selected" if selected else ("needs_materials" if material_missing else "no_matching_book")}
