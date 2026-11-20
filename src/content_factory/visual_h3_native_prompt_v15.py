"""Source-bound H3 native prompt compiler and bounded motion-only planner.

This independent adapter never edits a screenplay, source audio, a media graph,
an existing first frame, or a prior model request.  Images/media are dispatched
by the existing handoff after separately checking its endpoint policy.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.request import urlopen

from jsonschema import validate
from . import visual_continuous_stage_v6 as stage
from . import visual_static_start_planner_v13 as static
from .visual_source_voice_v13 import source_direction

CONTRACT = 'official_multimodal/v15'
SCHEMA = 'h3_native_prompt_plan/v15'
VERSION = 'h3_motion_planner/v15'
# Frozen v15 receipts keep their original schema and compiler bytes.  Newly
# prepared work inherits the director's shot instead of imposing a tripod.
CONTRACT_V19 = 'official_multimodal/v19'
SCHEMA_V19 = 'h3_native_prompt_plan/v19'
VERSION_V19 = 'h3_motion_planner/v19'
CAMERA_CONTRACT_V19 = 'source_designed/v19'
LEGACY_CAMERA_CONTRACT = 'legacy_locked_off/v15'
GUIDE_URL = 'https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md'
ENGLISH = r'^[^\u3400-\u9FFF]+$'
OFFSCREEN_PHRASE = 'says in an off-screen voiceover'
AUDIO_MODES = ('onscreen', 'inner_voice', 'voiceover', 'offscreen_dialogue')
ROOM_SOUNDSCAPE = 'Quiet indoor room tone and soft natural breathing.'


class NativePromptBlocked(ValueError):
    pass


def _binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=stage.files.file_sha(path))


def _read_binding(binding):
    if (not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}
            or stage.files.file_sha(binding['path']) != binding['sha256']):
        raise NativePromptBlocked('native_prompt_artifact_changed')
    return stage.files.read(binding['path'])


def _guard(run):
    run = Path(run).resolve()
    if run.parent.name not in ('visual_h3_native_prompts_v15','visual_h3_native_prompts_v19') or not re.fullmatch(stage.legacy.SLUG, run.name):
        raise NativePromptBlocked('new_h3_native_prompt_namespace_required')
    return run


def speaker_map(parent):
    """Assign IDs once from the full ordered source audio, never per clip."""
    characters = {c['id']: c for c in parent['characters']}
    found = {}
    for shot in parent['shots']:
        for audio in shot.get('audio', []):
            if audio.get('mode') not in AUDIO_MODES or not audio.get('text'):
                raise NativePromptBlocked('invalid_source_audio')
            key = audio.get('source_speaker') or audio['speaker']
            if key not in found:
                actor = characters.get(audio['speaker'], {})
                found[key] = dict(source_speaker=key, character_id=audio['speaker'],
                    speaker_id='S' + str(len(found) + 1), age_band=actor.get('age_band', 'unspecified'),
                    first_shot=shot['id'])
            elif found[key]['character_id'] != audio['speaker']:
                raise NativePromptBlocked('source_speaker_identity_changed')
    return list(found.values())


def _validate_audio(shot, source):
    for audio in shot.get('audio', []):
        if (audio.get('mode') not in AUDIO_MODES or not isinstance(audio.get('text'), str)
                or not audio['text'].strip() or not audio.get('speaker')
                or '<d>' in audio['text'] or '</d>' in audio['text']):
            raise NativePromptBlocked('invalid_verbatim_audio')
        if audio['mode'] == 'onscreen' and audio['speaker'] not in shot['visible_cast']:
            raise NativePromptBlocked('onscreen_speaker_not_visible')
        if not all(k in audio for k in ('source_start', 'source_end')):
            raise NativePromptBlocked('source_audio_exact_range_required')
        a, b = audio['source_start'], audio['source_end']
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source) or source[a:b] != audio['text']:
            raise NativePromptBlocked('verbatim_audio_source_mismatch')


def audio_insertion_spec(shot,speakers):
    """Program-owned source speech slots; the model only positions their IDs."""
    audio=shot.get('audio',[])
    if not audio:raise NativePromptBlocked('source_audio_insertion_requires_existing_audio')
    mapping={s['source_speaker']:s for s in speakers};slots=[];last_end=-1
    for index,item in enumerate(audio):
        key=item.get('source_speaker') or item['speaker']
        if key not in mapping or mapping[key]['character_id']!=item['speaker']:
            raise NativePromptBlocked('source_audio_slot_speaker_changed')
        if item['source_start']<last_end:raise NativePromptBlocked('source_audio_slots_not_original_order')
        last_end=item['source_end'];identity=f'A{index+1:04d}'
        slots.append(dict(id=identity,token='[[SOURCE_AUDIO:'+identity+']]',index=index,
            source_start=item['source_start'],source_end=item['source_end'],
            text_sha256=hashlib.sha256(item['text'].encode()).hexdigest(),
            source_speaker=key,speaker_id=mapping[key]['speaker_id'],character_id=item['speaker'],mode=item['mode']))
    return dict(schema='source_audio_markers/v15',audio_sha256=stage.fingerprint(audio),slots=slots)


def audio_order_context(shot,source,spec):
    """Replace only exact original spoken ranges; retain source action order."""
    units=[];seen=[]
    for unit in shot.get('source_evidence',[]):
        original=source[unit['start']:unit['end']]
        if original!=unit['text'] or hashlib.sha256(original.encode()).hexdigest()!=unit['sha256']:
            raise NativePromptBlocked('source_audio_order_context_changed')
        matches=[s for s in spec['slots'] if unit['start']<=s['source_start']<s['source_end']<=unit['end']]
        value=original
        for slot in reversed(matches):
            a,b=slot['source_start']-unit['start'],slot['source_end']-unit['start']
            value=value[:a]+slot['token']+value[b:]
        seen.extend(s['id'] for s in matches)
        units.append(dict(source_id=unit['id'],start=unit['start'],end=unit['end'],original_unit_sha256=unit['sha256'],
            derived_text_with_audio_markers=value,original_spoken_text_omitted=True))
    if seen!=[s['id'] for s in spec['slots']]:
        raise NativePromptBlocked('source_audio_slot_must_have_one_current_source_unit')
    return units


def _check_audio_markers(text,spec):
    marks=re.findall(r'\[\[(.*?)\]\]',text,re.S)
    expected=['SOURCE_AUDIO:'+s['id'] for s in spec['slots']]
    if marks!=expected:raise NativePromptBlocked('source_audio_markers_missing_duplicate_or_out_of_order')
    stripped=text
    for slot in spec['slots']:stripped=stripped.replace(slot['token'],'')
    if '[[' in stripped or ']]' in stripped:
        raise NativePromptBlocked('source_audio_marker_malformed_or_arbitrary')


def _masked_issue_material(issue,evidence,source,spec,audio):
    """Keep original correction proof on disk, redact speech only in model I/O."""
    issue=issue or None
    if issue:
        for slot,item in zip(spec['slots'],audio):issue=issue.replace(item['text'],slot['token'])
    result=[]
    for unit in evidence or []:
        text=source[unit['start']:unit['end']]
        for slot in reversed(spec['slots']):
            if unit['start']<=slot['source_start']<slot['source_end']<=unit['end']:
                a,b=slot['source_start']-unit['start'],slot['source_end']-unit['start'];text=text[:a]+slot['token']+text[b:]
        result.append(dict(source_id=unit['id'],start=unit['start'],end=unit['end'],original_unit_sha256=unit['sha256'],derived_text_with_audio_markers=text))
    return issue,result or None


def _source_shot(shot, entry):
    try:
        projected = {key: shot[key] for key in entry['source_shot_keys']}
    except KeyError as error:
        raise NativePromptBlocked('source_shot_fields_missing') from error
    if (shot.get('id') != entry['shot_id'] or stage.fingerprint(projected) != entry['shot_sha256']
            or shot.get('visible_cast') != entry['visible_cast']
            or stage.fingerprint(shot.get('audio', [])) != entry['audio_sha256']):
        raise NativePromptBlocked('native_prompt_source_shot_changed')
    return projected


def source_camera_design(shot, explicit=None):
    """Bind existing direction, never ask the video adapter to direct a shot.

    An optional explicit design is an immutable upstream artifact.  Otherwise
    the original shot fields are the authority, including its visual prompt.
    No general camera-motion choice is inferred from a first-frame camera ROI.
    """
    fields={k:deepcopy(shot[k]) for k in ('camera_design','camera_instructions','camera_motion','visual_prompt') if k in shot}
    value=dict(schema='bound_source_camera_design/v19',source_shot_sha256=stage.fingerprint(shot),
        authority='source_shot',source_fields=fields,camera_motion='inherit_source_shot_design',mode='inherit')
    if explicit is not None:
        design=_read_binding(explicit)
        if (design.get('schema')!='source_camera_design/v19'
                or design.get('shot_sha256')!=stage.fingerprint(shot)
                or not isinstance(design.get('instruction'),str) or not design['instruction'].strip()
                or not isinstance(design.get('camera_motion'),str) or not design['camera_motion'].strip()):
            raise NativePromptBlocked('explicit_upstream_camera_design_required')
        value.update(authority='explicit_upstream_design',explicit=deepcopy(explicit),
            instruction=design['instruction'],camera_motion=design['camera_motion'])
        mode=design.get('mode',design['camera_motion'])
    else:
        structured=shot.get('camera_design')
        mode=(structured.get('mode',structured.get('camera_motion')) if isinstance(structured,dict)
              else shot.get('camera_motion'))
    if mode in ('fixed','locked_off','locked_off_tripod','static','static_shot'):
        value['mode']='explicit_fixed'
    return value


def response_schema(visible, camera_design=None):
    fields=dict(visible_cast=dict(const=visible),
        camera_motion=dict(const=camera_design['camera_motion'] if camera_design else 'locked_off_tripod'),
        motion_description=dict(type='string', minLength=40, maxLength=2400, pattern=ENGLISH))
    if camera_design:fields['camera_contract']=dict(const=CAMERA_CONTRACT_V19)
    return stage.legacy.obj(fields)


def _camera_operations(text):
    """Conservative operation bounds; semantic camera QA still follows text QA.

    These are source-operation permissions, not a new shot-selection policy.
    Unrecognized direction remains in the source material for adaptation.
    """
    patterns=dict(
        cut=r'\b(?:cuts? to|camera cuts?|shot cuts?|reverse shot)\b|(?<!无)(?<!不)切(?:镜|换)',
        push=r'\b(?:push(?:es)? in|doll(?:y|ies) in)\b|(?<!无)(?<!不)推进',
        pull=r'\bpull(?:s)? back\b|(?<!无)(?<!不)拉远|(?<!无)(?<!不)拉开',
        zoom=r'\bzoom(?:s)?(?: in| out)?\b|(?<!无)(?<!不)变焦',
        pan=r'\bpan(?:s)?(?: left| right)?\b|(?<!无)(?<!不)摇镜|(?<!无)(?<!不)横摇',
        tilt=r'\btilt(?:s)?(?: up| down)?\b|(?<!无)(?<!不)纵摇',
        arc=r'\b(?:camera arcs?|arc shot)\b|(?<!无)(?<!不)环绕',
        track=r'\b(?:camera tracks?|tracking shot)\b|(?<!无)(?<!不)跟拍')
    return {name for name,pattern in patterns.items() if re.search(pattern,text,re.I)}


def _check_motion(candidate, shot, all_characters, camera_design=None):
    validate(candidate, response_schema(shot['visible_cast'],camera_design))
    text = candidate['motion_description']
    if re.search(r'<d>|\[Shot|overall_soundscape:|non_diegetic_music:', text, re.I):
        raise NativePromptBlocked('motion_node_cannot_write_audio_or_native_wrapper')
    if re.search(r'\b(?:says?|speaks?|voiceover|offscreen|off-screen)\b',text,re.I):
        raise NativePromptBlocked('motion_node_added_camera_transition_or_voice')
    legacy_camera=r'\b(?:camera (?:pans?|turns?|cuts?|arcs?|zooms?|moves?|tracks?|rotates?)|cut to|reverse shot|new angle|new scene)\b'
    fixed_camera=r'\b(?:camera (?:pans?|turns?|cuts?|arcs?|zooms?|moves?|tracks?|rotates?|pushes?|pulls?|dollies?)|cut to|cuts? to|reverse shot|new angle|new scene|push(?:es)? in|pull(?:s)? back)\b'
    if ((camera_design is None and re.search(legacy_camera,text,re.I)) or
        (camera_design and camera_design['mode']=='explicit_fixed' and re.search(fixed_camera,text,re.I))):
        raise NativePromptBlocked('motion_node_added_camera_transition_or_voice')
    if camera_design and camera_design['mode']!='explicit_fixed':
        source_text=(camera_design['instruction'] if camera_design.get('authority')=='explicit_upstream_design'
            else json.dumps(camera_design.get('source_fields',{}),ensure_ascii=False))
        if _camera_operations(text)-_camera_operations(source_text):
            raise NativePromptBlocked('camera_operation_not_in_upstream_design')
    normalized = ''.join(c for c in text.casefold() if c.isalnum())
    for identity in set(all_characters) - set(shot['visible_cast']):
        if ''.join(c for c in identity.casefold() if c.isalnum()) in normalized:
            raise NativePromptBlocked('motion_node_added_nonvisible_identity')
    if len(shot['visible_cast']) == 1:
        if re.search(r'\b(?:two|three|second|another)\s+(?:man|men|adult|person|people|body|bodies)\b', text, re.I):
            raise NativePromptBlocked('motion_node_added_body')
        if all(all_characters[c].get('age_band') == 'adult' for c in shot['visible_cast']):
            if re.search(r'\b(?:child|children|boy|boys|girl|girls)\b', text, re.I):
                raise NativePromptBlocked('motion_node_added_unseen_child')


FRAME_STATE_KEYS=('asset_plan','input_ready','reviewed_first_frame','selected_static_plan')


def _frame_state(plan):
    return {key:deepcopy(plan[key]) for key in FRAME_STATE_KEYS}


def _validate_frame_correction(binding, previous_prompt_binding, previous_plan, new_state, source, full_parent, packet_sha256, shot):
    proof=_read_binding(binding)
    expected=dict(schema='root_reviewed_first_frame_correction/v15',root_accepted=True,source=source,full_parent=full_parent,
        packet_sha256=packet_sha256,shot_id=shot['id'],shot_sha256=stage.fingerprint(shot),
        predecessor_prompt_plan=previous_prompt_binding,old_state=_frame_state(previous_plan),new_state=new_state)
    if (any(proof.get(k)!=value for k,value in expected.items()) or not proof.get('authorization') or not proof.get('reason')):
        raise NativePromptBlocked('root_frame_correction_scope_or_bindings_changed')
    for state in (proof['old_state'],proof['new_state']):
        if set(state)!=set(FRAME_STATE_KEYS):raise NativePromptBlocked('root_frame_correction_state_incomplete')
        for record in state.values():
            if not isinstance(record,dict) or set(record)!={'path','sha256'} or stage.files.file_sha(record['path'])!=record['sha256']:
                raise NativePromptBlocked('root_frame_correction_artifact_changed')
    _read_binding(proof['root_review'])
    if proof.get('root_rejection'):_read_binding(proof['root_rejection'])
    return proof


def prepare(run, parent_packet, scope_packet, asset_run, *, user_statement, official_guide_path=None,
            known_predecessor=None, known_issue=None, issue_evidence=None,frame_correction_proof=None,source_audio_insertion=None,
            camera_contract=CAMERA_CONTRACT_V19,camera_design=None):
    """Freeze one scoped canary and all-parent speaker order, with max two calls."""
    run = _guard(run)
    parent_packet, scope_packet, asset_run = map(lambda p: Path(p).resolve(), (parent_packet, scope_packet, asset_run))
    parent, scope = stage.files.read(parent_packet), stage.files.read(scope_packet)
    stage.validate_packet(parent); stage.validate_packet(scope)
    if len(scope['shots']) != 1 or not user_statement or scope['source'] != parent['source']:
        raise NativePromptBlocked('single_source_bound_canary_required')
    shot = scope['shots'][0]
    if camera_contract not in (CAMERA_CONTRACT_V19,LEGACY_CAMERA_CONTRACT):
        raise NativePromptBlocked('unsupported_camera_contract')
    if camera_contract==LEGACY_CAMERA_CONTRACT and camera_design is not None:
        raise NativePromptBlocked('legacy_camera_contract_cannot_take_new_design')
    directed=source_camera_design(shot,camera_design) if camera_contract==CAMERA_CONTRACT_V19 else None
    original = next((s for s in parent['shots'] if s['id'] == shot['id']), None)
    if original != shot:
        raise NativePromptBlocked('scope_shot_differs_from_full_parent')
    from .visual_h3_handoff_v3 import validate_ready
    snapshot, ready, _ = validate_ready(asset_run)
    if snapshot['plan']['packet'] != scope or ready['source'] != scope['source']:
        raise NativePromptBlocked('reviewed_first_frame_scope_changed')
    frame = ready['first_frames'][shot['id']]
    if stage.files.file_sha(frame['path']) != frame['sha256']:
        raise NativePromptBlocked('reviewed_first_frame_changed')
    selected_static = snapshot['plan']['config'].get('first_frame_plan')
    if not selected_static:
        raise NativePromptBlocked('current_selected_static_plan_required')
    from .visual_first_frame_static_v13 import validate_plan as validate_static_plan
    validate_static_plan(scope, snapshot['plan']['config'])
    source = Path(scope['source']['path']).read_text(encoding='utf-8')
    for item in parent['shots']:
        _validate_audio(item, source)
    predecessor=None;maximum_calls=2
    if source_audio_insertion is not None and type(source_audio_insertion) is not bool:
        raise NativePromptBlocked('explicit_source_audio_insertion_boolean_required')
    insertion_enabled=bool(source_audio_insertion)
    if known_predecessor is not None:
        previous_path=Path(known_predecessor).resolve()
        previous_run=previous_path if previous_path.is_dir() else previous_path.parent
        previous_status=status(previous_run)
        if previous_status['unknown_calls']:
            raise NativePromptBlocked('unknown_predecessor_cannot_have_successor')
        previous_path=previous_run/'NATIVE_PROMPT_PLAN.json'
        previous=verify_plan(previous_path)
        previous_plan=previous_status['plan']
        if source_audio_insertion is None:insertion_enabled=bool(previous_plan.get('audio_insertion'))
        elif previous_plan.get('audio_insertion') and not source_audio_insertion:
            raise NativePromptBlocked('known_successor_cannot_drop_source_audio_insertion')
        used=previous_status['claimed_calls']+previous_status['predecessor_claimed_calls']
        if used>=2:raise NativePromptBlocked('known_predecessor_total_two_calls_exhausted')
        if (not known_issue or not issue_evidence or previous['packet_sha256']!=stage.fingerprint(scope)
                or previous['full_parent']!=_binding(parent_packet)):
            raise NativePromptBlocked('known_successor_source_or_issue_required')
        new_state=dict(asset_plan=_binding(asset_run/'PLAN.json'),input_ready=_binding(asset_run/'H3_INPUT_READY.json'),
            reviewed_first_frame=dict(path=frame['path'],sha256=frame['sha256']),selected_static_plan=selected_static)
        if frame_correction_proof is not None:
            correction_binding=frame_correction_proof if isinstance(frame_correction_proof,dict) else _binding(frame_correction_proof)
            _validate_frame_correction(correction_binding,_binding(previous_path),previous_plan,new_state,
                scope['source'],_binding(parent_packet),stage.fingerprint(scope),shot)
        elif _frame_state(previous_plan)!=new_state:
            raise NativePromptBlocked('known_successor_frame_change_requires_root_proof')
        context,_,_,_=static._materials(dict(packet=_binding(scope_packet)),parent)
        allowed=list(shot.get('source_evidence',[]))
        allowed.extend(dict(id=e['source_id'],start=e['start'],end=e['end'],text=e['text'],sha256=e['sha256'])
            for e in context.get('source_physical_history_before_current_window',[]))
        for evidence in issue_evidence:
            if (not any(all(evidence.get(k)==item.get(k) for k in ('id','start','end','text','sha256')) for item in allowed)
                    or source[evidence['start']:evidence['end']]!=evidence['text']):
                raise NativePromptBlocked('known_successor_issue_evidence_changed')
        maximum_calls=2-used
        predecessor=dict(prompt_plan=_binding(previous_path),plan=_binding(previous_run/'PLAN.json'),prior_claimed_calls=used,
            issue=known_issue,source_evidence=deepcopy(issue_evidence),joint_maximum_calls=2)
        if frame_correction_proof is not None:predecessor['frame_correction_proof']=correction_binding
    elif frame_correction_proof is not None:
        raise NativePromptBlocked('frame_correction_requires_known_predecessor')
    run.mkdir(parents=True, exist_ok=True)
    guide = run / 'official_VIDEO_PROMPT_WRITING_GUIDE_base_en.md'
    if not guide.exists():
        if official_guide_path is not None:
            content=Path(official_guide_path).read_bytes()
        else:
            with urlopen(GUIDE_URL, timeout=60) as response:
                content = response.read()
        if b'integrated_multimodal_description' not in content or b'says in an off-screen voiceover' not in content:
            raise NativePromptBlocked('official_prompt_guide_unrecognized')
        guide.write_bytes(content)
    old = stage.files.read(parent['stage_plan']['path'])
    value = dict(schema=VERSION_V19 if directed else VERSION, full_parent=_binding(parent_packet), packet=_binding(scope_packet),
        packet_sha256=stage.fingerprint(scope), source=scope['source'], shot_id=shot['id'],
        shot_sha256=stage.fingerprint(shot), reviewed_first_frame=dict(path=frame['path'], sha256=frame['sha256']),
        selected_static_plan=selected_static,
        asset_plan=_binding(asset_run/'PLAN.json'), input_ready=_binding(asset_run/'H3_INPUT_READY.json'),
        speaker_map=speaker_map(parent), official_guide=dict(url=GUIDE_URL, **_binding(guide)),
        config={**old['config'], 'provider':'minimax', 'reasoning_effort':'medium', 'max_tokens':6000},
        max_calls=maximum_calls, user_statement=user_statement, media_dispatch=False, production_approved=False)
    if directed:
        value.update(native_prompt_contract=CONTRACT_V19,camera_contract=CAMERA_CONTRACT_V19,camera_design=directed)
        if camera_design is not None:value['camera_design_input']=deepcopy(camera_design)
    if predecessor is not None:value['known_predecessor']=predecessor
    if insertion_enabled:
        value['audio_insertion']=audio_insertion_spec(shot,value['speaker_map'])
        audio_order_context(shot,source,value['audio_insertion'])
    stage.files.freeze(run/'PLAN.json', value)
    if not (run/'STATE.json').exists():
        stage.files.write(run/'STATE.json', dict(status='prepared', claimed_calls=0))
    return status(run)


def status(run):
    run = _guard(run); plan = stage.files.read(run/'PLAN.json')
    predecessor=plan.get('known_predecessor');prior_claimed=0
    if predecessor:
        _read_binding(predecessor['prompt_plan']);previous=_read_binding(predecessor['plan'])
        previous_status=status(Path(predecessor['plan']['path']).parent)
        if previous_status['unknown_calls']:raise NativePromptBlocked('unknown_predecessor_cannot_have_successor')
        prior_claimed=previous_status['claimed_calls']+previous_status['predecessor_claimed_calls']
        if (prior_claimed!=predecessor['prior_claimed_calls'] or predecessor.get('joint_maximum_calls')!=2
                or previous['source']!=plan['source'] or not predecessor.get('issue') or not predecessor.get('source_evidence')):
            raise NativePromptBlocked('known_predecessor_budget_or_source_changed')
        scope=_read_binding(plan['packet']);shot=scope['shots'][0]
        if predecessor.get('frame_correction_proof'):
            _validate_frame_correction(predecessor['frame_correction_proof'],predecessor['prompt_plan'],previous,
                _frame_state(plan),plan['source'],plan['full_parent'],plan['packet_sha256'],shot)
        elif _frame_state(previous)!=_frame_state(plan):
            raise NativePromptBlocked('known_successor_frame_change_requires_root_proof')
    if plan.get('schema') not in (VERSION,VERSION_V19) or plan.get('max_calls') != 2-prior_claimed or plan.get('max_calls') not in (1,2) or plan.get('media_dispatch') is not False:
        raise NativePromptBlocked('native_motion_canary_contract_changed')
    for key in ('full_parent','packet','asset_plan','input_ready','selected_static_plan'):
        _read_binding(plan[key])
    if stage.files.file_sha(plan['source']['path']) != plan['source']['sha256']:
        raise NativePromptBlocked('native_motion_source_changed')
    for key in ('reviewed_first_frame','official_guide'):
        if stage.files.file_sha(plan[key]['path']) != plan[key]['sha256']:
            raise NativePromptBlocked('native_motion_reference_changed')
    parent = _read_binding(plan['full_parent'])
    if plan['schema']==VERSION_V19:
        scope=_read_binding(plan['packet'])
        if (plan.get('camera_contract')!=CAMERA_CONTRACT_V19 or plan.get('native_prompt_contract')!=CONTRACT_V19
                or plan.get('camera_design')!=source_camera_design(scope['shots'][0],plan.get('camera_design_input'))):
            raise NativePromptBlocked('source_camera_design_changed')
    elif any(k in plan for k in ('camera_contract','camera_design','camera_design_input','native_prompt_contract')):
        raise NativePromptBlocked('legacy_camera_contract_changed')
    if speaker_map(parent) != plan['speaker_map']:
        raise NativePromptBlocked('native_speaker_map_changed')
    if plan.get('audio_insertion'):
        scope=_read_binding(plan['packet']);shot=scope['shots'][0]
        if plan['audio_insertion']!=audio_insertion_spec(shot,plan['speaker_map']):
            raise NativePromptBlocked('source_audio_insertion_contract_changed')
    claims = list((run/'calls').glob('attempt_*/CLAIM.json'))
    unknown = [c for c in claims if not (c.parent/'NATIVE.json').exists()
        or stage.files.read(c.parent/'NATIVE.json').get('completion_known') is not True]
    if len(claims)>plan['max_calls']:raise NativePromptBlocked('native_motion_joint_budget_exceeded')
    return dict(plan=plan, claimed_calls=len(claims), predecessor_claimed_calls=prior_claimed,joint_claimed_calls=prior_claimed+len(claims),unknown_calls=len(unknown),
        remaining_calls=plan['max_calls']-len(claims), state=stage.files.read(run/'STATE.json'))


def motion_materials(materials):
    """Remove inherited still-task instructions while keeping its factual data."""
    value=deepcopy(materials)
    value.pop('requested_output',None)
    value['requested_output']='Continuous visible motion over the complete current video window. Enact its explicit current physical source actions in order, even when the opening and ending large-scale posture stays the same.'
    value['motion_input_roles']=dict(
        selected_static_start_context='Opening-state/identity/composition data only. Its frozen-instant wording is not an instruction to freeze the video.',
        current_physical_source='Current-scene source evidence. Enact explicit facial, breathing, hand and prop actions only for current visible_cast actors. Actions of people outside visible_cast stay outside the image and can motivate the visible actors reactions.',
        source_physical_history_before_current_window='Already established prior facts and held-item continuity, not future actions to repeat.',
        cast_domain='visible_cast bounds eligible identities. Source exits may reduce the visible people; never add another identity or body part to preserve an initial count.')
    return value


def plan(run, *, client=None):
    run = _guard(run); state = status(run); p = state['plan']
    output = run/'NATIVE_PROMPT_PLAN.json'
    if output.exists():
        verify_plan(output)
        return _binding(output)
    if state['unknown_calls']:
        raise NativePromptBlocked('unknown_native_motion_not_replayed')
    scope = _read_binding(p['packet']); shot = scope['shots'][0]
    parent = _read_binding(p['full_parent']); characters = {c['id']:c for c in parent['characters']}
    row = dict(packet=p['packet']); materials, _, _, _ = static._materials(row, parent)
    materials=motion_materials(materials)
    # Isolate physical motion from current-source spoken labels and other bodies.
    materials.pop('room', None)
    materials['visible_identities'] = [dict(id=c['id'],age_band=c.get('age_band')) for c in scope['characters'] if c['id'] in shot['visible_cast']]
    materials['reviewed_first_frame'] = p['reviewed_first_frame']
    selected_static = _read_binding(p['selected_static_plan'])
    static_entry = next(s for s in selected_static['shots'] if s['shot_id']==shot['id'])
    materials['selected_static_start_context'] = dict(
        source='current asset plan selected native static plan, including approved prop continuity successors',
        binding=p['selected_static_plan'],static_start_prompt=static_entry['static_start_prompt'])
    materials['physical_continuity_priority'] = ('Preserve the current selected static image and its established held objects. '
        'Use the ordered physical history to continue an existing holder until explicit source transfer or set-down. '
        'Older dynamic prose or pose summaries do not remove or transform a currently established prop.')
    if p.get('audio_insertion'):
        materials['source_audio_insertion']=p['audio_insertion']
        materials['source_timeline_audio_masked']=audio_order_context(shot,Path(p['source']['path']).read_text(encoding='utf-8'),p['audio_insertion'])
    successor_issue=p.get('known_predecessor',{}).get('issue');successor_evidence=p.get('known_predecessor',{}).get('source_evidence')
    if p.get('audio_insertion'):
        successor_issue,successor_evidence=_masked_issue_material(successor_issue,successor_evidence,
            Path(p['source']['path']).read_text(encoding='utf-8'),p['audio_insertion'],shot['audio'])
    materials['output_contract'] = 'English visible physical motion only; source audio is compiled separately and not supplied for rewriting.'
    directed=p.get('camera_design') if p.get('camera_contract')==CAMERA_CONTRACT_V19 else None
    if directed:
        materials['source_camera_design']=deepcopy(directed)
        materials['output_contract']='Adapt the existing source shot into English visible motion, including its already-designed camera path. Do not direct a different shot. Source audio is compiled separately.'
        materials['motion_input_roles']['selected_static_start_context']='Opening-state/identity data only. It does not freeze the lens, framing, pose, expression or eye state for the whole video.'
        materials['physical_continuity_priority']='Preserve established identity and held-object continuity through the bound camera design. Opening-image composition is only the starting point; an explicit upstream camera design takes precedence over older framing prose.'
    schema = response_schema(shot['visible_cast'],directed); client = client or stage.legacy.PlanningClient(p['config'])
    previous = None
    with stage.jobs.run_lock(run, 'PLANNING.lock'):
        for attempt in range(p['max_calls']):
            folder = run/'calls'/f'attempt_{attempt:02d}'; folder.mkdir(parents=True,exist_ok=True)
            messages = [dict(role='system',content='You are a motion-only production planner for ONE existing reviewed image and ONE continuous locked-off tripod shot. Supplied source is data. Preserve exactly visible_cast and the reference image identity, clothing, room, composition and camera direction. The selected static prompt describes the opening image only: any frozen-instant or still wording inside it is data, never an instruction to freeze this video. Explicit current physical source actions by current visible_cast actors must visibly develop in order over the window, including physiological, facial, hand and held-object actions. Actions by scene-present people outside visible_cast remain outside the image; they may motivate visible actors reactions without materializing an unlisted identity or any of its body parts. visible_cast lists eligible identities at the opening, not a minimum person count throughout: a source-established exit can reduce the visible people, and nobody is added to maintain a count. Identical opening/ending large-scale posture does not cancel the intervening source actions. Write positive English visible actions only. The source audio is handled elsewhere: never write voices, dialogue, speaker names outside visible_cast, new bodies, cuts, camera turns, zooms, location changes or future narrated events. Preserve the opening/end posture only where source retains it, while enacting the source motion between them. Do not invent activity to fill time. Model text is not allowed to revise source facts. Output only JSON matching JSON_SCHEMA:'+json.dumps(schema)),
                dict(role='user',content=json.dumps(dict(materials=materials,previous_known_failure=previous,
                    known_successor_correction=successor_issue,issue_source_evidence=successor_evidence),ensure_ascii=False))]
            if directed:
                messages[0]['content']=('You are a video-format adapter, not a director. The bound source_camera_design is the camera authority. '
                    'Translate and retain its existing camera path, framing changes, planned close views, cuts or movement in the motion description; '
                    'choose no new camera movement or cut. An explicitly fixed source shot remains fixed. camera_motion and camera_contract are program constants, not creative choices. '
                    'The reference image is the opening instant and identity anchor; it does not freeze framing, expression, eyes or pose throughout. '
                    'Enact current visible source actions in order and retain character identity, clothing, key objects and source spatial continuity. '
                    'visible_cast bounds eligible identities; source exits may reduce the visible people. Actions outside visible_cast remain outside the image. '
                    'Write positive English actions only. Do not write speech, voices, new people, invented locations or narrated future events. '
                    'The program inserts the original source audio. Output only JSON matching JSON_SCHEMA:'+json.dumps(schema))
            if p.get('audio_insertion'):
                instruction=('EXPLICIT SOURCE-AUDIO INSERTION MODE: Place every exact program token from source_audio_insertion.slots ONCE, in its fixed original order, inside motion_description at the source-correct moment between visible actions. Read source_timeline_audio_masked to position each token; its speech words are deliberately absent. Tokens stand for existing source audio that the program will insert, not image text. Never rewrite, translate, summarize or supply any speech words, <d> blocks, speaker lines, alternate IDs or extra JSON fields. A token for an on-screen speaker must occur while that speaker is still visible, before any following source exit. Do not duplicate the audio at the end. ')
                messages[0]['content']=instruction+messages[0]['content']
            if len(json.dumps(messages,ensure_ascii=False))>p['config'].get('max_input_chars',60000):
                raise NativePromptBlocked('native_motion_context_capacity_exceeded')
            request = dict(schema=p['schema'],model=client.binding(),messages=messages,response_schema=schema)
            stage.files.freeze(folder/'REQUEST.json',request)
            if (folder/'NATIVE.json').exists():
                raw = stage.files.read(folder/'NATIVE.json')
            else:
                if (folder/'CLAIM.json').exists():
                    raise NativePromptBlocked('unknown_native_motion_not_replayed')
                if len(list((run/'calls').glob('attempt_*/CLAIM.json')))>=p['max_calls']:
                    raise NativePromptBlocked('native_motion_canary_budget_exhausted')
                stage.files.freeze(folder/'CLAIM.json',dict(at=time.time(),request_sha256=stage.fingerprint(request)))
                try:
                    raw = client.call(messages,schema)
                except Exception as error:
                    from .creative_workflow_roles import RoleResponseError
                    native=getattr(error,'response_payload',None);metadata=getattr(error,'response_metadata',{})
                    choices=native.get('choices',[]) if isinstance(native,dict) else []
                    known=isinstance(error,RoleResponseError) and len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and choices[0]['finish_reason']==metadata.get('finish_reason')
                    stage.files.freeze(folder/'ERROR.json',dict(type=type(error).__name__,message=str(error),completion_known=known,native=native,metadata=metadata))
                    if not known:
                        raise NativePromptBlocked('unknown_native_motion_not_replayed') from error
                    raw=dict(text=choices[0].get('message',{}).get('content') or '',native=native,metadata=metadata,completion_known=True,rejected=True)
                stage.files.freeze(folder/'NATIVE.json',raw)
            if raw.get('completion_known') is not True:
                raise NativePromptBlocked('unknown_native_motion_not_replayed')
            try:
                if raw.get('rejected') or raw.get('metadata',{}).get('finish_reason')=='length':
                    raise NativePromptBlocked('known_native_motion_incomplete')
                text=raw['text'].strip()
                if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
                candidate=json.loads(text);_check_motion(candidate,shot,characters,directed)
                if p.get('audio_insertion'):_check_audio_markers(candidate['motion_description'],p['audio_insertion'])
            except Exception as error:
                previous=dict(reason=str(error),candidate=raw.get('text'))
                stage.files.freeze(folder/'VALIDATION_ERROR.json',previous)
                continue
            stage.files.freeze(folder/'RESULT.json',candidate)
            entry=dict(shot_id=shot['id'],shot_sha256=stage.fingerprint(shot),source_shot_keys=list(shot),
                visible_cast=deepcopy(shot['visible_cast']),audio_sha256=stage.fingerprint(shot.get('audio',[])),
                motion_description=candidate['motion_description'],camera_motion=candidate['camera_motion'],
                overall_soundscape=ROOM_SOUNDSCAPE,non_diegetic_music='N/A')
            if directed:entry.update(camera_contract=CAMERA_CONTRACT_V19,camera_design=deepcopy(directed))
            if p.get('audio_insertion'):entry['audio_insertion']=deepcopy(p['audio_insertion'])
            value=dict(schema=SCHEMA_V19 if directed else SCHEMA,source=scope['source'],packet_sha256=stage.fingerprint(scope),full_parent=p['full_parent'],
                speaker_map=p['speaker_map'],shots=[entry],reviewed_first_frame=p['reviewed_first_frame'],
                planning_provenance=dict(plan=_binding(run/'PLAN.json'),bindings={key:_binding(folder/name) for key,name in [('request','REQUEST.json'),('native','NATIVE.json'),('result','RESULT.json')]}),
                media_dispatch=False,production_approved=False)
            if directed:value.update(native_prompt_contract=CONTRACT_V19,camera_contract=CAMERA_CONTRACT_V19)
            stage.files.freeze(output,value);verify_plan(output)
            stage.files.write(run/'STATE.json',dict(status='native_prompt_ready',claimed_calls=status(run)['claimed_calls']))
            return _binding(output)
    raise NativePromptBlocked('known_native_motion_validation_failed')


def verify_plan(path):
    value = stage.files.read(path)
    if value.get('schema') not in (SCHEMA,SCHEMA_V19) or value.get('media_dispatch') is not False:
        raise NativePromptBlocked('invalid_native_prompt_plan')
    proof = value['planning_provenance'];p = _read_binding(proof['plan'])
    status(Path(proof['plan']['path']).parent)
    for binding in proof['bindings'].values(): _read_binding(binding)
    scope = _read_binding(p['packet']);parent=_read_binding(p['full_parent'])
    if (value['source'] != scope['source'] or value['packet_sha256'] != stage.fingerprint(scope)
            or value['full_parent'] != p['full_parent'] or value['speaker_map'] != speaker_map(parent)
            or value['reviewed_first_frame'] != p['reviewed_first_frame'] or len(value['shots'])!=1):
        raise NativePromptBlocked('native_prompt_scope_or_speakers_changed')
    shot=scope['shots'][0];entry=value['shots'][0];_source_shot(shot,entry)
    directed=p.get('camera_design') if p.get('camera_contract')==CAMERA_CONTRACT_V19 else None
    if directed:
        if (value.get('schema')!=SCHEMA_V19 or value.get('native_prompt_contract')!=CONTRACT_V19
                or value.get('camera_contract')!=CAMERA_CONTRACT_V19
                or entry.get('camera_contract')!=CAMERA_CONTRACT_V19 or entry.get('camera_design')!=directed):
            raise NativePromptBlocked('native_camera_contract_changed')
    elif value.get('schema')!=SCHEMA or any(k in entry for k in ('camera_contract','camera_design')):
        raise NativePromptBlocked('legacy_camera_contract_changed')
    if entry.get('audio_insertion')!=p.get('audio_insertion'):
        raise NativePromptBlocked('native_audio_insertion_entry_changed')
    if entry['overall_soundscape'] != ROOM_SOUNDSCAPE or entry['non_diegetic_music'] != 'N/A':
        raise NativePromptBlocked('native_program_sound_fields_changed')
    raw=_read_binding(proof['bindings']['native']);result=_read_binding(proof['bindings']['result'])
    if raw.get('completion_known') is not True or raw.get('metadata',{}).get('finish_reason')=='length':
        raise NativePromptBlocked('native_prompt_model_not_completed')
    text=raw['text'].strip()
    if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
    if json.loads(text)!=result or entry['motion_description']!=result['motion_description'] or entry['camera_motion']!=result['camera_motion']:
        raise NativePromptBlocked('native_motion_differs_from_receipt')
    _check_motion(result,shot,{c['id']:c for c in parent['characters']},directed)
    if p.get('audio_insertion'):_check_audio_markers(result['motion_description'],p['audio_insertion'])
    return value


def load_for(packet, binding, shot):
    """Validate external plan and return its single native compiler entry."""
    value = _read_binding(binding);verify_plan(binding['path'])
    if value['source'] != packet['source'] or value['packet_sha256'] != stage.fingerprint(packet):
        raise NativePromptBlocked('native_prompt_wrong_packet')
    original=next((s for s in packet['shots'] if s['id']==shot['id']),None)
    if original is None:
        raise NativePromptBlocked('native_prompt_shot_not_in_packet')
    entry=next((s for s in value['shots'] if s['shot_id']==shot['id']),None)
    if entry is None or stage.fingerprint(original)!=entry['shot_sha256']:
        raise NativePromptBlocked('native_prompt_missing_source_shot')
    _source_shot(shot,entry)
    return dict(entry, speaker_map=deepcopy(value['speaker_map']), source=deepcopy(value['source']),
        visible_subject_labels=subject_labels(packet, original))


def subject_labels(packet, shot):
    """Use explicit frozen visual-design gender, never infer it from a name.

    Labels disambiguate a visible girl/boy or child/adult without importing
    whole-cast appearance prompts, costumes or studio poses into the video.
    Same-label people require a later explicit spatial/identity anchor instead
    of a guessed left/right position.
    """
    cast={c['id']:c for c in packet['characters']};labels={}
    for identity in shot['visible_cast']:
        actor=cast[identity];text=actor.get('appearance_design') or actor.get('front_prompt') or ''
        if actor.get('age_band')=='child':
            noun='girl' if re.search(r'\bgirl\b',text,re.I) else 'boy' if re.search(r'\bboy\b',text,re.I) else 'child'
        else:
            noun='adult woman' if re.search(r'\bwoman\b',text,re.I) else 'adult man' if re.search(r'\bman\b',text,re.I) else 'adult person'
        labels[identity]='The visible '+noun
    return labels


def _speaker_text(audio, speaker, shot, visible_labels):
    visible=audio['speaker'] in shot['visible_cast']
    child=speaker['age_band']=='child'
    if audio['speaker']=='narrator':subject='An unseen neutral narrator voice'
    elif audio['mode']=='offscreen_dialogue':subject='An unseen child voice' if child else 'An unseen adult voice'
    elif visible:subject=visible_labels.get(audio['speaker']) or ('The visible child' if child else 'The visible adult man')
    else:subject='An unseen child voice' if child else 'An unseen adult voice'
    direction=source_direction(shot,audio) or ''
    delivery=[]
    if '怯' in direction:delivery.append('with a timid delivery')
    if '压低声音' in direction:delivery.append('at a low volume')
    if '稳稳' in direction:delivery.append('with a steady delivery')
    subject+=' ('+speaker['speaker_id']+')'
    if delivery:subject+=', '+', '.join(delivery)+','
    spoken='<d>[Chinese] '+audio['text']+'</d>'
    if audio['mode']=='onscreen':return subject+' says: '+spoken+' with lips moving in sync with these words.'
    # The training guide requires this exact voiceover phrase and an immediate
    # closed-lips clause after EVERY off-screen <d> block, including inner voice.
    return subject+' '+OFFSCREEN_PHRASE+': '+spoken+" while all visible characters' lips remain completely closed."


def compile_for(shot, timing, planentry, anchor_mode):
    """Deterministic native wrapper; it never asks an LLM to rewrite speech."""
    _source_shot(shot,planentry)
    if anchor_mode not in ('first','first_last'):
        raise NativePromptBlocked('unsupported_native_anchor_mode')
    seconds=timing.get('native_seconds');frames=timing.get('native_frames')
    requested=timing.get('requested_seconds',shot['end']-shot['start'])
    # H3 accepts requests through 15s; its legal final 5+17n-frame bucket is
    # 362/24=15.08333s.  Do not reject or silently truncate those native frames.
    if (type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=362/24
            or type(frames) is not int or not 124<=frames<=362 or (frames-5)%17
            or abs(seconds-frames/24)>1e-8
            or type(requested) not in (int,float) or not math.isfinite(requested) or not 0<requested<=15
            or abs(requested-(shot['end']-shot['start']))>1e-8
            or any(k in timing and timing[k]!=shot[k] for k in ('start','end'))
            or shot.get('source_native_frames')!=frames):
        raise NativePromptBlocked('native_prompt_timing_changed')
    if anchor_mode=='first':
        instruction='For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.'
    else:
        instruction=('How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; '
            f'Picture 2 (from Shot 1) aligns with the {seconds:.2f}-second mark of the target video.')
    source=Path(planentry['source']['path']).read_text(encoding='utf-8')
    if stage.files.file_sha(planentry['source']['path'])!=planentry['source']['sha256']:
        raise NativePromptBlocked('native_audio_source_changed')
    _validate_audio(shot,source)
    speakers={s['source_speaker']:s for s in planentry['speaker_map']}
    lines=[];visible_labels=planentry.get('visible_subject_labels',{})
    for audio in shot.get('audio',[]):
        key=audio.get('source_speaker') or audio['speaker']
        if key not in speakers or speakers[key]['character_id']!=audio['speaker']:
            raise NativePromptBlocked('native_audio_speaker_not_in_global_map')
        if audio['mode']=='onscreen':
            label=visible_labels.get(audio['speaker'])
            if label and sum(other==label for other in visible_labels.values())>1:
                raise NativePromptBlocked('ambiguous_onscreen_speaker_visual_anchor')
        lines.append(_speaker_text(audio,speakers[key],shot,visible_labels))
    insertion=planentry.get('audio_insertion')
    if insertion:
        if insertion!=audio_insertion_spec(shot,planentry['speaker_map']):
            raise NativePromptBlocked('compiled_audio_insertion_source_or_speaker_changed')
        _check_audio_markers(planentry['motion_description'],insertion)
    anchor=('The single locked-off tripod shot preserves the reference image framing, camera direction, visible subjects, clothing and room throughout. '
        +'The subject settles into Picture 2 in the same composition at the end. ' if anchor_mode=='first_last' else
        'The single locked-off tripod shot preserves the reference image framing, camera direction, visible subjects, clothing and room throughout. ')
    motion=planentry['motion_description']
    if insertion:
        anchor=('The single locked-off tripod shot preserves the reference image camera direction, clothing, room and actor identities. Source-established exits may reduce the people visible in the frame; only the initial eligible identities can appear. ')
        for slot,line in zip(insertion['slots'],lines):motion=motion.replace(slot['token'],'\n'+line+'\n')
        if '[[' in motion or ']]' in motion:raise NativePromptBlocked('unresolved_source_audio_marker_in_compiled_prompt')
    if planentry.get('camera_contract') is not None:
        if planentry['camera_contract']!=CAMERA_CONTRACT_V19:
            raise NativePromptBlocked('unsupported_compiled_camera_contract')
        design=planentry.get('camera_design',{})
        if design!=source_camera_design(_source_shot(shot,planentry),design.get('explicit')):
            raise NativePromptBlocked('compiled_source_camera_design_changed')
        anchor=('Camera direction follows the bound upstream shot design. Preserve character identity, clothing, key objects and source spatial continuity while performing the designed camera path and visible actions. ')
        if design['mode']=='explicit_fixed':anchor+='The explicitly fixed source camera remains fixed. '
        if design.get('instruction'):anchor+='Upstream camera instruction: '+design['instruction']+' '
        if anchor_mode=='first_last':anchor+='Reach the supplied final keyframe at the end. '
    body='[Shot 1] Live-action, cinematic. '+anchor+motion
    if lines and not insertion:body+='\n'+'\n'.join(lines)
    return instruction+'\n\nintegrated_multimodal_description: '+body+'\n\noverall_soundscape: '+planentry['overall_soundscape']+'\n\nnon_diegetic_music: '+planentry['non_diegetic_music']
