"""Immutable quoted context and a small audiovisual line protocol."""
import re
from .contracts import digest

PROMPT = '''将完整target原文依原顺序转写为可拍摄和配音的剧本。context_only仅用于理解。
背景由程序原文摘录提供，你只输出场景正文。按自然时间地点变化组织场次，同地点连续行动合并。
逐行使用以下格式（不使用Markdown标题、列表、表格或说明段）：
场次：编号与场景名称
时间：本场时间
地点：本场地点
人物：本场实际在场的人
画面：可见行动和自然表情；原文明示的人物去向和重要道具归属保持不变
对白[姓名]：原文已有出声对白，可保留原句；说话人有明确上下文依据才署名
对白[待核]：原文未署名且不能确定的原句
旁白：必要背景、心理、推测或解释，保持原文第三人称与不确定语气
原段：本场对应原段号或同章范围，例如CH2-P001—CH2-P008
待核：有疑义的来源原句与问题（仅制作说明，不作表演内容）
一个场次可有多行画面、对白、旁白。未确定的说话人只用待核，不加哥哥、某人等推断身份。
心理叙述统一交由旁白，保留意思；不再生成心声音轨，也不将心理变成出声对白。
目标章首尾、关键行动、条件否定、人物称谓含义和心理因果需完整表现。
表情、景别和普通光线可放画面栏；剧情事实以原文为准。人物排行年龄不要求补齐。
原文只说回忆时，用旁白表达回忆，不编具体回忆画面。未发生的计划不画成已完成。
背景条目、人物传记、行程总结和全局演出方案由其他部分负责，本阶段不生成。
输出只含以上行；完整转写所有target章节，不限制时长，不提前按15秒拆段。只返回text。'''

REVIEW = '''依据完整原文审查候选全文。程序背景是原文引用，不是新的人物事实表。
核对首尾覆盖、事件顺序因果、称谓关系、对白归属和重要道具/人物去向。
心理用第三人称旁白是合法表达，不要求改心声；普通微动作和转场省略可接受。
每条问题给候选引句和正确原段号/原句；不要借用候选新增的背景来证明候选。
待核不等于原著笔误，不把哥哥姐姐不同称谓当作矛盾，需看各自说话人与对象。
区分剧情错误、语义未决、制作标注和风格建议。未决说话人仍不能直接生产。
检查画面栏是否把源文心理当可见行为、计划当结果，或者缺少必要的心理因果旁白。
程序检查只能发现格式问题，不能替代你的语义核查。输出完整审查text，不改写候选。'''

PROMPT_V2 = '''将完整target原文按顺序转成可拍摄配音剧本。背景由程序引用，context_only仅理解。
只输出下列类型的行，无Markdown/列表；每场必有场次、时间、地点、人物、原段。
场次：编号与场景名
时间：原文可支持的时段
地点：原文地点（不为不明场所添加附近/楼下/商场内等地理关系）
人物：本场实际在场的人或原文明示群体；这是在场表，不是镜头焦点名单
画面[〈原文段号〉]：源于该段的可见行动及自然微动作
旁白[〈原文段号〉]：该段的心理、动机或必要解释，保留原文语气、人称和条件
对白[姓名|〈台词原段号〉|〈说话人证据段号〉]：原文出声台词
对白[待核|〈台词原段号〉|-]：不能确定说话人的原文出声台词
系统[〈原文段号〉]：原有系统提示字幕和提示音
原段：本场涉及原段范围
待核：原句歧义与待核原因，不填猜测角色
对白第二项是台词所在段号，第三项是明确支持说话人的证据段号（同章距离不超过3段，原句需出现该姓名/群体）。证据仅提到角色但不是其说话不能使用。无可靠局部证据用待核；不用猜测把格子填满。
台词使用对应原段中的连续原句，保留原义；间接引语只在主体明确时使用原文中的连续语句。群体发言可以用原文明示群体名。
逐条音画锚点按原段顺序，不把后面的换装、疑问、回应提前或后移；同段可拆多行。音画承载内容较长时拆成多条，不跨过中间事件。
完整性以连续事件及其含义为单位，不以排版段落数量为单位。保留目标章关键行动、心理因果、条件否定和回应；相邻段可以合并表达，不能用原段范围伪装内容已经表现。
纯标点或列举中的省略号不要求单独生成音画，按前后文理解它省略的内容；标点本身不能证明角色停顿、忘词、犹豫或语塞。原文明写这些状态时仍须保留；不能把所有省略号都当列举省略或一概删除。
故事需要的心理因果用旁白，不只留表情。
不另写身份背景/人物传记/全局演出设计；不生成心声；不把人物想法改成对白或既成行为。
同时间地点连续行动尽量同场。普通灯光与微动作可在画面栏，不新增人物去向、物品归属、关系或事件结果。
输出完整所有target，不限制时长。只返回text字段。'''

def prompt(version, packet=None):
    if version!=2:return PROMPT
    text=PROMPT_V2+'\n尖括号内容是字段说明，不是段号。所有段号必须原样取自输入paragraphs.id；原段号不是镜头流水号，不得重新编号。'
    if packet is not None:
        known=paragraphs(packet)
        # Prevent invented concrete ID examples from leaking into a production prompt.
        if set(re.findall(r'CH\d+-P\d+',text))-set(known):raise ValueError('prompt_example_id_outside_source')
        ids=[p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']]
        text+='\n本次允许的目标原段号：'+','.join(ids)
    return text

def review_prompt(version):
    return REVIEW + ('\n另有程序从原文构建的逐条归属证据表；引用包含姓名不等于证明该人说话，逐条核对。原段顺序只证明编号顺序，不证明语义。系统字幕/音效是合法视听表达。完整性核对连续事件与含义，不要求每个排版段各有镜头。纯标点需结合上下文；不能单凭省略号要求角色停顿/犹豫，也不能忽略原文明写的停顿。' if version==2 else '')

def coverage_guidance(packet):
    """Flag layout-only ellipses without deciding their narrative meaning."""
    result=[]
    for chapter in packet['chapters']:
        if chapter['role']!='target':continue
        ps=chapter['paragraphs']
        for i,p in enumerate(ps):
            if not re.fullmatch(r'[.\u2026\s]+',p['text']) or not p['text'].strip():continue
            result.append({'id':p['id'],'kind':'bare_ellipsis','not_action_evidence_alone':True,
                           'context':ps[max(0,i-3):i+3]})
    return {'unit':'continuous_events_and_meaning','source_preserved':True,'ellipsis_contexts':result,
            'warning':'只是排版提示，不自动判断停顿或列举，不删除原段，不自动豁免语义覆盖。'}

def location_prompt(packet):
    text=prompt(2,packet)
    old='地点：原文地点（不为不明场所添加附近/楼下/商场内等地理关系）'
    new='地点：〈证据原段号〉|〈原文连续地点词〉；确实转场可按顺序列多个条目，用中文分号分隔；无法确认写“地点：待核”'
    if old not in text:raise ValueError('location_prompt_contract_changed')
    return text.replace(old,new)+'\n地点只选择属于本场的原文连续地点词，保留其原字，不拼接别处的地名来补层级、附近或归属。相同地点可继续引用前面明确建立地点的原段。原句中的否定/回忆/计划不证明当前身处该地。场名和画面也遵守同样空间边界；未明示的地理关系留空，内景灯光及普通微动作仍可设计。'

def location_review_prompt():
    return review_prompt(2)+'\n专项逐场核对location_diagnostics的原文证据：词语存在不代表当前场景地点正确。检查否定、回忆、未来计划、转场及地点继承；不要把此前的上级地点延伸给后面新出现的场所。地点字段、场名、画面中的空间关系均核对。原文只给笼统地点时不要求擅自补具体地址。'

def location_diagnostics(text, packet):
    """Validate provenance, not whether the cited place is the current scene."""
    source=paragraphs(packet);issues=[];unresolved=[];evidence=[]
    scene=None;location_count=0
    def finish_scene():
        if scene is not None and location_count!=1:
            issues.append({'scene':scene,'code':'location_field_count','count':location_count})
    for n,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if line.startswith('场次：'):
            finish_scene();scene=line[3:];location_count=0
        if not line.startswith('地点：'):continue
        location_count+=1;value=line[3:].strip()
        if scene is None:issues.append({'line':n,'code':'location_outside_scene'})
        if value=='待核':unresolved.append({'scene':scene,'line':n});continue
        for item in value.split('；'):
            m=re.fullmatch(r'(CH\d+-P\d+)\|([^|]+)',item.strip())
            if not m:issues.append({'line':n,'code':'location_reference_required'});continue
            sid,label=m.groups();label=label.strip()
            if sid not in source:issues.append({'line':n,'code':'location_unknown_source','id':sid});continue
            if not label or label not in source[sid]:
                issues.append({'line':n,'code':'location_not_verbatim_source_span','id':sid,'label':label})
            evidence.append({'scene':scene,'line':n,'source_id':sid,'label':label,'original':source[sid]})
    finish_scene()
    if scene is None:issues.append({'code':'missing_scenes'})
    return {'candidate_sha256':digest(text),'issues':issues,'unresolved':unresolved,
            'references_valid':not issues,'ready_for_semantic_review':not issues and not unresolved,
            'semantic_acceptance':False,'evidence':evidence}

def anchored_diagnostics(text, packet):
    source=paragraphs(packet);targets=[p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']]
    order={sid:i for i,sid in enumerate(targets)};issues=[];evidence=[];last=-1;fields=set();has_scene=False
    required={'时间','地点','人物','原段'}
    for n,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line:continue
        if line.startswith('场次：'):
            if has_scene and required-fields:issues.append({'line':n,'code':'missing_scene_fields','fields':sorted(required-fields)})
            has_scene=True;fields=set();continue
        if any(line.startswith(x+'：') for x in required):fields.add(line.split('：')[0]);continue
        if line.startswith('待核：'):continue
        m=re.fullmatch(r'(画面|旁白|对白|系统)\[([^\]]+)\]：(.+)',line)
        if not m:issues.append({'line':n,'code':'invalid_typed_line'});continue
        kind,keys,body=m.groups();parts=keys.split('|')
        sid=parts[1] if kind=='对白' and len(parts)==3 else keys
        if sid not in order:issues.append({'line':n,'code':'not_target_anchor','id':sid});continue
        if order[sid]<last:issues.append({'line':n,'code':'source_order_reversal','id':sid})
        last=max(last,order[sid])
        if kind!='对白':continue
        if len(parts)!=3:issues.append({'line':n,'code':'dialogue_keys_required'});continue
        who,_,ref=parts;quote=body.strip('“”"')
        # Terminal speech punctuation can differ when indirect speech is voiced.
        core=quote.rstrip('。！？?!')
        if not core or core not in source[sid]:issues.append({'line':n,'code':'dialogue_not_source_substring','id':sid})
        if who=='待核':
            if ref!='-':issues.append({'line':n,'code':'unknown_must_not_have_assignment'})
        else:
            if '待核' in who:issues.append({'line':n,'code':'unknown_identity_must_remain_empty'})
            ok=ref in source and ref.split('-')[0]==sid.split('-')[0]
            if ok:ok=abs(int(ref.split('-P')[1])-int(sid.split('-P')[1]))<=3 and who in source[ref]
            if not ok:issues.append({'line':n,'code':'speaker_evidence_not_local_or_missing','id':sid})
        position=order[sid];near=targets[max(0,position-3):position+4]
        evidence.append({'line':n,'speaker':who,'quote':quote,'source_id':sid,'claimed_evidence_id':ref,
                         'original_context':[{'id':i,'text':source[i]} for i in near]})
    if not has_scene:issues.append({'code':'missing_scenes'})
    elif required-fields:issues.append({'code':'missing_scene_fields','fields':sorted(required-fields)})
    return {'issues':issues,'format_passed':not issues,'semantic_acceptance':False,'candidate_sha256':digest(text),'attribution_evidence':evidence}

def paragraphs(packet):
    return {p['id']:p['text'] for ch in packet['chapters'] for p in ch['paragraphs']}

def background(packet):
    # This is a lexical source excerpt index, never a model-written synopsis.
    cues=('爸爸','父亲','原主','上一世','穿过来','城中村','广场','周六')
    selected=[]
    for ch in packet['chapters']:
        for p in ch['paragraphs']:
            if any(cue in p['text'] for cue in cues):
                selected.append({'id':p['id'],'text':p['text'],'role':ch['role']})
    return {'kind':'quoted_context_not_verified_world_model','source_sha256':packet['source_sha256'],'excerpts':selected}

def render_background(value):
    return '# 背景原文摘录（制作参考，不直接配音；人物陈述仍是人物陈述）\n\n'+ '\n\n'.join(
        f"[{p['id']} / {p['role']}]\n> "+p['text'].replace('\n','\n> ') for p in value['excerpts'])

def validate(text, packet):
    issues=[];known=paragraphs(packet);seen_scene=False
    allowed=('场次：','时间：','地点：','人物：','画面：','旁白：','原段：','待核：')
    for n,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line:continue
        if line.startswith('场次：'):seen_scene=True
        elif line.startswith('对白['):
            match=re.fullmatch(r'对白\[([^\]]+)\]：(.+)',line)
            if not match:issues.append({'line':n,'code':'invalid_dialogue_line'})
            elif '待核' in match[1] and match[1]!='待核':issues.append({'line':n,'code':'unknown_identity_must_remain_empty'})
        elif not line.startswith(allowed):issues.append({'line':n,'code':'untyped_or_forbidden_content'})
        if line.startswith('原段：'):
            ids=re.findall(r'CH\d+-P\d+',line)
            if not ids:issues.append({'line':n,'code':'missing_source_ids'})
            for sid in ids:
                if sid not in known:issues.append({'line':n,'code':'unknown_source_id','id':sid})
    if not seen_scene:issues.append({'code':'missing_scenes'})
    return {'issues':issues,'format_passed':not issues,'semantic_acceptance':False,'candidate_sha256':digest(text)}
