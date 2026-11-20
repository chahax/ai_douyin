"""Screen continuity policy; no book-specific place inference or semantic auto-pass."""
import re
from . import restricted_transcription as r
from .contracts import digest

POLICY = '''过渡动作不必逐个拍摄，可合并或省略，直接切到下一处有剧情信息的画面。
先区分实际发生、拟进行、回忆及猜测，再判断哪些事件必须表现。保留核心对白、关系和因果；不能借过渡省略删掉重要结果。
只核对最终保留画面的连续性：原文已离开某处，后续画面不能明确仍在该处，除非原文有返回依据；不强制补一个出门镜头。
原文未说明新位置时，可以用不强调具体位置的近景；场所层级写到原文支持的程度，不猜附近、楼层、归属，也不把待核位置变成明确地址。
计划不更新实际位置；回忆不改变当前场景；分头行动分别看各自主体，不把一个人的位置套给全体。
相同地点连续行动无需硬拆场；剪辑省略不等于剧情遗漏。判断的是保留画面是否与源文矛盾，而非转场镜头是否齐全。
普通光线、自然表情和微动作可设计；不能把未确定的事件改成事实。'''

def author_prompt(packet):
    return r.prompt(2,packet)+'\n通用画面取舍和承接规则：\n'+POLICY+'\n地点仍为普通文字，可写位置不强调；不需要提交地点词出处串。每条对白必须包含冒号后的完整台词，引用标签不能代替正文。'

def review_prompt():
    return r.review_prompt(2)+'\n通用画面取舍和承接规则：\n'+POLICY+'''\n先单独核对对白是否有正文。语义审查逐项指出原文事实、候选明确呈现、两者是否冲突；不因缺少过渡镜头而判错。
泛称地点和近景未说明位置不能自动解释成进入某处。要判错须指出候选实际写出的矛盾，不替它补画面再批评。未决事实与制作建议分别列出。'''

def dialogue_integrity(text):
    missing=[];count=0
    for n,line in enumerate(text.splitlines(),1):
        if line.strip().startswith('对白['):
            count+=1
            if not re.fullmatch(r'对白\[[^\]]+\]：[\s\S]*\S',line.strip()):missing.append(n)
    return {'candidate_sha256':digest(text),'dialogue_lines':count,'missing_body_lines':missing,
            'body_format_passed':not missing,'semantic_acceptance':False,
            'limit':'检查已输出对白行，不证明所有原文对白已覆盖。'}

def probe_prompt():
    return '''判断每条独立测试中的候选画面是否与其原文冲突。仅依据给定原文与候选，不补剧情。
'''+POLICY+'''\n每条输出一行：输入ID|consistent或contradiction或uncertain|依据。只输出这些行。'''

def score_probe(text,cases):
    decisions={};errors=[]
    for line in text.splitlines():
        if not line.strip():continue
        parts=line.split('|',2)
        if len(parts)!=3 or parts[0] in decisions or parts[1] not in ('consistent','contradiction','uncertain'):
            errors.append(line);continue
        decisions[parts[0]]=parts[1]
    expected={c['id']:c['expected'] for c in cases}
    return {'format_errors':errors,'missing':sorted(set(expected)-set(decisions)),
            'unexpected':sorted(set(decisions)-set(expected)),
            'correct':sum(decisions.get(k)==v for k,v in expected.items()),'total':len(cases),
            'mismatches':[{'id':k,'expected':v,'actual':decisions.get(k)} for k,v in expected.items() if decisions.get(k)!=v],
            'scope':'人工构造的对照材料，仅测通用规则判断，不是其他小说生产验收。'}
