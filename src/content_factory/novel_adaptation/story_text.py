"""Story before shots: source-bound event outline, then readable scene dialogue.

No shot timing, camera, asset generation or physical inventory in these stages.
Structural checks do not certify the interpretation of the source.
"""
from . import contracts as c

OUTLINE_PROMPT='''读完整章节，按target_chapters组织连续故事事件。其他章只作理解上下文，不提前演出。
先确定人物处境、冲突、转折及事件结果，再决定自然场次边界，不按固定秒数或每章一集压缩。
保留否定、条件、猜测和时间层；书中未来不是当前已发生，人物私下讨论不等于其他人知情。
source_ids只选支持本事件的原段。重要省略注明原因。这里只规划剧情，不写机位、器具库存或逐秒镜头。'''

DRAFT_PROMPT='''依据完整原文及事件规划写可读的连续剧本。按自然事件写场景、动作神情、对白和内心/旁白。
保留所有规划事件及其因果，不提前演出未来事件；回忆/原书未来的表述须保持时间限定。
原文之外兼容的动作或环境补足写adaptation_notes，不冒充原文事实。不为无关器具编造操作链。
人物进入、离开及影响剧情的重要交接应在动作中清楚可见；镜头外不等于离场。
对白不是对程序解释，旁白不能自称角色；不让人物知道其未获知的秘密。
先让故事成立；不生成分镜、秒数或固定短片段，不以重复解释凑时长。后续阶段才做视觉设计与关键状态核验。'''


def people(packet):
    return [e['id'] for e in packet['entities'] if e['kind']=='character']


def reviewed_materials(source,packet,targets):
    if packet.get('semantic_status')!='selected_dependencies_reviewed' or packet['source_sha256']!=c.digest(source):
        raise ValueError('reviewed_materials_missing_or_stale')
    catalog=c.catalog(source);target_ids={key for key in catalog if any(key.startswith(f'CH{n}-') for n in targets)}
    result={'target_facts':[],'context_only_facts':[],'packet_sha256':c.digest(packet),
            'scope':'Selected previously reviewed dependencies, not exhaustive source coverage.'}
    seen=set()
    for fact in packet.get('facts',[]):
        refs=set(fact['source_ids'])
        if fact['id'] in seen or not refs or not refs<=set(catalog):raise ValueError('invalid_reviewed_fact_binding')
        seen.add(fact['id'])
        row={'fact':fact,'fact_sha256':c.digest(fact)}
        result['target_facts' if refs<=target_ids else 'context_only_facts'].append(row)
    return result


def outline_schema(source,packet,targets):
    ids=[key for key in c.catalog(source) if any(key.startswith(f'CH{n}-') for n in targets)]
    return c.obj(title=c.TEXT,premise=c.TEXT,beats=c.array(c.obj(
        id=c.TEXT,source_ids=c.refs(ids),time_layer=c.choices(['current','past','book_future','belief']),
        participants=c.refs(people(packet)),location=c.TEXT,situation=c.TEXT,turn=c.TEXT,outcome=c.TEXT),1),
        omissions=c.array(c.obj(source_ids=c.refs(ids),reason=c.TEXT)))


def draft_schema(packet,outline,*,explicit_timeline=False):
    scene=c.obj(id=c.TEXT,beat_ids=c.refs([b['id'] for b in outline['beats']]),
        location=c.TEXT,cast=c.refs(people(packet)),action=c.TEXT,
        lines=c.array(c.obj(kind=c.choices(['dialogue','inner','narration']),
            speaker=c.choices(people(packet)+['NARRATOR']),text=c.TEXT)),
        ending=c.TEXT,adaptation_notes=c.array(c.TEXT))
    if explicit_timeline:
        scene['properties']['timeline']=c.choices(['current','past','book_future','belief'])
        scene['required'].append('timeline')
    return c.obj(title=c.TEXT,scenes=c.array(scene,1))


def checked(value,schema):
    issues=c.schema_issues(value,schema,'story_text')
    if issues:raise c.ContractError(issues)


def validate_outline(value,source,packet,targets):
    checked(value,outline_schema(source,packet,targets))
    ids=[b['id'] for b in value['beats']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_story_beat')


def validate_draft(value,packet,outline,*,explicit_timeline=False):
    checked(value,draft_schema(packet,outline,explicit_timeline=explicit_timeline))
    ids=[s['id'] for s in value['scenes']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_story_scene')
    if {b for s in value['scenes'] for b in s['beat_ids']}!={b['id'] for b in outline['beats']}:
        raise ValueError('planned_story_beat_missing')
    for s in value['scenes']:
        for line in s['lines']:
            if (line['kind']=='narration')!=(line['speaker']=='NARRATOR'):
                raise ValueError('story_narrator_identity_mismatch')
            if line['kind']=='dialogue' and line['speaker'] not in s['cast']:
                raise ValueError('story_dialogue_speaker_absent')


def generate(ledger,source,packet,targets,save,*,use_reviewed_materials=False,scope_guard=False,direct_story=False):
    if packet['source_sha256']!=c.digest(source):raise ValueError('story_source_identity_mismatch')
    if not targets or not set(targets)<={x['index'] for x in source['chapters']}:
        raise ValueError('story_target_chapters_missing')
    payload={'complete_chapters':c.indexed_chapters(source),'target_chapters':targets,'entities':packet['entities']}
    guidance=''
    if use_reviewed_materials:
        payload['reviewed_materials']=reviewed_materials(source,packet,targets)
        save('REVIEWED_MATERIALS_INPUT',payload['reviewed_materials'])
        guidance='\n复用reviewed_materials中已核对的事实，不重新猜测其动机。target_facts是本章资料；context_only_facts仅帮助理解，不提前演出、不把后章解释变成本章已知。保留事实的certainty与temporal_scope；材料只是已核对的部分，不代替完整原文或证明覆盖完整。正文与材料有冲突时保留未确定性，不补出新的肯定原因。'
    if scope_guard:
        # Keep the authoritative full source untouched, but do not expose later
        # chapter explanations during authoring of the current event range.
        payload['complete_chapters']=[x for x in payload['complete_chapters'] if x['index']<=max(targets)]
        available={key for key in c.catalog(source) if int(key.split('-')[0][2:])<=max(targets)}
        material=payload.get('reviewed_materials')
        withheld=[]
        if material:
            for key in ('target_facts','context_only_facts'):
                withheld.extend(x['fact']['id'] for x in material[key] if not set(x['fact']['source_ids'])<=available)
                material[key]=[x for x in material[key] if set(x['fact']['source_ids'])<=available]
        save('AUTHORING_SCOPE',{'full_source_sha256':c.digest(source),
            'included_chapters':[x['index'] for x in payload['complete_chapters']],
            'withheld_fact_ids':withheld,'request_materials_sha256':c.digest(material)})
        guidance+='\n当前阶段只提供目标章及之前的完整原文。没有在这些材料中说明的动机保持未知，不推断后续解释。一个事件只对应一个时间层；当前回忆行为与回忆中的历史事件分开。scene.timeline表示实际画面所在时间，cast只列这一画面真实出现的人；仅旁白提及的父母、兄妻不要列入当前在场；要演回忆就另设对应时间层的场。好像、如果、猜测等限定在摘要、正文、结尾均保持。'
    if direct_story:
        guidance=guidance.replace('scene.timeline表示实际画面所在时间，cast只列这一画面真实出现的人',
                                  '每场注明实际画面的时间层，人物名单只列这一画面真实出现的人')
        catalog=c.catalog(source)
        refs=[key for key in catalog if any(key.startswith(f'CH{n}-') for n in targets)]
        schema=c.obj(title=c.TEXT,screenplay=c.TEXT,source_ids=c.refs(refs))
        prompt='''直接依据完整原文和已核对资料写目标章节的完整可读剧本，不先提交事件表。
screenplay使用自然文本，按场写清时间层、地点、当前在场人物、动作神情、对白及必要旁白/内心；回忆中的人物不算当前屋内在场。
涉及具体细节直接回看带编号的原句，保留条件、否定和不确定性，不能把摘要当原文。原文外观描述可以只通过画面表达，不必转换成确定时长或新增旁白。相关人物心理依据目标章节，缺失动机不补结论。
场内人物进出、重要交接清楚，普通动作自然省略；不生成器具库存或复杂JSON场次表，不强行固定总秒数。
source_ids列实际使用的目标章节原段，程序另存原句以便审核；引用存在不等于内容正确。
不要把审核要求、禁止项、程序操作写进剧本。输出完整剧情与对白，格式只需title、screenplay、source_ids三个字段。'''
        draft=ledger.call('STORY_DIRECT','writer',prompt+guidance,payload,schema)
        save('STORY_DIRECT_NATIVE',draft);checked(draft,schema)
        save('STORY_SOURCE_EVIDENCE',{key:catalog[key] for key in draft['source_ids']})
        result={'source_sha256':c.digest(source),'draft_sha256':c.digest(draft),
                'status':'story_draft_awaiting_source_and_continuity_review','semantic_acceptance':False,
                'outline_required':False,'shot_planning_started':False,'fixed_duration_seconds':None}
        save('STORY_STAGE_RESULT',result)
        return result
    outline=ledger.call('STORY_EVENTS','writer',OUTLINE_PROMPT+guidance,payload,outline_schema(source,packet,targets))
    save('STORY_EVENTS_NATIVE',outline)
    validate_outline(outline,source,packet,targets)
    draft=ledger.call('STORY_DIALOGUE','writer',DRAFT_PROMPT+guidance,{**payload,'outline':outline},draft_schema(packet,outline,explicit_timeline=scope_guard))
    save('STORY_DIALOGUE_NATIVE',draft)
    validate_draft(draft,packet,outline,explicit_timeline=scope_guard)
    result={'source_sha256':c.digest(source),'outline_sha256':c.digest(outline),'draft_sha256':c.digest(draft),
            'status':'story_draft_awaiting_source_and_continuity_review','semantic_acceptance':False,
            'shot_planning_started':False,'fixed_duration_seconds':None}
    save('STORY_STAGE_RESULT',result)
    return result
