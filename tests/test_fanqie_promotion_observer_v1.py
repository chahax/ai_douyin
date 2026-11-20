import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.platform_adapter import fanqie_promotion_observer_v1 as m


SUBJECT = dict(resource_id='fanqie:fixture', binding_version='v1',
    platform_identity_key='uid:123456', environment_key='fanqie-fixture',
    owner_id='owner1', generation=1, task_id='command1')
ENDPOINT = '/api/promotion/list/v1'


class Page:
    def __init__(self):
        self.url = m.ORIGIN + '/page/promotion-list?tab_type=2'
        self.main_frame = object()
        self.handlers = {}
        self.evaluations = []
        self.resources = [dict(origin=m.ORIGIN, path=ENDPOINT, initiator_type='fetch')]

    def evaluate(self, js):
        self.evaluations.append(js)
        assert js == m.RESOURCE_JS
        return self.resources

    def on(self, event, callback):
        self.handlers[event] = callback

    def remove_listener(self, event, callback):
        assert self.handlers[event] == callback
        del self.handlers[event]


class Response:
    def __init__(self, page, body=None, *, url=None, status=200,
                 resource_type='fetch', method='GET', frame=None,
                 content_type='application/json; charset=utf-8', length='auto', size='auto', size_error=None):
        self.url = url or m.ORIGIN + ENDPOINT + '?token=do-not-save'
        self.status = status
        self.request = SimpleNamespace(frame=frame or page.main_frame,
            resource_type=resource_type, method=method, url=self.url)
        self.raw = json.dumps(body if body is not None else {
            'data': {'list': [{'book_id': '123', 'book_name': 'Fixture',
                'alias': 'keyword', 'id': 94, 'status': 1}]}}).encode()
        self.values = {'content-type': content_type,
                       'content-length': str(len(self.raw)) if length == 'auto' else length}
        self.body_reads = 0
        self.header_reads = []
        self.finished_size = len(self.raw) if size == 'auto' else size
        self.size_error = size_error
        self.request.response = lambda: self
        self.request.sizes = self.sizes

    def sizes(self):
        if self.size_error:raise self.size_error
        return {'responseBodySize':self.finished_size}

    @property
    def headers(self):
        raise AssertionError('aggregate headers must never be read')

    def header_value(self, name):
        assert name == 'content-type'
        self.header_reads.append(name)
        return self.values[name]

    def body(self):
        self.body_reads += 1
        return self.raw


def observer(page=None):
    return m.PromotionObserver(page or Page(), SUBJECT, [ENDPOINT], page_id='tab-fixture', clock=lambda: 10)


def test_resources_only_existing_safe_paths_without_requests():
    page = Page()
    page.resources += [dict(origin='https://evil.invalid',path='/api/promotion',initiator_type='fetch'),
        dict(origin=m.ORIGIN,path='/api/login/token',initiator_type='fetch'),
        dict(origin=m.ORIGIN,path='/api/x?session=secret',initiator_type='fetch')]
    result = m.discover_resources(page)
    assert result['resources'] == [dict(path=ENDPOINT,initiator_type='fetch')]
    assert result['native_requests_issued'] == 0
    assert 'pathname' in m.RESOURCE_JS and 'u.search' not in m.RESOURCE_JS
    assert page.handlers == {}


def test_cross_domain_or_non_promotion_page_rejected():
    for url in ['https://evil.invalid/page/promotion-list', m.ORIGIN+'/page/content']:
        page=Page();page.url=url
        with pytest.raises(ValueError,match='same_promotion_list'):
            m.discover_resources(page)
        assert page.evaluations == []


def test_arm_requires_actual_previously_observed_endpoint():
    with pytest.raises(ValueError,match='not_previously_observed'):
        m.PromotionObserver(Page(),SUBJECT,['/api/guessed/endpoint'],page_id='tab1')


@pytest.mark.parametrize('change',[{'generation':True},{'owner_id':''},{'headers':{}}, {'task_id':'x\nsecret'}])
def test_exact_owner_context_required(change):
    with pytest.raises(ValueError):
        observer_context=dict(SUBJECT,**change)
        m.PromotionObserver(Page(),observer_context,[ENDPOINT],page_id='tab1')


def test_capture_keeps_native_names_not_invented_task_semantics_or_private_values():
    page=Page();o=observer(page)
    response=Response(page,{'data':{'list':[{'id':94,'book_id':'123','alias':'fixture',
        'status':1,'token':'secret-token','cookies':'session=secret',
        'nickname':'private','phone':'12345678901','promotion_path':'https://x/?token=private'}],
        'user':{'id':555,'name':'private-user','token':'secret'}}})
    o.on_request_finished(response.request);result=o.snapshot();raw=json.dumps(result)
    assert len(result['captures'])==1
    fields=result['captures'][0]['metadata']['records'][0]['fields']
    assert {f['name'] for f in fields} == {'id','book_id','alias','status'}
    assert 'task_id' not in {f['name'] for f in fields}
    assert all(x not in raw for x in ('secret','private-user','12345678901','do-not-save'))
    assert response.header_reads == ['content-type']
    assert result['native_body_sha256'] is None
    assert result['promotion_contract_verified'] is False


@pytest.mark.parametrize('changes',[
    {'url':'https://evil.invalid/api/promotion/list/v1'},
    {'url':m.ORIGIN+'/api/not-selected'}, {'resource_type':'document'},
    {'frame':object()}, {'method':'PUT'}, {'status':401},
    {'content_type':'text/html'}, {'size':None},
    {'size':m.MAX_BODY_BYTES+1},
])
def test_response_domain_frame_type_status_and_size_gates(changes):
    page=Page();o=observer(page);response=Response(page,**changes)
    o.on_request_finished(response.request)
    assert o.snapshot()['captures'] == []
    assert response.body_reads == 0


def test_actual_decoded_size_and_json_error_do_not_leak_native_body():
    page=Page();o=observer(page);r=Response(page,length=None,size=20)
    r.raw=b'x'*(m.MAX_BODY_BYTES+1);o.on_request_finished(r.request)
    r.raw=b'{"token":"secret"';o.on_request_finished(r.request)
    assert not o.captures
    assert 'secret' not in json.dumps(o.snapshot())
    assert o.skips['decoded_body_too_large']==1
    assert o.skips['response_unreadable_JSONDecodeError']==1


def test_headerless_completed_request_uses_real_size_metadata_before_body():
    page=Page();o=observer(page);response=Response(page,length=None)
    assert set(page.handlers)=={'requestfinished'}
    o.on_request_finished(response.request)
    assert len(o.captures)==1 and response.body_reads==1
    proof=o.captures[0]['body_size_evidence']
    assert proof=={'source':'request.sizes.responseBodySize','completion_event':'requestfinished',
        'response_body_size':len(response.raw),'decoded_body_bytes':len(response.raw)}
    assert response.header_reads==['content-type']


@pytest.mark.parametrize('size',[True,False,-1,0,'12',1.5,{}])
def test_finished_size_must_be_positive_bounded_integer_not_bool(size):
    page=Page();o=observer(page);response=Response(page,length=None,size=size)
    o.on_request_finished(response.request)
    assert not o.captures and response.body_reads==0
    assert o.skips['bounded_finished_response_size_required']==1


def test_finished_size_timeout_is_notice_without_body_or_exception_message():
    page=Page();o=observer(page)
    response=Response(page,length=None,size_error=TimeoutError('secret native URL'))
    o.on_request_finished(response.request)
    assert not o.captures and response.body_reads==0
    assert o.skips['response_unreadable_TimeoutError']==1
    assert 'secret' not in json.dumps(o.snapshot())
    assert o.inflight==0


def test_finished_response_missing_is_notice_without_body():
    page=Page();o=observer(page);response=Response(page,length=None)
    response.request.response=lambda:None
    o.on_request_finished(response.request)
    assert not o.captures and response.body_reads==0
    assert o.skips['finished_response_missing']==1


def test_exact_observed_promotion_native_subset_keeps_names_and_raw_alias_dates():
    item={'book_id':'123','alias_id':'a1','alias_name':'推广词','task_type':2,
        'alias_start_time':'2026-11-01 00:00:00','alias_end_time':'2026-12-01 23:59:59',
        'alias_post_type':12,'invite_code':'PRIVATE-INVITE','income':999,
        'thumbnail_url':'https://private.invalid/signed?token=secret'}
    result=m.sanitize_metadata({'code':0,'data':{'promotion_list':[item],
        'total':5,'search_after':'PRIVATE-CURSOR','has_more':True}},endpoint_path=m.PROMOTION_ENDPOINT)
    fields={f['name']:f['value'] for f in result['records'][0]['fields']}
    assert fields=={k:v for k,v in item.items() if k in {'book_id','alias_id',*m.PROMOTION_NATIVE_FIELDS}}
    assert 'platform_task_id' not in fields and 'promotion_path' not in fields
    assert fields['alias_end_time']=='2026-12-01 23:59:59'
    assert result['response_fields']==[{'name':'code','path':'$.code','value':0},
        {'name':'total','path':'$.data.total','value':5}]
    raw=json.dumps(result)
    assert all(s not in raw for s in ('PRIVATE-INVITE','PRIVATE-CURSOR','invite_code','income','thumbnail_url','search_after'))
    assert 'has_more' not in {f['name'] for f in result['response_fields']}


@pytest.mark.parametrize('endpoint,path',[(m.ENUM_ENDPOINT,'promotion_list'),(m.PROMOTION_ENDPOINT,'list')])
def test_new_promotion_fields_never_apply_to_other_endpoint_or_container(endpoint,path):
    body={'data':{path:[{'book_id':'1','alias_name':'NEW-NATIVE-VALUE','task_type':2}]}}
    result=m.sanitize_metadata(body,endpoint_path=endpoint)
    assert all(f['name'] not in m.PROMOTION_NATIVE_FIELDS for r in result['records'] for f in r['fields'])
    assert 'NEW-NATIVE-VALUE' not in json.dumps(result)


def test_only_exact_observed_enum_container_exposes_text_value_pairs():
    items=[{'text':'已观察枚举'+str(i),'value':i} for i in range(12)]
    result=m.sanitize_metadata({'code':0,'data':{'kol_alias_post_type':items,
        'other_enum':[{'text':'PRIVATE-OTHER-LABEL','value':123}],
        'nested':{'kol_alias_post_type':[{'text':'PRIVATE-NESTED-LABEL','value':123}]}}},
        endpoint_path=m.ENUM_ENDPOINT)
    assert len(result['records'])==12
    assert all(r['native_path'].startswith('$.data.kol_alias_post_type[') for r in result['records'])
    assert [r['fields'] for r in result['records']][0]==[
        {'name':'text','path':'$.data.kol_alias_post_type[0].text','value':'已观察枚举0'},
        {'name':'value','path':'$.data.kol_alias_post_type[0].value','value':0}]
    assert all(s not in json.dumps(result) for s in ('PRIVATE-OTHER-LABEL','PRIVATE-NESTED-LABEL'))
    wrong=m.sanitize_metadata({'data':{'kol_alias_post_type':items}},endpoint_path=m.PROMOTION_ENDPOINT)
    assert wrong['records']==[]


def test_enum_and_response_control_types_are_not_coerced():
    result=m.sanitize_metadata({'code':True,'data':{'total':-1,'kol_alias_post_type':[
        {'text':'bool','value':True},{'text':'x'*81,'value':1},
        {'text':'label','value':2,'invite_code':'secret'}]}},endpoint_path=m.ENUM_ENDPOINT)
    assert result['records']==[] and result['response_fields']==[]
    result=m.sanitize_metadata({'code':'0','data':{'total':False}},endpoint_path=m.PROMOTION_ENDPOINT)
    assert result['response_fields']==[]


def test_saved_enum_fields_cannot_be_relabelled_as_another_endpoint(tmp_path):
    page=Page();page.resources=[dict(origin=m.ORIGIN,path=m.ENUM_ENDPOINT,initiator_type='fetch')]
    o=m.PromotionObserver(page,SUBJECT,[m.ENUM_ENDPOINT],page_id='actual-page')
    r=Response(page,{'code':0,'data':{'kol_alias_post_type':[{'text':'AIGC','value':12}]}},
        url=m.ORIGIN+m.ENUM_ENDPOINT)
    o.on_request_finished(r.request);saved=o.snapshot()
    assert m.save_observation(tmp_path/'VALID_ENUM.json',saved)
    bad=copy.deepcopy(saved);bad['captures'][0]['endpoint']['path']=m.PROMOTION_ENDPOINT
    with pytest.raises(ValueError,match='field_invalid'):
        m.save_observation(tmp_path/'WRONG_ENDPOINT.json',bad)


def test_unknown_structure_is_not_guessed_and_missing_concepts_are_not_invented():
    result=m.sanitize_metadata({'data':{'unknown_table':[{'id':1,'name':'x'}]}})
    assert result['records'] == []
    result=m.sanitize_metadata({'data':{'list':[{'book_id':'1','alias':'x'}]}})
    names={f['name'] for f in result['records'][0]['fields']}
    assert names=={'book_id','alias'}
    assert not {'task_id','valid_from','valid_until','promotion_path'} & names


def test_unknown_native_containers_project_safe_key_types_and_counts_without_values():
    body={'data':{'book_promotion_word_list':[{'word_id':'sensitive-unclassified-id',
        'word_text':'do-not-save-unknown-value','access_token':'secret',
        'https://x/?session=secret':'private','bad\nkey':'private'}]}}
    result=m.sanitize_metadata(body);raw=json.dumps(result)
    assert result['records']==[]
    entries={item['path']:item for item in result['structure']}
    assert entries['$.data.book_promotion_word_list']['item_count']==1
    assert entries['$.data.book_promotion_word_list[0].word_id']['type']=='string'
    assert not any(value in raw for value in ('sensitive-unclassified-id','do-not-save-unknown-value','access_token','https://x','bad\\nkey'))
    assert result['statistics']['filtered_structure_keys']==3


def test_structure_only_response_remains_discovery_evidence_not_contract_or_value_capture():
    page=Page();o=observer(page)
    o.on_request_finished(Response(page,{'data':{'book_promotion_word_list':[{'word_id':123}]}}).request)
    value=o.snapshot();assert len(value['captures'])==1
    assert value['captures'][0]['metadata']['records']==[]
    assert value['promotion_contract_verified'] is False
    assert o.skips['no_whitelisted_values_structure_only']==1


def test_row_limit_and_recorded_sanitized_hash_are_real():
    result=m.sanitize_metadata({'data':{'list':[{'book_id':str(i)} for i in range(100)]}})
    assert len(result['records'])==50 and result['statistics']['truncated']
    saved=result.pop('sanitized_sha256')
    assert saved==hashlib.sha256(m._canonical(result)).hexdigest()


def test_capture_limit_bounded_and_stop_removes_listener():
    page=Page();o=observer(page)
    for _ in range(12):o.on_request_finished(Response(page).request)
    assert len(o.captures)==8 and o.skips['capture_limit_reached']==4
    result=o.stop();assert result['active'] is False and not page.handlers
    o.on_request_finished(Response(page).request);assert len(o.captures)==8


def test_navigation_to_other_page_never_captures_response():
    page=Page();o=observer(page);page.url='https://evil.invalid/page/promotion-list'
    r=Response(page);o.on_request_finished(r.request)
    assert not o.captures and r.body_reads==0


def test_observation_window_is_bounded():
    page=Page();now=[10]
    o=m.PromotionObserver(page,SUBJECT,[ENDPOINT],page_id='tab1',clock=lambda:now[0])
    now[0]=71;r=Response(page);o.on_request_finished(r.request)
    assert o.snapshot()['active'] is False
    assert o.skips['observation_window_expired']==1 and r.body_reads==0


def test_worker_action_is_page_and_owner_scoped_and_does_not_rearm_implicitly():
    page=Page();sessions={}
    m.worker_action(page,sessions,'tab1',mode='resources')
    assert not sessions
    first=m.worker_action(page,sessions,'tab1',mode='arm',subject=SUBJECT,endpoint_paths=[ENDPOINT])
    assert first['worker_page_id']=='tab1'
    with pytest.raises(ValueError,match='already_armed'):
        m.worker_action(page,sessions,'tab1',mode='arm',subject=SUBJECT,endpoint_paths=[ENDPOINT])
    with pytest.raises(ValueError,match='subject_changed'):
        m.worker_action(page,sessions,'tab1',mode='snapshot',subject=dict(SUBJECT,generation=2))
    result=m.worker_action(page,sessions,'tab1',mode='stop',subject=SUBJECT)
    assert result['active'] is False and not sessions


def test_page_typed_wrapper_preserves_tab_and_old_worker_script_compiles():
    from src.platform_adapter.browser_session import Page as ForwardPage, _PW_SCRIPT
    class Session:
        def __init__(self):self.commands=[]
        def cmd(self,action,**kw):self.commands.append((action,kw));return {'evidence':{'ok':True}}
    session=Session();p=ForwardPage(session,tab_id='actual-page')
    assert p.fanqie_promotion_observer('arm',subject=SUBJECT,endpoint_paths=[ENDPOINT])=={'ok':True}
    assert session.commands==[('fanqie_promotion_observer',dict(mode='arm',subject=SUBJECT,endpoint_paths=[ENDPOINT],tab_id='actual-page'))]
    compile(_PW_SCRIPT,'<worker>','exec')


def test_save_is_fresh_project_only_sanitized_and_does_not_accept_extra_native_body(tmp_path):
    page=Page();o=observer(page);o.on_request_finished(Response(page).request);value=o.snapshot()
    target=tmp_path/'EVIDENCE.json';binding=m.save_observation(target,value)
    assert binding['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='new_project'):
        m.save_observation(target,value)
    bad=copy.deepcopy(value);bad['raw_body']={'token':'secret'}
    with pytest.raises(ValueError,match='sanitized_promotion'):
        m.save_observation(tmp_path/'BAD.json',bad)
    bad=copy.deepcopy(value);bad['captures'][0]['metadata']['records'][0]['fields'][0]['value']='tampered'
    with pytest.raises(ValueError,match='metadata_changed'):
        m.save_observation(tmp_path/'TAMPERED.json',bad)
