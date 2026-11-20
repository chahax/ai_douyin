"""Streamlit controls use isolated QA files and fake process launchers."""
from pathlib import Path
from types import SimpleNamespace
import json
import socket
import subprocess
import sys
import ast

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from src.web import visual_assets_panel_v3 as panel
from src.web.components import auth


def admin(monkeypatch,role='admin'):
    monkeypatch.setattr(auth,'get_current_user',lambda:'qa-admin')
    monkeypatch.setattr(auth,'get_current_role',lambda:role)


def run_fixture(root):
    source=root/'data/script.md';source.parent.mkdir(parents=True,exist_ok=True);source.write_text('Bound script.')
    packet=dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path=str(source),sha256=panel.flow.file_sha(source)),
        characters=[dict(id='actor',name='QA actor',design_version='v1')],places=[],shots=[])
    run=panel.home(root)/'runs'/'qa_run';panel.flow.prepare(run,packet,panel.default_config(root));return run


def app(root):
    return AppTest.from_string('from src.web.visual_assets_panel_v3 import render\nrender('+repr(str(root))+')').run(timeout=30)


def button(a,label):return next(x for x in a.button if x.label==label)


def test_view_is_readonly_no_files_network_or_startup(tmp_path,monkeypatch):
    admin(monkeypatch);before=list(tmp_path.rglob('*'))
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('view network forbidden'))
    monkeypatch.setattr(panel.subprocess,'Popen',lambda *a,**k:pytest.fail('view spawn forbidden'))
    a=app(tmp_path);assert not a.exception and list(tmp_path.rglob('*'))==before
    assert button(a,'导入当前九人81张候选并建立任务').disabled is False


def test_viewer_controls_disabled_and_helpers_recheck_server_role(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch,'viewer');before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    a=app(tmp_path);assert not a.exception and all(b.disabled for b in a.button)
    for operation in [lambda:panel.prepare_current(tmp_path),lambda:panel.control_run(tmp_path,run,True),lambda:panel.launch_worker(tmp_path,run),lambda:panel.control_watch(tmp_path,True),lambda:panel.save_policy(tmp_path,{}),lambda:panel.launch_watch(tmp_path,'anything')]:
        with pytest.raises(PermissionError):operation()
    assert {str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before


def test_pause_and_resume_buttons_have_real_bound_effect(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);old=tmp_path/'data/video_generation/h3_old/PAUSE.json';panel.flow.write(old,dict(id='old'))
    calls,processes=fake_launch(tmp_path,monkeypatch)
    a=app(tmp_path);assert not a.exception
    button(a,'暂停后续资产任务').click().run(timeout=30)
    assert (run/'PAUSE.json').exists() and not a.exception
    button(a,'继续后续资产任务').click().run(timeout=30)
    assert not (run/'PAUSE.json').exists() and not a.exception and panel.read(old)==dict(id='old')
    assert len(calls)==1 and str(run) in calls[0][0]
    assert len(list((panel.home(tmp_path)/'audit').glob('*.json')))==3


def test_text_watch_pause_resume_and_save_disabled_policy_buttons(tmp_path,monkeypatch):
    admin(monkeypatch);a=app(tmp_path)
    button(a,'暂停文本自动接入').click().run(timeout=30);assert (panel.home(tmp_path)/'PAUSE.json').exists()
    button(a,'继续文本自动接入').click().run(timeout=30);assert not (panel.home(tmp_path)/'PAUSE.json').exists()
    button(a,'保存独立文本接入策略').click().run(timeout=30)
    saved=list((panel.home(tmp_path)/'policies').glob('*.json'));assert len(saved)==1 and panel.read(saved[0])['enabled'] is False
    assert not a.exception and not (panel.home(tmp_path)/'runs').exists()


def test_prepare_current_button_calls_native_import_as_candidates_idempotently(tmp_path,monkeypatch):
    admin(monkeypatch);seed=run_fixture(tmp_path);packet=panel.flow.status(seed)['plan']['packet'];packet['book_id']=panel.BOOK_ID
    cast=tmp_path/'data/image_model_trials/20261106_novel_cast_turnaround';panel.flow.write(cast/'CAST_PLAN.json',{'bound':'QA'})
    panel.flow.write(cast/'FINAL_MAP.json',dict(cast_plan_sha256=panel.flow.file_sha(cast/'CAST_PLAN.json')))
    monkeypatch.setattr(panel.flow,'packet_from_cast',lambda *a:packet)
    calls=[]
    def imported(*a,**kw):calls.append(kw);return dict(manifest_sha256='a'*64)
    monkeypatch.setattr(panel.library,'import_manifest',imported)
    a=app(tmp_path);button(a,'导入当前九人81张候选并建立任务').click().run(timeout=30)
    assert not a.exception and len(calls)==1 and calls[0]['verify_native'] is True
    first=set((panel.home(tmp_path)/'runs').iterdir())
    button(a,'导入当前九人81张候选并建立任务').click().run(timeout=30)
    assert set((panel.home(tmp_path)/'runs').iterdir())==first
    assert calls[0]['book_id']==panel.BOOK_ID


def fake_launch(root,monkeypatch):
    scripts=root/'scripts';scripts.mkdir(exist_ok=True);(scripts/'run_visual_asset_pipeline_v3.py').write_text('# QA entry')
    (scripts/'run_visual_asset_watch_v3.py').write_text('# QA watch entry')
    executable=root/'.venv/Scripts/pythonw.exe';executable.parent.mkdir(parents=True);executable.write_text('QA placeholder')
    processes={};calls=[]
    def popen(args,**options):
        calls.append((args,options));pid=1000+len(calls);processes[pid]=dict(pid=pid,create_time=float(pid),cmdline=args)
        return SimpleNamespace(pid=pid)
    monkeypatch.setattr(panel.subprocess,'Popen',popen);monkeypatch.setattr(panel,'_process',lambda pid:processes.get(pid));monkeypatch.setattr(panel,'_token_processes',lambda token:[p for p in processes.values() if token in p['cmdline']])
    return calls,processes


def test_start_worker_button_hidden_duplicate_and_native_receipt_not_overwritten(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    a=app(tmp_path);button(a,'启动资产执行器').click().run(timeout=30)
    assert not a.exception and len(calls)==1
    args,kw=calls[0];assert '--launch-id' in args and '--run' in args and str(run) in args
    assert kw['stdin']==panel.subprocess.DEVNULL and kw.get('shell',False) is False
    assert (run/'WORKER_PARENT_LAUNCH.json').exists() and not (run/'WORKER.json').exists()
    button(a,'启动资产执行器').click().run(timeout=30);assert len(calls)==1


def test_confirmed_old_worker_exit_allows_same_run_resume_preserving_native_unknown(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    panel.launch_worker(tmp_path,run);processes.clear()
    native=run/'image_jobs'/'unknown'/'CLAIM.json';panel.flow.write(native,dict(original='unknown'))
    second=panel.launch_worker(tmp_path,run)
    assert second['status']=='started' and len(calls)==2 and panel.read(native)==dict(original='unknown')
    assert list((run/'worker_history').glob('*/WORKER_PARENT_LAUNCH.json'))


def test_unconfirmed_launch_or_pid_collision_blocks_duplicate(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    panel.flow.write(run/'WORKER_LAUNCH_CLAIM.json',dict(id='orphan'))
    with pytest.raises(ValueError,match='未知'):panel.launch_worker(tmp_path,run)
    assert calls==[]
    (run/'WORKER_LAUNCH_CLAIM.json').unlink();panel.launch_worker(tmp_path,run)
    processes[1001]['create_time']=2.0
    with pytest.raises(ValueError,match='未知'):panel.launch_worker(tmp_path,run)
    assert len(calls)==1


def test_old_h3_paths_cannot_be_controls_target(tmp_path,monkeypatch):
    admin(monkeypatch);old=tmp_path/'data/video_generation/h3_old'
    for call in [lambda:panel.control_run(tmp_path,old,True),lambda:panel.launch_worker(tmp_path,old)]:
        with pytest.raises(ValueError,match='新资产'):call()
    assert not old.exists()


def test_preview_filters_use_registered_book_entity_view_status(tmp_path,monkeypatch):
    admin(monkeypatch);run_fixture(tmp_path);image=tmp_path/'qa.png';Image.new('RGB',(32,48),'gray').save(image)
    panel.library.register(tmp_path/'data/serial_story_assets',image,book_id='book1',entity_id='actor',kind='character',view='front',design_version='v1',input_sha256='a'*64)
    a=app(tmp_path);assert not a.exception
    assert next(s for s in a.selectbox if s.label=='资产书籍').value=='book1'
    next(s for s in a.selectbox if s.label=='人物或地点').select('actor').run(timeout=30)
    next(s for s in a.selectbox if s.label=='视图').select('front').run(timeout=30)
    assert not a.exception and a.get('imgs') is not None


def test_start_watch_button_passes_explicit_execution_choice(tmp_path,monkeypatch):
    from test_visual_asset_handoff_v3 import server
    from test_visual_asset_watch_v3 import fixture_policy
    admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        a=app(tmp_path);assert not a.exception
        next(c for c in a.checkbox if c.label=='接入后自动执行新资产任务').check().run(timeout=30)
        button(a,'启动文本接入执行器').click().run(timeout=30)
        assert not a.exception and len(calls)==1
        args,options=calls[0];assert '--watch' in args and '--execute' in args and str(path) in args and '--launch-id' in args
        assert fake.chats==[]


def test_worker_self_receipt_plan_and_argv_binding(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    panel.launch_worker(tmp_path,run);claim=panel.read(run/'WORKER_LAUNCH_CLAIM.json')
    args=calls[0][0];actual=dict(pid=2000,create_time=2000.0,cmdline=args,launch_id=claim['id'],plan_sha256=panel.flow.file_sha(run/'PLAN.json'))
    processes[2000]={k:actual[k] for k in ('pid','create_time','cmdline')};panel.flow.write(run/'WORKER.json',actual)
    assert panel.worker_state(run)['status']=='running'
    assert panel.launch_worker(tmp_path,run)['status']=='already_running' and len(calls)==1
    assert panel.read(run/'WORKER.json')['pid']==2000
    actual['plan_sha256']='0'*64;panel.flow.write(run/'WORKER.json',actual)
    with pytest.raises(ValueError,match='未知'):panel.launch_worker(tmp_path,run)
    assert len(calls)==1


def test_original_run_lock_still_held_blocks_relaunch(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    panel.launch_worker(tmp_path,run);processes.clear()
    with panel.images.run_lock(run):
        with pytest.raises(ValueError,match='run锁'):panel.launch_worker(tmp_path,run)
    assert len(calls)==1


def test_view_existing_workers_does_not_create_lock_or_network(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);args=['pythonw',str(tmp_path/'scripts/run_visual_asset_pipeline_v3.py'),'run','--run',str(run)]
    panel.flow.write(run/'WORKER.json',dict(pid=9,create_time=9.0,cmdline=args,plan_sha256=panel.flow.file_sha(run/'PLAN.json')))
    monkeypatch.setattr(panel,'_process',lambda pid:None)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()};snapshot=panel.snapshot(tmp_path)
    assert snapshot['runs'][0]['worker']['status']=='ended'
    assert {str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before


def test_role_change_after_render_cannot_execute_button(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);a=app(tmp_path)
    monkeypatch.setattr(auth,'get_current_role',lambda:'viewer')
    button(a,'暂停后续资产任务').click().run(timeout=30)
    assert not (run/'PAUSE.json').exists() and not a.exception


def test_known_process_creation_rejection_can_retry_without_losing_audit(tmp_path,monkeypatch):
    run=run_fixture(tmp_path);admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    popen=panel.subprocess.Popen
    monkeypatch.setattr(panel.subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(PermissionError('QA denial')))
    with pytest.raises(ValueError,match='明确拒绝'):panel.launch_worker(tmp_path,run)
    assert panel.worker_state(run)['status']=='ended'
    monkeypatch.setattr(panel.subprocess,'Popen',popen)
    assert panel.launch_worker(tmp_path,run)['status']=='started' and len(calls)==1
    assert list((run/'worker_history').glob('*/WORKER_LAUNCH_ERROR.json'))


def test_latest_unreviewed_version_still_counts_missing(tmp_path,monkeypatch):
    run=run_fixture(tmp_path)
    base=dict(entity_id='actor',kind='character',view='front',design_version='v1')
    rows=[dict(**base,asset_id='a',book_id='book1',version=1,status='reviewed',sha256='a'*64),dict(**base,asset_id='a',book_id='book1',version=2,status='candidate',sha256='b'*64)]
    monkeypatch.setattr(panel.library,'get',lambda *a,**k:[r for r in rows if r['view']==k.get('view','front')])
    data=panel.snapshot(tmp_path)
    assert not data['errors'] and len(data['runs'][0]['missing'])==9


def test_dependency_revision_invalidates_previously_reviewed_ui_views(tmp_path):
    run=run_fixture(tmp_path);config=panel.default_config(tmp_path);lib=config['library']
    def register(view,color,provenance=None):
        path=tmp_path/(view+color+'.png');Image.new('RGB',(32,48),color).save(path)
        row=panel.library.register(lib,path,book_id='book1',entity_id='actor',kind='character',view=view,design_version='v1',provenance=provenance)
        panel.library.review(lib,book_id='book1',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],decision='accepted',reviewer='fixture_protocol_only',checks={k:True for k in panel.library.REVIEW_CHECKS['character']},evidence=dict(image_sha256=row['sha256'],observations=['Protocol fixture only.']))
        return row
    first=register('front','gray');plan=panel.flow.status(run)['plan'];dependency=panel.flow._asset_identity(first)
    register('left_oblique','white',dict(dependencies=[dependency],dependency_fingerprint=panel.fingerprint([dependency])))
    before=panel.snapshot(tmp_path);assert not before['errors']
    assert not any(r['view']=='left_oblique' for r in before['runs'][0]['missing'])
    register('front','red')
    after=panel.snapshot(tmp_path);missing=after['runs'][0]['missing']
    assert any(r['view']=='left_oblique' and r['readiness']=='pending' and r['dependency_error']=='source_version_changed_or_unbound' for r in missing)


def test_resume_watch_only_restarts_previously_launched_policy_in_original_mode(tmp_path,monkeypatch):
    from test_visual_asset_handoff_v3 import server
    from test_visual_asset_watch_v3 import fixture_policy
    admin(monkeypatch);calls,processes=fake_launch(tmp_path,monkeypatch)
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        panel.launch_watch(tmp_path,path,execute=True);assert len(calls)==1
        processes.clear();panel.control_watch(tmp_path,True)
        other=dict(policy);other['user_statement']='Another saved but never launched policy.'
        panel.save_policy(tmp_path,other)
        result=panel.resume_watch(tmp_path)
        assert len(result)==1 and len(calls)==2 and '--execute' in calls[1][0]
        assert not (panel.home(tmp_path)/'PAUSE.json').exists() and fake.chats==[]


def test_native_cli_paused_qa_worker_writes_own_identity_and_known_exit(tmp_path):
    original=run_fixture(tmp_path);packet=panel.flow.status(original)['plan']['packet']
    base=tmp_path/'visual_asset_runs_v3';run=base/'paused_native'
    panel.flow.prepare(run,packet,panel.default_config(tmp_path))
    panel.flow.set_paused(run,True,actor='qa-native',role='admin')
    command=[sys.executable,'-B','scripts/run_visual_asset_pipeline_v3.py','run','--run',str(run),'--runs-root',str(base),'--launch-id','qa-native']
    process=subprocess.run(command,capture_output=True,text=True,timeout=30)
    assert process.returncode==0,process.stdout+process.stderr
    assert json.loads(process.stdout)['status']=='paused'
    worker=panel.read(run/'WORKER.json');ended=panel.read(run/'WORKER_EXIT.json')
    assert worker['pid']!=0 and worker['launch_id']=='qa-native' and worker['plan_sha256']==panel.flow.file_sha(run/'PLAN.json')
    assert ended['exit_known'] is True and ended['pid']==worker['pid'] and ended['status']=='paused'
    assert panel.worker_state(run)['status']=='ended'
    assert panel.read(run/'STATE.json')['jobs']=={} and not (tmp_path/'data/serial_story_assets').exists()
    # Re-enter the same paused run; no model or image call occurs in either process.
    command[-1]='qa-native-again';again=subprocess.run(command,capture_output=True,text=True,timeout=30)
    assert again.returncode==0 and panel.read(run/'WORKER.json')['launch_id']=='qa-native-again'
    assert len(list((run/'WORKER_EXITS').glob('*.json')))==2


def test_existing_video_page_preserves_old_renderer_and_mounts_new_panel(tmp_path,monkeypatch):
    from src.web import video_production_dashboard as dashboard
    from src.web import h3_manifest_progress
    from src.services import production_registry
    import src.operations_accounts as accounts
    admin(monkeypatch);old=[]
    monkeypatch.setattr(dashboard,'ROOT',tmp_path)
    monkeypatch.setattr(h3_manifest_progress,'render',lambda root:old.append(root))
    monkeypatch.setattr(production_registry,'list_projects',lambda *a,**kw:[])
    monkeypatch.setattr(accounts,'AccountProfileRepository',lambda:SimpleNamespace(list_active=lambda **kw:[]))
    a=AppTest.from_string('from src.web.video_production_dashboard import page_video_production\npage_video_production()').run(timeout=30)
    assert not a.exception and old==[tmp_path]
    assert button(a,'导入当前九人81张候选并建立任务').disabled is False
    assert not panel.home(tmp_path).exists()


def route_app(root):
    # Compile only the actual root-script wrapper; executing the entire app would
    # enter login/navigation and unrelated production account repositories.
    source='''import ast
from pathlib import Path
app_path=Path(APP_PATH)
tree=ast.parse(app_path.read_text(encoding='utf-8'))
wrapper=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='page_video_production')
namespace={'PROJECT_ROOT':Path(QA_ROOT)}
exec(compile(ast.Module(body=[wrapper],type_ignores=[]),str(app_path),'exec'),namespace)
namespace['page_video_production']()
'''.replace('APP_PATH',repr(str(panel.ROOT/'src/web/app.py'))).replace('QA_ROOT',repr(str(root)))
    return AppTest.from_string(source)


@pytest.mark.parametrize('cached_has_panel',[False,True])
def test_actual_root_wrapper_mounts_once_for_old_and_new_cached_dashboard(tmp_path,monkeypatch,cached_has_panel):
    from src.web import video_production_dashboard as dashboard
    import streamlit as st
    admin(monkeypatch);calls=[]
    def cached_dashboard():
        calls.append('main');st.write('Cached dashboard body')
        if cached_has_panel:
            panel.render(tmp_path)
            panel.render(tmp_path)  # An accidental second nested call is skipped.
    monkeypatch.setattr(dashboard,'page_video_production',cached_dashboard)
    a=route_app(tmp_path).run(timeout=30)
    assert not a.exception and len([b for b in a.button if b.label=='导入当前九人81张候选并建立任务'])==1
    assert panel._RENDER_SCOPE.get() is None and not panel.home(tmp_path).exists()
    a.run(timeout=30)
    assert not a.exception and len([b for b in a.button if b.label=='导入当前九人81张候选并建立任务'])==1
    assert calls==['main','main'] and panel._RENDER_SCOPE.get() is None


def test_route_scope_does_not_leak_between_sessions(tmp_path,monkeypatch):
    from src.web import video_production_dashboard as dashboard
    admin(monkeypatch)
    monkeypatch.setattr(dashboard,'page_video_production',lambda:None)
    first=route_app(tmp_path).run(timeout=30);second=route_app(tmp_path).run(timeout=30)
    for a in (first,second):
        assert not a.exception and len([b for b in a.button if b.label=='导入当前九人81张候选并建立任务'])==1
    first.run(timeout=30);second.run(timeout=30)
    for a in (first,second):
        assert not a.exception and len([b for b in a.button if b.label=='导入当前九人81张候选并建立任务'])==1
    assert panel._RENDER_SCOPE.get() is None and not panel.home(tmp_path).exists()


def test_nested_route_scope_deduplicates_and_cleans_on_failure(tmp_path,monkeypatch):
    admin(monkeypatch)
    source='''from src.web.visual_assets_panel_v3 import render_route,render
def outer():
    render_route(lambda:render(QA_ROOT),QA_ROOT)
render_route(outer,QA_ROOT)
'''.replace('QA_ROOT',repr(str(tmp_path)))
    a=AppTest.from_string(source).run(timeout=30)
    assert not a.exception and len([b for b in a.button if b.label=='导入当前九人81张候选并建立任务'])==1
    assert panel._RENDER_SCOPE.get() is None
    def failing():raise RuntimeError('QA route failure')
    with pytest.raises(RuntimeError,match='QA route failure'):panel.render_route(failing,tmp_path)
    assert panel._RENDER_SCOPE.get() is None
    b=AppTest.from_string('from src.web.visual_assets_panel_v3 import render_route\nrender_route(lambda:None,'+repr(str(tmp_path))+')').run(timeout=30)
    assert not b.exception and len([x for x in b.button if x.label=='导入当前九人81张候选并建立任务'])==1
