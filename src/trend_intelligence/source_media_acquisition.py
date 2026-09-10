"""Acquire explicitly identified source videos through one authenticated page.

No inferred API endpoints, signatures, or CAPTCHA handling. Only media addresses
observed in a matching player or source-bound page JSON may be downloaded.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from .source_policy import SourcePolicy, SourcePolicyGate, SourceProvider, SourceRequest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_FIELDS = frozenset({"video_id", "url", "original_video"})
MAX_SOURCE_BYTES = 256 * 1024 * 1024
ANALYSIS_SOURCE_BUDGET = 96 * 1024 * 1024


def safe_binary_failure(exc):
    """Whitelist binary-layer diagnostics; never trust arbitrary prefixed text."""
    message = str(exc)
    literals = {
        "binary download target must be inside the project workspace", "binary download target is a directory",
        "binary download requires an HTTP(S) URL without embedded credentials",
        "binary download redirect host is outside the allowed hosts", "binary download host could not be validated",
        "binary download requires HTTPS on every redirect", "binary download rejects private or non-public network addresses",
        "binary download target already exists", "binary download exceeded its redirect limit",
        "binary download redirect has no Location", "binary download Content-Type is not allowed",
        "binary download has an invalid Content-Length", "binary download declared size is empty or exceeds max_bytes",
        "binary response body was not raw bytes", "binary download body is empty or exceeds max_bytes",
        "binary download body differs from declared Content-Length", "binary download target appeared during download",
    }
    if message in literals or re.fullmatch(r"binary download HTTP status [1-5]\d{2}; no output saved", message):
        return message
    if re.fullmatch(r"binary (?:request|download) failed \([A-Za-z_][A-Za-z0-9_]{0,63}(?:; request_sha256=[0-9a-f]{16})?\)", message):
        return message
    return None


def select_analysis_variant(video, *, max_bytes=MAX_SOURCE_BYTES, analysis_budget=ANALYSIS_SOURCE_BUDGET):
    """Choose a complete source rendition, never a DASH video-only track or crop."""
    reference = video.get("play_addr_h264") or video.get("play_addr") or {}
    reference_width = _positive_seconds(reference.get("width")) or _positive_seconds(video.get("width"))
    reference_height = _positive_seconds(reference.get("height")) or _positive_seconds(video.get("height"))
    reference_ratio = reference_width / reference_height if reference_width and reference_height else None
    options = []

    def append(address, field, *, format_kind="mp4", h265=None, gear=None):
        if not isinstance(address, dict) or format_kind != "mp4":
            return
        urls = [url for url in address.get("url_list") or [] if isinstance(url, str) and url.startswith("https://")]
        if not urls:
            return
        width, height = _positive_seconds(address.get("width")), _positive_seconds(address.get("height"))
        size = _positive_seconds(address.get("data_size"))
        if reference_ratio and width and height and abs(width / height - reference_ratio) > reference_ratio * .03:
            return
        options.append({"url": urls[0], "field": field, "data_size": int(size) if size else None,
            "width": int(width) if width else None, "height": int(height) if height else None,
            "format": "mp4", "codec": "h265" if h265 is True else "h264" if h265 is False else "unspecified", "gear_name": gear})

    for field in ("play_addr_h264", "play_addr", "download_addr"):
        append(video.get(field), "aweme_detail.video." + field, h265=False if field == "play_addr_h264" else None)
    for index, row in enumerate(video.get("bit_rate") or []):
        if isinstance(row, dict):
            append(row.get("play_addr"), f"aweme_detail.video.bit_rate[{index}].play_addr",
                format_kind=row.get("format"), h265=bool(row.get("is_h265")), gear=row.get("gear_name"))
    primary = next((row for row in options if row["field"] in {
        "aweme_detail.video.play_addr_h264", "aweme_detail.video.play_addr"}), None)
    if primary and primary["data_size"] and primary["data_size"] <= min(max_bytes, analysis_budget):
        chosen, reason = primary, "primary_complete_media_within_analysis_budget"
    else:
        suitable = [row for row in options if row["data_size"] and row["data_size"] <= max_bytes
            and row["width"] and row["height"] and 480 <= min(row["width"], row["height"]) <= 720]
        budgeted = [row for row in suitable if row["data_size"] <= analysis_budget]
        if budgeted:
            chosen = min(budgeted, key=lambda row: (-min(row["width"], row["height"]), row["data_size"]))
            reason = "complete_mp4_preserve_aspect_480_to_720_within_analysis_budget"
        elif suitable:
            chosen = min(suitable, key=lambda row: row["data_size"])
            reason = "smallest_complete_analysis_mp4_within_hard_limit"
        elif primary and (primary["data_size"] is None or primary["data_size"] <= max_bytes):
            chosen, reason = primary, "primary_no_verified_smaller_complete_variant"
        else:
            raise AcquisitionStop("source_unavailable", "该来源没有尺寸合适且不超过 256 MiB 的完整 MP4 版本；未截短或改用其他来源")
    variant = {key: value for key, value in chosen.items() if key != "url"}
    variant.update(selection_reason=reason, analysis_budget_bytes=analysis_budget, hard_limit_bytes=max_bytes,
        original_duration_seconds=(_positive_seconds(video.get("duration")) or 0) / 1000 or None,
        excluded_formats=["dash"], preserves_source_aspect_ratio=True)
    return {"url": chosen["url"], "field": chosen["field"], "variant": variant,
        "requires_audio": bool(video.get("audio") or video.get("bit_rate_audio") or ".bit_rate[" in chosen["field"])}

# Inspect only page-owned, known JSON containers and the visible player. No
# window-wide object enumeration or authenticated API endpoint guessing.
SOURCE_MEDIA_INSPECTION_JS = r"""(() => {
  // source-media-acquisition-inspect/v1
  const visible = e => { if (!e) return false; const r=e.getBoundingClientRect(), s=getComputedStyle(e);
    return r.width>8 && r.height>8 && s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity||1)>0; };
  const bodyText=(document.body?.innerText||'');
  const challenge=Array.from(document.querySelectorAll('iframe[src*="captcha"],iframe[src*="/verifycenter/"]')).some(visible);
  const blocked=challenge || /\/(?:login|passport)(?:[/?#]|$)/.test(location.pathname)
    || /扫码登录|验证码登录|请完成验证|点击两个形状相同|拖动滑块|访问异常|账号异常/.test(bodyText);
  const players=Array.from(document.querySelectorAll('video')).filter(visible)
    .sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height);
  const player=players[0]; let playerOwner='';
  for(let node=player, depth=0; node && depth<12; node=node.parentElement, depth++) {
    for(const key of ['data-e2e-vid','data-video-id','data-aweme-id']) {
      const value=node.getAttribute?.(key); if (/^\d{8,}$/.test(value||'')) {playerOwner=value; break;}
    }
    if(!playerOwner) for(const value of node.classList||[]) {const found=/^video_(\d{8,})$/.exec(value); if(found){playerOwner=found[1];break;}}
    if(playerOwner) break;
  }
  const embedded=[]; let visited=0;
  const mediaFields=['play_addr_h264','play_addr','playAddr','download_addr','downloadAddr'];
  const urls=(value)=> typeof value==='string' ? [value] : Array.isArray(value) ? value.filter(x=>typeof x==='string')
    : value && typeof value==='object' ? [...(value.url_list||value.urlList||[]), ...(value.url?[value.url]:[])] : [];
  const walk=(node,container,path,depth=0)=>{
    if(!node || typeof node!=='object' || depth>30 || ++visited>100000) return;
    const owner=String(node.aweme_id||node.awemeId||node.item_id||node.itemId||'');
    if(/^\d{8,}$/.test(owner) && node.video && typeof node.video==='object') {
      for(const key of mediaFields) for(const url of urls(node.video[key]))
        if(typeof url==='string' && /^https?:\/\//.test(url)) embedded.push({owner_id:owner,url,field:'video.'+key,container,path});
      for(const [index,rate] of (Array.isArray(node.video.bit_rate)?node.video.bit_rate:[]).entries())
        for(const url of urls(rate.play_addr)) if(/^https?:\/\//.test(url))
          embedded.push({owner_id:owner,url,field:'video.bit_rate['+index+'].play_addr',container,path});
    }
    if(Array.isArray(node)) node.forEach((value,i)=>walk(value,container,path+'['+i+']',depth+1));
    else for(const [key,value] of Object.entries(node)) walk(value,container,path+'.'+key,depth+1);
  };
  for(const node of document.querySelectorAll('script[type="application/json"],script#RENDER_DATA,script#__NEXT_DATA__,script#SIGI_STATE,script#__UNIVERSAL_DATA_FOR_REHYDRATION__')) {
    const raw=node.textContent||''; if(!raw || raw.length>8000000) continue;
    try {let value; try{value=JSON.parse(raw);}catch(_){value=JSON.parse(decodeURIComponent(raw));}
      walk(value,node.id||'application/json','$');}catch(_){}
  }
  return {page_url:location.href,blocked,block_reason:blocked?'login_or_visible_verification':'',
    player:{found:!!player,owner_id:playerOwner,current_src:player?.currentSrc||player?.src||'',
      duration:Number.isFinite(player?.duration)?player.duration:null},embedded,
    observed_resources:performance.getEntriesByType('resource').map(entry=>entry.name).filter(value=>{
      try{const u=new URL(value);return u.protocol==='https:' && u.hostname==='www.douyin.com'
        && u.pathname==='/aweme/v1/web/aweme/detail/' && /^\d{8,}$/.test(u.searchParams.get('aweme_id')||'');}catch(_){return false;}})};
})()"""


@dataclass(slots=True)
class SourceMediaAcquisitionResult:
    status: str = "running"
    manifest_path: str = ""
    selected_count: int = 0
    acquired_count: int = 0
    cached_count: int = 0
    attempted_count: int = 0
    stopped_reason: str = ""
    records: list[dict] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    session_left_open: bool = False

    def to_dict(self):
        return asdict(self)


class AcquisitionStop(ValueError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path, payload):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex[:10] + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _safe_component(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)[:80] + "_" + hashlib.sha256(value.encode()).hexdigest()[:8]


def _public_url(value):
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.hostname or "", parsed.path, "", "", ""))


def _page_video_id(value):
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or parsed.hostname != "www.douyin.com" or parsed.username or parsed.password:
        return ""
    match = re.fullmatch(r"/video/(\d{8,})/?", parsed.path)
    return match.group(1) if match else ""


def _positive_seconds(value):
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _matching_detail_urls(snapshot, video_id):
    found = []
    for value in snapshot.get("observed_resources") or []:
        parsed = urlparse(str(value))
        if (parsed.scheme == "https" and parsed.hostname == "www.douyin.com"
            and parsed.path == "/aweme/v1/web/aweme/detail/" and not parsed.username and not parsed.password
            and parse_qs(parsed.query).get("aweme_id") == [video_id]):
            found.append(str(value))
    return found


def locate_source_media(snapshot, expected_video_id):
    """Return a source address only with an independent player or JSON identity."""
    if snapshot.get("blocked"):
        raise AcquisitionStop("human_required", "原页面要求登录或人工验证；已停留在当前页面")
    if _page_video_id(snapshot.get("page_url")) != expected_video_id:
        raise AcquisitionStop("identity_unconfirmed", "原页面视频 ID 与本批来源不一致")
    player = snapshot.get("player") or {}
    player_owner = str(player.get("owner_id") or "")
    if player_owner and player_owner != expected_video_id:
        raise AcquisitionStop("identity_unconfirmed", "实际播放器属于其他视频，未下载推荐内容")
    matching = [row for row in snapshot.get("embedded") or [] if isinstance(row, dict)
        and str(row.get("owner_id")) == expected_video_id]
    current = str(player.get("current_src") or "")
    if current.startswith("https://") and (player_owner == expected_video_id
            or any(row.get("url") == current for row in matching)):
        return {"url": current, "identity_kind": "visible_player_owner" if player_owner else "player_url_matches_bound_json",
            "owner_id": expected_video_id, "page_url": snapshot["page_url"], "field": "video.currentSrc",
            "duration_seconds": _positive_seconds(player.get("duration"))}
    for row in matching:
        if str(row.get("url") or "").startswith("https://"):
            return {"url": row["url"], "identity_kind": "embedded_video_owner",
                "owner_id": expected_video_id, "page_url": snapshot["page_url"],
                "field": row.get("field"), "container": row.get("container"), "json_path": row.get("path")}
    if current.startswith("blob:"):
        raise AcquisitionStop("source_unavailable", "播放器仅提供 blob 地址，且页面没有明确绑定该来源的可用媒体地址")
    raise AcquisitionStop("identity_unconfirmed", "没有找到与本来源 ID 明确对应的播放器或页面媒体地址")


def _probe(path):
    completed = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", timeout=45)
    if completed.returncode:
        raise ValueError("下载内容不能作为视频解码")
    return json.loads(completed.stdout)


def _validate_probe(probe, expected_duration=None):
    streams = probe.get("streams") or []
    video = next((row for row in streams if row.get("codec_type") == "video"
        and int(row.get("width") or 0) > 0 and int(row.get("height") or 0) > 0), None)
    duration = float((probe.get("format") or {}).get("duration") or (video or {}).get("duration") or 0)
    if video is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError("下载内容没有有效视频轨道或时长")
    if expected_duration is not None:
        expected = float(expected_duration)
        # A percentage tolerance would accept a missing minute in a long clip.
        if math.isfinite(expected) and expected > 0 and abs(duration - expected) > 1.0:
            raise ValueError("下载时长与来源页面记录明显不一致")
    return duration


class SourceMediaAcquisitionService:
    def __init__(self, *, output_root=None, session_factory=None, probe=None):
        self.output_root = Path(output_root or PROJECT_ROOT / "data/trend_source_media").resolve()
        if not self.output_root.is_relative_to(PROJECT_ROOT / "data"):
            raise ValueError("来源原片输出须位于项目 data 目录")
        self.session_factory = session_factory
        self.session = None
        self._current_page = None
        self._last_navigation_at = None
        self.probe = probe or _probe
        self.gate = SourcePolicyGate()

    def acquire(self, candidates, *, account_uuid, collection_run_id, policy: SourcePolicy,
                session=None, max_items=1, pages_used_today=0):
        candidates = list(candidates)
        if not candidates or not account_uuid or not collection_run_id or not 1 <= int(max_items) <= 200:
            raise ValueError("须提供来源、账号、采集批次及 1—200 条获取上限")
        identities = set()
        for row in candidates:
            if row.run_id != collection_run_id or _page_video_id(row.url) != row.video_id:
                raise ValueError("来源必须属于指定批次且使用对应的真实抖音视频页面")
            if row.video_id in identities:
                raise ValueError("来源视频 ID 不能重复")
            identities.add(row.video_id)
        folder = self.output_root / _safe_component(account_uuid) / _safe_component(collection_run_id)
        folder.mkdir(parents=True, exist_ok=True)
        manifest_path = folder / "manifest.json"
        result = SourceMediaAcquisitionResult(manifest_path=str(manifest_path), selected_count=len(candidates), started_at=_now())
        previous = {}
        if manifest_path.is_file():
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("account_uuid") != account_uuid or old.get("collection_run_id") != collection_run_id:
                raise ValueError("已保存清单与账号或采集批次不匹配")
            previous = {row["item_id"]: row for row in old.get("items") or []}
        manifest = {"schema": "research_local_media/v1", "account_uuid": account_uuid,
            "collection_run_id": collection_run_id, "created_at": _now(), "items": [],
            "acquisition": {"status": "running", "source": "observed_source_page_media", "started_at": result.started_at}}
        entries = []
        pending = []
        for candidate in candidates:
            row = {"item_id": candidate.item_id, "video_id": candidate.video_id, "title": candidate.title,
                "source_url": candidate.url, "video": "", "status": "pending"}
            prior = previous.get(candidate.item_id)
            if prior and self._cache_valid(prior, candidate, folder, account_uuid, collection_run_id):
                row.update(prior)
                result.cached_count += 1
                result.records.append({"item_id": candidate.item_id, "video_id": candidate.video_id, "status": "cached", "video": row["video"]})
            else:
                pending.append((candidate, row))
            entries.append(row)
        def persist():
            manifest["items"] = [row for row in entries if row.get("video")]
            manifest["pending_items"] = [row for row in entries if not row.get("video")]
            manifest["selection"] = [{"item_id": row["item_id"], "video_id": row["video_id"], "source_url": row["source_url"]} for row in entries]
            _atomic_json(manifest_path, manifest)
        persist()
        if session is not None and session is not self.session:
            self._current_page = None
        self.session = session or self.session
        active_item, active_stage = None, "initialize"
        try:
            for candidate, row in pending[:int(max_items)]:
                active_item, active_stage = candidate, "policy_check"
                self._require_policy(policy, candidate.url, min(len(pending), int(max_items)), pages_used_today)
                if self.session is None:
                    if self.session_factory is None:
                        raise AcquisitionStop("failed", "未提供当前账号的认证浏览器会话")
                    self.session = self.session_factory()
                result.session_left_open = True
                result.attempted_count += 1
                requested_at = _now()
                active_stage = "page_readiness"
                page = self._current_page
                if page is None or _page_video_id(getattr(page, "url", "")) != candidate.video_id:
                    if self._last_navigation_at is not None:
                        delay = policy.min_interval_seconds - (time.monotonic() - self._last_navigation_at)
                        while delay > 0:
                            time.sleep(min(delay, 1.0))
                            delay = policy.min_interval_seconds - (time.monotonic() - self._last_navigation_at)
                    page = self.session.open_page(candidate.url)
                    self._current_page = page
                    self._last_navigation_at = time.monotonic()
                snapshot = {}
                readiness_deadline = time.monotonic() + 15.0
                for attempt in range(20):
                    page.wait_for_timeout(750)
                    snapshot = page.locator("").evaluate(SOURCE_MEDIA_INSPECTION_JS) or {}
                    player = snapshot.get("player") or {}
                    if (snapshot.get("blocked") or (player.get("owner_id") and str(player["owner_id"]) != candidate.video_id)
                        or any(str(row.get("owner_id")) == candidate.video_id for row in snapshot.get("embedded") or [])
                        or _matching_detail_urls(snapshot, candidate.video_id)
                        or (str(player.get("current_src") or "").startswith("https://") and player.get("owner_id") == candidate.video_id)
                        or time.monotonic() >= readiness_deadline):
                        break
                try:
                    active_stage = "source_identity"
                    source = locate_source_media(snapshot, candidate.video_id)
                except AcquisitionStop as exc:
                    if exc.status not in {"source_unavailable", "identity_unconfirmed"} or snapshot.get("blocked"):
                        raise
                    if _page_video_id(snapshot.get("page_url")) != candidate.video_id:
                        raise
                    owner = str((snapshot.get("player") or {}).get("owner_id") or "")
                    if owner and owner != candidate.video_id:
                        raise
                    active_stage = "observed_detail_lookup"
                    source = self._observed_detail(page, snapshot, candidate, policy,
                        min(len(pending), int(max_items)), pages_used_today, original_stop=exc)
                # Inspect a real, already-observed detail request before a large
                # GET: Playwright buffers the body before our size check.
                if source["identity_kind"] != "observed_detail_response_owner" and _matching_detail_urls(snapshot, candidate.video_id):
                    active_stage = "observed_detail_lookup"
                    source = self._observed_detail(page, snapshot, candidate, policy,
                        min(len(pending), int(max_items)), pages_used_today,
                        original_stop=AcquisitionStop("source_unavailable", "无法核对本来源的媒体规格"))
                token = uuid.uuid4().hex[:16]
                temporary = folder / f"{candidate.video_id}.{token}.candidate.mp4"
                for download_attempt in range(2):
                    active_stage = "media_download"
                    parsed_media = urlparse(source["url"])
                    media_policy = replace(policy, policy_id=policy.policy_id + "-observed-source-media",
                        allowed_hosts=(parsed_media.hostname or "",), allowed_path_prefixes=(parsed_media.path or "/",))
                    self._require_policy(media_policy, source["url"], min(len(pending), int(max_items)), pages_used_today)
                    try:
                        downloaded = page.request.download(source["url"], temporary,
                            headers={"Referer": candidate.url}, timeout=90_000,
                            max_bytes=MAX_SOURCE_BYTES, expected_content_types=["video/*", "application/octet-stream"],
                            allowed_hosts=list(media_policy.allowed_hosts))
                        break
                    except Exception as exc:
                        if temporary.is_file():
                            temporary.unlink()
                        failure = safe_binary_failure(exc)
                        if (download_attempt or source["identity_kind"] == "observed_detail_response_owner" or failure not in {
                            "binary download declared size is empty or exceeds max_bytes", "binary download body is empty or exceeds max_bytes"}):
                            raise
                        fresh = page.locator("").evaluate(SOURCE_MEDIA_INSPECTION_JS) or {}
                        if (fresh.get("blocked") or _page_video_id(fresh.get("page_url")) != candidate.video_id
                            or str((fresh.get("player") or {}).get("owner_id") or candidate.video_id) != candidate.video_id):
                            raise AcquisitionStop("identity_unconfirmed", "下载后页面状态或来源身份发生变化，未重试")
                        active_stage = "observed_detail_lookup_after_size_limit"
                        old_request_sha = hashlib.sha256(source["url"].encode()).hexdigest()
                        source = self._observed_detail(page, fresh, candidate, policy,
                            min(len(pending), int(max_items)), pages_used_today,
                            original_stop=AcquisitionStop("source_unavailable", "原片超过下载上限，当前页面没有可核对的替代规格"))
                        source["fallback_from_download"] = {"safe_reason": failure, "request_url_sha256": old_request_sha,
                            "retry_limit": 1, "size_limit_unchanged": MAX_SOURCE_BYTES}
                try:
                    active_stage = "media_probe"
                    if not temporary.is_file() or temporary.stat().st_size <= 0:
                        raise ValueError("媒体下载未生成完整文件")
                    actual_sha = _sha(temporary)
                    if downloaded.get("sha256") != actual_sha:
                        raise ValueError("媒体下载回执哈希不匹配")
                    probe = self.probe(temporary)
                    expected_duration = (_positive_seconds(source.get("duration_seconds"))
                        or _positive_seconds((snapshot.get("player") or {}).get("duration"))
                        or _positive_seconds(candidate.duration_seconds))
                    duration = _validate_probe(probe, expected_duration)
                    variant = source.get("variant") or {}
                    actual_video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
                    if variant.get("width") and variant.get("height") and (
                        int(actual_video.get("width") or 0), int(actual_video.get("height") or 0)) != (variant["width"], variant["height"]):
                        raise ValueError("下载画面尺寸与所选原片规格不一致")
                    if source.get("requires_audio"):
                        audio_streams = [stream for stream in probe.get("streams") or [] if stream.get("codec_type") == "audio"]
                        if not audio_streams:
                            raise ValueError("所选原片缺少音频轨道，未接受独立视频轨")
                        durations = [_positive_seconds(stream.get("duration")) for stream in audio_streams]
                        known_audio_durations = [value for value in durations if value is not None]
                        if known_audio_durations and max(known_audio_durations) < duration - .5:
                            raise ValueError("下载音轨未覆盖完整原片")
                    known_hashes = {entry.get("source_video_sha256") for entry in entries if entry.get("video")}
                    if actual_sha in known_hashes:
                        raise ValueError("其他来源已使用同一原片，不能重复计数")
                    final = folder / f"{candidate.video_id}.{token}.mp4"
                    temporary.replace(final)
                except Exception:
                    if temporary.is_file():
                        temporary.unlink()
                    raise
                receipt_path = folder / f"{candidate.video_id}.{token}.receipt.json"
                active_stage = "receipt_write"
                receipt = {"schema": "source_media_receipt/v1", "account_uuid": account_uuid,
                    "collection_run_id": collection_run_id, "item_id": candidate.item_id, "video_id": candidate.video_id,
                    "source_page_url": candidate.url, "observed_source": source, "identity_confirmed": True,
                    "requested_at": requested_at, "download_completed_at": _now(), "video": str(final),
                    "source_video_sha256": actual_sha, "probe": probe, "duration_seconds": duration,
                    "media_policy": {"parent_policy_id": policy.policy_id, "derived_policy_id": media_policy.policy_id,
                        "allowed_hosts": list(media_policy.allowed_hosts), "allowed_path_prefixes": list(media_policy.allowed_path_prefixes),
                        "basis": "exact media host/path observed on the identity-verified source page or its observed identity-matched response"},
                    "download": downloaded, "scope": "page/video identity plus observed URL provenance; original content was not yet analyzed"}
                _atomic_json(receipt_path, receipt)
                row.update(video=str(final), status="acquired", source_video_sha256=actual_sha,
                    acquisition_receipt=str(receipt_path), acquisition_receipt_sha256=_sha(receipt_path),
                    acquired_at=receipt["download_completed_at"])
                result.acquired_count += 1
                result.records.append({"item_id": candidate.item_id, "video_id": candidate.video_id, "status": "acquired",
                    "video": str(final), "duration_seconds": duration, "source_video_sha256": actual_sha,
                    "receipt_path": str(receipt_path), "media_host": urlparse(source["url"]).hostname})
                if source.get("variant"):
                    result.records[-1]["variant"] = source["variant"]
                persist()
            result.status = "completed" if result.acquired_count + result.cached_count == len(candidates) else "partial"
            if result.status == "partial":
                result.stopped_reason = "本次新获取上限已到，已保存文件可在同一批次续跑"
        except AcquisitionStop as exc:
            result.status, result.stopped_reason = exc.status, exc.reason
        except Exception as exc:
            # Requests may contain signed addresses. Never surface exception text.
            safe_reasons = {"下载内容不能作为视频解码", "下载内容没有有效视频轨道或时长",
                "下载时长与来源页面记录明显不一致", "媒体下载未生成完整文件", "媒体下载回执哈希不匹配",
                "其他来源已使用同一原片，不能重复计数", "下载画面尺寸与所选原片规格不一致",
                "所选原片缺少音频轨道，未接受独立视频轨", "下载音轨未覆盖完整原片"}
            result.status = "failed"
            binary_reason = safe_binary_failure(exc)
            result.stopped_reason = (str(exc) if isinstance(exc, ValueError) and str(exc) in safe_reasons else
                f"二进制下载失败：{binary_reason}" if binary_reason else
                f"来源媒体获取失败（{type(exc).__name__}）；已保留当前页面和成功文件")
        if result.status not in {"completed", "partial"} and active_item is not None:
            result.records.append({"item_id": active_item.item_id, "video_id": active_item.video_id,
                "status": result.status, "stage": active_stage, "safe_reason": result.stopped_reason})
        result.finished_at = _now()
        manifest["acquisition"].update(status=result.status, stopped_reason=result.stopped_reason,
            finished_at=result.finished_at, acquired_count=result.acquired_count, cached_count=result.cached_count)
        persist()
        return result

    def _observed_detail(self, page, snapshot, candidate, policy, planned_pages, pages_used_today, *, original_stop):
        observed = _matching_detail_urls(snapshot, candidate.video_id)
        if not observed:
            raise original_stop
        request_url = observed[-1]
        self._require_policy(policy, request_url, planned_pages, pages_used_today)
        response = page.request.get(request_url, headers={"Referer": candidate.url}, timeout=30_000)
        if response.status != 200:
            raise AcquisitionStop("source_unavailable", "原页面已观察到的详情请求未返回成功响应")
        payload = response.json()
        detail = payload.get("aweme_detail") if isinstance(payload, dict) else None
        if not isinstance(detail, dict) or str(detail.get("aweme_id")) != candidate.video_id:
            raise AcquisitionStop("identity_unconfirmed", "真实详情响应的视频 ID 与本批来源不一致")
        video = detail.get("video") or {}
        selected = select_analysis_variant(video)
        return {**selected, "identity_kind": "observed_detail_response_owner", "owner_id": candidate.video_id,
            "page_url": snapshot["page_url"],
            "detail_request_url": request_url, "detail_request_url_sha256": hashlib.sha256(request_url.encode()).hexdigest(),
            "detail_response_subset": {"aweme_id": detail["aweme_id"], "desc": detail.get("desc"), "video": video},
            "duration_seconds": (_positive_seconds(video.get("duration")) or 0) / 1000 or None,
            "detail_response_sha256": hashlib.sha256(response.body()).hexdigest()}

    def _require_policy(self, policy, target_url, planned_pages, pages_used_today):
        decision = self.gate.evaluate(policy, SourceRequest(provider=SourceProvider.AUTHORIZED_WEB,
            purposes=frozenset({"trend_analysis"}), requested_fields=MEDIA_FIELDS, target_url=target_url,
            planned_pages=max(1, planned_pages), pages_used_today=pages_used_today), web_crawler_enabled=True)
        if not decision.allowed:
            raise AcquisitionStop("policy_blocked", f"来源媒体授权范围不匹配：{decision.code}")

    def _cache_valid(self, entry, candidate, folder, account_uuid, collection_run_id):
        try:
            video, receipt_path = Path(entry["video"]).resolve(), Path(entry["acquisition_receipt"]).resolve()
            if not video.is_relative_to(folder) or not receipt_path.is_relative_to(folder):
                return False
            if _sha(receipt_path) != entry["acquisition_receipt_sha256"] or _sha(video) != entry["source_video_sha256"]:
                return False
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (receipt.get("schema") != "source_media_receipt/v1" or receipt.get("account_uuid") != account_uuid
                or receipt.get("collection_run_id") != collection_run_id or receipt.get("item_id") != candidate.item_id
                or receipt.get("video_id") != candidate.video_id or receipt.get("identity_confirmed") is not True
                or receipt.get("source_video_sha256") != entry["source_video_sha256"] or receipt.get("video") != str(video)):
                return False
            _validate_probe(receipt["probe"], candidate.duration_seconds)
            return True
        except (OSError, ValueError, TypeError, KeyError):
            return False
