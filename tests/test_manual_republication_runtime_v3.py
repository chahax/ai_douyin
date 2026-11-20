"""Four narrow current-page bridge regressions; private v2 Store fixture reuse."""
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import manual_republication_runtime_v3 as bridge

_support_path = Path(__file__).with_name('test_manual_republication_runtime_v2.py')
_spec = importlib.util.spec_from_file_location('_manual_v2_private_fixture', _support_path)
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
v2_case = _support.case

FLOW = '''def run_action(actor,resource,config,request,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    with (outdir/'OBSERVED_ONCE').open('x') as f:f.write('only local protocol observation')
    return {'schema':'manual_republication_observation/v3','action':'observe_current',
      'uploaded':False,'submitted':False,'input_performed':False,'navigation_performed':False,'file_selected':False}
'''


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return bridge.reference(path)


@pytest.fixture
def case(v2_case, monkeypatch):
    c = v2_case
    monkeypatch.setattr(bridge, 'ROOT', bridge.v2.ROOT)
    monkeypatch.setattr(bridge, 'RUN', c.run)
    monkeypatch.setattr(bridge, 'ARM', c.run / 'runtime_v3/ARM.json')
    old_plan = bridge.v2.prepare(c.config_ref, c.request_ref, c.run / 'old_upload')
    claim = dict(schema='manual_republication_upload_claim/v1', action='prepare_upload', plan=old_plan,
        config=c.config_ref, request=c.request_ref, authority=c.config['authority'], metadata=c.config['metadata'],
        media=bridge._read(c.config['authority'])['media'], owner_id=c.actor.owner_id,
        generation=c.actor.generation, tab_id=c.config['tab_id'], submissions_allowed=0)
    prior_claim = put(c.run / 'UPLOAD_CLAIM.json', claim)
    folder = Path(old_plan['path']).parent
    failure = dict(schema='manual_prepare_upload_failure/v1', global_upload_claim=prior_claim,
        error_type='BrowserNavigationTimeout', reason_code='prepare_upload_surface_unconfirmed',
        upload_attempted=False, submitted=False, upload_completion_claimed=False)
    prior_failure = put(folder / 'preparation/PREPARE_FAILURE.json', failure)
    put(folder / 'UNKNOWN.json', dict(schema='manual_republication_upload_unknown/v1', claim=prior_claim,
        plan=old_plan, status='outcome_unknown', scope='upload_preparation', automatic_replay_allowed=False))
    paths = dict(bridge.v2.SOURCE_PATHS)
    for name in ('runtime_v3', 'flow_v3'):
        path = bridge.v2.ROOT / 'src/operations_accounts' / (name + '.py')
        path.write_text(FLOW if name == 'flow_v3' else '# reviewed v3', encoding='utf-8')
        paths[name] = path
    monkeypatch.setattr(bridge, 'SOURCE_PATHS', paths)
    config = dict(c.config, schema=bridge.CONFIG_SCHEMA,
        sources={name: bridge.reference(path) for name, path in paths.items()})
    config_ref = put(c.run / 'CONFIG_V3.json', config)
    request = dict(schema=bridge.REQUEST_SCHEMA, config=config_ref, action='observe_current',
        prior_upload_claim=prior_claim, prior_failure=prior_failure)
    request_ref = put(c.run / 'REQUEST_V3.json', request)
    return NS(**{**vars(c), 'config': config, 'config_ref': config_ref, 'request': request,
        'request_ref': request_ref, 'prior_claim': prior_claim, 'prior_failure': prior_failure,
        'failure': failure, 'old_plan': old_plan, 'paths_v3': paths})


def arm(c):
    ref = bridge.prepare(c.config_ref, c.request_ref, c.run / 'observe_001')
    put(bridge.ARM, dict(schema='manual_republication_runtime_arm/v3', plan=ref))
    return ref


def test_same_original_observation_once_no_old_record_changes(case):
    manual = case.store.get(case.manual['command_id'])
    old = {ref['path']: Path(ref['path']).read_bytes() for ref in
           (case.prior_claim, case.prior_failure, case.old_plan)}
    assert bridge.install_if_armed() == {'status': 'not_armed'}
    for action in ('resume_prepare_upload', 'submit_once'):
        bad = put(case.run / (action + '.json'), dict(case.request, action=action))
        with pytest.raises(ValueError, match='current_page_only'):
            bridge.prepare(case.config_ref, bad, case.run / action)
    ref = arm(case)
    assert bridge.install_if_armed()['status'].startswith('callback_registered')
    assert not (Path(ref['path']).parent / 'ACTION_CLAIM.json').exists()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'observed_current'
    assert bridge.install_if_armed()['status'] == 'observed_current'
    assert case.store.get(case.manual['command_id']) == manual
    assert all(Path(path).read_bytes() == raw for path, raw in old.items())
    assert not (case.run / 'FILE_SELECTED.json').exists()


def test_zero_file_proof_cannot_be_inferred_or_borrowed(case):
    bad_failure = put(Path(case.prior_failure['path']), dict(case.failure, upload_attempted=True))
    bad_request = put(case.run / 'bad_request.json', dict(case.request, prior_failure=bad_failure))
    with pytest.raises(ValueError, match='known_preselection'):
        bridge.prepare(case.config_ref, bad_request, case.run / 'bad_proof')
    put(Path(case.prior_failure['path']), case.failure)
    (Path(case.prior_failure['path']).parent / 'FILE_SELECTION_INTENT.json').write_text('{}')
    with pytest.raises(ValueError, match='known_preselection'):
        bridge.prepare(case.config_ref, case.request_ref, case.run / 'selection_exists')


def test_wrong_thread_never_touches_ordinary_poll_or_page(case):
    ref = arm(case)
    bridge.install_if_armed()
    case.actor._thread_id = threading.get_ident() + 1
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert not case.events
    assert bridge.status(ref)['status'] == 'prepared'
    assert not (Path(ref['path']).parent / 'ACTION_CLAIM.json').exists()


def test_current_read_lost_ack_keeps_named_claim_no_replay(case):
    case.paths_v3['flow_v3'].write_text('''
class ObservationBlocked(ValueError):
    def __init__(self):self.code='observation_surface_unconfirmed';super().__init__('private page text')
SAFE_REASONS=frozenset({'observation_surface_unconfirmed'})
def run_action(*a):raise ObservationBlocked()
''', encoding='utf-8')
    case.config['sources']['flow_v3'] = bridge.reference(case.paths_v3['flow_v3'])
    case.config_ref = put(case.run / 'CONFIG_V3.json', case.config)
    case.request_ref = put(case.run / 'REQUEST_V3.json', dict(case.request, config=case.config_ref))
    ref = arm(case)
    bridge.install_if_armed()
    case.namespace['_poll_manual_windows'](case.actor, case.resource)
    assert bridge.status(ref)['status'] == 'outcome_unknown'
    assert bridge.install_if_armed()['status'] == 'outcome_unknown'
    assert bridge.reference(case.prior_claim['path']) == case.prior_claim
    raw = (Path(ref['path']).parent / 'UNKNOWN.json').read_text(encoding='utf-8')
    assert json.loads(raw)['reason_code'] == 'observation_surface_unconfirmed' and 'private page text' not in raw
