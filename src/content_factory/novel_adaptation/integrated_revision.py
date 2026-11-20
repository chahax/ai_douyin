"""Evidence-bound local revision, with explicit semantic adjudication."""
from . import contracts as c, prose_patch

ISSUE = c.obj(category={'type':'string','enum':['facts','continuity','expression','scope','style']},
              severity={'type':'string','enum':['must_fix','optional','unresolved']},
              quote=c.TEXT, source_ids={'type':'array','items':c.TEXT}, reason=c.TEXT, repair_constraint=c.TEXT)
REVIEW_SCHEMA = c.obj(issues={'type':'array','items':ISSUE}, summary=c.TEXT)

REVIEW = '''独立审查source和candidate，不重写剧本。目标是忠实的可拍剧本，不是自由改编；context_only只解释前情，target才是要演出的章节。production_choices只在指定范围成立。
检查三类：事实与目标范围；人物/道具/动作前后状态；观众如何通过声音或画面获得必要信息。背景与正文同样需核对。原文假设不能改成过去发生，未署名不能猜具体姓名，几个不等于所有人；走路顺序不是排行，唯一女孩仍可有弟弟。普通灯光、微动作和合理过渡省略允许，不要求逐字复述。
逐项检查同一行动是否无据重复或换人，场首是否提前摆出后续才引入的道具，未知是否在待核之前已被正文写成确定事实。心理可用心声/旁白，动作已经表达的不要再要求旁白。
只提交output_schema规定的issues与summary。每个issue的quote必须逐字引用candidate中唯一且完整可替换的连续文本，不能用省略号替代中间文字。不同问题的quote不要重叠；同一句有多项问题请合成一个issue。source_ids只使用source实际段号，不编示例编号。reason说明原文如何支持判断，repair_constraint给出保持/删除/恢复的边界，不创作新情节或直接撰写替换稿。
must_fix是真实事实冲突或影响制作的错误；optional是非必要风格建议；unresolved是真实缺证据。不要用待核要求补全无关背景。不要把引用存在当语义成立。不保证无误，不报告虚构的检查次数。'''

REPAIR = '''对当前完整candidate执行已核实问题的局部返修。source是事实依据，production_choices只在明确范围有效。只返回slots中每个edit键的完整替换文本，未选区域由程序原样保留；不返回完整重写稿。
保留正确剧情、台词含义和交织的动作神情。优先删除无据新增，或恢复原文主体、数量、条件、先后顺序；不得编另一件事来消除矛盾。原文未署名继续保持开放，必要声音不能因归属不明被删除。心理用心声或旁白，不改成在场其他人听见的对白；画面足以表达的不重复配音。删除无必要背景时不要补其他未知资料。
每个slots.reason包含问题和修复边界，以原文核对其成立；若边界无法满足，保持原片段，不能自行扩大修改。普通演出设计允许，但不得改核心人物、事件或道具状态。'''

FINAL = '''独立对照完整source与candidate，审核当前整稿能否作为后续视频制作文本依据。只审本次候选，不重写。context_only仅前情，不应大段重演；production_choices仅本次指定范围。
检查必要剧情是否实际演出，背景/正文/待核一致性，人物关系与具体署名、人数、条件/猜测/事实区别，进退场、移动前途中抵达后、道具引入和动作重复，以及心理内容是否以合理心声旁白或画面让观众理解。动作能表达的信息不要再强加旁白。普通光线微动作与路程省略允许。
未知归属不能凭邻近姓名猜；不以走路顺序判断排行，唯一女孩也可有弟弟。原文自身有歧义须保持未决，不将本地缺资料等同全书没有。不要为每个背景未知要求补设定。每个错误必须引用实际候选原句和source实际段号，并说明语义依据；区分阻断错误、未决和风格建议。没有发现不等于保证正确。
返回JSON对象，格式为{"text":"完整审核报告"}。报告包含实际核查范围、问题证据、可执行性及结论；不要返回修订稿。'''


def diagnose(packet, candidate, review):
    errors=c.schema_issues(review, REVIEW_SCHEMA, 'revision_review')
    if errors: raise c.ContractError(errors)
    source_ids={p['id'] for ch in packet['chapters'] for p in ch['paragraphs']}
    rows=[]
    for i,item in enumerate(review['issues']):
        faults=[]
        if not item['quote'] or candidate.count(item['quote'])!=1: faults.append('quote_not_unique')
        if not item['source_ids'] or any(x not in source_ids for x in item['source_ids']): faults.append('source_id_invalid')
        if not item['reason'].strip() or not item['repair_constraint'].strip(): faults.append('empty_reason_or_constraint')
        rows.append({'index':i,'structural_issues':faults,'semantic_accepted':False})
    return {'candidate_digest':c.digest(candidate),'review_digest':c.digest(review),'issues':rows}


def span_plan(candidate, review, diagnostics, decisions):
    if diagnostics['candidate_digest']!=c.digest(candidate) or diagnostics['review_digest']!=c.digest(review):
        raise ValueError('diagnostic_binding_mismatch')
    if decisions.get('candidate_digest')!=c.digest(candidate) or decisions.get('review_digest')!=c.digest(review):
        raise ValueError('decision_binding_mismatch')
    items=decisions['decisions']
    if sorted(x['index'] for x in items)!=list(range(len(review['issues']))): raise ValueError('decisions_incomplete')
    accepted=[];indices=[]
    for row in items:
        if row['decision'] not in ('accept','reject','defer') or not row.get('reason','').strip(): raise ValueError('decision_invalid')
        i=row['index'];issue=review['issues'][i]
        if row['decision']=='accept':
            if diagnostics['issues'][i]['structural_issues']: raise ValueError('invalid_issue_selected')
            if issue['severity']=='unresolved': raise ValueError('cannot_resolve_unknown_by_patch')
            accepted.append({'quote':issue['quote'],'reason':issue['reason']+'\n修复边界：'+issue['repair_constraint']})
            indices.append(i)
    if not accepted: raise ValueError('no_accepted_patches')
    plan=prose_patch.prepare(candidate,accepted)
    plan['accepted_issue_indices']=indices
    plan['adjudication_digest']=c.digest(decisions)
    return plan
