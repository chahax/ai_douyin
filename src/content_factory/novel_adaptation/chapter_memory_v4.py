"""Append-only, source-bound chapter analyses; never generated-script canon."""
from copy import deepcopy
from . import contracts as c

ANALYZE = '''分析当前target完整章节，并结合previous_memory中此前逐章分析和source中的真实前文，形成可供本章剧本及后续章节使用的增量资料。
这是分析，不是编剧，不新增小说事实。previous_memory是有原文依据但仍可能有误的模型分析，发生矛盾以source原文为准。
只提取有叙事作用的身份/身体身份、人物关系、地点环境、实际事件/状态变化、计划与未结束事项。不要把每个形容词变成事实；不要重写全部旧资料。
每项statement准确保留主体、时间与确定程度；certainty区分explicit/contextual/uncertain，temporal区分current/past/plan/original_future。
opening_bridge必须检查上一章末尾和当前章开头：谁刚说了什么/做了什么，开头他/她/这/那么等回指谁或什么，动作地点是否承接。首章没有前情则说明起始场面，不编前情。referents记录必要指代与原文依据；不明确就标uncertain，不猜名字。
closing_state说明本章结尾实际完成到哪里、当前有哪些人物和未完成行动；不把计划当作已发生，也不把结尾状态提前到本章开头。
同一人物的原主/穿越者/外在身体不能混成新人物；称谓不是自动新增身份。后章新事实补充旧认识，记录变化而不篡改原章节记录。
只输出本章delta；source_ids只引用原文段号，不复制虚构编号。'''

AUDIT = '''独立对照source原文审核analysis这个当章增量分析及其与previous_memory的承接。原文优先，旧模型分析不是事实裁判。
重点：主体和身体身份、称谓/关系、章节开头代词及发言承接、结尾位置与行动是否已完成、人物猜测/原书未来/计划是否被写成现时事实。
不要求罗列所有细节；仅列会误导当前或后续剧本的事实错误、必要漏项或矛盾。不因可省美术或动作偏好阻断。
issues给出analysis里的具体字段路径、理由与原文引用。passed必须与issues是否为空一致。不要把未知当确定，不要求人工确认。'''
AUDIT += '''\n下游作者同时读取完整原文，分析是辅助前情资料而不是取代原文。不要要求分析重复全部对白、表情、保护动作等当前场细节。
只在遗漏会让跨章身份/状态/行动承接被误解时拦截。普通不改变剧情的姿态推断不能直接等同原文矛盾；先核对中间是否已有起身、离开等动作，不能跳过它们凭两个端点判断冲突。'''
RESOLVE = AUDIT + '''\n请独立核验review每条阻断理由是否成立。逐项给blocks_memory及原文理由；确实会误导人物、事件、时序或跨章承接才阻断。
不是通过增加审核轮数强求通过：成立的问题保持阻断；发现其他同等实质错误放入additional_issues。不改analysis，不给人工作业，不因旧审核写了问题就认定它成立。'''


def resolution_schema(source,audit):
    return c.obj(decisions=c.obj(**{f'i{i}':c.obj(blocks_memory={'type':'boolean'},reason=c.TEXT,source_ids=c.refs(source_ids(source)))
        for i in range(len(audit['issues']))}),additional_issues=audit_schema(source)['properties']['issues'])


def resolved_audit(source,audit,resolution):
    faults=c.schema_issues(resolution,resolution_schema(source,audit),'analysis_resolution')
    if faults:raise c.ContractError(faults)
    remaining=[deepcopy(x) for i,x in enumerate(audit['issues']) if resolution['decisions'][f'i{i}']['blocks_memory']]
    remaining+=resolution['additional_issues']
    return dict(passed=not remaining,issues=remaining)

AUTHOR_CONTEXT = '''
current_analysis为null或某历史entry标source_only_fallback时，表示该章辅助分析未采用，不是没有剧情；请直接读取source中该章完整原文，不读取隔离分析，不猜补资料，不省略目标章。
chapter_memory是逐章累积的原文分析，不是需要全部演出的剧情；source仍是事实依据。各entry只描述那一章，不把旧结尾当当前状态，也不把本章结尾当开场。
特别核对current_analysis.opening_bridge与previous_chapter_tail：前一句谁说/做、当前代词指谁、说话与被说对象不同。chapter_memory里的不确定解释不能升级成确定署名。
只演target，context_only中的事件不重复演。若需独立成段的简短承接，可用原文已有信息说明，不补造关系、行动或对话。
普通动作省略不损害理解时允许，不必把每个心理或道具判断逐一改写成动作。人物关系、事件主体、必要剧情和事实/猜测边界须保持。
'''


def packet(corpus, chapter):
    by={x['index']:x for x in corpus['chapters']}
    if chapter<1 or any(i not in by for i in range(1,chapter+1)):raise ValueError('noncontiguous_source')
    return dict(chapters=[dict(chapter=i,role='target' if i==chapter else 'context_only',
        text_sha256=c.digest(by[i]['text']),paragraphs=[dict(id=f'CH{i}-P{j:03}',text=t)
        for j,t in enumerate(by[i]['text'].split('\n\n'),1)]) for i in range(1,chapter+1)])


def source_ids(source):return [p['id'] for ch in source['chapters'] for p in ch['paragraphs']]


def schema(source):
    refs=c.refs(source_ids(source))
    return c.obj(facts=c.array(c.obj(kind=c.choices(['identity','relationship','environment','event_state','open_thread','plan']),
        statement=c.TEXT,temporal=c.choices(['current','past','plan','original_future']),
        certainty=c.choices(['explicit','contextual','uncertain']),source_ids=refs)),
        opening_bridge=c.obj(statement=c.TEXT,source_ids=refs,
            referents=c.array(c.obj(expression=c.TEXT,referent=c.TEXT,certainty=c.choices(['explicit','contextual','uncertain']),source_ids=refs))),
        closing_state=c.obj(statement=c.TEXT,source_ids=refs))


def audit_schema(source):
    return c.obj(passed={'type':'boolean'},issues=c.array(c.obj(path=c.TEXT,reason=c.TEXT,source_ids=c.refs(source_ids(source)))))


def validate_memory(memory,corpus,next_chapter):
    if len(memory)!=next_chapter-1:raise ValueError('memory_not_contiguous')
    for i,row in enumerate(memory,1):
        source=packet(corpus,i)
        if row['chapter']!=i or row['source_digest']!=c.digest(source):raise ValueError('memory_source_changed')
        if row.get('origin')=='source_only_fallback':
            if set(row)!={'chapter','source_digest','previous_memory_digest','origin','semantic_guarantee','unavailable_analysis'} or row['semantic_guarantee'] is not False or not row['unavailable_analysis']:
                raise ValueError('invalid_source_only_record')
            if row['previous_memory_digest']!=c.digest(memory[:i-1]):raise ValueError('memory_parent_changed')
            continue
        if row['analysis_digest']!=c.digest(row['analysis']):raise ValueError('memory_analysis_changed')
        if row['previous_memory_digest']!=c.digest(memory[:i-1]):raise ValueError('memory_parent_changed')
        if row['audit_digest']!=c.digest(row['audit']) or row['audit']!={'passed':True,'issues':[]}:
            raise ValueError('memory_audit_not_passed')
        if 'audit_evidence' in row and row.get('audit_evidence_digest')!=c.digest(row['audit_evidence']):raise ValueError('memory_audit_evidence_changed')
        faults=c.schema_issues(row['analysis'],schema(source),'chapter_memory')
        if faults:raise c.ContractError(faults)


def append(memory,corpus,chapter,analysis,audit,audit_evidence=None):
    validate_memory(memory,corpus,chapter)
    source=packet(corpus,chapter)
    faults=c.schema_issues(analysis,schema(source),'analysis')+c.schema_issues(audit,audit_schema(source),'analysis_audit')
    if faults:raise c.ContractError(faults)
    if audit!={'passed':True,'issues':[]}:raise ValueError('analysis_not_approved')
    row=dict(chapter=chapter,source_digest=c.digest(source),previous_memory_digest=c.digest(memory),
        analysis=deepcopy(analysis),analysis_digest=c.digest(analysis),audit=deepcopy(audit),audit_digest=c.digest(audit),
        origin='source_analysis_only',semantic_guarantee=False)
    if audit_evidence is not None:
        row['audit_evidence']=deepcopy(audit_evidence);row['audit_evidence_digest']=c.digest(audit_evidence)
    return deepcopy(memory)+[row]


def author_context(memory,corpus,chapter):
    validate_memory(memory,corpus,chapter+1)
    source=packet(corpus,chapter)
    previous=source['chapters'][-2]['paragraphs'][-8:] if chapter>1 else []
    return dict(prior_analyses=deepcopy(memory[:-1]),current_analysis=deepcopy(memory[-1].get('analysis')),
        previous_chapter_tail=deepcopy(previous),memory_digest=c.digest(memory),
        evidence_priority='original_source_over_model_analysis',current_chapter=chapter)


def append_source_only(memory,corpus,chapter,evidence):
    """Keep a source pointer when optional analysis is rejected; never call it approved."""
    validate_memory(memory,corpus,chapter)
    if not evidence:raise ValueError('missing_rejection_evidence')
    return deepcopy(memory)+[dict(chapter=chapter,source_digest=c.digest(packet(corpus,chapter)),
        previous_memory_digest=c.digest(memory),origin='source_only_fallback',semantic_guarantee=False,
        unavailable_analysis=deepcopy(evidence))]
