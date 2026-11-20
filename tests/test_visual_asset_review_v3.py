"""Protocol/state black boxes; synthetic providers are NOT semantic vision tests."""
import base64
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
from contextlib import contextmanager

from PIL import Image
import pytest

from src.content_factory import visual_asset_review_v3 as v


def observation(**changes):
    result=dict(checks={k:True for k in v.CHARACTER_CHECKS},
        observations=dict(people_count=1,age_band='child',orientation='front',framing='full_body'),
        issues=[],rois={k:None for k in v.ROI_NAMES},reference_rois={k:None for k in v.ROI_NAMES},
        evidence=['Target visibly contains one child in the requested clothing.'])
    result.update(changes);return result


@pytest.fixture
def images(tmp_path):
    a=tmp_path/'source.png';b=tmp_path/'target.png'
    Image.new('RGB',(256,384),'gray').save(a);Image.new('RGB',(256,384),'silver').save(b)
    return a,b


@contextmanager
def provider(responses,*,capabilities=('vision',),model='vision-test',on_post=None,style='ollama',blind=None,count_recheck=None,
             people_observation=None,furniture_observation=None):
    """Real local HTTP transport, fixed fake results to test the software contract."""
    received=[];response_index=0
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,obj):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(obj).encode())
        def do_GET(self):
            if self.path=='/api/tags':self.reply(dict(models=[dict(name=model,digest='test-digest',capabilities=list(capabilities))]))
            elif self.path=='/v1/models':self.reply(dict(data=[dict(id=model)]))
            else:self.send_error(404)
        def do_POST(self):
            nonlocal response_index
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append(body)
            if on_post:on_post(body)
            schema=body['format'] if style=='ollama' else body['response_format']['json_schema']['schema']
            if set(schema['properties'])=={'people_count','evidence'}:
                if 'target_people' in body['messages'][0]['content']:
                    response=deepcopy(people_observation) if people_observation is not None else dict(people_count=0,evidence=['Protocol fixture: zero visible people.'])
                else:
                    response=deepcopy(count_recheck) if count_recheck is not None else dict(
                        people_count=None,evidence=['Protocol fixture still cannot count the actual target.'])
            elif set(schema['properties'])=={'object_observations'}:
                response=deepcopy(furniture_observation) if furniture_observation is not None else dict(object_observations={
                    k:dict(count=0,regions=[],evidence='Protocol fixture: zero visible instances.') for k in schema['properties']['object_observations']['properties']})
            elif {'observations','rois','evidence'}<=set(schema['properties']) and 'checks' not in schema['properties']:
                # Simulated observation is fixture data, never claimed as visual QA.
                planned=responses[response_index] if response_index<len(responses) else observation()
                planned=planned if isinstance(planned,dict) and 'observations' in planned else observation()
                ob=deepcopy(planned['observations']);orientation=ob['orientation']
                pose={'front':'front','back':'back','screen_left':'left_profile','screen_right':'right_profile'}.get(orientation,'unknown') if ob['framing']=='full_body' else 'unknown'
                response=deepcopy(blind) if blind is not None else dict(observations=dict(ob,pose_view=pose),rois=deepcopy(planned['rois']),evidence=['Simulated independent image observation.'])
                if blind is None and 'object_observations' in schema['properties']:
                    response['object_observations']={k:dict(count=0,regions=[],evidence='Protocol fixture: zero visible instances, not actual image inference.') for k in schema['properties']['object_observations']['properties']}
            else:
                response=responses[response_index];response_index+=1
            if isinstance(response,dict) and response.get('_native'):
                self.reply(response['_native']);return
            text=response if isinstance(response,str) else json.dumps(response)
            if style=='ollama':self.reply(dict(model=model,done=True,done_reason='stop',message=dict(content=text)))
            else:self.reply(dict(model=model,choices=[dict(finish_reason='stop',message=dict(content=text))]))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',received
    finally:server.shutdown();server.server_close();thread.join(5)


def test_real_http_sends_actual_two_images_schema_and_bound_result(images,tmp_path):
    source,target=images
    with provider([observation()]) as (url,requests):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=c.review(target,source,dict(kind='character',age_band='child',view='front',locate_rois=[]),tmp_path/'job')
        assert result['decision']=='accepted' and all(result['checks'].values())
        assert result['target_sha256']==v.file_sha(target) and result['reference_sha256']==v.file_sha(source)
        assert result['production_approved'] is False and result['visual_evidence']
        body=requests[1];assert body['keep_alive']==0 and body['stream'] is False
        assert len(requests[0]['messages'][0]['images'])==1
        assert 'EXPECTATION_JSON' not in requests[0]['messages'][0]['content']
        assert body['format']['additionalProperties'] is False
        encoded=body['messages'][0]['images'];assert len(encoded)==2
        assert Image.open(io.BytesIO(base64.b64decode(encoded[0]))).size==(256,384)
        assert base64.b64decode(encoded[0])==v._png(dict(binding=v.image_binding(target)))
        again=c.review(target,source,dict(kind='character',age_band='child',view='front',locate_rois=[]),tmp_path/'job')
        assert again==result and len(requests)==2


def test_text_only_model_blocks_before_any_image_post(images):
    with provider([],capabilities=['completion','tools']) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0])
        assert result['decision']=='unavailable' and not result['visual_evidence'] and requests==[]


@pytest.mark.parametrize('url',[
    'https://127.0.0.1:11434','http://example.com:1234','http://user:secret@127.0.0.1:1234',
    'http://127.0.0.1:11434/proxy','http://127.0.0.1:11434?target=x','http://127.0.0.1:11434#x'])
def test_cannot_exfiltrate_images_to_remote_or_proxy(url):
    with pytest.raises(ValueError):v.loopback_endpoint(url)


def test_crop_recheck_clears_false_pocket_claim_with_actual_source_crops(images,tmp_path):
    raw=observation();raw['checks']['clothing']=False
    raw['issues']=[dict(kind='clothing',severity='blocking',evidence='Pocket looks added in target thumbnail.',
                        target_region=[300,300,600,600],reference_region=[300,300,600,600])]
    answer=dict(confirmed=False,corrected_check=True,evidence='Both actual crops visibly contain the same pocket.')
    with provider([raw,answer]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(locate_rois=[]),tmp_path/'job')
        assert len(requests)==3 and result['decision']=='accepted' and result['issues']==[]
        assert result['roi_rechecks'][0]['result']['confirmed'] is False
        data=base64.b64decode(requests[2]['messages'][0]['images'][0])
        crop=Image.open(io.BytesIO(data));assert crop.size==(78,116)
        assert (tmp_path/'job/item_0000/recheck_0_source_region.png').exists()


def test_missing_source_region_is_uncertain_not_accepted(images):
    raw=observation();raw['checks']['clothing']=False
    raw['issues']=[dict(kind='clothing',severity='blocking',evidence='Unclear pocket.',target_region=None,reference_region=None)]
    with provider([raw]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(locate_rois=[]))
        assert result['decision']=='needs_review' and result['checks']['clothing'] is None and len(requests)==2


@pytest.mark.parametrize('mutation',[
    lambda raw:raw['checks'].update(identity=1),
    lambda raw:raw.update(extra_approval=True),
    lambda raw:raw['checks'].pop('view'),
    lambda raw:raw.update(evidence=[]),
    lambda raw:raw['rois'].update(face=[100,0,0,500]),
])
def test_invalid_model_format_cannot_pass(images,mutation):
    raw=observation();mutation(raw)
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0])
        assert result['decision']=='unavailable' and not result['visual_evidence']


@pytest.mark.parametrize('body',[
    'I cannot inspect the image but probably pass.',
    {'_native':dict(model='wrong',done=True,done_reason='stop',message=dict(content=json.dumps(observation())))},
    {'_native':dict(model='vision-test',done=False,message=dict(content=json.dumps(observation())))},
    {'_native':dict(model='vision-test',done=True,done_reason='length',message=dict(content=json.dumps(observation())))},
])
def test_unknown_truncated_or_wrong_model_is_never_success(images,body):
    with provider([body]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0])
        assert result['decision']=='unavailable'


@pytest.mark.parametrize('expectation,changes',[
    (dict(expected_people=1),dict(people_count=2)),
    (dict(age_band='child'),dict(age_band='adult')),
    (dict(view='right_profile'),dict(orientation='screen_left')),
    (dict(view='face'),dict(framing='full_body')),
])
def test_model_positive_checks_cannot_override_obvious_observation_mismatch(images,expectation,changes):
    raw=observation();raw['observations'].update(changes)
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],expectation)
        assert result['decision']=='repair_required' and result['issues']


def test_front_cannot_pass_without_actual_roi_localization(images):
    with provider([observation()]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(view='front'))
        assert result['decision']=='needs_review'


def test_minor_normal_difference_note_does_not_force_generation(images):
    raw=observation();raw['issues']=[dict(kind='clothing',severity='note',evidence='Normal cloth folds differ with pose.',target_region=None,reference_region=None)]
    with provider([raw]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(locate_rois=[]))
        assert result['decision']=='accepted' and len(requests)==2


def test_file_mutation_during_inference_invalidates_result(images):
    def change(_):Image.new('RGB',(256,384),'red').save(images[1])
    with provider([observation()],on_post=change) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(locate_rois=[]))
        assert result['decision']=='unavailable' and 'changed' in result['error']


def test_known_result_cannot_be_reused_for_changed_source(images,tmp_path):
    with provider([observation()]) as (url,_):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        c.review(images[1],images[0],dict(locate_rois=[]),tmp_path/'job')
        Image.new('RGB',(256,384),'red').save(images[1])
        with pytest.raises(ValueError):c.review(images[1],images[0],dict(locate_rois=[]),tmp_path/'job')


def test_explicit_unknown_claim_is_retained_without_model_post(images,tmp_path):
    with provider([]) as (url,requests):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        request=dict(target=images[1],reference=images[0],expectation={})
        prepared=[v._prepared(request)];job=tmp_path/'job';job.mkdir()
        binding=v.digest(dict(config=c.config,requests=prepared));v._write(job/'CLAIM.json',dict(request_binding_sha256=binding))
        result=c.review_many([request],evidence_dir=job)[0]
        assert result['decision']=='unavailable' and requests==[] and 'unknown' in result['error']


def test_openai_compatible_requires_vision_pin_and_uses_image_content(images):
    with provider([observation()],style='openai') as (url,requests):
        config=dict(provider='openai_compatible',endpoint=url,model='vision-test')
        assert not v.VisualReviewClient(config).discover()['available']
        c=v.VisualReviewClient(dict(config,vision_capable=True))
        result=c.review(images[1],images[0],dict(locate_rois=[]));assert result['decision']=='accepted'
        content=requests[1]['messages'][0]['content'];assert len([x for x in content if x['type']=='image_url'])==2


def test_local_discovery_checks_architecture_shards_and_dependencies_without_inference(tmp_path):
    model=tmp_path/'model';model.mkdir()
    for name,data in [('config.json',dict(model_type='qwen3_vl')),('model.safetensors.index.json',dict(weight_map={'a':'model.safetensors'})),('preprocessor_config.json',{}),('tokenizer_config.json',{}),('tokenizer.json',{})]:
        (model/name).write_text(json.dumps(data))
    (model/'model.safetensors').write_bytes(b'x'*2048)
    c=v.VisualReviewClient(dict(model_path=str(model)))
    assert c.discover()['available']
    (model/'config.json').write_text(json.dumps(dict(model_type='qwen3')))
    assert not c.discover()['available']


def place_observation(count=1):
    raw=observation();raw['checks']={k:True for k in v.PLACE_CHECKS}
    raw['observations'].update(people_count=count,framing='environment',age_band='unknown')
    return raw


def test_composition_compares_every_actual_actor_and_room_before_acceptance(images,tmp_path):
    actor,frame=images
    with provider([observation(),place_observation()]) as (url,requests):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=c.review_composition(frame,[dict(id='actor',path=str(actor))],dict(id='room',path=str(actor)),evidence_dir=tmp_path/'composition')
        assert result['decision']=='accepted' and len(result['subreviews'])==2 and len(requests)==4
        assert len(result['reference_bindings'])==2 and len(result['checks'])==7
        assert all(v is True for v in result['checks'].values())
        assert 'composition_subject' in requests[1]['messages'][0]['content']
        assert 'composition_place' in requests[3]['messages'][0]['content']


def test_composition_without_real_environment_source_is_rejected_before_dispatch(images):
    c=v.VisualReviewClient(dict(provider='ollama',endpoint='http://127.0.0.1:1',model='x'))
    with pytest.raises(ValueError):c.review_composition(images[1],[dict(id='a',path=str(images[0]))],None)


def test_composition_actor_pass_cannot_hide_layout_failure(images):
    room=place_observation();room['checks']['layout']=False
    room['issues']=[dict(kind='layout',severity='blocking',evidence='Door in wrong wall.',target_region=None,reference_region=None)]
    with provider([observation(),room]) as (url,_):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=c.review_composition(images[1],[dict(id='a',path=str(images[0]))],dict(id='p',path=str(images[0])))
        assert result['decision']=='needs_review' and result['checks']['layout'] is None


def test_empty_room_frame_does_not_require_unseen_people_identity_checks(images):
    with provider([place_observation(0)]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(images[1],[],dict(id='p',path=str(images[0])))
        assert result['decision']=='accepted' and set(result['checks'])==set(v.PLACE_CHECKS)


@pytest.mark.parametrize('view',['reverse','side'])
@pytest.mark.parametrize('primary,decision',[(False,'repair_required'),(None,'needs_review')])
def test_current_guide_layout_verdict_cannot_be_upgraded_by_two_old_view_crops(images,tmp_path,view,primary,decision):
    guide=tmp_path/'actual_camera_guide.png';Image.new('RGB',(256,384),'white').save(guide)
    raw=place_observation(0);raw['checks']['layout']=primary
    raw['issues']=[dict(kind='layout',severity='blocking' if primary is False else 'uncertain',
        evidence='Actual target does not establish the current guide door/furniture relationship.',
        target_region=[200,200,600,600],reference_region=[250,250,650,650])]
    crop_answer=dict(confirmed=False,corrected_check=True,evidence='Only these two close crops look similar.')
    with provider([raw,crop_answer]) as (url,requests):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review_many([dict(target=images[1],reference=images[0],layout_guide=guide,
            expectation=dict(kind='place',view=view,expected_people=0))],evidence_dir=tmp_path/'guide_review')[0]
        assert result['decision']==decision and result['checks']['layout'] is primary
        assert result['roi_rechecks']==[] and len(requests)==2
        assert len(requests[1]['messages'][0]['images'])==3
        assert result['reference_sha256']==v.file_sha(images[0]) and result['layout_guide_sha256']==v.file_sha(guide)


def test_legacy_layout_crop_recheck_without_actual_guide_remains_supported(images,tmp_path):
    raw=place_observation(0);raw['checks']['layout']=False
    raw['issues']=[dict(kind='layout',severity='blocking',evidence='Proposed legacy detail mismatch.',
        target_region=[200,200,600,600],reference_region=[250,250,650,650])]
    answer=dict(confirmed=False,corrected_check=True,evidence='The same legacy room detail is visibly present in both actual crops.')
    with provider([raw,answer]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],dict(kind='place',expected_people=0),tmp_path/'legacy_layout')
        assert result['decision']=='accepted' and result['checks']['layout'] is True
        assert len(result['roi_rechecks'])==1 and len(requests)==3


def empty_unknown_blind():
    return dict(observations=dict(people_count=None,age_band='unknown',orientation='unknown',
        framing='environment',pose_view='unknown'),rois={k:None for k in v.ROI_NAMES},
        evidence=['An empty room is visible with no human figures.'])


def test_null_count_gets_one_actual_target_only_recheck_and_keeps_original_native(images,tmp_path):
    original=empty_unknown_blind();answer=dict(people_count=0,evidence=['Only room furniture is visible; no human depiction.'])
    with provider([place_observation(0)],blind=original,count_recheck=answer) as (url,requests):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review(images[1],images[0],dict(kind='place',view='front'),tmp_path/'count_job')
        assert result['decision']=='accepted' and result['observations']['people_count']==0
        assert len(requests)==3 and len(requests[1]['messages'][0]['images'])==1
        message=requests[1]['messages'][0]['content']
        assert v.COUNT_RECHECK_PROMPT in message and 'EXPECTATION_JSON' not in message
        assert 'expected_people' not in message and images[0].name not in message
        assert base64.b64decode(requests[1]['messages'][0]['images'][0])==v._png(dict(binding=v.image_binding(images[1])))
        kept=v._parse_content(v._read(tmp_path/'count_job/item_0000/BLIND_NATIVE.json')['text'])
        assert kept==original and kept['observations']['people_count'] is None
        correction=result['blind_count_recheck'];native=v._read(tmp_path/'count_job/item_0000/COUNT_RECHECK_NATIVE.json')
        assert correction['initial_people_count'] is None and correction['people_count']==0
        assert correction['native_sha256']==v.digest(native) and correction['target_sha256']==v.file_sha(images[1])
        assert correction['prompt_sha256']==v.digest(v.COUNT_RECHECK_PROMPT)
        assert client.review(images[1],images[0],dict(kind='place',view='front'),tmp_path/'count_job')==result
        assert len(requests)==3


def test_empty_room_evidence_never_converts_null_to_zero_without_visual_recheck(images):
    with provider([place_observation(0)],blind=empty_unknown_blind()) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],dict(kind='place',view='front'))
        assert result['decision']=='needs_review' and result['observations']['people_count'] is None
        assert result['checks']['consistency'] is None and len(requests)==3
        assert result['blind_count_recheck']['people_count'] is None


def test_independent_count_mismatch_and_uncertain_layout_still_block(images):
    with provider([place_observation(0)],blind=empty_unknown_blind(),
            count_recheck=dict(people_count=2,evidence=['Two visible figures remain in target.'])) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],dict(kind='place',view='front'))
        assert result['decision']=='repair_required' and result['checks']['consistency'] is False
    uncertain=place_observation(0);uncertain['checks']['layout']=None
    with provider([uncertain],blind=empty_unknown_blind(),
            count_recheck=dict(people_count=0,evidence=['No human depiction is visible.'])) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],dict(kind='place',view='front'))
        assert result['decision']=='needs_review' and result['checks']['layout'] is None


@pytest.mark.parametrize('answer',[
    dict(people_count=True,evidence=['Invalid boolean count.']),
    dict(people_count=-1,evidence=['Invalid negative count.']),
    dict(people_count=0,evidence=[]),
])
def test_invalid_count_recheck_fails_known_without_repeating_or_comparing(images,answer):
    with provider([place_observation(0)],blind=empty_unknown_blind(),count_recheck=answer) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],dict(kind='place',view='front'))
        assert result['decision']=='unavailable' and result['completion_known'] and len(requests)==2


def test_unknown_count_recheck_keeps_unknown_and_never_calls_model_or_replays(images,tmp_path):
    incomplete=dict(_native=dict(model='vision-test',done=False,message=dict(content='')))
    with provider([place_observation(0)],blind=empty_unknown_blind(),count_recheck=incomplete) as (url,requests):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review(images[1],images[0],dict(kind='place',view='front'),tmp_path/'count_unknown')
        assert result['decision']=='unavailable' and result['outcome_unknown'] and not result['retryable']
        assert len(requests)==2 and (tmp_path/'count_unknown/item_0000/COUNT_RECHECK_ERROR.json').is_file()
        assert client.review(images[1],images[0],dict(kind='place',view='front'),tmp_path/'count_unknown')==result
        assert len(requests)==2


def test_completed_review_cache_detects_mutated_result(images,tmp_path):
    with provider([observation()]) as (url,_):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'));job=tmp_path/'job'
        c.review(images[1],images[0],dict(locate_rois=[]),job)
        saved=v._read(job/'RESULTS.json');saved['results'][0]['decision']='repair_required';v._write(job/'RESULTS.json',saved)
        with pytest.raises(ValueError):c.review(images[1],images[0],dict(locate_rois=[]),job)


def test_configs_cannot_persist_credentials():
    with pytest.raises(ValueError):v.VisualReviewClient(dict(api_key='never-save'))


def test_schema_prompt_server_agree_on_required_evidence_and_front_rois():
    schema=v.observation_schema(dict(view='front'))['properties']
    assert schema['evidence']['minItems']==1
    assert schema['evidence']['items']['minLength']==1
    for key in v.ROI_NAMES:
        assert schema['rois']['properties'][key]['type']=='array'
        assert schema['rois']['properties'][key]['minItems']==4


def test_blind_actual_direction_cannot_be_overwritten_by_requested_comparison_answer(images):
    raw=observation();raw['observations'].update(orientation='screen_right')
    blind=dict(observations=dict(people_count=1,age_band='child',orientation='screen_left',
        framing='full_body',pose_view='left_profile'),rois={k:None for k in v.ROI_NAMES},evidence=['Nose visibly points toward left edge.'])
    with provider([raw],blind=blind) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(view='right_profile'))
        assert result['decision']=='repair_required' and result['checks']['view'] is False
        assert result['observations']['pose_view']=='left_profile'
        assert 'right_profile' not in requests[0]['messages'][0]['content']


def test_completion_flags_known_format_failure_and_absent_vision_are_retryable(images):
    with provider(['invalid native content']) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1])
        assert result['completion_known'] and result['retryable'] and result['inference_dispatched']
        assert result['outcome_unknown'] is False
    with provider([],capabilities=['completion']) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1])
        assert result['completion_known'] and result['retryable'] and not result['inference_dispatched']


def test_unknown_native_terminal_never_becomes_retryable(images):
    with provider([{'_native':dict(model='vision-test',done=False,message=dict(content=''))}]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1])
        assert not result['completion_known'] and not result['retryable'] and result['outcome_unknown']


def test_composition_completion_flags_aggregate_strictly(images):
    with provider(['bad',place_observation()]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(
            images[1],[dict(id='a',path=str(images[0]))],dict(id='p',path=str(images[0])))
        assert result['decision']=='unavailable' and result['completion_known'] and result['retryable']
        assert not result['outcome_unknown'] and result['inference_dispatched']
    with provider([{'_native':dict(model='vision-test',done=False,message=dict(content=''))},place_observation()]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(
            images[1],[dict(id='a',path=str(images[0]))],dict(id='p',path=str(images[0])))
        assert result['decision']=='unavailable' and not result['completion_known'] and not result['retryable']


def test_ambiguous_direction_corroboration_cannot_accept_model_positive(images,monkeypatch):
    raw=observation();raw['observations'].update(orientation='screen_right')
    monkeypatch.setattr(v,'profile_direction_auxiliary',lambda binding:dict(orientation='unknown',target_sha256=binding['sha256']))
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(view='right_profile'))
        assert result['decision']=='needs_review' and result['checks']['view'] is None
        assert result['completion_known'] and not result['retryable']


def test_direction_auxiliary_cannot_override_model_rejection(images,monkeypatch):
    raw=observation();raw['observations'].update(orientation='screen_left')
    monkeypatch.setattr(v,'profile_direction_auxiliary',lambda binding:dict(orientation='screen_right',target_sha256=binding['sha256']))
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],dict(view='right_profile'))
        assert result['decision']=='repair_required' and result['checks']['view'] is False


def roi_expectation(source):
    return dict(view='face',locate_rois=[],reference_roi=dict(x=64,y=96,width=80,height=120),
        reference_roi_source=dict(asset_id='canonical',version=1,image_sha256=v.file_sha(source),review_sha256='c'*64))


def face_observation():
    raw=observation();raw['observations']['framing']='face';return raw


def test_reference_roi_sends_real_crop_preserving_full_source_sha_and_origin(images,tmp_path):
    source,target=images;expectation=roi_expectation(source)
    with provider([face_observation()]) as (url,requests):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=c.review(target,source,expectation,tmp_path/'roi_job')
        assert result['decision']=='accepted' and result['reference_sha256']==v.file_sha(source)
        evidence=result['reference_roi_evidence'];assert evidence['source_sha256']==v.file_sha(source)
        assert evidence['pixel_roi']==expectation['reference_roi'] and evidence['roi_source']==expectation['reference_roi_source']
        assert evidence['source_dimensions']==[256,384] and evidence['roi_source_sha256']==v.digest(expectation['reference_roi_source'])
        cropped=base64.b64decode(requests[1]['messages'][0]['images'][1])
        assert Image.open(io.BytesIO(cropped)).size==(80,120)
        import hashlib
        assert hashlib.sha256(cropped).hexdigest()==evidence['crop_sha256']
        assert evidence['crop_sha256']!=result['reference_sha256']
        assert len(requests[0]['messages'][0]['images'])==1
        assert 'reference_roi_source' not in requests[0]['messages'][0]['content']
        spec=v._read(tmp_path/'roi_job/item_0000/MODEL_REQUEST.json')['images'][1]
        assert spec['binding']['sha256']==v.file_sha(source) and spec['region']==expectation['reference_roi']
        assert v.file_sha(tmp_path/'roi_job/item_0000/reference_roi.png')==evidence['crop_sha256']


def test_reference_crop_coordinates_map_to_full_source_and_recheck_exact_crop(images,tmp_path):
    source,target=images;raw=face_observation();raw['checks']['clothing']=False
    raw['reference_rois']['face']=[0,0,1000,1000]
    raw['issues']=[dict(kind='clothing',severity='blocking',evidence='Possible seam change.',
        target_region=[0,0,1000,1000],reference_region=[0,0,1000,1000])]
    answer=dict(confirmed=False,corrected_check=True,evidence='The actual crops show the same seam.')
    with provider([raw,answer]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(target,source,roi_expectation(source),tmp_path/'roi_job')
        assert result['decision']=='accepted'
        assert result['reference_rois']['face']==dict(x=64,y=96,width=80,height=120)
        assert Image.open(io.BytesIO(base64.b64decode(requests[2]['messages'][0]['images'][1]))).size==(80,120)
        # Model coordinates described crop pixels; final issue coordinates refer to full source.
        assert result['roi_rechecks'][0]['issue']['reference_region']==[250,250,563,563]


@pytest.mark.parametrize('roi',[
    dict(x=-1,y=0,width=20,height=20),dict(x=250,y=0,width=20,height=20),
    dict(x=0,y=0,width=20,height=400),dict(x=0,y=0,width=0,height=20),
    dict(x=0.1,y=0,width=20,height=20),dict(x=0,y=0,width=20,height=20,unit='pixels'),
])
def test_reference_roi_invalid_pixel_coordinates_block_before_model_post(images,roi):
    with provider([]) as (url,requests):
        c=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        with pytest.raises(ValueError):c.review(images[1],images[0],dict(view='face',reference_roi=roi))
        assert requests==[]


def test_reference_roi_origin_cannot_claim_another_source_sha(images):
    expectation=roi_expectation(images[0]);expectation['reference_roi_source']['image_sha256']='0'*64
    with pytest.raises(ValueError,match='binding'):v._prepared(dict(target=images[1],reference=images[0],expectation=expectation))


def test_reference_roi_bound_coordinates_and_crop_hash_cannot_be_changed(images):
    prepared=v._prepared(dict(target=images[1],reference=images[0],expectation=roi_expectation(images[0])))
    wrong=deepcopy(prepared);wrong['reference_roi_evidence']['pixel_roi']['x']+=1
    with pytest.raises(ValueError,match='binding'):v._unchanged(wrong)
    wrong=deepcopy(prepared);wrong['reference_roi_evidence']['crop_sha256']='0'*64
    with pytest.raises(ValueError,match='crop SHA'):v._unchanged(wrong)


def test_source_roi_never_converts_actual_fullbody_target_to_face_acceptance(images):
    with provider([observation()]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],roi_expectation(images[0]))
        assert result['decision']=='repair_required' and result['checks']['view'] is False


def test_source_roi_does_not_upgrade_unknown_identity_from_same_man_prose(images):
    raw=face_observation();raw['checks'].update(identity=None,clothing=None,anatomy=None)
    raw['evidence']=['The source seems to show the same man; detailed comparison is uncertain.']
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],roi_expectation(images[0]))
        assert result['decision']=='needs_review' and result['checks']['identity'] is None
        assert result['checks']['clothing'] is None and result['checks']['anatomy'] is None


@pytest.mark.parametrize('artifact',['reference_roi.png','REFERENCE_ROI_EVIDENCE.json'])
def test_saved_source_roi_artifact_tampering_is_not_silently_reused(images,tmp_path,artifact):
    with provider([face_observation()]) as (url,requests):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'));job=tmp_path/'roi_job'
        client.review(images[1],images[0],roi_expectation(images[0]),job)
        (job/'item_0000'/artifact).write_text('{}')
        with pytest.raises(ValueError):client.review(images[1],images[0],roi_expectation(images[0]),job)
        assert len(requests)==2


def test_same_review_directory_cannot_reuse_a_different_source_roi(images,tmp_path):
    with provider([face_observation()]) as (url,_):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'));expectation=roi_expectation(images[0]);job=tmp_path/'roi_job'
        client.review(images[1],images[0],expectation,job);expectation['reference_roi']['x']+=1
        with pytest.raises(ValueError,match='inputs changed'):client.review(images[1],images[0],expectation,job)


def test_model_prompt_excludes_audit_coordinates_hashes_and_versions_but_keeps_program_binding(images,tmp_path):
    source,target=images;expectation=roi_expectation(source)
    expectation['reference_roi_source']['asset_id']='audit_asset_82f88'
    expectation['reference_roi_source']['version']=317
    expectation['other_audit_sha256']='f'*64
    with provider([face_observation()]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(target,source,expectation,tmp_path/'roi_job')
        prompt=requests[1]['messages'][0]['content']
        assert 'reference_roi_source' not in prompt and 'reference_roi' not in prompt.replace('reference_rois','')
        assert '"x": 64' not in prompt and '"width": 80' not in prompt
        assert v.file_sha(source) not in prompt and 'c'*64 not in prompt and 'f'*64 not in prompt
        assert 'audit_asset_82f88' not in prompt and '317' not in prompt
        program_request=v._read(tmp_path/'roi_job/REQUEST.json')
        assert program_request['prepared'][0]['expectation']['reference_roi']==expectation['reference_roi']
        assert result['reference_roi_evidence']['roi_source']==expectation['reference_roi_source']
        assert 'normalized integer [left,top,right,bottom]' in prompt


def test_invalid_native_xywh_copied_as_normalized_corners_is_never_rewritten(images,tmp_path):
    raw=face_observation();raw['checks']['clothing']=None
    raw['reference_rois']['face']=[307,30,139,165]
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],roi_expectation(images[0]),tmp_path/'roi_job')
        assert result['decision']=='unavailable' and result['error']=='invalid normalized image region'
        native=v._read(tmp_path/'roi_job/item_0000/MODEL_NATIVE.json')
        assert json.loads(native['text'])['reference_rois']['face']==[307,30,139,165]


def test_valid_source_crop_comparison_does_not_upgrade_unknown_clothing(images):
    raw=face_observation();raw['checks']['clothing']=None
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],roi_expectation(images[0]))
        # A face crop can pass its applicable visual checks while the absent
        # garment comparison remains null. Registry still checks real lineage.
        assert result['decision']=='accepted' and result['checks']['identity'] is True
        assert result['view_scope']['not_applicable']==['clothing']
        assert result['checks']['clothing'] is None and result['checks']['anatomy'] is True
