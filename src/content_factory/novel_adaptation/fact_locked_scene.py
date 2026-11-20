"""Reviewed source facts are immutable; the writer selects bounded performance.

This is a conservative scene route, not a semantic proof for unrestricted prose.
Approval binds source, registry, contract and candidate; no unreviewed handoff.
"""
from copy import deepcopy
from . import contracts as c
from . import prose_patch

SPEECH_STYLE=('自然表达','短暂停顿后说','轻声说','压低声音说','迟疑地说')
ACTION_STYLE=('不追加动作','短暂停顿','抬眼','垂眼')

def approved(value,source,review):
    if (review.get('verdict')!='approved' or review.get('open_issues')!=[]
        or review.get('artifact_sha256')!=c.digest(value)
        or review.get('source_sha256')!=c.digest(source)
        or review.get('reviewer')!='primary_assistant'):
        raise ValueError('review_missing_stale_or_unresolved')

def validate_registry(registry,source,review):
    approved(registry,source,review)
    if registry['source_sha256']!=c.digest(source):raise ValueError('registry_source_changed')
    catalog=c.catalog(source);ids=set()
    for row in registry['characters']:
        if row['id'] in ids:raise ValueError('duplicate_character')
        ids.add(row['id'])
        if not row['source_ids'] or not set(row['source_ids'])<=set(catalog):raise ValueError('identity_evidence_missing')
        age=row['age']
        if age is not None:
            if age['source_id'] not in catalog or age['text'] not in catalog[age['source_id']]['text']:
                raise ValueError('age_not_literal_source')
    for relation in registry.get('relationships',[]):
        if relation['from'] not in ids or relation['to'] not in ids:raise ValueError('relationship_unknown_person')
        if not relation['source_ids'] or not set(relation['source_ids'])<=set(catalog):raise ValueError('relationship_evidence_missing')
    return deepcopy(registry)

def cast_header(registry,cast,show_age=False):
    people={x['id']:x for x in registry['characters']}
    if len(cast)!=len(set(cast)) or not set(cast)<=set(people):raise ValueError('unknown_or_duplicate_cast')
    labels=[]
    for key in cast:
        person=people[key];age=person['age']
        labels.append(person['name']+(f"（{age['text']}）" if show_age and age is not None else ''))
    return '在场：'+'、'.join(labels)

def source_span(source,ref,start=0,end=None):
    text=c.catalog(source)[ref]['text'];end=len(text) if end is None else end
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):raise ValueError('invalid_source_span')
    return {'source_id':ref,'start':start,'end':end,'text':text[start:end]}

def validate_contract(contract,registry,source,review):
    approved(contract,source,review)
    if contract['registry_sha256']!=c.digest(registry):raise ValueError('scene_registry_changed')
    people={p['id']:p for p in registry['characters']};seen=set()
    for row in contract['lines']:
        if row['id'] in seen:raise ValueError('duplicate_line')
        seen.add(row['id'])
        if row['kind'] not in ('dialogue','action','narration','inner'):raise ValueError('unsupported_line_kind')
        ref=row['evidence'];expected=source_span(source,ref['source_id'],ref['start'],ref['end'])
        if ref!=expected:raise ValueError('source_text_changed')
        if row['speaker'] is not None and row['speaker'] not in people:raise ValueError('unknown_speaker')
        if row['kind'] in ('dialogue','inner','action') and row['speaker'] is None:raise ValueError('speaker_required')
        if row['kind']=='dialogue' and row['speaker'] not in contract['presence']['end_cast']:raise ValueError('speaker_not_on_screen')
        if row['listener'] is not None and row['listener'] not in people:raise ValueError('unknown_listener')
    # Reuse the existing location/entry/exit validator instead of making prose
    # summaries authoritative. Off-screen narration does not move people.
    return c.validate_screen_presence(contract['presence'],contract['previous_locations'],
                                     set(people),set(contract['places']))

def expression_schema(contract):
    fields={}
    for row in contract['lines']:
        if row['kind']=='narration':continue
        choices=SPEECH_STYLE if row['kind'] in ('dialogue','inner') else ACTION_STYLE
        if 'styles' in row:
            if not row['styles'] or not set(row['styles'])<=set(choices):raise ValueError('unsafe_performance_vocabulary')
            choices=row['styles']
        fields[row['id']]=c.choices(choices)
    return c.obj(**fields)

def render(contract,registry,source,registry_review,contract_review,expressions):
    validate_registry(registry,source,registry_review)
    end=validate_contract(contract,registry,source,contract_review)
    errors=c.schema_issues(expressions,expression_schema(contract),'performance')
    if errors:raise c.ContractError(errors)
    people={p['id']:p for p in registry['characters']}
    rendered=[]
    for line in contract['lines']:
        text=line['evidence']['text'];kind=line['kind'];speaker=line['speaker']
        if kind=='narration':value='旁白：'+text
        elif kind=='action':
            style=expressions[line['id']]
            prefix='' if style=='不追加动作' else people[speaker]['name']+style+'。'
            value=prefix+text
        else:
            mode='（内心）' if kind=='inner' else ''
            value=people[speaker]['name']+mode+'（'+expressions[line['id']]+'）：'+text
        rendered.append({'id':line['id'],'text':value,'source_text':text,'speaker':speaker})
    body='时间：'+contract['time_label']+'\n地点：'+contract['place_label']+'\n'+cast_header(registry,contract['presence']['end_cast'])+'\n\n'
    body+='\n\n'.join(x['text'] for x in rendered)
    return {'scene_id':contract['id'],'screenplay':body,'lines':rendered,'end_locations':end,
            'source_sha256':c.digest(source),'registry_sha256':c.digest(registry),
            'contract_sha256':c.digest(contract),'expressions_sha256':c.digest(expressions),
            'semantic_status':'awaiting_primary_review','fact_text_generated_by_model':False}

def repair_spans(original,patch_plan,replacements):
    return {**original,'screenplay':prose_patch.apply(original['screenplay'],patch_plan,replacements)}

def repair_literal_fields(original,changes):
    """Approved field spans only; preserve neighbouring posture and visual text."""
    plan=prose_patch.prepare(original['screenplay'],[
        {'quote':x['before'],'reason':x['reason']} for x in changes])
    replacements={f'edit_{i}':x['after'] for i,x in enumerate(changes)}
    return repair_spans(original,plan,replacements),{'plan':plan,'replacements':replacements}

def release_handoff(candidate,contract,registry,source,review):
    if (candidate['source_sha256']!=c.digest(source) or candidate['registry_sha256']!=c.digest(registry)
        or candidate['contract_sha256']!=c.digest(contract)):
        raise ValueError('handoff_dependencies_changed')
    approved(candidate,source,review)
    if review.get('scope')!='scene' or review.get('scene_id')!=candidate['scene_id']:
        raise ValueError('handoff_review_scope_mismatch')
    return {'scene_id':candidate['scene_id'],'candidate_sha256':c.digest(candidate),
            'contract_sha256':c.digest(contract),'registry_sha256':c.digest(registry),
            'source_sha256':c.digest(source),'locations':deepcopy(candidate['end_locations']),
            'source_facts':[deepcopy(x['evidence']) for x in contract['lines']],
            'freeform_model_continuity_used':False}

def episode_ready(required_scene_ids,handoffs,candidates):
    if len(handoffs)!=len(required_scene_ids) or {x['scene_id'] for x in handoffs}!=set(required_scene_ids):
        return False
    if len(set(required_scene_ids))!=len(required_scene_ids):return False
    return all(x['scene_id'] in candidates and x['candidate_sha256']==c.digest(candidates[x['scene_id']]) for x in handoffs)
