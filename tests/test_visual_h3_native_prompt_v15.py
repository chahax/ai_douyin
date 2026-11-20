"""CPU contracts for native H3 format, verbatim audio and bounded motion calls."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

import pytest
from src.content_factory import visual_h3_native_prompt_v15 as flow


def source_fixture(tmp_path):
    lines=['孩子（画外，童声，带着点怯）：「你好。」','男孩（画外，压低声音，稳稳的）：「嗯，好的！」',
           '旁白：「他躺着。」','男人：「回来。」','孩子：「爸爸。」']
    source='\n'.join(lines);path=tmp_path/'source.md';path.write_text(source,encoding='utf-8')
    def audio(index,text,speaker,mode,label):
        start=source.index(text)
        return dict(speaker=speaker,mode=mode,text=text,source_speaker=label,source_channel=mode,source_start=start,source_end=start+len(text))
    def shot(sid,audios,visible,indexes):
        evidence=[]
        for n in indexes:
            start=source.index(lines[n]);evidence.append(dict(id=f'U{n}',start=start,end=start+len(lines[n]),text=lines[n],sha256=flow.hashlib.sha256(lines[n].encode()).hexdigest()))
        return dict(id=sid,visible_cast=visible,source_native_frames=277,start=0,end=277/24,
            audio=audios,source_evidence=evidence,visual_prompt='Current physical action only.')
    shots=[shot('F0001',[audio(0,'你好。','c1','offscreen_dialogue','小一'),audio(1,'嗯，好的！','c2','offscreen_dialogue','小二')],['a'],[0,1]),
        shot('F0002',[audio(2,'他躺着。','narrator','voiceover','中性旁白')],['a'],[2]),
        shot('F0003',[audio(3,'回来。','a','inner_voice','成人')],['c1','c2'],[3]),
        shot('F0004',[audio(4,'爸爸。','c1','onscreen','小一')],['c1'],[4])]
    return dict(source=flow._binding(path),characters=[dict(id='a',age_band='adult'),dict(id='c1',age_band='child'),dict(id='c2',age_band='child')],shots=shots)


def entry(parent,shot):
    return dict(shot_id=shot['id'],shot_sha256=flow.stage.fingerprint(shot),source_shot_keys=list(shot),
        visible_cast=shot['visible_cast'],audio_sha256=flow.stage.fingerprint(shot['audio']),
        motion_description='The single adult man remains lying on his back, eyes closed, with a faint brow contraction and soft natural breathing.',
        overall_soundscape='Quiet room tone and soft breathing.',non_diegetic_music='N/A',
        speaker_map=flow.speaker_map(parent),source=parent['source'],visible_subject_labels=flow.subject_labels(parent,shot))


def test_global_source_speakers_keep_first_occurrence_ids_across_modes(tmp_path):
    parent=source_fixture(tmp_path);speakers=flow.speaker_map(parent)
    assert [(s['source_speaker'],s['speaker_id']) for s in speakers]==[('小一','S1'),('小二','S2'),('中性旁白','S3'),('成人','S4')]
    assert speakers[0]['first_shot']=='F0001' and len(speakers)==4


def test_fl2va_has_exact_native_sections_duration_verbatim_audio_and_per_line_closed_lips(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][0]
    result=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry(parent,shot),'first_last')
    assert result.startswith('How the reference pictures align with the target video — Picture 1 (from Shot 1)')
    assert 'Picture 2 (from Shot 1) aligns with the 11.54-second mark' in result
    assert result.count('integrated_multimodal_description: [Shot 1]')==1 and '[Shot 2]' not in result
    assert '\n\noverall_soundscape: ' in result and result.endswith('non_diegetic_music: N/A')
    for audio in shot['audio']:
        assert '<d>[Chinese] '+audio['text']+"</d> while all visible characters' lips remain completely closed." in result
    assert result.count(flow.OFFSCREEN_PHRASE)==2
    assert 'An unseen child voice (S1)' in result and 'An unseen child voice (S2)' in result
    assert 'with a timid delivery' in result and 'with a steady delivery' in result


def test_i2va_and_inner_voice_of_nonvisible_actor_do_not_add_a_visible_body(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][2]
    result=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry(parent,shot),'first')
    assert result.startswith('For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n')
    assert 'An unseen adult voice (S4) '+flow.OFFSCREEN_PHRASE in result
    assert 'The visible adult man (S4)' not in result


def test_onscreen_dialogue_has_lipsync_instead_of_voiceover_closed_mouth(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][3]
    result=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry(parent,shot),'first')
    assert 'The visible child (S1) says: <d>[Chinese] 爸爸。</d> with lips moving in sync' in result
    assert flow.OFFSCREEN_PHRASE not in result and 'lips remain completely closed' not in result


def test_15_second_request_keeps_native_362_frames_and_1508_anchor(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][0];shot.update(source_native_frames=362,end=15.0)
    result=flow.compile_for(shot,dict(native_frames=362,native_seconds=362/24,requested_seconds=15.0),entry(parent,shot),'first_last')
    assert '15.08-second mark' in result
    with pytest.raises(flow.NativePromptBlocked,match='timing_changed'):
        flow.compile_for(shot,dict(native_frames=362,native_seconds=15.0,requested_seconds=15.0),entry(parent,shot),'first_last')


def test_two_child_speakers_use_frozen_girl_boy_identity_without_guessed_position(tmp_path):
    parent=source_fixture(tmp_path);parent['characters'][1]['appearance_design']='A small Chinese girl in her established clothing.'
    parent['characters'][2]['appearance_design']='A small Chinese boy in his established clothing.'
    shot=parent['shots'][0];shot['visible_cast']=['c1','c2']
    for audio in shot['audio']:audio['mode']='onscreen'
    result=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry(parent,shot),'first')
    assert 'The visible girl (S1)' in result and 'The visible boy (S2)' in result
    assert result.count('says: <d>')==2
    assert 'left' not in result and 'right' not in result
    parent['characters'][1]['appearance_design']='A small Chinese boy in his established clothing.'
    with pytest.raises(flow.NativePromptBlocked,match='ambiguous_onscreen_speaker'):
        flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry(parent,shot),'first')


@pytest.mark.parametrize('timing',[dict(native_frames=278,native_seconds=278/24),dict(native_frames=277,native_seconds=11.54),dict(native_frames=277,native_seconds=float('nan'))])
def test_source_native_clock_cannot_change(tmp_path,timing):
    parent=source_fixture(tmp_path);shot=parent['shots'][0]
    with pytest.raises(flow.NativePromptBlocked,match='timing_changed'):
        flow.compile_for(shot,timing,entry(parent,shot),'first_last')


def test_additive_generated_fields_allowed_but_source_audio_and_cast_changes_rejected(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][0];e=entry(parent,shot)
    decorated=dict(shot,references=['generated'],binding_sha256='binding',first_frame='frame')
    assert flow.compile_for(decorated,dict(native_frames=277,native_seconds=277/24),e,'first')
    changed=deepcopy(shot);changed['audio'][0]['text']='改写台词'
    with pytest.raises(flow.NativePromptBlocked,match='source_shot_changed'):
        flow.compile_for(changed,dict(native_frames=277,native_seconds=277/24),e,'first')
    changed=deepcopy(shot);changed['visible_cast']=['c1']
    with pytest.raises(flow.NativePromptBlocked,match='source_shot_changed'):
        flow.compile_for(changed,dict(native_frames=277,native_seconds=277/24),e,'first')


@pytest.mark.parametrize('addition',['The camera turns toward the door.','A child enters the room.','Another man is beside him.','He says hello.'])
def test_motion_node_cannot_introduce_camera_cut_body_or_audio(tmp_path,addition):
    parent=source_fixture(tmp_path);shot=parent['shots'][0]
    candidate=dict(visible_cast=['a'],camera_motion='locked_off_tripod',motion_description='One adult man lies with closed eyes on the bed. '+addition)
    with pytest.raises(flow.NativePromptBlocked):
        flow._check_motion(candidate,shot,{c['id']:c for c in parent['characters']})


def planner_fixture(tmp_path,monkeypatch,*,camera_contract=flow.LEGACY_CAMERA_CONTRACT,shot_updates=None,real_image=False):
    parent=source_fixture(tmp_path)
    if shot_updates:parent['shots'][0].update(shot_updates)
    old=tmp_path/'old.json';flow.stage.files.write(old,dict(config=dict(provider='minimax',max_input_chars=60000)))
    parent['stage_plan']=flow._binding(old);scope=deepcopy(parent);scope['shots']=[scope['shots'][0]]
    pp=tmp_path/'parent.json';sp=tmp_path/'scope.json';flow.stage.files.write(pp,parent);flow.stage.files.write(sp,scope)
    image=tmp_path/'first.png';image.write_bytes(b'CPU fixture, not a generated image')
    if real_image:
        from PIL import Image
        Image.new('RGB',(736,1312),'gray').save(image)
    static_plan=tmp_path/'static.json';flow.stage.files.write(static_plan,dict(shots=[dict(shot_id='F0001',static_start_prompt='One adult man lies on the existing bed, eyes closed. Same held item remains where established.')]))
    asset=tmp_path/'asset';flow.stage.files.write(asset/'PLAN.json',dict(packet=scope,config=dict(first_frame_plan=flow._binding(static_plan))))
    ready=dict(source=parent['source'],first_frames=dict(F0001=flow._binding(image)));flow.stage.files.write(asset/'H3_INPUT_READY.json',ready)
    from src.content_factory import visual_h3_handoff_v3 as handoff,visual_first_frame_static_v13 as static_validator
    monkeypatch.setattr(flow.stage,'validate_packet',lambda packet:True)
    monkeypatch.setattr(handoff,'validate_ready',lambda path:(dict(plan=flow.stage.files.read(asset/'PLAN.json')),ready,{}))
    monkeypatch.setattr(static_validator,'validate_plan',lambda *args:True)
    monkeypatch.setattr(flow,'urlopen',lambda *args,**kwargs:BytesIO(b'integrated_multimodal_description says in an off-screen voiceover'))
    monkeypatch.setattr(flow.static,'_materials',lambda row,parent:(dict(source_physical_history_before_current_window=[],
        current_physical_source=[dict(id='fixture_action',text='The man clenches his jaw and takes several deep breaths.')],
        requested_output='One frozen opening instant only, with exactly the already-visible actors; no audio text is supplied.'),scope,scope['shots'][0],{}))
    run=tmp_path/'visual_h3_native_prompts_v15'/'trial';flow.prepare(run,pp,sp,asset,user_statement='CPU canary fixture authorization',camera_contract=camera_contract)
    return run,scope


class Client:
    def __init__(self,mode='valid'):self.mode=mode;self.calls=[]
    def binding(self):return dict(provider='fixture',model='not-a-model',retries=0)
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages))
        if self.mode=='unknown':raise TimeoutError('Missing terminal native response')
        if self.mode=='length' and len(self.calls)==1:
            from src.content_factory.creative_workflow_roles import RoleResponseError
            raise RoleResponseError('known length',dict(finish_reason='length'),response_payload=dict(choices=[dict(finish_reason='length',message=dict(content='{"unfinished":'))]))
        text='One adult man remains on his back on the bed, eyes closed, brow gently tense, with soft breathing and tiny eyelid movement.'
        if self.mode=='bad':text+=' The camera turns toward the door.'
        return dict(text=json.dumps(dict(visible_cast=['a'],camera_motion='locked_off_tripod',motion_description=text)),completion_known=True,metadata=dict(finish_reason='stop'),native=dict(fixture=True))


def test_native_planner_freezes_receipts_reads_selected_static_and_preserves_source(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);original=deepcopy(scope);client=Client();binding=flow.plan(run,client=client)
    assert len(client.calls)==1 and flow.verify_plan(binding['path'])
    material=json.loads(client.calls[0][1]['content'])['materials']
    assert 'selected_static_start_context' in material and 'source_physical_history_before_current_window' in material
    assert 'frozen opening instant' not in material['requested_output'] and 'Continuous visible motion' in material['requested_output']
    assert 'several deep breaths' in material['current_physical_source'][0]['text']
    assert 'Opening-state' in material['motion_input_roles']['selected_static_start_context']
    assert 'only for current visible_cast actors' in material['motion_input_roles']['current_physical_source']
    assert 'outside visible_cast remain outside the image' in client.calls[0][0]['content']
    assert 'not a minimum person count throughout' in client.calls[0][0]['content']
    assert 'Source exits may reduce' in material['motion_input_roles']['cast_domain']
    assert scope==original and '"audio"' not in json.dumps(material)
    shot=dict(scope['shots'][0],references=[]);entry=flow.load_for(scope,binding,shot)
    assert flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),entry,'first_last')
    flow.plan(run,client=client);assert len(client.calls)==1


def test_known_length_can_use_only_second_canary_call_but_unknown_cannot_replay(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);client=Client('length');flow.plan(run,client=client)
    assert len(client.calls)==2 and flow.status(run)['claimed_calls']==2
    assert flow.stage.files.read(run/'calls/attempt_00/ERROR.json')['completion_known'] is True


def test_unknown_canary_retains_claim_and_does_not_call_again(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);client=Client('unknown')
    with pytest.raises(flow.NativePromptBlocked,match='unknown_native_motion'):flow.plan(run,client=client)
    other=Client()
    with pytest.raises(flow.NativePromptBlocked,match='unknown_native_motion'):flow.plan(run,client=other)
    assert len(client.calls)==1 and not other.calls and flow.status(run)['unknown_calls']==1


def test_two_known_invalid_candidates_exhaust_bounded_canary(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);client=Client('bad')
    with pytest.raises(flow.NativePromptBlocked,match='known_native_motion_validation_failed'):flow.plan(run,client=client)
    assert len(client.calls)==2 and flow.status(run)['claimed_calls']==2


def test_program_sound_fields_cannot_hide_unmodelled_story_or_music(tmp_path,monkeypatch):
    run,_=planner_fixture(tmp_path,monkeypatch);binding=flow.plan(run,client=Client())
    path=Path(binding['path']);value=flow.stage.files.read(path)
    value['shots'][0]['overall_soundscape']='A second adult enters the room and shouts.'
    flow.stage.files.write(path,value)
    with pytest.raises(flow.NativePromptBlocked,match='program_sound_fields_changed'):
        flow.verify_plan(path)


def successor(run,scope,new_run,predecessor=None):
    p=flow.status(run)['plan']
    return flow.prepare(new_run,p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
        user_statement='CPU known successor, joint maximum two calls.',official_guide_path=p['official_guide']['path'],
        known_predecessor=predecessor or run,known_issue='Prior motion omitted an explicit source action.',issue_evidence=[scope['shots'][0]['source_evidence'][0]],camera_contract=p.get('camera_contract',flow.LEGACY_CAMERA_CONTRACT))


def test_known_motion_successor_uses_only_remaining_one_call_preserves_parent_and_f1_wrapper(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);flow.plan(run,client=Client());before={p:p.read_bytes() for p in [run/'PLAN.json',run/'NATIVE_PROMPT_PLAN.json',run/'calls/attempt_00/NATIVE.json']}
    shot=scope['shots'][0];original_prompt=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),flow.load_for(scope,flow._binding(run/'NATIVE_PROMPT_PLAN.json'),shot),'first_last')
    new_run=run.parent/'known_r1';s=successor(run,scope,new_run)
    assert s['plan']['max_calls']==1 and s['predecessor_claimed_calls']==1
    client=Client();flow.plan(new_run,client=client)
    assert len(client.calls)==1 and flow.status(new_run)['joint_claimed_calls']==2
    assert flow.verify_plan(new_run/'NATIVE_PROMPT_PLAN.json')
    assert all(p.read_bytes()==content for p,content in before.items())
    assert original_prompt==flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),flow.load_for(scope,flow._binding(run/'NATIVE_PROMPT_PLAN.json'),shot),'first_last')
    with pytest.raises(flow.NativePromptBlocked,match='total_two_calls_exhausted'):
        successor(new_run,scope,run.parent/'third_rejected')


def test_unknown_predecessor_cannot_spawn_a_fresh_namespace(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch)
    with pytest.raises(flow.NativePromptBlocked,match='unknown_native_motion'):flow.plan(run,client=Client('unknown'))
    new_run=run.parent/'unknown_successor_forbidden'
    with pytest.raises(flow.NativePromptBlocked,match='unknown_predecessor_cannot_have_successor'):
        successor(run,scope,new_run)
    assert not (new_run/'PLAN.json').exists() and flow.status(run)['claimed_calls']==1


def test_known_successor_failure_cannot_take_a_third_call(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);flow.plan(run,client=Client());new_run=run.parent/'known_bad_r1';successor(run,scope,new_run)
    client=Client('bad')
    with pytest.raises(flow.NativePromptBlocked,match='known_native_motion_validation_failed'):
        flow.plan(new_run,client=client)
    assert len(client.calls)==1 and flow.status(new_run)['joint_claimed_calls']==2


def test_known_successor_can_cite_exact_prior_physical_history_but_not_unsupplied_context(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);flow.plan(run,client=Client());p=flow.status(run)['plan']
    source=Path(scope['source']['path']).read_text(encoding='utf-8');quote='他躺着。';start=source.index(quote)
    evidence=dict(id='EXACT_PRIOR_UNIT',start=start,end=start+len(quote),text=quote,sha256=flow.hashlib.sha256(quote.encode()).hexdigest())
    # The allowed domain is the actual context supplied by the source adapter,
    # not arbitrary other chapters/lines from the same source file.
    material=dict(source_physical_history_before_current_window=[dict(source_id=evidence['id'],**{k:v for k,v in evidence.items() if k!='id'})])
    monkeypatch.setattr(flow.static,'_materials',lambda *args:(material,scope,scope['shots'][0],{}))
    new_run=run.parent/'prior_context_r1'
    flow.prepare(new_run,p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
        user_statement='Exact prior context known correction.',official_guide_path=p['official_guide']['path'],known_predecessor=run,
        known_issue='Preserve the prior established physical state.',issue_evidence=[evidence])
    evidence=dict(evidence,id='NOT_IN_CONTEXT')
    with pytest.raises(flow.NativePromptBlocked,match='issue_evidence_changed'):
        flow.prepare(run.parent/'unrelated_rejected',p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
            user_statement='Must reject unrelated context.',official_guide_path=p['official_guide']['path'],known_predecessor=run,
            known_issue='Unknown claimed evidence.',issue_evidence=[evidence])


def corrected_frame_fixture(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);flow.plan(run,client=Client());p=flow.status(run)['plan']
    new_asset=tmp_path/'corrected_asset';new_image=tmp_path/'corrected_first.png';new_image.write_bytes(b'CPU corrected frame, not production media')
    new_static=tmp_path/'corrected_static.json';new_static.write_bytes(Path(p['selected_static_plan']['path']).read_bytes())
    flow.stage.files.write(new_asset/'PLAN.json',dict(packet=scope,config=dict(first_frame_plan=flow._binding(new_static))))
    flow.stage.files.write(new_asset/'H3_INPUT_READY.json',dict(source=scope['source'],first_frames=dict(F0001=flow._binding(new_image))))
    from src.content_factory import visual_h3_handoff_v3 as handoff
    monkeypatch.setattr(handoff,'validate_ready',lambda path:(dict(plan=flow.stage.files.read(Path(path)/'PLAN.json')),flow.stage.files.read(Path(path)/'H3_INPUT_READY.json'),{}))
    review=tmp_path/'ROOT_CORRECTED_FRAME_REVIEW.json';flow.stage.files.write(review,dict(frame=flow._binding(new_image),accepted=True,scope='CPU contract fixture'))
    proof=dict(schema='root_reviewed_first_frame_correction/v15',root_accepted=True,authorization='CPU explicit root correction fixture.',reason='The old reviewed frame contained a wrong held-item state.',
        source=scope['source'],full_parent=p['full_parent'],packet_sha256=flow.stage.fingerprint(scope),shot_id='F0001',shot_sha256=flow.stage.fingerprint(scope['shots'][0]),
        predecessor_prompt_plan=flow._binding(run/'NATIVE_PROMPT_PLAN.json'),old_state=flow._frame_state(p),
        new_state=dict(asset_plan=flow._binding(new_asset/'PLAN.json'),input_ready=flow._binding(new_asset/'H3_INPUT_READY.json'),reviewed_first_frame=flow._binding(new_image),selected_static_plan=flow._binding(new_static)),
        root_review=flow._binding(review))
    proof_path=tmp_path/'FRAME_CORRECTION_PROOF.json';flow.stage.files.write(proof_path,proof)
    return run,scope,new_asset,proof_path


def prepare_corrected(run,scope,new_asset,target,proof=None):
    p=flow.status(run)['plan']
    return flow.prepare(target,p['full_parent']['path'],p['packet']['path'],new_asset,
        user_statement='CPU frame correction known successor, joint two maximum.',official_guide_path=p['official_guide']['path'],known_predecessor=run,
        known_issue='Keep the source action and corrected first-frame held-item state.',issue_evidence=[scope['shots'][0]['source_evidence'][0]],frame_correction_proof=proof,camera_contract=flow.LEGACY_CAMERA_CONTRACT)


def test_changed_reviewed_frame_remains_rejected_without_explicit_root_proof(tmp_path,monkeypatch):
    run,scope,new_asset,proof=corrected_frame_fixture(tmp_path,monkeypatch)
    target=run.parent/'unproved_frame_r1'
    with pytest.raises(flow.NativePromptBlocked,match='frame_change_requires_root_proof'):
        prepare_corrected(run,scope,new_asset,target)
    assert not (target/'PLAN.json').exists() and flow.status(run)['claimed_calls']==1


def test_root_proof_can_change_only_reviewed_frame_layer_with_joint_two_calls(tmp_path,monkeypatch):
    run,scope,new_asset,proof=corrected_frame_fixture(tmp_path,monkeypatch);before=(run/'NATIVE_PROMPT_PLAN.json').read_bytes();target=run.parent/'proved_frame_r1'
    state=prepare_corrected(run,scope,new_asset,target,proof)
    assert state['plan']['max_calls']==1 and state['predecessor_claimed_calls']==1
    client=Client();binding=flow.plan(target,client=client);value=flow.verify_plan(binding['path'])
    assert len(client.calls)==1 and flow.status(target)['joint_claimed_calls']==2
    assert value['reviewed_first_frame']!=flow.verify_plan(run/'NATIVE_PROMPT_PLAN.json')['reviewed_first_frame']
    assert (run/'NATIVE_PROMPT_PLAN.json').read_bytes()==before


@pytest.mark.parametrize('field',['packet_sha256','root_accepted','old_state'])
def test_frame_correction_scope_or_old_frame_tamper_rejected_before_call(tmp_path,monkeypatch,field):
    run,scope,new_asset,path=corrected_frame_fixture(tmp_path,monkeypatch);proof=flow.stage.files.read(path)
    if field=='packet_sha256':proof[field]='wrong_source_scope'
    elif field=='root_accepted':proof[field]=False
    else:proof[field]=proof['new_state']
    flow.stage.files.write(path,proof)
    with pytest.raises(flow.NativePromptBlocked,match='root_frame_correction_scope_or_bindings_changed'):
        prepare_corrected(run,scope,new_asset,run.parent/'bad_proof_r1',path)
    assert flow.status(run)['claimed_calls']==1


def test_frame_correction_proof_cannot_release_an_unknown_predecessor(tmp_path,monkeypatch):
    run,scope,new_asset,proof=corrected_frame_fixture(tmp_path,monkeypatch)
    flow.stage.files.write(run/'calls/attempt_01/CLAIM.json',dict(unresolved=True))
    with pytest.raises(flow.NativePromptBlocked,match='unknown_predecessor_cannot_have_successor'):
        prepare_corrected(run,scope,new_asset,run.parent/'unknown_frame_r1',proof)


@pytest.mark.parametrize('mode',['missing','duplicate','reversed','unknown','malformed'])
def test_source_audio_markers_require_fixed_ids_count_and_original_order(tmp_path,mode):
    parent=source_fixture(tmp_path);spec=flow.audio_insertion_spec(parent['shots'][0],flow.speaker_map(parent));a,b=[s['token'] for s in spec['slots']]
    text={'missing':a,'duplicate':a+a+b,'reversed':b+a,'unknown':a+'[[SOURCE_AUDIO:A9999]]','malformed':a+b+'[[BROKEN'}[mode]
    with pytest.raises(flow.NativePromptBlocked,match='source_audio_marker'):
        flow._check_audio_markers(text,spec)


def test_source_audio_insertion_is_before_exit_verbatim_and_never_tail_duplicated(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][3];shot['visible_cast']=['a','c1'];e=entry(parent,shot);e['audio_insertion']=flow.audio_insertion_spec(shot,e['speaker_map'])
    token=e['audio_insertion']['slots'][0]['token'];e['motion_description']='The adult stands near the child, who lowers onto both knees. '+token+' The child rises and runs out of the frame. The adult remains standing alone.'
    compiled=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),e,'first')
    assert compiled.index('lowers onto both knees')<compiled.index('<d>[Chinese] 爸爸。</d>')<compiled.index('runs out of the frame')
    assert compiled.count('<d>')==1 and '[[SOURCE_AUDIO' not in compiled
    assert 'Source-established exits may reduce' in compiled
    assert 'visible subjects, clothing and room throughout' not in compiled
    assert 'actor identities' in compiled and 'adult remains standing alone' in compiled


def test_audio_insertion_context_masks_exact_speech_and_keeps_source_actions(tmp_path):
    parent=source_fixture(tmp_path);shot=parent['shots'][0];spec=flow.audio_insertion_spec(shot,flow.speaker_map(parent))
    context=flow.audio_order_context(shot,Path(parent['source']['path']).read_text(encoding='utf-8'),spec)
    text=json.dumps(context,ensure_ascii=False)
    assert '你好。' not in text and '嗯，好的！' not in text
    assert all(slot['token'] in text for slot in spec['slots'])
    assert all('original_unit_sha256' in item for item in context)


@pytest.mark.parametrize('field',['speaker_id','text_sha256'])
def test_compiled_audio_insertion_cannot_change_source_voice_or_text_hash(tmp_path,field):
    parent=source_fixture(tmp_path);shot=parent['shots'][0];e=entry(parent,shot);e['audio_insertion']=flow.audio_insertion_spec(shot,e['speaker_map'])
    e['motion_description']='One adult rests. '+' '.join(s['token'] for s in e['audio_insertion']['slots'])+' He remains on the bed.'
    e['audio_insertion']['slots'][0][field]='changed'
    with pytest.raises(flow.NativePromptBlocked,match='audio_insertion_source_or_speaker_changed'):
        flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),e,'first')


def test_audio_insertion_mode_same_native_request_never_sends_speech_for_rewriting(tmp_path,monkeypatch):
    old,scope=planner_fixture(tmp_path,monkeypatch);p=flow.status(old)['plan'];run=old.parent/'insertion_mode'
    flow.prepare(run,p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
        user_statement='CPU explicit insertion mode.',official_guide_path=p['official_guide']['path'],source_audio_insertion=True,camera_contract=flow.LEGACY_CAMERA_CONTRACT)
    class MarkerClient(Client):
        def call(self,messages,schema):
            raw=super().call(messages,schema);candidate=json.loads(raw['text']);m=json.loads(messages[1]['content'])['materials'];tokens=[s['token'] for s in m['source_audio_insertion']['slots']]
            candidate['motion_description']='One adult man rests on the bed. '+tokens[0]+' His brow settles. '+tokens[1]+' He continues breathing.'
            raw['text']=json.dumps(candidate);return raw
    client=MarkerClient();binding=flow.plan(run,client=client);v=flow.verify_plan(binding['path'])
    assert len(client.calls)==1 and v['shots'][0]['audio_insertion']['audio_sha256']==flow.stage.fingerprint(scope['shots'][0]['audio'])
    supplied=json.loads(client.calls[0][1]['content'])['materials'];encoded=json.dumps(supplied,ensure_ascii=False)
    assert '你好。' not in encoded and '嗯，好的！' not in encoded and 'source_timeline_audio_masked' in supplied
    shot=scope['shots'][0];compiled=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),flow.load_for(scope,binding,shot),'first')
    assert compiled.count('<d>')==2 and compiled.count('你好。')==1 and compiled.count('嗯，好的！')==1
    next_run=run.parent/'insertion_known_r1';state=successor(run,scope,next_run)
    assert state['plan']['audio_insertion']==flow.status(run)['plan']['audio_insertion']
    issue,evidence=flow._masked_issue_material('Place 你好。 earlier.',scope['shots'][0]['source_evidence'],
        Path(scope['source']['path']).read_text(encoding='utf-8'),state['plan']['audio_insertion'],scope['shots'][0]['audio'])
    assert '你好。' not in issue and '你好。' not in json.dumps(evidence,ensure_ascii=False)


def test_default_f1_compiler_golden_remains_byte_identical(tmp_path):
    # Golden is the reviewed pre-insertion compiler string (LF UTF-8). The
    # separately saved Windows text file has CRLF and a different physical SHA.
    # Only the tiny source lines are recreated locally; paths never enter prompt.
    text='老六（画外，童声，带着点怯）：「二哥，今天没偷到钱，怎么办呀？」\n叶南（画外，压低声音，稳稳的）：「哥哥发传单挣了十块，先给你。」'
    path=tmp_path/'f1_source.md';path.write_text(text,encoding='utf-8');audio=[];units=[]
    for n,(speaker,label,spoken) in enumerate([('ye_xijue','叶西决','二哥，今天没偷到钱，怎么办呀？'),('ye_nan','叶南','哥哥发传单挣了十块，先给你。')]):
        line=text.splitlines()[n];start=text.index(line);a=text.index(spoken)
        units.append(dict(id=str(n),start=start,end=start+len(line),text=line,sha256=flow.hashlib.sha256(line.encode()).hexdigest()))
        audio.append(dict(speaker=speaker,source_speaker=label,mode='offscreen_dialogue',text=spoken,source_start=a,source_end=a+len(spoken)))
    shot=dict(id='F0001',visible_cast=['su_mo'],audio=audio,source_evidence=units,source_native_frames=277,start=0,end=277/24)
    parent=dict(source=flow._binding(path),characters=[dict(id='su_mo',age_band='adult'),dict(id='ye_xijue',age_band='child'),dict(id='ye_nan',age_band='child')],shots=[shot])
    e=entry(parent,shot);e['motion_description']='Su Mo lies motionless on his back with his head and shoulders resting on the narrow wooden bed, his eyes closed and brow faintly tightened. Only imperceptible breathing and slight eyelid tension are visible; the camera and room remain completely still.'
    e['overall_soundscape']=flow.ROOM_SOUNDSCAPE
    prompt=flow.compile_for(shot,dict(native_frames=277,native_seconds=277/24),e,'first_last')
    assert flow.hashlib.sha256(prompt.encode()).hexdigest()=='b54f2b0c7e5aeb62037eaa525ba338c3291ee933115a965fc9c4130921986f44'

