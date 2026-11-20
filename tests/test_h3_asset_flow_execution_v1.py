"""Real offline compiler + local staging, with a fully mocked native service."""
from copy import deepcopy
import json
from pathlib import Path
import os

from PIL import Image
import pytest

from h3_asset_flow_fixture_v2 import build_fixture
from src.content_factory import h3_asset_flow_execution_v1 as x


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    spec, draft = build_fixture(tmp_path / 'source', mode='prompt_only')
    assert x.flow.prepare(spec, draft)['status'] == 'offline_draft_valid'
    input_root = tmp_path / 'input'; output_root = tmp_path / 'output'
    input_root.mkdir(); output_root.mkdir(); pause = tmp_path / 'old_PAUSE.json'; pause.write_text('{"preserve":true}', encoding='utf-8')
    cfg = dict(service_url='http://127.0.0.1:8190', input_root=str(input_root), output_root=str(output_root),
        gpu_lock_root=str(tmp_path / 'shared_gpu_lock'), protected_pause_path=str(pause),
        runs_root=str(tmp_path / 'visual_h3_v3'), timeout=20, video_enabled=True)
    # The production anchor comes from the authenticated guide's original PLAN.
    # Only its service environment is replaced for this isolated mock service.
    monkeypatch.setattr(x, '_service_anchor', lambda manifest: cfg)
    run = Path(cfg['runs_root']) / 'fresh_asset_state_S04'
    auth = tmp_path / 'AUTH.json'; auth.write_text('{"scope":"CPU mock only","real_model_calls":0}', encoding='utf-8')
    service = dict(posts=0, gets=[], queue=[], history={}, response=dict(prompt_id='controlled-execution-001'))
    def http(config, path, value=None):
        assert config['service_url'] == 'http://127.0.0.1:8190'
        if value is not None:
            assert path == '/prompt'; service['posts'] += 1
            if isinstance(service['response'], Exception):raise service['response']
            service['request'] = deepcopy(value); return deepcopy(service['response'])
        service['gets'].append(path)
        if path == '/system_stats':return dict(system=dict(argv=['main.py','--input-directory',str(input_root),'--output-directory',str(output_root)]))
        if path == '/queue':return dict(queue_running=service['queue'], queue_pending=[])
        if path.startswith('/history/'):return deepcopy(service['history'])
        raise AssertionError('unexpected mock-only route ' + path)
    monkeypatch.setattr(x.native, '_http', http)
    return dict(run=run, draft=draft, cfg=cfg, auth=x.bind(auth), service=service, tmp=tmp_path)


def start(fixture):
    return x.prepare(fixture['run'], fixture['draft'], fixture['cfg'], authorization=fixture['auth'])


def approve(fixture):
    x._freeze(fixture['run'] / 'LAUNCH_APPROVAL.json', dict(schema=x.LAUNCH, request=x.launch_request(fixture['run']),
        approved_by='root', evidence=['Actual graph/manifest/inputs inspected in isolated CPU fixture; no real submission.']))


def test_preparation_rebases_every_image_save_and_stages_actual_SHA_RGB(prepared):
    f = prepared; assert start(f)['status'] == 'prepared' and f['service']['posts'] == 0
    run, plan, row, folder = x._load(f['run']); graph = x.read(folder / 'workflow_api.json')
    receipt = x.read(run / 'STAGING_RECEIPT.json'); original = x.read(f['draft'] / 'DRAFT_WORKFLOW.json')
    assert len(receipt['inputs']) == 9 and graph['guide_start']['inputs']['image'] == ['ref_8',0]
    for i, item in enumerate(receipt['inputs']):
        assert graph['ref_' + str(i)]['inputs']['image'] == item['input_name']
        assert item['source']['sha256'] == item['staged']['sha256'] and item['source']['rgb_sha256'] == item['staged']['rgb_sha256']
        assert Path(item['staged']['path']).is_relative_to(Path(f['cfg']['input_root']))
        assert item['input_name'].startswith(row['scope'] + '/')
    restored = deepcopy(graph)
    for i in range(9):restored['ref_' + str(i)] = original['ref_' + str(i)]
    for role in ('video','audio','first','last'):restored['save_' + role] = original['save_' + role]
    assert restored == original
    assert graph['condition']['inputs']['prompt'] == original['condition']['inputs']['prompt']
    assert x.prepare(f['run'], f['draft'], f['cfg'], authorization=f['auth'])['status'] == 'prepared'
    assert (run / 'LAUNCH_REQUEST.json').is_file() and not (folder / 'CLAIM.json').exists()


def test_missing_or_changed_Root_approval_never_posts(prepared):
    start(prepared)
    with pytest.raises(FileNotFoundError):x.submit(prepared['run'])
    request = x.launch_request(prepared['run']); request['shot_id'] = 'wrong'
    x._freeze(prepared['run'] / 'LAUNCH_APPROVAL.json', dict(schema=x.LAUNCH,request=request,approved_by='root',evidence=['fixture']))
    with pytest.raises(ValueError, match='Root_launch'):x.submit(prepared['run'])
    assert prepared['service']['posts'] == 0


def test_unknown_POST_is_claimed_once_and_never_reposted(prepared):
    start(prepared); approve(prepared); prepared['service']['response'] = TimeoutError('controlled timeout')
    assert x.submit(prepared['run'])['status'] == 'outcome_unknown'
    assert x.submit(prepared['run'])['status'] == 'outcome_unknown'
    assert x.collect_known(prepared['run'])['status'] == 'outcome_unknown'
    assert prepared['service']['posts'] == 1


def test_nonroot_approval_is_rejected_before_claim_or_POST(prepared):
    start(prepared)
    x._freeze(prepared['run'] / 'LAUNCH_APPROVAL.json', dict(schema=x.LAUNCH,
        request=x.launch_request(prepared['run']), approved_by='background-worker', evidence=['Not the Root dispatch owner.']))
    with pytest.raises(ValueError, match='Root_launch'):x.submit(prepared['run'])
    assert prepared['service']['posts'] == 0
    _,_,_,folder=x._load(prepared['run'])
    assert not (folder/'CLAIM.json').exists()


@pytest.mark.parametrize('response', [[], {}, dict(prompt_id='not/a/UUID')])
def test_malformed_200_response_preserves_unknown_claim(prepared, response):
    start(prepared); approve(prepared); prepared['service']['response'] = response
    assert x.submit(prepared['run'])['status'] == 'outcome_unknown'
    assert x.submit(prepared['run'])['status'] == 'outcome_unknown' and prepared['service']['posts'] == 1


def test_staged_mtime_changed_with_same_SHA_blocks_before_claim(prepared):
    start(prepared); approve(prepared); receipt = x.read(prepared['run'] / 'STAGING_RECEIPT.json')
    p = Path(receipt['inputs'][3]['staged']['path']); stat = p.stat(); os.utime(p, ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
    with pytest.raises(ValueError, match='SHA_mtime_or_RGB'):x.submit(prepared['run'])
    assert prepared['service']['posts'] == 0


def test_all_reference_SHA_is_rechecked_not_only_guide(prepared):
    start(prepared); approve(prepared); receipt = x.read(prepared['run'] / 'STAGING_RECEIPT.json')
    Path(receipt['inputs'][0]['staged']['path']).write_bytes(b'corrupt non-guide reference')
    with pytest.raises(Exception):x.submit(prepared['run'])
    assert prepared['service']['posts'] == 0


def test_queue_busy_service_mismatch_and_pause_preserved(prepared, monkeypatch):
    start(prepared); approve(prepared); prepared['service']['queue'] = [[0,'other-id',{}]]
    assert x.submit(prepared['run'])['dispatch'] == 'waiting_gpu_queue' and prepared['service']['posts'] == 0
    prepared['service']['queue'] = []
    original = x.native._http
    def wrong(config,path,value=None):
        if path == '/system_stats':return dict(system=dict(argv=['--input-directory','D:/wrong','--output-directory','D:/wrong']))
        return original(config,path,value)
    monkeypatch.setattr(x.native,'_http',wrong)
    with pytest.raises(ValueError, match='wrong_h3_service_paths'):x.submit(prepared['run'])
    assert prepared['service']['posts'] == 0 and Path(prepared['cfg']['protected_pause_path']).read_text(encoding='utf-8') == '{"preserve":true}'


def test_endpoint_and_shared_lock_scope_cannot_change(prepared):
    cfg = deepcopy(prepared['cfg']); cfg['service_url'] = 'http://localhost:8190'
    with pytest.raises(ValueError, match='8190'):x.prepare(prepared['run'],prepared['draft'],cfg,authorization=prepared['auth'])
    cfg = deepcopy(prepared['cfg']);cfg['gpu_lock_root'] = str(prepared['tmp'] / 'different_lock')
    with pytest.raises(ValueError, match='preserve_original'):x.prepare(prepared['run'],prepared['draft'],cfg,authorization=prepared['auth'])
    assert prepared['service']['posts'] == 0


def test_collector_only_original_UUID_and_history_graph(prepared):
    start(prepared); approve(prepared); result = x.submit(prepared['run']); pid = result['prompt_id']
    with pytest.raises(ValueError, match='original_native_UUID'):x.collect_known(prepared['run'],'different')
    _,_,row,folder = x._load(prepared['run']); graph = x.read(folder/'workflow_api.json'); changed = deepcopy(graph)
    changed['129']['inputs']['noise_seed'] += 1
    prepared['service']['history'] = {pid:dict(prompt=[0,pid,changed],status=dict(completed=True,status_str='success'),outputs={})}
    with pytest.raises(ValueError, match='history'):x.collect_known(prepared['run'],pid)
    assert prepared['service']['posts'] == 1 and not (folder/'RESULT.json').exists()


def test_collects_four_mock_originals_with_native_schema_and_idempotent_ledger(prepared, monkeypatch):
    start(prepared); approve(prepared); pid = x.submit(prepared['run'])['prompt_id']
    run,plan,row,folder = x._load(prepared['run']); output = Path(plan['config']['output_root']) / row['scope'];output.mkdir(parents=True)
    outputs = {}
    for role, suffix, key in [('video','.mp4','images'),('audio','.flac','audio'),('first','.png','images'),('last','.png','images')]:
        name=role+'_00001_'+suffix if role!='audio' else 'audio_00001.flac';path=output/name
        if role in ('first','last'):Image.new('RGB',(736,1312),'gray').save(path)
        else:path.write_bytes(b'CPU mock container; not playable generated media')
        outputs['save_'+role] = {key:[dict(type='output',filename=name,subfolder=row['scope'])]}
    graph=x.read(folder/'workflow_api.json'); observed=deepcopy(graph);observed['130']['inputs']['fps']=24.0
    prepared['service']['history']={pid:dict(prompt=[0,pid,observed],status=dict(completed=True,status_str='success'),outputs=outputs)}
    monkeypatch.setattr(x.native,'_metadata',lambda path:dict(streams=[dict(codec_type='audio')] if str(path).endswith('.flac') else [
        dict(codec_type='video',width=736,height=1312,nb_frames='362',r_frame_rate='24/1'),dict(codec_type='audio')]))
    assert x.collect_known(run,pid)['status']=='technical_saved'
    result=x.read(folder/'RESULT.json');assert result['schema']==x.native.SCHEMA and set(result['files'])=={'video','audio','first','last'}
    assert result['prompt_id']==pid and result['production_approved'] is False
    assert x.collect_known(run,pid)['status']=='technical_saved' and prepared['service']['posts']==1
    assert (run/'job_ids.txt').read_text(encoding='utf-8').splitlines()==['S04 '+pid]


def test_collect_known_keeps_original_ID_when_upstream_changes(prepared):
    start(prepared);approve(prepared);pid=x.submit(prepared['run'])['prompt_id']
    manifest=x.read(prepared['draft']/'INPUT_MANIFEST.json');source=Path(manifest['references'][0]['image']['path'])
    # Never touch a real shared asset: invalidate only this draft CHECK binding.
    check=prepared['draft']/'CHECK_RESULT.json';check.write_text('{}',encoding='utf-8')
    prepared['service']['queue']=[[0,pid,prepared['service']['request']['prompt']]]
    assert x.collect_known(prepared['run'],pid)['status']=='running' and prepared['service']['posts']==1
