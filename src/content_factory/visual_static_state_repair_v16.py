"""Small, source-bound r2 successor layer for approved static-state defects.

Keeps v13 still-file compatibility; never edits its 33-call ledger or selected
index. New per-shot requests are bounded by a separate explicit authorization.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import time
from jsonschema import validate
from . import visual_static_start_planner_v13 as base

VERSION='static_start_state_successor/v16'


def _guard(run):
    run=Path(run).resolve()
    if run.parent.name!='visual_static_state_repairs_v16' or not re.fullmatch(base.stage.legacy.SLUG,run.name):
        raise base.StaticBlocked('new_static_state_successor_namespace_required')
    return run


def _binding(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=base.stage.files.file_sha(path))


def _read(binding):
    if base.stage.files.file_sha(binding['path'])!=binding['sha256']:
        raise base.StaticBlocked('state_successor_binding_changed')
    return base.stage.files.read(binding['path'])


def _current_selection(binding,original):
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'}:
        raise base.StaticBlocked('state_successor_selected_index_binding_required')
    selected=_read(binding);source_rows={r['shot_id']:r for r in original['shots']};rows=selected.get('plans')
    if selected.get('schema')!='selected_static_plans/v13' or selected.get('source')!=original['source']:
        raise base.StaticBlocked('state_successor_selected_index_foreign_source')
    if (not isinstance(rows,list) or len(rows)!=len(source_rows) or len({r.get('shot_id') for r in rows})!=len(rows)
        or {r.get('shot_id') for r in rows}!=set(source_rows)):
        raise base.StaticBlocked('state_successor_selected_index_shot_scope_changed')
    for row in rows:
        sid=row['shot_id']
        if base.stage.files.file_sha(row['path'])!=row['sha256']:
            raise base.StaticBlocked('state_successor_selected_parent_changed')
        base.verify_plan(row['path'],source_rows[sid]);value=base.stage.files.read(row['path']);shot=value['shots'][0]
        if (value['source']!=original['source'] or shot['shot_id']!=sid or row.get('packet_sha256')!=value['packet_sha256']
            or row.get('shot_sha256')!=shot['shot_sha256'] or row.get('visible_cast')!=shot['visible_cast']):
            raise base.StaticBlocked('state_successor_selected_index_row_not_native')
        if value['planning_provenance'].get('state_successor_plan'):verify_plan(row['path'])
    return selected


def prepare(run,static_run,targets,*,root_authorization,selected_index=None):
    run=_guard(run);static_run=Path(static_run).resolve();old=base.status(static_run)['plan']
    selected_binding=_binding(static_run/'SELECTED_PLANS.json') if selected_index is None else deepcopy(selected_index)
    selected=(base.stage.files.read(selected_binding['path']) if selected_index is None else _current_selection(selected_binding,old))
    selected_map={r['shot_id']:r for r in selected['plans']};source_rows={r['shot_id']:r for r in old['shots']}
    if not root_authorization or not targets or len(targets)>3 or len({t['shot_id'] for t in targets})!=len(targets):
        raise base.StaticBlocked('explicit_bounded_state_successors_required')
    frozen=[]
    for target in targets:
        sid=target['shot_id']
        if sid not in selected_map or sid not in source_rows or not target.get('instructions'):
            raise base.StaticBlocked('state_successor_target_not_selected')
        parent=selected_map[sid];base.verify_plan(parent['path'],source_rows[sid])
        if base.stage.files.file_sha(parent['path'])!=parent['sha256']:
            raise base.StaticBlocked('state_successor_selected_parent_changed')
        source=Path(old['source']['path']).read_text(encoding='utf-8')
        for evidence in target.get('source_issue_evidence',[]):
            quote=source[evidence['start']:evidence['end']]
            if quote!=evidence['text'] or base.hashlib.sha256(quote.encode()).hexdigest()!=evidence['sha256']:
                raise base.StaticBlocked('state_successor_issue_source_quote_changed')
        frozen.append(dict(target,parent_static_plan=dict(path=parent['path'],sha256=parent['sha256']),
            source_row=source_rows[sid],max_calls=2))
    value=dict(schema=VERSION,original_static_plan=_binding(static_run/'PLAN.json'),
        original_static_ledger=_binding(static_run/'CALL_LEDGER.json'),parent_selected=selected_binding,
        full_source_parent=old['parent'],source=old['source'],targets=frozen,max_calls=2*len(frozen),
        config=old['config'],root_authorization=root_authorization,media_dispatch=False,production_approved=False,
        **({'current_selected_index_validated':True} if selected_index is not None else {}))
    run.mkdir(parents=True,exist_ok=True);base.stage.files.freeze(run/'PLAN.json',value)
    if not (run/'STATE.json').exists():base.stage.files.write(run/'STATE.json',dict(status='prepared',completed=[]))
    return status(run)


def status(run):
    run=_guard(run);p=base.stage.files.read(run/'PLAN.json')
    if (p['schema']!=VERSION or p['max_calls']!=2*len(p['targets']) or p['max_calls']>6 or p['media_dispatch'] is not False
            or any(t.get('max_calls')!=2 for t in p['targets'])):
        raise base.StaticBlocked('state_successor_authorization_changed')
    for key in ('original_static_plan','original_static_ledger','parent_selected','full_source_parent'):_read(p[key])
    if p.get('current_selected_index_validated'):
        selected=_current_selection(p['parent_selected'],_read(p['original_static_plan']));parents={r['shot_id']:r for r in selected['plans']}
        for target in p['targets']:
            row=parents[target['shot_id']]
            if target['parent_static_plan']!={k:row[k] for k in ('path','sha256')}:
                raise base.StaticBlocked('state_successor_target_not_current_selected_parent')
    if base.stage.files.file_sha(p['source']['path'])!=p['source']['sha256']:
        raise base.StaticBlocked('state_successor_source_changed')
    for target in p['targets']:
        _read(target['parent_static_plan']);_read(target['source_row']['packet'])
    claims=list((run/'calls').glob('*/attempt_*/CLAIM.json'))
    unknown=[c for c in claims if not (c.parent/'NATIVE.json').exists() or base.stage.files.read(c.parent/'NATIVE.json').get('completion_known') is not True]
    return dict(plan=p,claimed_calls=len(claims),unknown_calls=len(unknown),remaining_calls=p['max_calls']-len(claims),
        state=base.stage.files.read(run/'STATE.json'))


def response_schema(visible):
    schema=base.response_schema(visible)
    schema['properties']['opening_states']=dict(type='array',minItems=len(visible),maxItems=len(visible),items=base.stage.legacy.obj(dict(
        character_id=dict(type='string',enum=visible),
        posture=dict(type='string',enum=['lying_supine','standing','seated','kneeling','other','unspecified']),
        eyes=dict(type='string',enum=['open','closed','unseen','unspecified']),
        held_items=dict(type='string',maxLength=300))))
    schema['required'].append('opening_states');return schema


def _check(candidate,shot,scope,target):
    validate(candidate,response_schema(shot['visible_cast']))
    base._check(candidate,shot,scope,target['constraints'])
    states={s['character_id']:s for s in candidate['opening_states']}
    if len(states)!=len(shot['visible_cast']) or list(states)!=shot['visible_cast']:
        raise base.StaticBlocked('state_successor_actor_order_changed')
    for expected in target['expected_opening_states']:
        actual=states[expected['character_id']]
        if any(actual[k]!=v for k,v in expected.items()):
            raise base.StaticBlocked('state_successor_expected_initial_state_missing')
    for pattern in target['constraints'].get('forbidden_patterns',[]):
        if re.search(pattern,candidate['static_start_prompt'],re.I|re.S):
            raise base.StaticBlocked('state_successor_prompt_contradicts_initial_state')


def plan(run,*,client=None):
    run=_guard(run);p=status(run)['plan']
    if status(run)['unknown_calls']:raise base.StaticBlocked('unknown_state_successor_not_replayed')
    client=client or base.stage.legacy.PlanningClient(p['config']);completed=[]
    with base.stage.jobs.run_lock(run,'PLANNING.lock'):
        for target in p['targets']:
            sid=target['shot_id'];output=run/'plans'/(sid+'_r2.json')
            if output.exists():verify_plan(output);completed.append(sid);continue
            original=_read(target['parent_static_plan']);parent=_read(p['full_source_parent'])
            raw_material,scope,shot,_=base._materials(target['source_row'],parent)
            material=base.start_boundary_materials(raw_material)
            schema=response_schema(shot['visible_cast']);previous=None
            for attempt in range(target['max_calls']):
                folder=run/'calls'/sid/f'attempt_{attempt:02d}';folder.mkdir(parents=True,exist_ok=True)
                messages=[dict(role='system',content='Create ONE corrected static opening image, not a video motion path. Use the latest explicit prior physical source state; initial scene metadata is only a fallback. A model candidate or previous model summary is not evidence and must not undo later source changes. The first image precedes the current window first state-changing action: an upcoming kneel, handoff, departure or eye change belongs in the later video, not a pre-completed opening still. Preserve exactly visible_cast, source identity, existing room, clothing, same held item and its latest holder. Correct only the bounded issues. Return a complete positive English static prompt and concise opening_states in visible_cast order. Camera is inherited unchanged; do not output camera/audio. JSON_SCHEMA:'+json.dumps(schema,ensure_ascii=False)),
                    dict(role='user',content=json.dumps(dict(materials=material,candidate_to_correct_not_state_evidence=original['shots'][0]['static_start_prompt'],
                        correction=target['instructions'],expected_opening_states=target['expected_opening_states'],acceptance_constraints=target['constraints'],previous_known_failure=previous),ensure_ascii=False))]
                if len(json.dumps(messages,ensure_ascii=False))>p['config']['max_input_chars']:
                    raise base.StaticBlocked('state_successor_context_capacity_exceeded')
                request=dict(schema=VERSION,model=client.binding(),messages=messages,response_schema=schema)
                base.stage.files.freeze(folder/'REQUEST.json',request)
                if (folder/'NATIVE.json').exists():raw=base.stage.files.read(folder/'NATIVE.json')
                else:
                    if (folder/'CLAIM.json').exists():raise base.StaticBlocked('unknown_state_successor_not_replayed')
                    claims=list((run/'calls').glob('*/attempt_*/CLAIM.json'))
                    if len(claims)>=p['max_calls']:raise base.StaticBlocked('state_successor_budget_exhausted')
                    base.stage.files.freeze(folder/'CLAIM.json',dict(at=time.time(),request_sha256=base.stage.fingerprint(request),authorization_plan=_binding(run/'PLAN.json')))
                    try:raw=client.call(messages,schema)
                    except Exception as error:
                        from .creative_workflow_roles import RoleResponseError
                        native=getattr(error,'response_payload',None);metadata=getattr(error,'response_metadata',{})
                        choices=native.get('choices',[]) if isinstance(native,dict) else []
                        known=isinstance(error,RoleResponseError) and len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and choices[0]['finish_reason']==metadata.get('finish_reason')
                        base.stage.files.freeze(folder/'ERROR.json',dict(type=type(error).__name__,message=str(error),completion_known=known,native=native,metadata=metadata))
                        if not known:raise base.StaticBlocked('unknown_state_successor_not_replayed') from error
                        raw=dict(text=choices[0].get('message',{}).get('content') or '',metadata=metadata,native=native,completion_known=True,rejected=True)
                    base.stage.files.freeze(folder/'NATIVE.json',raw)
                if raw.get('completion_known') is not True:raise base.StaticBlocked('unknown_state_successor_not_replayed')
                try:
                    if raw.get('rejected') or raw.get('metadata',{}).get('finish_reason')=='length':raise base.StaticBlocked('known_state_successor_incomplete')
                    text=raw['text'].strip()
                    if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
                    candidate=json.loads(text);_check(candidate,shot,scope,target)
                except Exception as error:
                    previous=dict(reason=str(error),candidate=raw.get('text'));base.stage.files.freeze(folder/'VALIDATION_ERROR.json',previous);continue
                base.stage.files.freeze(folder/'RESULT.json',candidate)
                result=deepcopy(original);result['shots'][0]['static_start_prompt']=candidate['static_start_prompt']
                proof=result['planning_provenance'];proof.pop('parser_revalidation',None);proof.pop('word_target_overrun',None)
                proof.update(parent_static_plan=target['parent_static_plan'],acceptance_constraints=target['constraints'],state_successor_plan=_binding(run/'PLAN.json'),
                    opening_states=deepcopy(candidate['opening_states']),camera_inherited_from_parent=True,
                    bindings={key:_binding(folder/name) for key,name in [('request','REQUEST.json'),('native','NATIVE.json'),('result','RESULT.json')]})
                base.stage.files.freeze(output,result);verify_plan(output);completed.append(sid);break
            else:raise base.StaticBlocked('known_state_successor_validation_failed:'+sid)
        base.stage.files.write(run/'STATE.json',dict(status='state_successors_ready',completed=completed))
    return selected_plans(run)


def verify_plan(path):
    base.verify_plan(path);value=base.stage.files.read(path);proof=value['planning_provenance']
    p=_read(proof['state_successor_plan']);status(Path(proof['state_successor_plan']['path']).parent)
    target=next(t for t in p['targets'] if t['shot_id']==value['shots'][0]['shot_id'])
    candidate=_read(proof['bindings']['result']);scope=_read(target['source_row']['packet']);shot=scope['shots'][0]
    _check(candidate,shot,scope,target)
    if proof['parent_static_plan']!=target['parent_static_plan'] or proof['opening_states']!=candidate['opening_states']:
        raise base.StaticBlocked('state_successor_audit_changed')
    return True


def selected_plans(run):
    run=_guard(run);p=status(run)['plan'];old=_read(p['parent_selected']);result=deepcopy(old)
    target_ids={t['shot_id'] for t in p['targets']}
    for row in result['plans']:
        if row['shot_id'] not in target_ids:continue
        path=run/'plans'/(row['shot_id']+'_r2.json');verify_plan(path)
        row.update(path=str(path.resolve()),sha256=base.stage.files.file_sha(path),successor_selected=True,
            superseded_selected_plan=dict(path=next(t['parent_static_plan']['path'] for t in p['targets'] if t['shot_id']==row['shot_id']),
                sha256=next(t['parent_static_plan']['sha256'] for t in p['targets'] if t['shot_id']==row['shot_id'])),
            original_retained_not_selected=True)
    result['state_successor_layer']=dict(schema=VERSION,authorization_plan=_binding(run/'PLAN.json'),parent_selected=p['parent_selected'],
        new_claimed_calls=status(run)['claimed_calls'],new_maximum_calls=p['max_calls'],unknown_calls=status(run)['unknown_calls'])
    base.stage.files.freeze(run/'SELECTED_PLANS.json',result)
    return _binding(run/'SELECTED_PLANS.json')
