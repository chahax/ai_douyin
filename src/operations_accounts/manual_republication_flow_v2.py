"""Once-only media preparation on an existing manual Page. Never publishes.

The v2 runtime owns the global upload claim. This module selects its bound
media once, reuses existing upload/form leaf helpers, and records the actual
editor/declaration surface. No AI/declaration selection is performed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
import hashlib
import types
import marshal
from types import SimpleNamespace

from . import manual_republication_flow_v1 as inspect_v1
from src.platform_adapter.browser_session import Page
from src.platform_adapter.publish_verification import EDITORS, FICTION_NOTICE

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data/production_trials/fanqie_declared_republication_20261117_v1"
SCHEMA = "manual_republication_prepare_upload/v1"
TITLE_SELECTORS = ("input.semi-input[placeholder*='标题']", "input.semi-input[placeholder*='作品标题']",
                   ".semi-input-wrapper input.semi-input")
ENTRY = 'xpath=//*[normalize-space(.)="添加自主声明" and not(*[normalize-space(.)="添加自主声明"])]'
SAFE_REASONS = frozenset({"prepare_request_invalid", "prepare_metadata_invalid", "prepare_claim_changed",
    "prepare_session_changed", "prepare_deadline_reached", "prepare_same_page_required", "prepare_identity_unconfirmed",
    "prepare_upload_surface_unconfirmed", "prepare_file_selection_already_claimed", "prepare_rpc_not_allowed",
    "prepare_media_selection_not_allowed", "prepare_field_not_unique", "prepare_field_readback_unconfirmed",
    "prepare_upload_completion_unconfirmed", "prepare_editor_not_confirmed", "prepare_post_selection_unknown",
    "prepare_output_scope_invalid", "prepare_declaration_entry_ambiguous"})


class PrepareUploadBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def need(ok, code):
    if not ok:
        raise PrepareUploadBlocked(code)


def once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
        stream.flush();os.fsync(stream.fileno())
    return inspect_v1._reference(path)


def _load_leaves(config):
    """Compile exact pinned bytes privately; never patch cached/worker modules."""
    modules = {}
    paths = {"flow_v1": ROOT / "src/operations_accounts/manual_republication_flow_v1.py",
             "publish_workflow": ROOT / "src/platform_adapter/publish_workflow.py",
             "upload_diagnostic": ROOT / "src/platform_adapter/upload_surface_diagnostic.py"}
    for key, path in paths.items():
        ref = config["sources"][key]
        need(Path(ref["path"]).resolve() == path and inspect_v1._reference(path) == ref,"prepare_claim_changed")
        raw = path.read_bytes()
        need(hashlib.sha256(raw).hexdigest() == ref["sha256"],"prepare_claim_changed")
        package = "src.operations_accounts" if key == "flow_v1" else "src.platform_adapter"
        module = types.ModuleType(package + "._manual_prepare_" + key + "_" + ref["sha256"][:16])
        module.__package__, module.__file__ = package, str(path)
        exec(compile(raw, str(path), "exec"), module.__dict__)
        modules[key] = module
    modules["publish_workflow"].capture_upload_surface = modules["upload_diagnostic"].capture_upload_surface
    return modules["flow_v1"], modules["publish_workflow"].PublishWorkflow


def _metadata(config):
    value = inspect_v1._read(config["metadata"])
    authority = inspect_v1._read(config["authority"])
    fields = {"schema", "account_uuid", "account_key", "media", "title", "description", "hashtags",
              "ai_generated", "fictional_story", "visibility"}
    need(set(value) == fields and value["schema"] == "manual_republication_metadata/v1"
         and value["account_uuid"] == config["account_id"] and value["account_key"] == config["account_key"]
         and value["media"] == authority["media"] and value["ai_generated"] is True
         and value["fictional_story"] is True and value["visibility"] == "public"
         and isinstance(value["title"], str) and 0 < len(value["title"]) <= 200
         and isinstance(value["description"], str) and FICTION_NOTICE in value["description"]
         and len(value["description"]) <= 4000 and isinstance(value["hashtags"], list)
         and len(value["hashtags"]) == len(set(value["hashtags"])) == 5
         and all(isinstance(x, str) and re.fullmatch(r"\w+", x) for x in value["hashtags"]), "prepare_metadata_invalid")
    need(inspect_v1._reference(value["media"]["path"]) == value["media"], "prepare_metadata_invalid")
    return value, authority


UPLOAD_PROBE = r"""() => {
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&
  !e.closest('[hidden],[aria-hidden="true"]');
 const fs=Array.from(document.querySelectorAll('input[type="file"]'));
 const buttons=Array.from(document.querySelectorAll('button')).filter(e=>visible(e)&&(e.innerText||'').replace(/\s/g,'')==='上传视频');
 const editors=Array.from(document.querySelectorAll('[contenteditable="true"],div[data-slate-editor="true"]')).filter(visible);
 return {schema:'manual_upload_preselection/v1',origin:location.origin,path:location.pathname,
  file_count:fs.length,visible_file_count:fs.filter(visible).length,file_disabled:fs.length===1?fs[0].disabled:null,
  upload_button_count:buttons.length,editor_count:editors.length,input_values_read:false};
}"""

FIELD_PROBE = r"""el => ({schema:'manual_authorized_field/v1',visible:el.isConnected&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden',
 disabled:el.disabled===true,readonly:el.readOnly===true,tag:el.tagName.toLowerCase(),
 content:el.matches('input')?el.value:(el.innerText||'')})"""


def declaration_inventory_script():
    return r"""() => {
 const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'&&
   getComputedStyle(e).display!=='none'&&!e.closest('[hidden],[aria-hidden="true"]');
 const text=e=>String(e?.innerText||'').trim().replace(/\s+/g,' ').slice(0,700);
 const all=Array.from(document.querySelectorAll('button,label,input:not([type="hidden"]):not([type="password"]),textarea,select,[contenteditable="true"],[data-slate-editor],[role="dialog"],[role="option"],[role="listbox"],[role="radio"],[role="checkbox"],[role="switch"],[aria-multiselectable]')).filter(visible);
 const controls=all.slice(0,120).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',text:text(e),
  class_name:(e.getAttribute('class')||'').slice(0,240),type:(e.getAttribute('type')||'').slice(0,40),
  id:(e.getAttribute('id')||'').slice(0,160),name:(e.getAttribute('name')||'').slice(0,160),
  placeholder:(e.getAttribute('placeholder')||'').slice(0,240),data_placeholder:(e.getAttribute('data-placeholder')||'').slice(0,240),
  aria_label:(e.getAttribute('aria-label')||'').slice(0,240),contenteditable:e.getAttribute('contenteditable'),
  checked:e.matches('input[type="checkbox"],input[type="radio"]')?e.checked:null,
  aria_checked:e.getAttribute('aria-checked'),aria_selected:e.getAttribute('aria-selected'),
  aria_multiselectable:e.getAttribute('aria-multiselectable'),multiple:e.tagName==='SELECT'?e.multiple:null,
  disabled:e.matches(':disabled,[aria-disabled="true"]'),label:e.labels?[...e.labels].filter(visible).map(text).join(' ').slice(0,700):'',
  parent:{tag:e.parentElement?.tagName.toLowerCase()||'',role:e.parentElement?.getAttribute('role')||'',class_name:(e.parentElement?.getAttribute('class')||'').slice(0,240)}}));
 const lines=[];let n,count=0,truncated=false;const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 while((n=w.nextNode())){if(++count>20000){truncated=true;break}const p=n.parentElement;
   if(!visible(p)||p.closest('input,textarea,script,style,[role="textbox"]'))continue;
   const v=String(n.nodeValue||'').trim();if(v){if(lines.length<220)lines.push(v.slice(0,500));else truncated=true}}
 return {schema:'manual_editor_declaration_inventory/v1',location:{origin:location.origin,path:location.pathname},
  visible_text_lines:lines,controls,truncated:truncated||all.length>120,input_values_read:false,
  hidden_state_read:false,declaration_selected_by_this_action:false,submission_performed:false};
}"""


class GuardedOwner:
    """Existing RPC vocabulary only; no publication/AI selection command exists here."""
    def __init__(self, original, raw_page, guard, metadata, folder, claim):
        self.original,self.raw_page,self.guard,self.metadata,self.folder,self.claim = original,raw_page,guard,metadata,folder,claim
        self.selected=False;self.selection_armed=False;self.fields={};self.fills={};self.tags={};self.expand_armed=False;self.expanded=False

    def read(self, action, **kwargs):
        self.guard()
        result=self.original.cmd(action,tab_id=self.raw_page.tab_id,**kwargs)
        self.guard()
        return result

    def cmd(self, action, **kwargs):
        need(kwargs.pop("tab_id", self.raw_page.tab_id)==self.raw_page.tab_id,"prepare_same_page_required")
        self.guard()
        if action=="set_input_files":
            need(self.selection_armed and not self.selected and kwargs.get("selector")=="input[type=file]"
                 and kwargs.get("index",0) in (0,-1)
                 and Path(kwargs.get("file_path", "")).resolve()==Path(self.metadata["media"]["path"]).resolve(),
                 "prepare_media_selection_not_allowed")
            need(inspect_v1._reference(self.metadata["media"]["path"])==self.metadata["media"],"prepare_media_selection_not_allowed")
            surface=self.read("evaluate",selector="",index=-1,js=UPLOAD_PROBE).get("value",{})
            need(surface.get("origin")=="https://creator.douyin.com" and surface.get("path")=="/creator-micro/content/upload"
                 and surface.get("file_count")==surface.get("visible_file_count")==1 and surface.get("file_disabled") is False
                 and surface.get("upload_button_count")==1 and surface.get("editor_count")==0,"prepare_upload_surface_unconfirmed")
            once(self.folder/"FILE_SELECTION_INTENT.json",dict(schema="manual_file_selection_intent/v1",global_claim=self.claim,
                 media=self.metadata["media"],tab_id=self.raw_page.tab_id,automatic_reselection_allowed=False))
            self.selected=True
        elif action=="fill":
            selector=kwargs.get("selector");need(selector in self.fields and kwargs.get("value")==self.fields[selector]
                 and self.fills.get(selector,0)==0,"prepare_rpc_not_allowed")
            need(self.read("locator_count",selector=selector).get("count")==1,"prepare_field_not_unique")
            proof=self.read("evaluate",selector=selector,index=0,js=FIELD_PROBE).get("value",{})
            need(proof.get("visible") is True and not proof.get("disabled") and not proof.get("readonly"),"prepare_field_not_unique")
            self.fills[selector]=1
        elif action=="click":
            selector=kwargs.get("selector")
            if selector==ENTRY:
                need(self.expand_armed and not self.expanded,"prepare_rpc_not_allowed");self.expanded=True
            else:
                need(selector in self.fields and self.fields[selector]==self.metadata["description"],"prepare_rpc_not_allowed")
        elif action=="type_hashtag":
            tag=kwargs.get("tag");need(tag in self.metadata["hashtags"] and self.tags.get(tag,0)<2,"prepare_rpc_not_allowed")
            selectors=kwargs.get("selectors",[]);need(len(selectors)==1,"prepare_field_not_unique")
            chosen=[s for s,value in self.fields.items() if value==self.metadata["description"]]
            need(len(chosen)==1,"prepare_field_not_unique")
            same=self.read("evaluate",selector=selectors[0],index=0,
                js="el=>el===document.querySelector("+json.dumps(chosen[0])+")").get("value")
            need(same is True,"prepare_field_not_unique")
            self.tags[tag]=self.tags.get(tag,0)+1
        elif action=="goto":
            need(not self.selected and kwargs.get("url") in {inspect_v1.SELF_URL,inspect_v1.SITES["upload"]},"prepare_rpc_not_allowed")
        elif action=="screenshot":
            path=Path(kwargs.get("path", "")).resolve();need(path.is_relative_to(self.folder) and not path.exists(),"prepare_rpc_not_allowed")
        else:
            need(action in {"current_url","evaluate","locator_count","inner_text","get_attribute",
                            "wait_for_timeout","upload_check_proof"},"prepare_rpc_not_allowed")
        return self.read(action,**kwargs)


def _unique_field(page, selectors):
    for selector in selectors:
        count=page.locator(selector).count()
        if not count:continue
        need(count==1,"prepare_field_not_unique")
        proof=page.locator(selector).evaluate(FIELD_PROBE)
        need(proof.get("visible") is True and not proof.get("disabled") and not proof.get("readonly"),"prepare_field_not_unique")
        return selector
    raise PrepareUploadBlocked("prepare_editor_not_confirmed")


def run_action(actor, resource, config, request, outdir):
    from . import manual_republication_runtime_v2 as runtime
    need(set(request)=={"schema","config","action"} and request["schema"]=="manual_republication_operator_request/v2"
         and request["action"]=="prepare_upload","prepare_request_invalid")
    need(inspect_v1._read(request["config"])==config,"prepare_claim_changed")
    folder=Path(outdir).resolve();need(folder.is_relative_to(RUN.resolve()),"prepare_output_scope_invalid")
    folder.mkdir(parents=True,exist_ok=True)
    need(not (folder/"FILE_SELECTION_INTENT.json").exists(),"prepare_file_selection_already_claimed")
    metadata,authority=_metadata(config)
    claim_ref=inspect_v1._reference(RUN/"UPLOAD_CLAIM.json");claim=inspect_v1._read(claim_ref)
    bound_plan=inspect_v1._read(claim["plan"])
    need(claim.get("schema")=="manual_republication_upload_claim/v1" and claim.get("action")=="prepare_upload"
         and claim.get("config")==request["config"] and claim.get("authority")==config["authority"]
         and claim.get("metadata")==config["metadata"] and claim.get("media")==metadata["media"]
         and claim.get("owner_id")==actor.owner_id and claim.get("generation")==actor.generation
         and claim.get("tab_id")==config["tab_id"] and type(claim.get("submissions_allowed")) is int and claim["submissions_allowed"]==0
         and claim.get("actor_thread_id")==threading.get_ident()
         and inspect_v1._read(claim["request"])==request
         and bound_plan.get("schema")=="manual_republication_runtime_plan/v2"
         and bound_plan.get("config")==request["config"] and bound_plan.get("request")==claim["request"]
         and folder==Path(claim["plan"]["path"]).resolve().parent/"preparation","prepare_claim_changed")
    fresh_inspect, Workflow = _load_leaves(config)
    original=resource.session;started=time.monotonic();deadline=started+300
    def guard():
        reserve=max(15,float(getattr(original.config,"timeout_ms",30000))/1000+15)
        need(time.monotonic()+reserve<=deadline,"prepare_deadline_reached")
        need(resource.session is original and original._proc is not None and original._proc.poll() is None,"prepare_session_changed")
        runtime.validate_live(actor,resource,config)
        b=resource.runtime.bindings.get(config["account_key"]);p=resource.runtime.profiles.get(config["account_key"])
        need(b.account_uuid==p.account_uuid==config["account_id"]
             and inspect_v1._binding_version(SimpleNamespace(binding=b,profile=p))==config["binding_version"]
             and str(b.public_uid)==authority["expected_public_uid"],"prepare_session_changed")
        need(inspect_v1._reference(claim_ref["path"])==claim_ref,"prepare_claim_changed")
    guard();raw=original.get_page(config["tab_id"]);guard()
    need(raw.tab_id==config["tab_id"] and raw._session is original,"prepare_same_page_required")
    gate=GuardedOwner(original,raw,guard,metadata,folder,claim_ref);page=Page(gate,raw.tab_id)
    try:
        identity=fresh_inspect._read_identity(page,guard,authority["expected_public_uid"])
        need(identity["verified"],"prepare_identity_unconfirmed")
        page.goto(inspect_v1.SITES["upload"])
        probes=[]
        for _ in range(40):
            probe=page.evaluate(UPLOAD_PROBE);probes.append(probe)
            ready=(probe.get("origin")=="https://creator.douyin.com" and probe.get("path")=="/creator-micro/content/upload"
                   and probe.get("file_count")==probe.get("visible_file_count")==1
                   and probe.get("file_disabled") is False and probe.get("upload_button_count")==1 and probe.get("editor_count")==0)
            if ready:break
            page.wait_for_timeout(250)
        need(ready,"prepare_upload_surface_unconfirmed")
        surface=once(folder/"PRESELECTION_SURFACE.json",dict(schema="manual_upload_surface_observations/v1",samples=probes))
        workflow=Workflow(None)
        journal=folder/"UPLOAD_JOURNAL.jsonl"
        with journal.open("xb") as stream:stream.write(b"")
        workflow._journal_path=journal
        workflow._record("manual_prepare_bound",metadata=config["metadata"],global_claim=claim_ref,media=metadata["media"])
        gate.selection_armed=True
        workflow._upload_video_file(page,metadata["media"]["path"])
        need(workflow._wait_for_upload_complete(page,timeout=min(120,max(1,int(deadline-time.monotonic()-90)))),"prepare_upload_completion_unconfirmed")
        post_upload_editor=once(folder/"POST_UPLOAD_EDITOR.json",page.evaluate(declaration_inventory_script()))
        title_selector=_unique_field(page,TITLE_SELECTORS);editor_selector=_unique_field(page,EDITORS)
        gate.fields={title_selector:metadata["title"],editor_selector:metadata["description"]}
        workflow._fill_title(page,metadata["title"])
        title_read=page.locator(title_selector).evaluate(FIELD_PROBE)
        need(title_read.get("content")==metadata["title"],"prepare_field_readback_unconfirmed")
        workflow._fill_description(page,metadata["description"])
        desc_read=page.locator(editor_selector).evaluate(FIELD_PROBE)
        need(re.sub(r"\s+","",desc_read.get("content", ""))==re.sub(r"\s+","",metadata["description"]),"prepare_field_readback_unconfirmed")
        workflow._add_hashtags(page,metadata["hashtags"],expected_description=metadata["description"])
        workflow._confirm_hashtag_form(page,metadata["hashtags"],metadata["description"])
        need(page.locator(title_selector).count()==1 and page.locator(editor_selector).count()==1,"prepare_field_not_unique")
        title_read=page.locator(title_selector).evaluate(FIELD_PROBE)
        final_editor=workflow._hashtag_snapshot(page)
        need(title_read.get("content")==metadata["title"] and workflow._description_preserved(final_editor,metadata["description"])
             and all(tag in final_editor["tokens"] for tag in metadata["hashtags"]),"prepare_field_readback_unconfirmed")
        form_readback=once(folder/"FORM_READBACK.json",dict(title=title_read,editor_text=final_editor["text"],
            hashtag_tokens=list(final_editor["tokens"]),expected_hashtags=metadata["hashtags"],description_preserved=True))
        before=page.evaluate(declaration_inventory_script())
        before_ref=once(folder/"EDITOR_DECLARATIONS_BEFORE.json",before)
        entry=page.locator(ENTRY);count=entry.count()
        entry_proof={"count":count,"expanded":False,"reason":"not_unique_or_absent"}
        if count==1:
            entry_proof=entry.evaluate("""el=>({visible:el.isConnected&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden',
                tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',type:String(el.type||el.getAttribute('type')||''),
                haspopup:el.getAttribute('aria-haspopup')||'',expanded:el.getAttribute('aria-expanded')||''})""")
            expandable=(entry_proof.get("visible") is True
                and (entry_proof.get("tag")=="button" and entry_proof.get("type")!="submit" or entry_proof.get("role")=="button")
                and entry_proof.get("type") not in {"submit","reset"}
                and entry_proof.get("tag") not in {"label","input","select"}
                and entry_proof.get("role") not in {"checkbox","radio","option","switch"}
                and (entry_proof.get("haspopup") in {"true","dialog","menu","listbox"} or entry_proof.get("expanded") in {"true","false"}))
            if expandable:
                gate.expand_armed=True;entry.click(timeout=5000);page.wait_for_timeout(500)
            else:entry_proof["reason"]="native_expand_semantics_unconfirmed_no_click"
        after=page.evaluate(declaration_inventory_script());after_ref=once(folder/"EDITOR_DECLARATIONS_AFTER.json",after)
        need(after.get("schema")=="manual_editor_declaration_inventory/v1"
             and isinstance(after.get("controls"),list) and isinstance(after.get("visible_text_lines"),list)
             and after.get("location",{}).get("origin")=="https://creator.douyin.com"
             and after.get("location",{}).get("path", "").startswith("/creator-micro/content/")
             and after.get("input_values_read") is False and after.get("hidden_state_read") is False
             and after.get("submission_performed") is False,"prepare_editor_not_confirmed")
        guard()
        result={"schema":SCHEMA,"action":"prepare_upload","status":"prepared_not_submitted",
            "metadata":config["metadata"],"global_upload_claim":claim_ref,"file_selection_intent":inspect_v1._reference(folder/"FILE_SELECTION_INTENT.json"),
            "media":metadata["media"],"identity":identity,"preselection_surface":surface,
            "title_readback":title_read,"description_readback":desc_read,"hashtag_readback_verified":True,
            "form_readback":form_readback,
            "loaded_helpers":{"module":Workflow.__module__,"isolated_compile":True,
                "upload_code_sha256":hashlib.sha256(marshal.dumps(Workflow._upload_video_file.__code__)).hexdigest(),
                "wait_code_sha256":hashlib.sha256(marshal.dumps(Workflow._wait_for_upload_complete.__code__)).hexdigest()},
            "editor_before":before_ref,"editor_after":after_ref,"journal":inspect_v1._reference(journal),
            "post_upload_editor":post_upload_editor,
            "upload_attempted":True,"upload_completion_verified":True,"upload_ready":True,
            "metadata_readback_matched":True,"uploaded":True,"submitted":False,
            "declaration_entry_expanded":gate.expanded,"declaration_selected":False,"publication_ready":False,
            "declaration_entry_observation":entry_proof,
            "tab_id":raw.tab_id,"elapsed_seconds":round(time.monotonic()-started,3),
            "limits":["Metadata booleans are requirements, not checked platform declarations.",
                "Actual declaration choices and single/multiple-selection semantics require review of the saved inventory.",
                "No publish click; no file reselection after unknown. Old submission locks and old records are unchanged."]}
        once(folder/"PREPARED_RESULT.json",result);return result
    except Exception as error:
        code=("prepare_post_selection_unknown" if gate.selected else error.code if type(error) is PrepareUploadBlocked else "prepare_upload_surface_unconfirmed")
        failure={"schema":"manual_prepare_upload_failure/v1","reason_code":code,"error_type":type(error).__name__,
                 "cause_code":error.code if type(error) is PrepareUploadBlocked and error.code in SAFE_REASONS else None,
                 "upload_attempted":gate.selected,"upload_completion_claimed":False,"submitted":False,
                 "automatic_file_reselection_allowed":False,"global_upload_claim":claim_ref}
        path=folder/"PREPARE_FAILURE.json"
        if not path.exists():once(path,failure)
        raise PrepareUploadBlocked(code) from error
