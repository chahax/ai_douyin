"""Explicit trial-only specification, without changing the default prompts."""
from pathlib import Path
from copy import deepcopy
from . import contracts as c

PATH = Path('docs/VIDEO_SCRIPT_RULES_20261101.md')
PROFILE = 'video_script_rules_20261101'

POLICY = '''本轮按实际影响验收。人物身份关系、重要事件主体/署名、关键剧情信息、实际位置、因果结果必须正确。
不改变上述内容且不妨碍理解与制作的微动作衔接、普通措辞、景别偏好、布景细节或冗余说明，可记录为style保留，不因为小问题反复返修。
production不是人工待确认出口；真正需要修的制作问题自动修。未知不能猜事实，中性画外声不等于全体合说。原文优先于模型分析。
普通光线、微表情和合理布景可设计，不反写为小说背景。交付稿不留人工待核清单。相对时段可用于避免原文日期歧义，不改变剧情。'''

def config():
    text = PATH.read_text(encoding='utf-8').split('## 目标和结构',1)[1].split('## 实现与测试记录',1)[0]
    text = '## 目标和结构'+text
    return dict(profile=PROFILE, text=text, digest=c.digest(text))

def validate(value):
    if value and (value.get('profile')!=PROFILE or c.digest(value['text'])!=value['digest']):
        raise ValueError('specification_changed')

def prompt(name, original, spec):
    if not spec:return original
    validate(spec)
    from . import autonomous_revision_v3 as n
    result=original.replace(n.POLICY,POLICY)
    result=result.replace('keep：仅限rejected意见或真正可选的style。supported的facts/continuity/scope以及production/blocking不可keep。',
        'keep：错误审核意见或核验为style的轻微expression/continuity可保留。原production经核对确实只影响微小表达可改判style，理由说明为何不改变人物、剧情和可执行性。原blocking、facts/scope、实际位置/行动主体/因果变化不得用keep放行。')
    result=result.replace('即使意见severity为production，核验成立仍需repair_source/repair_neutral。',
        '核验后仍为production的必要制作问题需repair_source/repair_neutral。')
    result=result.replace('所有新问题，包括production，进入regressions；',
        '确需修复的问题进入regressions；不影响理解和制作的小问题可省略或标style；')
    # The specification is frozen into the task, not reread from a changing document.
    if name=='check':result+='\nresults只返回confirmed_issues列出的ID各一次；relevant_history中已keep/rejected的意见不再次报告resolved。'
    return result+'\n本轮统一剧本规范（创作与审核采用同一边界）：\n'+spec['text']

def check_schema(issues, original):
    result=deepcopy(original);ids=[x['id'] for x in issues]
    rows=result['properties']['results'];rows['minItems']=rows['maxItems']=len(ids)
    rows['items']['properties']['id']=c.choices(ids)
    return result

def normalize_check(check, adjudication):
    """Ignore only surplus results for explicitly kept issues from this same cycle."""
    expected={x['id'] for x in adjudication['accepted']}
    ids=[x['id'] for x in check['results']]
    kept={x['id'] for x in adjudication['rows'] if x['action']=='keep'}
    if len(ids)!=len(set(ids)) or not expected.issubset(ids) or set(ids)-expected-kept:
        raise ValueError('check_coverage')
    if any(x['result']!='resolved' for x in check['results'] if x['id'] not in expected):
        raise ValueError('kept_issue_reported_unresolved')
    fixed=deepcopy(check);fixed['results']=[x for x in fixed['results'] if x['id'] in expected]
    return fixed,dict(ignored_kept_ids=sorted(set(ids)-expected),raw_digest=c.digest(check),normalized_digest=c.digest(fixed))
