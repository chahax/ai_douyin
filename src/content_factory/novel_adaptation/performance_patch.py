"""Keep repair-process language out of newly patched performance fields.

This narrow lexical check is not a semantic or continuity review. It reports
evidence and never strips or rewrites supplier output.
"""
import re
from .narrative_patch import value_at

RULE = ('action、expression、camera、visual_additions 是成片表演内容。'
        'replacement只写演员可表演、摄影可拍摄的正向内容；'
        '修复原因、禁止生成项、验收结论和对程序的指令留在审核记录，'
        '不放入replacement，也不作为括号备注。对白中的否定和人物真实拒绝保留。')

PATTERN = re.compile(r'本段只生成|(?:不要|禁止|不)生成|不新(?:添|增|加)[^。；\n）)]{0,32}动作|'
                     r'按(?:本次)?(?:审核|返修)(?:要求|意见)|未授权字段|approved_paths|'
                     r'返修(?:指令|说明|要求)|已通过(?:终审|验收)')


def inspect(candidate, paths):
    findings=[]
    expanded=set(paths)
    for si,scene in enumerate(candidate.get('scenes',[])):
        for bi,segment in enumerate(scene.get('segments',[])):
            for field in ('action','expression','camera','visual_additions'):
                target=f'/scenes/{si}/segments/{bi}/{field}'
                if field in segment and any(target.startswith(p+'/') for p in paths):expanded.add(target)
    for path in sorted(expanded):
        tokens=path.split('/')
        if len(tokens)<6 or tokens[1]!='scenes' or tokens[3]!='segments':continue
        if tokens[5] not in ('action','expression','camera','visual_additions'):continue
        value=value_at(candidate,path)
        texts=value if isinstance(value,list) else [value]
        for index,text in enumerate(texts):
            if not isinstance(text,str):continue
            for match in PATTERN.finditer(text):
                findings.append({'path':path+(f'/{index}' if isinstance(value,list) else ''),
                    'code':'repair_process_language_in_performance','matched_text':match.group(),
                    'offset':match.start()})
    return {'issues':findings,'semantic_acceptance':False,
            'scope':'Selected performance fields only; no automatic text modification.'}
