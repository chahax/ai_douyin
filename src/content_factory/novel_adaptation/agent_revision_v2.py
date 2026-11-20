"""Task-scoped context, graded issues, and atomic multi-range repair contracts."""
from copy import deepcopy
from . import contracts as c, prose_patch

SEVERITIES=('blocking','production','style')
SCOPE=c.obj(quote=c.TEXT,boundary=c.TEXT)
ISSUE=c.obj(id=c.TEXT,subject=c.TEXT,kind=c.choices(['facts','continuity','expression','scope']),
    severity=c.choices(SEVERITIES),claim=c.TEXT,source_ids=c.array(c.TEXT,1),reason=c.TEXT,
    scopes=c.array(SCOPE,1))
REPORT=c.obj(issues=c.array(ISSUE),summary=c.TEXT)
VERDICT=c.obj(id=c.TEXT,decision=c.choices(['supported','rejected','unresolved']),
    severity=c.choices(SEVERITIES),reason=c.TEXT)
VERIFY=c.obj(decisions=c.array(VERDICT),summary=c.TEXT)
CHECK=c.obj(results=c.array(c.obj(id=c.TEXT,result=c.choices(['resolved','unresolved']),reason=c.TEXT)),
    regressions=c.array(ISSUE),summary=c.TEXT)

COMMON='''目标是把小说已有剧情转成可拍剧本，保持人物关系、事件主体、因果、必要信息和行动顺序；不是自由续写。source是原文依据；context_only仅前情，target才是本段要演的内容。production_choices仅在指定范围有效，不反写原文。普通光线、微表情、合理路程省略允许。当前资料未说明不等于全书不存在；未署名不凭邻近姓名猜。唯一女孩不等于最小，走路队序不等于排行。动作能表达的情绪无需再配旁白。'''
REVIEW=COMMON+'''
独立审核当前candidate，不重写。不提供旧审核是为了独立判断，不代表没有小说前情。
按严重度分类：blocking仅为真实剧情/人物/因果错误或使必要信息缺失的问题；production为分镜/首帧/声音制作前需要澄清的事项；style为可选表达优化。环境概述不必自动视为开场初态，若道具前后会影响镜头则列production；能靠动作表达的心理不因未标旁白而阻断。不要虚构事实纠正原文歧义。
只输出结构化issues及简短summary。每个问题需要候选原句、实际source_ids及语义依据。scopes可含多个不连续的关联修改范围（如背景/正文/待核），每个quote必须是候选中唯一、逐字、连续且非空的原句；boundary只写修改边界，不代写新剧情。没有需要修改的范围就不提出补丁问题。不要让不同问题重叠选中同一文字。
返回问题清单即可，不逐章复述全文、不输出逐项通过清单。id在当前报告内唯一；subject简写问题涉及的人物/物件/事件。不将本次没发现当作绝对无误。'''
REVIEW+='\n必要事件、人物互动或有信息的对白整段遗漏属于blocking，不能因以后能在分镜补写而归为production。production仅针对现有剧情如何拍摄/呈现的待明确事项。'
VERIFY_PROMPT=COMMON+'''
你是问题依据核验节点，不是改稿节点。逐条核对review.issues在candidate和source中是否成立。输入的审核结论是待验证意见，不是事实。
对每个id恰好返回一次decision：supported有据成立，rejected误判，unresolved无法判定；同时独立核对severity。不存在的矛盾、纯风格优化、未写明但不影响制作的背景不得升级为blocking。不得编新事实解决问题。只返回decisions/summary，不改稿。
relevant_history只包含本问题相关的已拒绝或已解决记录；如果本次意见没有新证据，不因换种说法推翻旧处理。'''
VERIFY_PROMPT+='\n若原文明示的目标事件/人物互动/有信息对白整段遗漏，必须归blocking；production只处理已有剧情的镜头或道具落实，不能把缺失剧情留给分镜补写。若有据发现遗漏，即使没有改变其余剧情，也属于必须修复。'
REPAIR_PROMPT=COMMON+'''
按slots进行局部返修，只返回每个edit键的完整替换字符串，允许空字符串删除。程序会原样保留其他区域。一个issue_id可以对应多个slots，需要一致处理；不得借局部修复扩大成完整重写。
confirmed_issues是经过核验的意见，仍需与原文一致；relevant_history仅为本问题先前处理，禁止重复已知无据替代。优先删除新增错误或恢复原文主体/先后，不能另编情节代替。如果发现无法在给定范围完成，保持该范围原句，交定向复核判未解决。
保留原对白含义和交织动作神情；未知署名保持开放，关键声音不能因归属未知删除。只为必要不可见信息安排声音，不把全部心理强制变成旁白。'''
CHECK_PROMPT=COMMON+'''
定向复核已批准问题的修复。读取before、candidate、confirmed_issues、patches及完整source。每个id返回一次resolved或unresolved及理由；不能因文字变了就判修好。
重点检查人物/主体/先后/条件是否真的恢复，以及一个问题多处引用是否一致。检查补丁对关联场景是否引入新问题，将确有证据的新问题放regressions，按blocking/production/style分级。普通空行和稳定编号有跳号不是剧情错误。不要求未涉及场景重写。'''
CHECK_PROMPT+='\n若某个原问题仍为unresolved，也放入regressions作为待继续处理的问题，沿用其id并引用当前candidate的完整唯一范围；不要沿用修改前已不存在的quote。这样后续才能针对当前文本继续修复。'
CHECK_PROMPT+='\n原文明示的目标事件/人物互动/有信息对白整段遗漏应归blocking，不是production。所有regressions都会传给下一次意见核验，不能当作可忽略附注。'


def context(node,source,choices,candidate=None,**extras):
    """No incidental call/chat history. Every state-bearing input is explicit."""
    payload=dict(source=deepcopy(source),production_choices=deepcopy(choices))
    if node=='generate':allowed={'continuity_evidence'}
    elif node=='review':allowed=set()
    elif node=='verify':allowed={'review','relevant_history'}
    elif node=='repair':allowed={'confirmed_issues','slots','relevant_history'}
    elif node=='check':allowed={'before','confirmed_issues','patches','relevant_history'}
    else:raise ValueError('unknown_node')
    if set(extras)-allowed:raise ValueError('context_field_not_allowed')
    if candidate is not None:payload['candidate']=candidate
    payload.update(deepcopy(extras));return payload


def validate_report(source,candidate,report):
    faults=c.schema_issues(report,REPORT,'report')
    if faults:raise c.ContractError(faults)
    ids=[x['id'] for x in report['issues']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_issue_id')
    valid={p['id'] for ch in source['chapters'] for p in ch['paragraphs']}
    addresses={}
    for row in report['issues']:
        errors=[]
        if any(ref not in valid for ref in row['source_ids']):errors.append('invalid_source_ref')
        for scope in row['scopes']:
            if candidate.count(scope['quote'])!=1:errors.append('nonunique_issue_range')
        addresses[row['id']]=sorted(set(errors))
    return dict(candidate_digest=c.digest(candidate),source_digest=c.digest(source),review_digest=c.digest(report),address_diagnostics=addresses)


def relevant_history(registry,issues):
    subjects={x['subject'] for x in issues};refs={ref for x in issues for ref in x['source_ids']}
    return [deepcopy(x) for x in registry if x['subject'] in subjects or refs.intersection(x['source_ids'])]


def adjudicate(source,candidate,report,verification):
    binding=validate_report(source,candidate,report)
    faults=c.schema_issues(verification,VERIFY,'verify')
    if faults:raise c.ContractError(faults)
    decisions=verification['decisions']
    expected=sorted(x['id'] for x in report['issues'])
    if sorted(x['id'] for x in decisions)!=expected:raise ValueError('decision_coverage')
    lookup={x['id']:x for x in decisions};accepted=[];rows=[];unresolved=[]
    for issue in report['issues']:
        decision=lookup[issue['id']]
        row={**deepcopy(issue),'decision':decision['decision'],'verified_severity':decision['severity'],
             'decision_reason':decision['reason'],**binding}
        rows.append(row)
        if decision['decision']=='supported' and decision['severity']=='blocking':
            if binding['address_diagnostics'][issue['id']]:raise ValueError('blocking_evidence_not_patchable')
            accepted.append(row)
        if decision['decision']=='unresolved' and (issue['severity']=='blocking' or decision['severity']=='blocking'):unresolved.append(row)
    return dict(binding=binding,rows=rows,accepted=accepted,unresolved_blocking=unresolved)


def multi_span_plan(candidate,adjudication):
    if adjudication['binding']['candidate_digest']!=c.digest(candidate):raise ValueError('stale_adjudication')
    edits=[];owners=[]
    for issue in adjudication['accepted']:
        for scope in issue['scopes']:
            edits.append(dict(quote=scope['quote'],reason=issue['claim']+'\n依据：'+issue['reason']+'\n边界：'+scope['boundary']))
            owners.append(issue['id'])
    if not edits:raise ValueError('no_blocking_patch')
    plan=prose_patch.prepare(candidate,edits)
    for slot,owner in zip(plan['slots'],owners):slot['issue_id']=owner
    plan['adjudication_digest']=c.digest(adjudication)
    return plan


def record_issues(registry,adjudication,round_index):
    for issue in adjudication['rows']:
        record=deepcopy(issue)
        record.update(round=round_index,status='open' if issue['decision']=='supported' else issue['decision'])
        matches=[i for i,x in enumerate(registry) if x['id']==record['id'] and x['review_digest']==record['review_digest'] and x['candidate_digest']==record['candidate_digest']]
        if matches:
            if len(matches)!=1 or registry[matches[0]]['decision']!='unverified':raise ValueError('duplicate_issue_record')
            registry[matches[0]]=record
        else:registry.append(record)


def remember_observations(registry,source,candidate,report,round_index):
    binding=validate_report(source,candidate,report)
    for issue in report['issues']:
        registry.append({**deepcopy(issue),**binding,'round':round_index,
                         'decision':'unverified','verified_severity':issue['severity'],
                         'status':'pending_verification'})


def apply_check(registry,adjudication,check,candidate_digest):
    faults=c.schema_issues(check,CHECK,'check')
    if faults:raise c.ContractError(faults)
    if sorted(x['id'] for x in check['results'])!=sorted(x['id'] for x in adjudication['accepted']):
        raise ValueError('check_coverage')
    for result in check['results']:
        matches=[x for x in registry if x['id']==result['id'] and x['review_digest']==adjudication['binding']['review_digest']]
        if len(matches)!=1:raise ValueError('registry_binding')
        matches[0].update(status=result['result'],check_reason=result['reason'],checked_candidate_digest=candidate_digest)
    return all(x['result']=='resolved' for x in check['results']) and not any(x['severity']=='blocking' for x in check['regressions'])
