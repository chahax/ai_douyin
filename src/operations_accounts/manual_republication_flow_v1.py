"""Read-only inventories on one existing, actor-owned manual browser Page.

No upload, field input, declaration selection, click, browser creation, cookie
storage or account-health update. Public identity is read from the same Page's
rendered SELF view; it is not promoted into an independently verified creator
account. The runtime bridge owns authorization/admission/once claims.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SELF_URL = "https://www.douyin.com/user/self?from_tab_name=main"
SITES = {
    "manage": "https://creator.douyin.com/creator-micro/content/manage",
    "upload": "https://creator.douyin.com/creator-micro/content/upload",
}
VERSION = "manual_republication_inspection/v1"
BLOCK_REASONS = frozenset({
    "inspection_project_file_required", "inspection_evidence_changed", "inspection_metadata_too_large",
    "inspection_artifact_already_exists", "inspection_authority_scope_changed", "inspection_readonly_action_required",
    "inspection_config_changed", "inspection_source_changed", "inspection_actor_identity_changed",
    "inspection_manual_page_scope_changed", "inspection_manual_command_changed", "inspection_original_worker_not_alive",
    "inspection_identity_surface_unconfirmed", "inspection_identity_shape_invalid",
    "inspection_public_uid_mismatch_or_ambiguous", "inspection_public_uid_not_observed",
    "inspection_original_browser_db_required", "inspection_old_target_not_unique",
    "inspection_output_directory_required", "inspection_existing_subject_changed", "inspection_page_changed",
    "inspection_session_changed", "inspection_creator_surface_unconfirmed", "inspection_inventory_too_large",
    "inspection_control_changed", "inspection_current_binding_changed",
})


class InspectionBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _need(ok, reason):
    if not ok:
        raise InspectionBlocked(reason)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _reference(path):
    path = Path(path).resolve()
    _need(path.is_relative_to(ROOT) and path.is_file(), "inspection_project_file_required")
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": sha}


def _read(ref):
    _need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
          and _reference(ref["path"]) == ref, "inspection_evidence_changed")
    path = Path(ref["path"])
    _need(path.stat().st_size <= 2 * 1024 * 1024, "inspection_metadata_too_large")
    return json.loads(path.read_text(encoding="utf8"))


def _write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if path.exists():
        _need(path.read_bytes() == raw, "inspection_artifact_already_exists")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return _reference(path)


def _binding_version(context):
    b = context.binding
    fields = {k: getattr(b, k) for k in ("account_uuid", "account_key", "platform_identity_key",
              "browser_environment_key", "browser_profile_dir", "storage_state_path", "confirmed_by", "created_at")}
    fields["profile_version"] = context.profile.profile_version
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _authority(config):
    a = _read(config["authority"])
    _need(a.get("schema") == "explicit_republication_intent/v1"
          and a.get("user_statement") and a.get("account_uuid") == config["account_id"]
          and a.get("account_key") == config["account_key"]
          and re.fullmatch(r"[0-9]{5,24}", str(a.get("expected_public_uid", "")))
          and re.fullmatch(r"[0-9]{10,24}", str(a.get("old_post_id", "")))
          and a.get("new_publication_limit") == 1 and a.get("old_records_unchanged") is True,
          "inspection_authority_scope_changed")
    return a


def _guard(actor, resource, config, request):
    actor._assert_thread()
    actor._check_owner()
    _need(set(request) == {"schema", "config", "action", "view"}
          and request["schema"] == "manual_republication_operator_request/v1"
          and request["action"] == "inspect_site" and request["view"] in SITES,
          "inspection_readonly_action_required")
    _need(_read(request["config"]) == config, "inspection_config_changed")
    for source in config["sources"].values():
        _need(_reference(source["path"]) == source, "inspection_source_changed")
    a = _authority(config)
    context = resource.context
    fresh_binding = resource.runtime.bindings.get(config["account_key"])
    fresh_profile = resource.runtime.profiles.get(config["account_key"])
    fresh_context = SimpleNamespace(binding=fresh_binding, profile=fresh_profile)
    _need(fresh_binding.account_uuid == fresh_profile.account_uuid == config["account_id"]
          and _binding_version(fresh_context) == config["binding_version"]
          and str(fresh_binding.public_uid) == a["expected_public_uid"], "inspection_current_binding_changed")
    _need(actor.account_id == resource.account_uuid == context.account_uuid == config["account_id"]
          and context.account_key == config["account_key"]
          and actor.owner_id == config["owner_id"] and actor.generation == config["generation"]
          and actor.binding_version == _binding_version(context) == config["binding_version"]
          and str(context.binding.public_uid) == a["expected_public_uid"], "inspection_actor_identity_changed")
    _need(not actor._stack and resource.manual_tasks == {config["manual_command_id"]: config["tab_id"]}
          and not getattr(resource, "console_tasks", {}), "inspection_manual_page_scope_changed")
    manual = actor.store.get(config["manual_command_id"])
    _need(manual and manual["kind"] == "manual" and manual["state"] == "waiting_human"
          and manual["owner_id"] == actor.owner_id and manual["generation"] == actor.generation
          and manual["account_id"] == actor.account_id and manual["binding_version"] == actor.binding_version
          and manual["request_sha"] == config["manual_request_sha256"]
          and (manual.get("result") or {}).get("tab_id") == config["tab_id"]
          and manual["payload"].get("account_key") == config["account_key"]
          and manual["payload"].get("account_uuid") == config["account_id"]
          and _digest([manual["account_id"], manual["binding_version"], manual["kind"],
                       manual["payload"], manual["priority"]]) == manual["request_sha"], "inspection_manual_command_changed")
    control_path = Path(config["control_db"]).resolve()
    _need(control_path.is_relative_to(ROOT / "data") and control_path.is_file(), "inspection_control_changed")
    with sqlite3.connect(control_path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        row = db.execute("SELECT state,revision FROM account_controls WHERE account_uuid=?", (config["account_id"],)).fetchone()
    _need(row is not None and {"state": row[0], "revision": row[1]} == config["control_snapshot"], "inspection_control_changed")
    owner = resource.session
    _need(owner is not None and owner.active is True and getattr(owner, "_closed", False) is False
          and getattr(owner, "_proc", None) is not None and owner._proc.poll() is None
          and not owner.worker_failure() and getattr(owner.config, "headless", None) is False,
          "inspection_original_worker_not_alive")
    return a


def _rpc(guard, operation, *args, **kwargs):
    guard()
    result = operation(*args, **kwargs)
    guard()
    return result


UID_JS = r"""() => {
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&
  getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[aria-hidden="true"]');
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 const uids=new Set();let n,count=0,truncated=false;
 while((n=walker.nextNode())){
  if(++count>20000){truncated=true;break}
  const p=n.parentElement;if(!visible(p)||p.closest('input,textarea,script,style,[role="textbox"]'))continue;
  if(!/^(?:抖音号|抖音ID)\s*[:：]?/.test(String(n.nodeValue||'').trim()))continue;
  let e=p;for(let level=0;e&&level<=2;level++,e=e.parentElement){
   if(['BODY','HTML','MAIN'].includes(e.tagName)||!visible(e)||e.children.length>8)break;
   const text=(e.innerText||'').trim();if(text.length>240)break;
   if((text.match(/抖音号|抖音ID/g)||[]).length!==1)continue;
   const m=text.match(/(?:抖音号|抖音ID)\s*[:：]?\s*([0-9]{5,24})(?![0-9])/);
   if(m){uids.add(m[1]);break}
  }
 }
 return {origin:location.origin,path:location.pathname,public_uids:[...uids].slice(0,4),
   truncated:truncated||uids.size>4,source:'rendered_public_uid_text',input_values_read:false};
}"""


def _read_identity(page, guard, expected):
    _rpc(guard, page.goto, SELF_URL)
    samples = []
    for _ in range(8):
        v = _rpc(guard, page.evaluate, UID_JS)
        _need(isinstance(v, dict) and set(v) == {"origin", "path", "public_uids", "truncated", "source", "input_values_read"}
              and v["source"] == "rendered_public_uid_text" and v["input_values_read"] is False,
              "inspection_identity_shape_invalid")
        samples.append(v)
        if (v.get("origin") != "https://www.douyin.com" or not str(v.get("path", "")).startswith("/user/")
                or v.get("truncated") is not False):
            return {"verified": False, "reason_code": "inspection_identity_surface_unconfirmed", "samples": samples}
        uids = v.get("public_uids")
        _need(isinstance(uids, list) and len(uids) <= 4
              and all(isinstance(uid, str) and re.fullmatch(r"[0-9]{5,24}", uid) for uid in uids), "inspection_identity_shape_invalid")
        if uids and uids != [expected]:
            return {"verified": False, "reason_code": "inspection_public_uid_mismatch_or_ambiguous", "samples": samples}
        if len(samples) >= 2 and samples[-1]["public_uids"] == samples[-2]["public_uids"] == [expected]:
            return {"verified": True, "actual_public_uid": expected,
                    "source": "same_manual_page_rendered_self_uid", "samples": samples,
                    "health_or_cookie_persisted": False, "creator_identity_independently_verified": False}
        _rpc(guard, page.wait_for_timeout, 250)
    return {"verified": False, "reason_code": "inspection_public_uid_not_observed", "samples": samples}


def _old_target(config, authority):
    path = Path(config["browser_db"]).resolve()
    _need(path.is_relative_to(ROOT / "data") and path.is_file(), "inspection_original_browser_db_required")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        rows = db.execute("SELECT command_id,payload,result FROM browser_control_commands WHERE account_id=? AND kind='publish' AND state='succeeded'",
                          (config["account_id"],)).fetchall()
    matches = []
    for cid, payload, result in rows:
        p, r = json.loads(payload), json.loads(result)
        if r.get("post_id") == authority["old_post_id"] and p.get("video_sha256") == authority["media"]["sha256"]:
            matches.append({"post_id": r["post_id"], "title": p["request"]["title"], "publication_command_id": cid})
    _need(len(matches) == 1, "inspection_old_target_not_unique")
    return matches[0]


def inventory_script(target):
    """Fixed read-only JS; only already-bound public target strings are embedded."""
    return "() => { const target=" + json.dumps(target, ensure_ascii=False) + r""";
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ');
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&
   getComputedStyle(e).display!=='none'&&!e.closest('[hidden],[aria-hidden="true"]');
 const safeHref=e=>{try{const u=new URL(e.getAttribute('href'),location.href);
   return ['https:','http:'].includes(u.protocol)?{origin:u.origin,path:u.pathname}:null}catch{return null}};
 const text=e=>norm(e?.innerText||'').slice(0,400);
 const desc=e=>({tag:e.tagName.toLowerCase(),type:(e.getAttribute('type')||'').slice(0,40),
   role:(e.getAttribute('role')||'').slice(0,40),text:text(e),
   label:([...(e.labels||[])].filter(visible).map(text).join(' ')).slice(0,400),
   aria_label:(e.getAttribute('aria-label')||'').slice(0,240),placeholder:(e.getAttribute('placeholder')||'').slice(0,240),
   id:(e.getAttribute('id')||'').slice(0,160),class_name:(e.getAttribute('class')||'').slice(0,240),
   disabled:e.matches(':disabled,[aria-disabled="true"]'),readonly:e.hasAttribute('readonly'),
   checked:e.matches('input[type="checkbox"],input[type="radio"]')?!!e.checked:null,
   aria_checked:(e.getAttribute('aria-checked')||'').slice(0,20),
   aria_selected:(e.getAttribute('aria-selected')||'').slice(0,20),href:e.tagName==='A'?safeHref(e):null});
 const all=Array.from(document.querySelectorAll('button,a,input,textarea,select,[role="button"],[role="checkbox"],[role="radio"],[role="switch"],[role="tab"]'));
 const visibleControls=all.filter(e=>visible(e)&&!e.matches('input[type="hidden"],input[type="password"]'));
 const controls=visibleControls.slice(0,100).map(desc);
 const challengeFrames=Array.from(document.querySelectorAll('iframe')).filter(visible).filter(e=>{
   try{const u=new URL(e.getAttribute('src'),location.href);return /verifycenter|captcha|verify/i.test(u.pathname)}catch{return false}}).length;
 const lines=[];let n,count=0,cut=false;const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((n=walker.nextNode())){if(++count>20000){cut=true;break}
   const p=n.parentElement;if(!visible(p)||p.closest('input,textarea,script,style,[role="textbox"]'))continue;
   const s=norm(n.nodeValue);if(s){if(lines.length<160)lines.push(s.slice(0,300));else cut=true}}
 const exact=Array.from(document.querySelectorAll('div,span,p,a')).filter(e=>visible(e)&&norm(e.innerText)===target.title);
 const leaves=exact.filter(e=>!exact.some(x=>x!==e&&e.contains(x)));
 const cards=[...new Set(leaves.map(e=>e.closest('[class*="video-card-"]')).filter(Boolean))];
 const candidates=cards.slice(0,4).map(card=>{
   const links=Array.from(card.querySelectorAll('a[href]')).filter(visible).map(safeHref).filter(Boolean);
   const restrictions=Array.from(card.querySelectorAll('div,span,a,button')).filter(e=>visible(e)&&
      /^(查看详情|流量减少|审核中|已发布)$/.test(norm(e.innerText))).filter(e=>!Array.from(e.children).some(c=>visible(c)&&norm(c.innerText)===norm(e.innerText)));
   return {card_class:(card.getAttribute('class')||'').slice(0,300),text:text(card).slice(0,1800),
     canonical_post_id_observed:links.some(x=>x.origin==='https://www.douyin.com'&&x.path==='/video/'+target.post_id),
     public_links:links.slice(0,12),restriction_entries:restrictions.slice(0,12).map(desc)};
 });
 return {schema:'manual_republication_visible_inventory/v1',location:{origin:location.origin,path:location.pathname},
   ready_state:document.readyState,document_title:String(document.title||'').slice(0,300),
   visible_challenge_frames:Math.min(challengeFrames,10),
   visible_text_lines:lines,controls,declaration_controls:controls.filter(x=>/声明|AI|人工智能|虚构|推广|单选|多选/.test(x.text+' '+x.label+' '+x.aria_label)).slice(0,50),
   target:{...target,exact_caption_nodes:leaves.length,candidate_count:cards.length,candidates,
     exact_post_and_title_bound:cards.length===1&&candidates[0].canonical_post_id_observed},
   truncated:cut||visibleControls.length>100||cards.length>4,
   input_values_read:false,hidden_state_read:false,interaction_performed:false};
} """


def _creator_inventory(page, guard, target, view):
    samples, previous = [], None
    for _ in range(8):
        value = _rpc(guard, page.evaluate, inventory_script(target))
        _need(isinstance(value, dict) and value.get("schema") == "manual_republication_visible_inventory/v1"
              and value.get("input_values_read") is False and value.get("hidden_state_read") is False
              and value.get("interaction_performed") is False, "inspection_creator_surface_unconfirmed")
        _need(len(json.dumps(value, ensure_ascii=False).encode()) <= 192 * 1024,
              "inspection_inventory_too_large")
        text = " ".join(value.get("visible_text_lines", []))
        correct_location = value.get("location") == {"origin": "https://creator.douyin.com",
                                                     "path": "/creator-micro/content/" + view}
        login = any(word in text for word in ("扫码登录", "验证码登录", "请先登录", "登录抖音"))
        challenge = (value.get("visible_challenge_frames", 0) > 0
                     or any(word in text for word in ("拖动滑块", "安全验证", "完成验证", "验证后继续")))
        fingerprint = _digest(value)
        populated = bool(value.get("ready_state") in {"interactive", "complete"}
                         and value.get("controls") and len(value.get("visible_text_lines", [])) >= 3)
        stable = fingerprint == previous
        samples.append({"location": value.get("location"), "ready_state": value.get("ready_state"),
                        "visible_controls": len(value.get("controls", [])), "visible_lines": len(value.get("visible_text_lines", [])),
                        "fingerprint": fingerprint, "stable_with_previous": stable})
        value["readiness"] = {"render_ready": bool(correct_location and populated and stable and not login and not challenge),
                              "expected_location": correct_location, "login_observed": login,
                              "challenge_text_observed": challenge, "stable_with_previous": stable,
                              "business_surface_state": ("target_caption_visible" if view == "manage" and value.get("target", {}).get("candidate_count") == 1
                                  else "visible_file_control" if view == "upload" and any(x.get("tag") == "input" and x.get("type") == "file" for x in value.get("controls", []))
                                  else "not_confirmed"),
                              "submission_ready": False, "samples": list(samples)}
        if not correct_location or login or challenge or (populated and stable):
            return value
        previous = fingerprint
        _rpc(guard, page.wait_for_timeout, 250)
    return value


def run_action(actor, resource, config, request, outdir):
    """Inspect one fixed creator view, using only the existing manual Page."""
    authority = _guard(actor, resource, config, request)
    directory = Path(outdir).resolve()
    _need(directory.is_relative_to(ROOT / "data"), "inspection_output_directory_required")
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "INSPECTION_RESULT.json"
    subject = {"config": request["config"], "request_digest": _digest(request),
               "manual_command_id": config["manual_command_id"], "tab_id": config["tab_id"]}
    if result_path.exists():
        previous = _read(_reference(result_path))
        _need(previous["subject"] == subject, "inspection_existing_subject_changed")
        _read(previous["inspection"])
        return dict(previous, reused=True, current_freshness_claimed=False)
    original_owner = resource.session
    def guard():
        _need(resource.session is original_owner, "inspection_session_changed")
        return _guard(actor, resource, config, request)
    page = _rpc(guard, resource.session.get_page, config["tab_id"])
    _need(page.tab_id == config["tab_id"] and getattr(page, "_session", None) is original_owner, "inspection_page_changed")
    identity = _read_identity(page, guard, authority["expected_public_uid"])
    if identity["verified"]:
        target = _old_target(config, authority)
        _rpc(guard, page.goto, SITES[request["view"]])
        inventory = _creator_inventory(page, guard, target, request["view"])
    else:
        inventory = {"schema": "manual_republication_visible_inventory/v1", "identity_observation": identity,
                     "readiness": {"render_ready": False, "submission_ready": False,
                                   "reason_code": identity["reason_code"]}, "creator_navigation_performed": False}
    artifact = _write(directory / "VISIBLE_INVENTORY.json", inventory)
    result = {"schema": VERSION, "status": "observed_readonly", "action": "inspect_site", "view": request["view"],
              "subject": subject, "account_id": actor.account_id, "account_key": config["account_key"],
              "owner_id": actor.owner_id, "generation": actor.generation, "identity": identity,
              "inspection": artifact, "screenshot": {"status": "not_requested"}, "observed_at": time.time(),
              "render_ready": inventory["readiness"]["render_ready"],
              "read_only": True, "uploaded": False, "submitted": False,
              "declaration_selected": False, "declaration_verified_for_publication": False,
              "current_freshness_claimed": True,
              "limitations": ["SELF rendered UID does not independently prove creator account identity.",
                  "Visible declaration controls are inventoried, not selected or verified for publication.",
                  "A unique caption without a canonical post link remains a candidate, not an exact post binding.",
                  "An unready or empty inventory does not prove that declaration or marketing controls do not exist."]}
    guard()
    _write(result_path, result)
    return result
