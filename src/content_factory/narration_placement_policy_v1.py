"""Evidence-bound narration placement before video prompt compilation.

An upstream scene planner supplies semantic dialogue groups, including turns
separated by narration. This policy judges narration; it never rewrites the
original dialogue, invents speaker knowledge, or submits media.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = 'narration_placement_policy/v1'
CASE = 'narration_placement_case/v1'
DECISIONS = 'narration_placement_decisions/v1'
REVIEW = 'narration_placement_semantic_review/v1'
RECEIPT = 'narration_placement_receipt/v1'
CLASSES = {'retain_scene_open':'scene_open', 'retain_action_gap':'action_gap', 'convert_character_oral':'oral_source_position'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def checked(binding):
    if bind(binding['path']) != {k:binding[k] for k in ('path','sha256')}: raise ValueError('bound_evidence_changed')
    return Path(binding['path'])


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def freeze(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value: raise ValueError('frozen_policy_evidence_changed')
    else:
        with path.open('x',encoding='utf-8') as stream: json.dump(value,stream,ensure_ascii=False,indent=2)
    return bind(path)


def validate_case(case):
    if case.get('schema') != CASE: raise ValueError('explicit_narration_case_required')
    tables = {}
    for key in ('scenes','quotes','actions','facts','dialogue_groups'):
        values = case.get(key)
        if not isinstance(values,list) or not values and key in ('scenes','quotes'): raise ValueError('explicit_policy_tables_required')
        ids = [v.get('id') for v in values]
        if any(not isinstance(i,str) or not i for i in ids) or len(ids) != len(set(ids)): raise ValueError('unique_source_ids_required')
        tables[key] = {v['id']:v for v in values}
    all_items = set(tables['quotes']) | set(tables['actions'])
    if len(all_items) != len(tables['quotes'])+len(tables['actions']): raise ValueError('quote_action_ids_must_be_distinct')
    scene_for, positions, global_positions = {}, {}, {}
    for scene in case['scenes']:
        if not scene.get('context') or not isinstance(scene.get('items'),list) or len(set(scene['items'])) != len(scene['items']):
            raise ValueError('ordered_scene_context_and_items_required')
        for index,item in enumerate(scene['items']):
            if item not in all_items or item in positions: raise ValueError('each_original_item_once_required')
            scene_for[item]=scene['id']; positions[item]=index
            global_positions[item]=len(global_positions)
    if set(positions) != all_items: raise ValueError('complete_source_item_coverage_required')
    for quote in case['quotes']:
        if (quote.get('kind') not in ('dialogue','narration') or not quote.get('text')
                or quote.get('scene_id') != scene_for[quote['id']]): raise ValueError('explicit_quote_kind_scene_required')
        if quote['kind']=='dialogue' and quote.get('speaker_id') not in case['characters']: raise ValueError('bound_dialogue_speaker_required')
        if any(f not in tables['facts'] for f in quote.get('fact_ids',[])): raise ValueError('unknown_narration_fact')
        ref=quote.get('source_ref')
        if case.get('source_refs_required') or ref is not None:
            if not isinstance(ref,dict): raise ValueError('quote_original_source_reference_required')
            original=checked(ref['document']).read_text(encoding='utf-8')[ref['start']:ref['end']]
            expected=original+'.' if ref.get('transform')=='append_ascii_period' else original+'。' if ref.get('transform')=='append_chinese_period' else original
            if expected!=quote['text']: raise ValueError('original_quote_text_or_transform_changed')
    for action in case['actions']:
        if not action.get('text') or action.get('scene_id') != scene_for[action['id']]: raise ValueError('source_action_scene_required')
    used=[]
    for group in case['dialogue_groups']:
        turns=group.get('quote_ids',[])
        if (len(turns)<2 or not group.get('semantic_relation') or any(q not in tables['quotes'] for q in turns)
                or any(tables['quotes'][q]['kind']!='dialogue' or scene_for[q]!=group['scene_id'] for q in turns)
                or turns!=sorted(turns,key=positions.get)):
            raise ValueError('semantic_dialogue_groups_must_preserve_question_answer_or_exchange')
        used += turns
    if len(used)!=len(set(used)): raise ValueError('dialogue_turn_has_multiple_protected_groups')
    for fact in case['facts']:
        if not fact.get('source_quote_ids') or any(q not in tables['quotes'] for q in fact['source_quote_ids']): raise ValueError('fact_original_evidence_required')
        for actor, evidence in fact.get('known_by',{}).items():
            if actor not in case['characters'] or not evidence or any(q not in tables['quotes'] for q in evidence): raise ValueError('actor_knowledge_evidence_required')
    for source in case.get('source_bindings',[]): checked(source)
    tables.update(positions=positions,scene_for=scene_for,global_positions=global_positions)
    return tables


def allowed_slots(case):
    t=validate_case(case); result=[]
    for scene in case['scenes']:
        result.append(dict(id='OPEN:'+scene['id'],kind='scene_open',scene_id=scene['id']))
    for action in case['actions']:
        position=t['positions'][action['id']]
        protected=[g['id'] for g in case['dialogue_groups'] if g['scene_id']==action['scene_id'] and
            min(t['positions'][q] for q in g['quote_ids']) <= position < max(t['positions'][q] for q in g['quote_ids'])]
        if not protected:
            result.append(dict(id='GAP:'+action['id'],kind='action_gap',scene_id=action['scene_id'],action_id=action['id'],relation='after'))
    result += [dict(id='ORAL:'+q['id'],kind='oral_source_position',scene_id=q['scene_id'],source_quote_id=q['id']) for q in case['quotes'] if q['kind']=='narration']
    return result


def messages(case, *, phase='judge', candidate=None, issues=None):
    validate_case(case)
    system = ('你是短剧音画调度判断节点，只判断每条旁白的放置，不重写整稿。原对白文字、说话人、人物关系、事实和事件顺序固定。'
        '旁白可以保留：场景开头说明背景，或不打断问答/劝阻等连续交流的动作间隙。不要一刀切转口述。'
        'dialogue_groups按语义连续性给定，即使原稿中夹了旁白仍是同一组，不能按旁白机械拆组。'
        '仅引用allowed_slots；retain_scene_open用scene_open；retain_action_gap用action_gap；convert_character_oral用该旁白的oral_source_position。'
        '转口述需每个fact对该角色有known_by原文证据，且知情不晚于当前位置，只能说自己亲历/已知的范围，避免把全知旁白强塞给角色。'
        '转口述落在保护组中时，还必须是当前问答的自然回答或同主题话轮；人物知道某事不代表可以在争执问答中突然讲旧背景。'
        '不能确定就certainty=uncertain，由独立语义修复处理，不输出人工待确认或伪ready。声音/画面生产不在此节点。只输出一个JSON对象，无Markdown。')
    contract = dict(schema=DECISIONS, case_sha256=digest(case), decisions=[dict(source_quote_id='输入旁白ID',classification='三类之一',
        slot_id='输入slotID',dialogue_group_ids=['相关语义组ID'],source_fact_ids=['本条原factID'],
        pov=dict(speaker_id=None,knowledge_evidence_quote_ids=[]),oral_suggestion=None,oral_relation='outside_group或natural_response或same_topic_turn',
        reason='引用具体问答/动作/知情关系的判断理由',certainty='sufficient或uncertain')])
    if phase=='review':
        system += ('你是独立语义复核，不重写候选。逐旁白检查：保留旁白是否落在完整交流之外；转口述是否完全有据、角色当时已知，并且与当前问答自然衔接。'
            '候选口述每个分句不能新增推断、动机或角色关系。依据不足必须needs_semantic_repair。')
        contract=dict(schema=REVIEW,candidate_sha256=digest(candidate),checks=[dict(source_quote_id='每条旁白ID',verdict='pass或needs_semantic_repair',
            evidence_quote_ids=['输入quoteID'],reason='具体依据')])
    elif phase=='repair':
        system += '这是独立语义修复请求，只重新返回各旁白判决，不改原对白和原事实；纠正issues，若口述依据不足改成合法位置的旁白。'
    payload=dict(task=phase,case=case,allowed_slots=allowed_slots(case),output_contract=contract)
    if candidate is not None: payload['candidate']=candidate
    if issues is not None: payload['issues']=issues
    if phase!='review':
        payload['oral_suggestion_contract']=dict(speaker_id='具有全部fact知情证据的角色ID',text='自然口语建议，不加新事实',source_fact_ids=['本旁白原factID'])
    return [dict(role='system',content=system),dict(role='user',content=json.dumps(payload,ensure_ascii=False))]


def _validate_decisions(case, candidate):
    t=validate_case(case); slots={s['id']:s for s in allowed_slots(case)}; issues=[]
    narrations={q['id']:q for q in case['quotes'] if q['kind']=='narration'}
    if candidate.get('schema')!=DECISIONS or candidate.get('case_sha256')!=digest(case): return ['candidate_case_or_schema_changed']
    rows=candidate.get('decisions',[])
    if not isinstance(rows,list) or len(rows)!=len(narrations) or {r.get('source_quote_id') for r in rows}!=set(narrations):
        return ['each_source_narration_requires_exactly_one_decision']
    for row in rows:
        q=narrations[row['source_quote_id']]; label=q['id']+':'
        slot=slots.get(row.get('slot_id')); classification=row.get('classification')
        if (classification not in CLASSES or slot is None or slot['kind']!=CLASSES.get(classification) or slot['scene_id']!=q['scene_id']):
            issues.append(label+'illegal_or_protected_dialogue_slot'); continue
        if (not isinstance(row.get('reason'),str) or not row['reason'].strip() or row.get('certainty')!='sufficient'):
            issues.append(label+'needs_independent_semantic_repair')
        groups=row.get('dialogue_group_ids')
        if not isinstance(groups,list) or len(groups)!=len(set(groups)) or any(g not in t['dialogue_groups'] for g in groups): issues.append(label+'unknown_dialogue_group')
        if set(row.get('source_fact_ids',[]))!=set(q.get('fact_ids',[])): issues.append(label+'source_facts_changed')
        if classification=='retain_scene_open' and any(not t['facts'][f].get('scene_open_allowed',False) for f in q.get('fact_ids',[])):
            issues.append(label+'future_or_unavailable_fact_cannot_open_scene')
        if classification=='retain_action_gap':
            for fact_id in q.get('fact_ids',[]):
                fact=t['facts'][fact_id]
                if not fact.get('scene_open_allowed',False) and slot.get('action_id') not in fact.get('available_after_action_ids',[]):
                    issues.append(label+'action_does_not_establish_fact:'+fact_id)
        pov=row.get('pov',{}); oral=row.get('oral_suggestion')
        if classification=='convert_character_oral':
            actor=pov.get('speaker_id'); expected=set(q.get('fact_ids',[]))
            if (slot.get('source_quote_id')!=q['id'] or not expected or actor not in case['characters'] or not isinstance(oral,dict)
                    or oral.get('speaker_id')!=actor or not isinstance(oral.get('text'),str) or not oral['text'].strip()
                    or set(oral.get('source_fact_ids',[]))!=expected):
                issues.append(label+'oral_source_or_speaker_missing'); continue
            evidence=set(pov.get('knowledge_evidence_quote_ids',[]))
            if not evidence or any(e not in t['quotes'] for e in evidence): issues.append(label+'missing_POV_evidence')
            for fact_id in expected:
                known=set(t['facts'][fact_id].get('known_by',{}).get(actor,[]))
                if not known or not evidence & known: issues.append(label+'actor_does_not_know_fact:'+fact_id)
                if not any(t['global_positions'][e]<=t['global_positions'][q['id']] for e in evidence & known):
                    issues.append(label+'actor_only_learns_fact_later:'+fact_id)
            protected=[g for g in case['dialogue_groups'] if g['scene_id']==q['scene_id'] and
                min(t['positions'][i] for i in g['quote_ids']) < t['positions'][q['id']] < max(t['positions'][i] for i in g['quote_ids'])]
            if protected and (row.get('oral_relation') not in ('natural_response','same_topic_turn')
                    or any(g['id'] not in groups for g in protected)):
                issues.append(label+'oral_interruption_not_a_natural_current_turn')
        elif oral is not None or pov.get('speaker_id') is not None:
            issues.append(label+'retained_narration_cannot_change_words_or_speaker')
    return issues


def validate_decisions(case, candidate):
    try: return _validate_decisions(case,candidate)
    except (TypeError,KeyError,AttributeError,IndexError): return ['invalid_decision_structure_needs_semantic_repair']


def _validate_review(case, candidate, review):
    if review.get('schema')!=REVIEW or review.get('candidate_sha256')!=digest(candidate): return ['semantic_review_candidate_changed']
    ids={q['id'] for q in case['quotes'] if q['kind']=='narration'}; rows=review.get('checks',[])
    if not isinstance(rows,list) or len(rows)!=len(ids) or {r.get('source_quote_id') for r in rows}!=ids: return ['semantic_review_incomplete']
    quotes={q['id'] for q in case['quotes']}; issues=[]
    for row in rows:
        if (row.get('verdict')!='pass' or not row.get('reason') or not row.get('evidence_quote_ids')
                or any(q not in quotes for q in row['evidence_quote_ids'])): issues.append(row.get('source_quote_id','?')+':needs_semantic_repair')
    return issues


def validate_review(case, candidate, review):
    try: return _validate_review(case,candidate,review)
    except (TypeError,KeyError,AttributeError,IndexError): return ['invalid_review_structure_needs_semantic_repair']


def compile_before_video(case, receipt):
    """Executable gate and actual prompt/audio-item ordering, never just metadata."""
    validate_case(case)
    if receipt.get('schema')!=RECEIPT or receipt.get('case_sha256')!=digest(case) or receipt.get('status')!='accepted':
        raise ValueError('accepted_evidence_bound_narration_receipt_required_before_video_compile')
    candidate=receipt['candidate']; review=receipt['semantic_review']
    issues=validate_decisions(case,candidate)+validate_review(case,candidate,review)
    if issues: raise ValueError('narration_compile_gate_failed:'+','.join(issues))
    t=validate_case(case); rows={r['source_quote_id']:r for r in candidate['decisions']}; insertion={}
    for row in rows.values():
        if row['classification']!='convert_character_oral': insertion.setdefault(row['slot_id'],[]).append(row['source_quote_id'])
    result=[]
    def narration(qid):
        q=t['quotes'][qid]; row=rows[qid]
        if row['classification']=='convert_character_oral':
            return dict(id=qid,kind='audio',scene_id=q['scene_id'],speaker_id=row['pov']['speaker_id'],mode='onscreen',
                text=row['oral_suggestion']['text'],source_quote_id=qid,source_fact_ids=row['source_fact_ids'])
        return dict(id=qid,kind='audio',scene_id=q['scene_id'],speaker_id='narrator',mode='voiceover',text=q['text'],source_quote_id=qid)
    for scene in case['scenes']:
        result.append(dict(id=scene['id'],kind='scene',text=scene['context']))
        result += [narration(qid) for qid in insertion.get('OPEN:'+scene['id'],[])]
        for item in scene['items']:
            if item in t['actions']:
                action=t['actions'][item]; result.append(dict(id=item,kind='action',scene_id=scene['id'],text=action['text']))
                result += [narration(qid) for qid in insertion.get('GAP:'+item,[])]
            else:
                quote=t['quotes'][item]
                if quote['kind']=='dialogue': result.append(dict(id=item,kind='audio',scene_id=scene['id'],speaker_id=quote['speaker_id'],mode='onscreen',text=quote['text'],source_quote_id=item))
                elif rows[item]['classification']=='convert_character_oral': result.append(narration(item))
    expected=[q for s in case['scenes'] for q in s['items'] if q in t['quotes'] and t['quotes'][q]['kind']=='dialogue']
    actual=[r['id'] for r in result if r['kind']=='audio' and t['quotes'][r['source_quote_id']]['kind']=='dialogue']
    if actual!=expected: raise ValueError('fixed_original_dialogue_order_changed')
    if {r['source_quote_id'] for r in result if r['kind']=='audio'}!=set(t['quotes']): raise ValueError('audio_coverage_changed')
    prompt=[]
    cursor=0.0; scene_id=None; last_action=None
    for item in result:
        if item['kind']=='scene':
            scene_id=item['id']; cursor=0.0; last_action=None
            prompt.append('场景：'+item['text'])
        elif item['kind']=='action':
            item['start']=round(cursor,3); item['end']=round(cursor+float(t['actions'][item['id']].get('duration_seconds',1.0)),3)
            cursor=item['end']; last_action=item
            prompt.append(f"{item['start']:g}—{item['end']:g}秒，动作与画面："+item['text'])
        else:
            row=rows.get(item['source_quote_id']); slot_id=row.get('slot_id') if row else None
            start=last_action['start'] if last_action is not None and slot_id=='GAP:'+last_action['id'] else cursor
            duration=max(0.8,len(item['text'])/4.2)
            item['start']=round(start,3); item['end']=round(start+duration,3)
            item['timing_basis']='conservative_sequential_speech_budget_not_measured_audio'
            cursor=max(cursor,item['end']); last_action=None
            lead='旁白画外叙述' if item['mode']=='voiceover' else case['characters'][item['speaker_id']]+'本人开口说'
            prompt.append(f"{item['start']:g}—{item['end']:g}秒，"+lead+'：“'+item['text']+'”')
    audio=[r for r in result if r['kind']=='audio']
    for scene in case['scenes']:
        ordered=sorted([a for a in audio if a['scene_id']==scene['id']],key=lambda a:a['start'])
        if any(a['end']>b['start'] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('narration_or_dialogue_audio_windows_overlap')
    return dict(schema=VERSION,case_sha256=digest(case),receipt_sha256=digest(receipt),items=result,
        compiled_prompt='\n'.join(prompt),audio_items=[r for r in result if r['kind']=='audio'],
        dispatched_media=False,production_approved=False,global_defaults_changed=False)
