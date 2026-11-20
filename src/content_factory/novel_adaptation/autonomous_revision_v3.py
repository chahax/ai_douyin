"""Separate issue importance from mandatory disposition; never hand off open work."""
from copy import deepcopy
from collections import Counter
import math
import re
from . import contracts as c, agent_revision_v2 as base, prose_patch

REPORT = base.REPORT
CHECK = base.CHECK
DECISION = c.obj(id=c.TEXT, decision=c.choices(['supported','rejected','unresolved']),
    severity=c.choices(base.SEVERITIES), action=c.choices(['repair_source','repair_neutral','keep','blocked']),
    reason=c.TEXT, source_ids=c.array(c.TEXT), scopes=c.array(base.SCOPE))
VERIFY = c.obj(decisions=c.array(DECISION), summary=c.TEXT)

POLICY = '''这是无人文本生产闭环。severity只表示影响程度，不决定是否修复。production不是转交人工的出口。
有据错误、无据确定的关系/署名/道具、正文与待核自相矛盾，均需自动处理。真正可选的风格建议或错误审查意见才可以保留不改。
资料不足时先使用程序检索的evidence_only原文；这些是前文事实证据，不是要重演的目标剧情。检索没有命中不证明全书不存在。不要把后来的事实提前写入过去场景。
仍不明确时删除不必要的确定性设定；必要台词保留，可用不指定人物口型的画外群体声音等明确制作方式，但不能借此新增多人说话或删台词。必要信息能用旁白表达时可明确旁白，不能把未证猜测讲成事实。
普通景别、光线和不改剧情的舞台安排可作本次制作决定，不能因此新增人物关系、事件结果或重要道具。推测保持推测。
交付稿不能包含需要人工选择的“待核/待确认/需要确认/制作时再定”；应改成确定可执行且不虚构事实的制作决定，或明确自动失败。删掉待办标题但保留错误不算解决。'''
POLICY += '''\n中性处理不是替作者裁定冲突事实。原文星期等互相矛盾时，不自行选一个星期或改台词内容；优先使用傍晚/翌日等相对时段，去掉本段非必要的确定日期。候选本已采用相对时段且忠实保留目标章对白，不要把原文矛盾当作必须改写剧情的理由。关键矛盾确实无法中性呈现时blocked。'''
WRITE = base.COMMON + '\n' + POLICY + '''
把完整target章节按顺序转为完整视频剧本，context_only/evidence_only只作前情依据。一次组织背景、场景、对白、动作、神情、反应，不拆为声音和画面两个自由创作任务。
结构为必要背景、连续场景正文、已落实的制作决定。每场交代时间地点人物与入场状态，正文对白动作交织。必要不可见信息用明确旁白或自然第一人称心声；不把全部心理都强配音。
保留原文人物关系、事件主体、台词含义、猜测与事实边界、必要事件和因果。普通表演可以设计，不凭空增加背景关系或结果。
未知署名不猜具体人物，明确采用中性画外声音且不做指定人物口型；保留原台词，不改成多人齐说。结尾不列未决事项，不要求人工补全。不固定总秒数。只返回text完整剧本。'''
REVIEW = base.REVIEW + '\n' + POLICY + '''
本次必须同时检查背景、正文和结尾说明。contract_findings是程序检测到的交付合同问题，请逐项判断并对确需处理的内容列出issues，避免把整份待核清单忽略。
scopes涵盖同一错误在背景/场头/正文/附注的全部相关位置。表达通道要可执行：旁白可以第三人称；标为角色心声的叙述应自然，不让配音员猜人物是在自称还是讲别人。'''
VERIFY_PROMPT = base.COMMON + '\n' + POLICY + '''
逐条核验review.issues，恰好返回每个id一次，独立核对严重度并选择处理动作：
repair_source：按明确原文修复，提供实际支持的source_ids。
repair_neutral：证据不足，恢复开放事实且给出明确可执行的中性表达；不猜答案、不删必要信息。
keep：仅限rejected意见或真正可选的style。supported的facts/continuity/scope以及production/blocking不可keep。
blocked：关键问题无法在不改变剧情的前提下解决，自动停止该任务。不可写“需要人工确认”当成功。
即使意见severity为production，核验成立仍需repair_source/repair_neutral。未决unresolved也只能repair_neutral或blocked，不能keep。
每条决策的scopes重新定位当前candidate中的全部关联修改处，quote逐字唯一，允许多个不连续范围；不得抄错标点。keep/blocked可为空。只给修改边界，不代写替换稿。relevant_history是同一候选链的有据记录，不能把旧意见当原文。
不要强改合理普通美术，也不要为了消除待办而补造小说事实。'''
VERIFY_PROMPT += '\n返回的decisions是以output_schema中预定问题ID为键的对象；不得重新编号或在值内再输出id。每个键直接填写该问题的决策字段。'
REPAIR_PROMPT = base.REPAIR_PROMPT + '\n' + POLICY + '''
slots中的issue_ids可以包含多个已核实问题，按全部边界一致处理。repair_source遵循原文，repair_neutral用明确中性制作方式解决。
只修确认的问题和对应附注；禁止引入新事实。已有未署名台词保留其原句和事件含义，中性声道不代表把它改为所有人齐说。'''
CHECK_PROMPT = base.CHECK_PROMPT + '\n' + POLICY + '''
检查的是已核实问题是否实际闭合，而不是severity有没有降低。修复后仍需人决定、附注转移待办、删台词规避问题均应unresolved。
所有新问题，包括production，进入regressions；原问题仍未解决时用同一id及当前有效范围记录。'''


def contract_findings(text):
    """A conservative textual guard, not semantic proof of completeness."""
    rows=[];lines=text.splitlines()
    for number,line in enumerate(text.splitlines(),1):
        clean=re.sub(r'[*#\s]','',line)
        if not clean:continue
        heading=r'(?:[一二三四五六七八九十\d]+[、.．])?(?:待核事项|待确认事项|待定事项)'
        if re.fullmatch(heading+r'[：:]?(?:无|没有)[。.]?',clean):continue
        if re.fullmatch(heading+r'[：:]?',clean):
            following=next((x.strip() for x in lines[number:] if x.strip()),'')
            if following in ('无','无。','没有','没有。'):continue
            rows.append(dict(line=number,text=line));continue
        # Ordinary in-story dialogue such as "我需要确认货款" is not a handoff.
        meta=bool(re.match(r'^\s*(?:\d+[.、．]|[-*]\s)',line)) or bool(re.search(r'【[^】]*(?:待核|待确认)|说话人待核|未明确的.*声音',line))
        if meta and re.search(r'待核|待确认|待定|需确认|需要确认|制作时.*(?:确定|确认)|未明确的.*声音',clean):
            rows.append(dict(line=number,text=line))
    return rows


def grams(text):
    result=set()
    for word in re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+',text):
        for width in (2,3,4):
            result.update(word[i:i+width] for i in range(len(word)-width+1))
    return result


def verification_schema(report):
    fields={k:deepcopy(v) for k,v in DECISION['properties'].items() if k!='id'}
    return c.obj(decisions=c.obj(**{x['id']:c.obj(**deepcopy(fields)) for x in report['issues']}),summary=c.TEXT)


def decode_verification(report,value):
    faults=c.schema_issues(value,verification_schema(report),'verification_by_id')
    if faults:raise c.ContractError(faults)
    return dict(decisions=[dict(id=x['id'],**value['decisions'][x['id']]) for x in report['issues']],summary=value['summary'])


def repair_unique_misplaced_scopes(report,value):
    """Recover only one missing scopes + one extra scopes/item, with no content edits."""
    fixed=deepcopy(value);rows=fixed.get('decisions',{});expected={x['id'] for x in report['issues']}
    # Complete decision objects occasionally spill out to the root. The expected
    # IDs identify their only owner; never merge duplicates or infer missing data.
    if isinstance(rows,dict):
        missing=expected-set(rows);extra=set(fixed)-{'decisions','summary'}
        if missing and extra==missing and not (set(rows)-expected):
            for key in missing:rows[key]=fixed.pop(key)
            empty_keep=[key for key in expected if isinstance(rows[key],dict) and 'scopes' not in rows[key]]
            if empty_keep and all(rows[key].get('action')=='keep' for key in empty_keep):
                for key in empty_keep:rows[key]['scopes']=[]
            else:empty_keep=[]
            decode_verification(report,fixed)
            return fixed,dict(method='exact_missing_decision_ids_at_root'+('_and_empty_keep_scopes' if empty_keep else ''),owners=sorted(missing),
                empty_keep_scopes=sorted(empty_keep),before_digest=c.digest(value),after_digest=c.digest(fixed),values_unchanged=True,no_edit_authority_added=True)
    # Provider sometimes nests the missing scopes wrapper inside source_ids.
    # Move only a uniquely identifiable item wrapper; keep all IDs and values.
    if set(rows)==expected:
        missing=[key for key in expected if isinstance(rows[key],dict) and 'scopes' not in rows[key]]
        if missing and all(rows[key].get('action')=='keep' for key in missing):
            for key in missing:rows[key]['scopes']=[]
            decode_verification(report,fixed)
            return fixed,dict(method='empty_scopes_for_keep_only',owners=sorted(missing),
                before_digest=c.digest(value),after_digest=c.digest(fixed),decisions_unchanged=True,no_edit_authority_added=True)
        if len(missing)==1:
            key=missing[0];ids=rows[key].get('source_ids',[])
            extras=[(i,x) for i,x in enumerate(ids) if not isinstance(x,str)]
            if len(extras)==1 and isinstance(extras[0][1],dict) and set(extras[0][1])=={'item'} and isinstance(extras[0][1]['item'],list):
                i,extra=extras[0];rows[key]['scopes']=ids.pop(i)['item']
                decode_verification(report,fixed)
                return fixed,dict(method='unique_scopes_wrapper_in_source_ids',owner=key,before_digest=c.digest(value),after_digest=c.digest(fixed),values_unchanged=True)
    if set(rows)-expected!={'scopes'} or expected-set(rows):raise ValueError('not_unique_scopes_displacement')
    missing=[key for key in expected if isinstance(rows[key],dict) and 'scopes' not in rows[key]]
    extra=rows['scopes']
    if len(missing)!=1 or not isinstance(extra,dict) or set(extra)!={'item'} or not isinstance(extra['item'],list):
        raise ValueError('not_unique_scopes_displacement')
    rows[missing[0]]['scopes']=rows.pop('scopes')['item']
    decode_verification(report,fixed)  # Reject any other missing/extra/invalid field.
    return fixed,dict(method='unique_missing_scopes_extra_scopes_item',owner=missing[0],
        before_digest=c.digest(value),after_digest=c.digest(fixed),values_unchanged=True)


def retrieve(source, packet, issues, per_issue=3, max_new_paragraphs=36):
    """Bounded lexical lookup with exact original paragraphs and adjacent context.

    No model-authored facts, no future chapters, no claim that no hit means absent.
    """
    result=deepcopy(packet)
    horizon=max(ch['chapter'] for ch in packet['chapters'] if ch['role']=='target')
    # Preserve short missing bridges between explicitly selected complete chapters.
    # These are full original chapters, not model summaries; larger gaps stay bounded.
    present={ch['chapter'] for ch in packet['chapters'] if ch['role']!='evidence_only'}
    gaps=[ch for ch in source['chapters'] if min(present)<ch['index']<horizon and ch['index'] not in present]
    gap_added=[]
    if len(gaps)<=2 and sum(len(ch['text']) for ch in gaps)<=10000:
        for ch in gaps:
            result['chapters']=[x for x in result['chapters'] if x['chapter']!=ch['index']]
            result['chapters'].append(dict(chapter=ch['index'],role='context_only',text_sha256=c.digest(ch['text']),
                paragraphs=[dict(id=f"CH{ch['index']}-P{i:03}",text=s) for i,s in enumerate(ch['text'].split('\n\n'),1)]))
            gap_added.append(ch['index'])
    existing={p['id'] for ch in result['chapters'] for p in ch['paragraphs']}
    catalog=[];by_ch={}
    for ch in source['chapters']:
        if ch['index']>horizon:continue
        rows=[dict(id=f"CH{ch['index']}-P{i:03}",text=text) for i,text in enumerate(ch['text'].split('\n\n'),1)]
        by_ch[ch['index']]=rows
        for i,row in enumerate(rows):catalog.append((ch['index'],i,row,grams(row['text'])))
    freq=Counter(g for *_,gs in catalog for g in gs)
    selected={};log=[]
    for issue in issues:
        anchors=grams(issue['subject'])
        query=anchors|grams(issue['claim'])
        scored=[]
        for ch,index,row,gs in catalog:
            if row['id'] in existing:continue
            overlap=query&gs
            if not overlap:continue
            # The subject names the disputed object. A long claim often contains
            # generic phrases (children, candidate, source) which must not drown it.
            score=sum(math.log(1+len(catalog)/(1+freq[g]))*(len(g)-1)*(6 if g in anchors else 1) for g in overlap)
            scored.append((score,ch,index,row))
        hits=[]
        for score,ch,index,row in sorted(scored,key=lambda v:(-v[0],v[1],v[2]))[:per_issue]:
            hits.append(dict(id=row['id'],score=round(score,4)))
            for near in range(max(0,index-2),min(len(by_ch[ch]),index+3)):
                p=by_ch[ch][near]
                if p['id'] not in existing and len(selected)<max_new_paragraphs:selected[p['id']]=(ch,near,p)
        log.append(dict(issue_id=issue['id'],hits=hits))
    for ch in sorted({x[0] for x in selected.values()}):
        paras=[p for chapter,_,p in sorted(selected.values(),key=lambda x:(x[0],x[1])) if chapter==ch]
        previous=next((x for x in result['chapters'] if x['chapter']==ch and x['role']=='evidence_only'),None)
        if previous:
            previous['paragraphs']+=paras
            previous['paragraphs'].sort(key=lambda p:p['id'])
        else:result['chapters'].append(dict(chapter=ch,role='evidence_only',paragraphs=paras))
    return result,dict(method='short_complete_chapter_gap_then_subject_weighted_lexical_adjacent',horizon=horizon,
        full_context_gaps_added=gap_added,gap_limit=dict(chapters=2,characters=10000),
        exact_source=True,no_hit_is_not_absence=True,added_ids=list(selected),queries=log,
        before_digest=c.digest(packet),after_digest=c.digest(result))


def adjudicate(source,candidate,report,verification,allow_minor=False):
    binding=base.validate_report(source,candidate,report)
    faults=c.schema_issues(verification,VERIFY,'verify_v3')
    if faults:raise c.ContractError(faults)
    lookup={x['id']:x for x in verification['decisions']}
    if len(lookup)!=len(verification['decisions']) or set(lookup)!={x['id'] for x in report['issues']}:
        raise ValueError('decision_coverage')
    valid={p['id'] for ch in source['chapters'] for p in ch['paragraphs']}
    rows=[];accepted=[];blocked=[]
    for issue in report['issues']:
        d=lookup[issue['id']];action=d['action'];decision=d['decision']
        if any(ref not in valid for ref in d['source_ids']):raise ValueError('invalid_decision_source')
        if decision=='rejected' and action!='keep':raise ValueError('rejected_issue_cannot_repair')
        if decision=='unresolved' and action not in ('repair_neutral','blocked'):raise ValueError('unresolved_cannot_pass')
        if action=='keep' and decision!='rejected':
            eligible=(issue['severity']!='blocking' and issue['kind'] in ('expression','continuity')) if allow_minor else (issue['severity']=='style' and issue['kind']=='expression')
            if d['severity']!='style' or not eligible:
                raise ValueError('confirmed_issue_cannot_be_downgraded_to_keep')
        if action=='repair_source' and (decision!='supported' or not d['source_ids']):raise ValueError('source_repair_requires_evidence')
        row={**deepcopy(issue),'decision':decision,'verified_severity':d['severity'],
             'action':action,'decision_reason':d['reason'],'resolution_source_ids':d['source_ids'],
             'scopes':deepcopy(d['scopes']),**binding}
        if action.startswith('repair_'):
            if not d['scopes']:raise ValueError('repair_range_not_unique')
            row['requested_scopes']=deepcopy(d['scopes'])
            row['scopes']=[{**s,'quote':resolve_typographic_span(candidate,s['quote'])} for s in d['scopes']]
            accepted.append(row)
        elif action=='blocked':blocked.append(row)
        rows.append(row)
    return dict(binding=binding,rows=rows,accepted=accepted,blocked=blocked)


def resolve_typographic_span(candidate,quote):
    """Unique exact text after *only* whitespace/comma-semicolon normalization.

    Never fuzzy word matching, guessing an address, or rewriting native text.
    Digits, decimal points, negations, quote order and all other symbols remain.
    """
    if not quote:raise ValueError('repair_range_not_unique')
    if candidate.count(quote)==1:return quote
    def normalized(text):
        chars=[];positions=[]
        for i,char in enumerate(text):
            if char.isspace():continue
            chars.append('，' if char in ',，;；' else char);positions.append(i)
        return ''.join(chars),positions
    target,_=normalized(quote);hay,positions=normalized(candidate)
    if len(target)<12 or hay.count(target)!=1:
        # A numbered metadata item has a stable structural address: its entire
        # label before the colon. Only match inside the final production appendix.
        label=quote.split('：',1)[0] if '：' in quote else ''
        if re.match(r'^\d+[.、．]\s*',label) and len(label)>=12:
            tail=re.split(r'(?m)^(?:三、|###?\s*)(?:待核事项|制作口径|制作决定)',candidate)
            if len(tail)==2:
                matches=[line for line in tail[-1].splitlines() if line.startswith(label+'：')]
                if len(matches)==1 and candidate.count(matches[0])==1:return matches[0]
        raise ValueError('repair_range_not_unique')
    start=hay.index(target);raw=candidate[positions[start]:positions[start+len(target)-1]+1]
    if candidate.count(raw)!=1:raise ValueError('repair_range_not_unique')
    return raw


def patch_plan(candidate,adjudication):
    if c.digest(candidate)!=adjudication['binding']['candidate_digest']:raise ValueError('stale_adjudication')
    ranges=[]
    for issue in adjudication['accepted']:
        for s in issue['scopes']:
            if candidate.count(s['quote'])!=1:raise ValueError('repair_range_not_unique')
            start=candidate.index(s['quote'])
            ranges.append(dict(start=start,end=start+len(s['quote']),owners=[issue['id']],
                reasons=[issue['claim']+'；处理：'+issue['action']+'；'+issue['decision_reason']+'；边界：'+s['boundary']]))
    merged=[]
    for r in sorted(ranges,key=lambda x:(x['start'],x['end'])):
        if merged and r['start']<merged[-1]['end']:
            old=merged[-1];old['end']=max(old['end'],r['end'])
            old['owners']=list(dict.fromkeys(old['owners']+r['owners']));old['reasons']+=r['reasons']
        else:merged.append(r)
    if not merged:raise ValueError('no_required_patch')
    plan=prose_patch.prepare(candidate,[dict(quote=candidate[x['start']:x['end']],reason='\n'.join(x['reasons'])) for x in merged])
    for slot,row in zip(plan['slots'],merged):slot['issue_ids']=row['owners']
    return plan


def completion_gate(candidate,registry,independent_review):
    failures=[]
    if not independent_review:failures.append('independent_review_required')
    if contract_findings(candidate):failures.append('unresolved_handoff_language')
    if any(x['status'] not in ('resolved','rejected','kept_style') for x in registry):failures.append('open_issue_ledger')
    return dict(passed=not failures,failures=failures,candidate_digest=c.digest(candidate),
                requires_human_confirmation=False,semantic_guarantee=False)
