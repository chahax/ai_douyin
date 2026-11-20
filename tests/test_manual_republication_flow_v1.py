"""Private protocol fixtures and a local rendered DOM; no real account/browser."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import manual_republication_flow_v1 as flow


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf8")
    return flow._reference(path)


def inventory(view="manage", *, populated=True, location=None):
    return {"schema": "manual_republication_visible_inventory/v1",
            "location": location or {"origin": "https://creator.douyin.com", "path": "/creator-micro/content/" + view},
            "ready_state": "complete", "visible_text_lines": ["作品管理", "声明", "作品列表"] if populated else [],
            "controls": [{"tag": "button", "type": "", "text": "声明"}] if populated else [],
            "target": {"candidate_count": 0}, "visible_challenge_frames": 0,
            "input_values_read": False, "hidden_state_read": False, "interaction_performed": False}


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "ROOT", tmp_path)
    data = tmp_path / "data";data.mkdir()
    binding = NS(account_uuid="account:test", account_key="novel-test", platform_identity_key="public_uid:75891235130",
                 browser_environment_key="original", browser_profile_dir="private-profile", storage_state_path="unused",
                 confirmed_by="user", created_at="bound", public_uid="75891235130")
    profile = NS(account_uuid=binding.account_uuid, profile_version=1)
    context = NS(account_uuid=binding.account_uuid, account_key=binding.account_key, binding=binding, profile=profile)
    version = flow._binding_version(context)
    authority = put(data / "AUTH.json", {"schema": "explicit_republication_intent/v1", "user_statement": "重新提交但加声明",
        "account_uuid": binding.account_uuid, "account_key": binding.account_key, "expected_public_uid": binding.public_uid,
        "old_post_id": "7709043480894524722", "new_publication_limit": 1, "old_records_unchanged": True,
        "media": {"path": str(data / "original.mp4"), "sha256": "same-media-sha"}})
    browser_db = data / "browser.db"
    with sqlite3.connect(browser_db) as db:
        db.execute("CREATE TABLE browser_control_commands(command_id TEXT,account_id TEXT,kind TEXT,state TEXT,payload TEXT,result TEXT)")
        db.execute("INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?)", ("original-publish", binding.account_uuid,
            "publish", "succeeded", json.dumps({"video_sha256": "same-media-sha", "request": {"title": "两分钟原作品"}}),
            json.dumps({"post_id": "7709043480894524722"})))
    control_db = data / "control.db"
    with sqlite3.connect(control_db) as db:
        db.execute("CREATE TABLE account_controls(account_uuid TEXT,state TEXT,revision INTEGER)")
        db.execute("INSERT INTO account_controls VALUES(?,?,?)", (binding.account_uuid, "paused", 61))
    manual = dict(command_id="manual-original", kind="manual", state="waiting_human", owner_id="original-owner", generation=33,
        account_id=binding.account_uuid, binding_version=version, payload={"account_key": binding.account_key, "account_uuid": binding.account_uuid},
        priority=300, result={"tab_id": "original-tab"})
    manual["request_sha"] = flow._digest([manual[k] for k in ("account_id", "binding_version", "kind", "payload", "priority")])
    events = []
    class Page:
        tab_id = "original-tab"
        def goto(self, url):events.append(("goto", url))
        def evaluate(self, script):
            events.append(("evaluate", "uid" if script == flow.UID_JS else "inventory"))
            if hook[0]:hook[0]()
            if script == flow.UID_JS:
                return {"origin": "https://www.douyin.com", "path": "/user/self", "public_uids": list(uids),
                        "truncated": False, "source": "rendered_public_uid_text", "input_values_read": False}
            v = snapshots.pop(0) if snapshots else inventory(view[0]);return deepcopy(v)
        def wait_for_timeout(self, ms):events.append(("wait", ms))
    owner = NS(active=True, _closed=False, _proc=NS(poll=lambda: None), worker_failure=lambda: "", config=NS(headless=False))
    page = Page();page._session = owner
    owner.get_page = lambda tab: (events.append(("get_page", tab)) or page)
    actor = NS(account_id=binding.account_uuid, owner_id="original-owner", generation=33, binding_version=version, _stack=[],
               store=NS(get=lambda cid: deepcopy(manual)), _assert_thread=lambda: None, _check_owner=lambda: None)
    runtime = NS(bindings=NS(get=lambda key: binding), profiles=NS(get=lambda key: profile),
                 resolve=lambda *a, **k: pytest.fail("inspect must not resolve/warm up account"),
                 verify_identity=lambda *a, **k: pytest.fail("inspect must not persist identity/cookies"))
    resource = NS(account_uuid=binding.account_uuid, context=context, session=owner, runtime=runtime,
                  manual_tasks={"manual-original": "original-tab"}, console_tasks={})
    source = data / "source.py";source.write_text("# private pinned source\n")
    config = dict(account_id=actor.account_id, account_key=binding.account_key, owner_id=actor.owner_id,
        generation=33, binding_version=version, authority=authority, browser_db=str(browser_db), control_db=str(control_db),
        control_snapshot={"state": "paused", "revision": 61}, manual_command_id="manual-original",
        manual_request_sha256=manual["request_sha"], tab_id="original-tab", sources={"flow": flow._reference(source)})
    config_ref = put(data / "CONFIG.json", config)
    request = dict(schema="manual_republication_operator_request/v1", config=config_ref, action="inspect_site", view="manage")
    uids, snapshots, hook, view = [binding.public_uid], [], [None], ["manage"]
    return NS(actor=actor, resource=resource, config=config, request=request, out=data / "out", events=events,
              owner=owner, page=page, manual=manual, uids=uids, snapshots=snapshots, hook=hook, view=view, control_db=control_db)


@pytest.mark.parametrize("view", ["manage", "upload"])
def test_same_live_tab_only_fixed_readonly_navigation_and_cache(case, view):
    x=case;x.request["view"]=view;x.view[0]=view
    before=deepcopy(x.manual);result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert result["read_only"] and not result["uploaded"] and not result["submitted"] and result["render_ready"]
    assert result["identity"]["verified"] and not result["identity"]["health_or_cookie_persisted"]
    assert not result["identity"]["creator_identity_independently_verified"]
    assert [e[1] for e in x.events if e[0]=="goto"]==[flow.SELF_URL,flow.SITES[view]]
    assert x.manual==before
    count=len(x.events);cached=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert cached["reused"] and cached["current_freshness_claimed"] is False and len(x.events)==count


def test_empty_spa_waits_then_rendered_snapshot_stabilizes(case):
    x=case;x.snapshots.extend([inventory(populated=False),inventory(populated=False),inventory(),inventory()])
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    data=flow._read(result["inspection"])
    assert result["render_ready"] and len(data["readiness"]["samples"])==4


@pytest.mark.parametrize("kind", ["empty", "login", "challenge"])
def test_unready_or_redirected_surface_is_evidence_not_submission_readiness(case,kind):
    x=case
    v=inventory(populated=False) if kind=="empty" else inventory()
    if kind=="login":v["location"]={"origin":"https://creator.douyin.com","path":"/login"};v["visible_text_lines"]=["扫码登录"]
    if kind=="challenge":v["visible_challenge_frames"]=1
    x.snapshots.extend([v]*8)
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    data=flow._read(result["inspection"])
    assert result["render_ready"] is False and data["readiness"]["submission_ready"] is False


def test_ambiguous_self_uid_records_blocked_inspection_without_creator_navigation(case):
    x=case;x.uids.append("123456789")
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert not result["identity"]["verified"] and not result["render_ready"]
    assert [e[1] for e in x.events if e[0]=="goto"]==[flow.SELF_URL]


@pytest.mark.parametrize("change", ["session", "control", "tab"])
def test_fresh_rpc_guard_stops_changed_session_control_or_manual_tab(case, change):
    x=case
    def alter():
        x.hook[0]=None
        if change=="session":x.resource.session=NS(**vars(x.owner))
        elif change=="tab":x.manual["result"]["tab_id"]="other-tab"
        else:
            with sqlite3.connect(x.control_db) as db:db.execute("UPDATE account_controls SET revision=revision+1")
    x.hook[0]=alter
    with pytest.raises(flow.InspectionBlocked):flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert len([e for e in x.events if e[0]=="evaluate"])==1
    assert not any(e==( "goto",flow.SITES["manage"]) for e in x.events)


def test_write_action_rejected_before_any_page_rpc(case):
    x=case;x.request["action"]="submit"
    with pytest.raises(flow.InspectionBlocked) as error:flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert error.value.code in flow.BLOCK_REASONS and x.events==[]


def test_local_rendered_sibling_uid_and_visible_control_inventory_without_values(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(tmp_path/"local-only-profile"),channel="chrome",headless=True,
            args=["--mute-audio","--disable-background-networking"])
        context.route("**/*",lambda route:route.fulfill(status=200,content_type="text/html",body="<html><body></body></html>"))
        page=context.new_page();page.goto(flow.SELF_URL)
        page.set_content('<section><div><span>抖音号：</span><span>75891235130</span></div></section><div hidden>抖音号：11111111</div>')
        assert page.evaluate(flow.UID_JS)["public_uids"]==["75891235130"]
        page.goto(flow.SITES["upload"])
        page.set_content('<main><h1>发布作品</h1><label><input type="checkbox" checked>AI内容声明</label>'
            '<input placeholder="标题" value="do-not-read"><input type="password" value="secret"><button>提交</button><div hidden>hidden secret</div></main>')
        page.evaluate("""()=>{Object.defineProperty(HTMLInputElement.prototype,'value',{get(){throw Error('value read')},set(){throw Error('value write')}});window.clicks=0;document.addEventListener('click',()=>window.clicks++,true)}""")
        data=page.evaluate(flow.inventory_script({"post_id":"7709043480894524722","title":"两分钟原作品"}))
        assert data["input_values_read"] is False and data["hidden_state_read"] is False
        assert "secret" not in json.dumps(data) and "do-not-read" not in json.dumps(data)
        assert [x for x in data["controls"] if x["type"]=="checkbox"][0]["checked"] is True
        assert page.evaluate("()=>window.clicks")==0
        context.close()
