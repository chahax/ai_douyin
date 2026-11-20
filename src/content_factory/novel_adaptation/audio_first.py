"""Separate source sound decisions from picture layout; preserve raw candidates."""
import re
from . import contracts as c, restricted_transcription as r, screen_continuity as sc

AUDIO_PROMPT='''整理完整target章节中剧本需要的声音内容，context_only仅帮助理解。此节点只处理声音，不生成场景或画面。
先判断内容是出声对白dialogue、心理/解释旁白narration、系统提示system，再独立判断对白由谁说。
心理不因主体未知变成待核对白；明确出声但人物不能确定才speaker为空。narration和system的speaker必须为空。
对白人物有明确上下文才署名，群体需原文支持；未知就空，不填哥哥、某人等推测身份，不补原文没有的排行。
每项text取对应source_id原文连续片段，可去掉外围引号；保留表达完整性和原有不确定语气。必要心理因果保留，普通可见动作无需旁白复述。
证据evidence_ids引用支持声音类型/说话人的原段，可跨当前所给上下文，不机械限定三段距离。未知署名证据可空。
按原文顺序覆盖目标章需要表达的对白、心理因果和系统提示；同段可拆不同声音项。不填镜头、备注、猜测说明。只提交items。'''

def schema(packet):
    sources=r.paragraphs(packet)
    targets=[p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']]
    return c.obj(items=c.array(c.obj(source_id=c.choices(targets),kind=c.choices(['dialogue','narration','system']),
        speaker={'type':'string'},text=c.TEXT,evidence_ids=c.refs(sources,0)),1))

def build_bank(raw,packet):
    issues=c.schema_issues(raw,schema(packet),'audio')
    if issues:raise c.ContractError(issues)
    source=r.paragraphs(packet);targets=[p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']]
    order={v:i for i,v in enumerate(targets)};last=-1;seen=set();items=[];questions=[]
    for n,item in enumerate(raw['items'],1):
        sid=item['source_id'];speaker=item['speaker'];text=item['text']
        if order[sid]<last:raise ValueError('audio_source_order_reversed')
        last=order[sid]
        if not text.strip() or text not in source[sid]:raise ValueError('audio_not_original_span')
        if item['kind']!='dialogue' and speaker:raise ValueError('non_dialogue_cannot_assign_speaker')
        if speaker and (not item['evidence_ids'] or not any(speaker in source[e] for e in item['evidence_ids'])):
            questions.append({'audio_id':f'A{n:03}','code':'speaker_evidence_requires_semantic_review',
                              'speaker':speaker,'source_id':sid,'evidence_ids':item['evidence_ids']})
        key=(sid,text)
        if key in seen:raise ValueError('duplicate_audio_content')
        seen.add(key)
        items.append({**item,'audio_id':f'A{n:03}','source_text':source[sid],
                      'evidence':{e:source[e] for e in item['evidence_ids']}})
    return {'items':items,'raw_sha256':c.digest(raw),'source_sha256':packet['source_sha256'],
            'semantic_acceptance':False,'evidence_questions':questions,
            'note':'类型和归属由模型判断，字面证据不证明判断正确；未字面命中也不等于归属错误，列为待审，不自动放行。'}

FACT_PRESERVATION='''本阶段是忠实剧本整理，不是改编或补写剧情。确认信息只指原文明示或有充分上下文支持的信息，不把模型判断、合理猜测当确认事实。
对原文已经确定的内容保持其含义：先确认描述中的主体、行为、对象及其条件和时间层，再组织表现；不为了让画面更完整而替换这些信息。
优先保留原文可见行动的表述。当前行动、过去见闻、心理、设想不能混成同一当前画面；不适合直接表现的内容保留在已有声音中，不另造一个看得见的替代事件。
原文没有确定的内容保持开放。场景名称、地点、人物表和表现文字遵守同一边界，不借常识、相邻地名或群体概括补成确定事实。
允许设计景别、自然光线、微表情和普通动作衔接，但补充不能引入新的剧情事实、改变既有信息或确定未知归属。缺少制作细节不等于缺剧情，不必填满。
允许合并连续动作、省略无必要信息的过渡；若会损失关键对白或因果就保留，不要求每个排版段都有画面。
当前交付是剧本，不是逐镜头音画时间表。每场画面和声音可以分组；逐镜头同步留给后续制作阶段，不据分组形式判断本稿错误。'''

def picture_prompt(confirmed=False):
    text='''根据完整target原文组织画面，context_only仅理解。audio_bank是前序声音决定，只能引用，不能改类型、署名或文字。
逐行输出以下格式，不使用Markdown或其他类型行：
场次：编号与名称
时间：本场时间
地点：普通地点描述，原文未明示时不强调位置
人物：本场实际在场的人
画面[原文段号或同章连续范围]：可见动作、表情、景别和光线
声音[音频ID]
原段：本场原段范围
每场包含场次、时间、地点、人物、原段，可有多行画面和声音。段号取自source.chapters.paragraphs.id；范围写完整起止段号，或末端仅保留P及数字，范围内必须都是同章目标原段。声音ID从audio_bank.items.audio_id原样选，每项恰好出现一次且保持声音表顺序。
声音节点无法确定的说话人不能在画面中偷偷指定发声人；旁白内容不能再安排人物张口说出。心理和回忆用既有声音表达，画面不编具体回忆。
不输出对白、旁白、系统、心声或待核说明行；声音引用由程序原样展开。输出完整所有target，时长不限，只返回text。
'''+sc.POLICY
    return text+('\n'+FACT_PRESERVATION if confirmed else '')

def expand_target_range(value,packet):
    targets={p['id'] for ch in packet['chapters'] if ch['role']=='target' for p in ch['paragraphs']}
    if value in targets:return [value]
    m=re.fullmatch(r'CH(\d+)-P(\d+)[—–~～-](?:CH(\d+)-)?P(\d+)',value)
    if not m:return None
    chapter,start,end_chapter,end=m.groups()
    if end_chapter is not None and end_chapter!=chapter:return None
    start,end=int(start),int(end)
    if end<start or end-start>=len(targets):return None
    ids=[f'CH{chapter}-P{n:03}' for n in range(start,end+1)]
    return ids if all(s in targets for s in ids) else None

def render_layout(text,bank,packet):
    items={i['audio_id']:i for i in bank['items']};used=[];output=[];issues=[];fields=set();scene=False
    sources=r.paragraphs(packet);required={'时间','地点','人物','原段'};evidence=[]
    for n,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line:continue
        if line.startswith('场次：'):
            if scene and required-fields:issues.append({'line':n,'code':'missing_scene_fields'})
            scene=True;fields=set();output.append(line);continue
        if not scene:issues.append({'line':n,'code':'outside_scene'})
        if any(line.startswith(f+'：') for f in required):fields.add(line.split('：')[0]);output.append(line);continue
        sound=re.fullmatch(r'声音(?:\[A\d+\])+',line)
        if sound:
            for aid in re.findall(r'\[(A\d+)\]',line):
                used.append(aid)
                if aid not in items:issues.append({'line':n,'code':'unknown_audio_id'});continue
                item=items[aid];kind={'dialogue':'对白','narration':'旁白','system':'系统'}[item['kind']]
                label=item['speaker'] or ('待核' if item['kind']=='dialogue' else kind)
                output.append(f"{kind}[{aid}|{label}|{item['source_id']}]：{item['text']}")
            continue
        visual=re.fullmatch(r'画面\[([^\]]+)\]：(.+)',line)
        ids=expand_target_range(visual[1],packet) if visual else None
        if ids:
            output.append(line)
            evidence.append({'line':n,'source_ids':ids,'originals':[{'id':s,'text':sources[s]} for s in ids]})
            continue
        issues.append({'line':n,'code':'forbidden_or_malformed_line'})
    if not scene or required-fields:issues.append({'code':'missing_scene_fields'})
    if used!=list(items):issues.append({'code':'audio_sequence_mismatch','expected':list(items),'actual':used})
    return {'issues':issues,'format_passed':not issues,'semantic_acceptance':False,
            'layout_sha256':c.digest(text),'bank_sha256':c.digest(bank),
            'visual_source_evidence':evidence,
            'rendered':'\n'.join(output) if not issues else None}

def review_prompt(confirmed=False):
    text=sc.review_prompt()+'''\n本次声音先整理，画面后引用。分别定位：
一、audio_bank与原文对照：声音类型、署名、漏掉的必要内容是否正确；不要把原词存在当正确归类。
二、layout/完整候选：画面是否偷偷指定未知发声人、把旁白演成对白，或者遗漏/倒置事件。
三、普通表现补足可接受，不要求每个原段配音或每个过渡单独拍摄。
具体错误指出原段、音频ID或场次，注明责任为声音整理或画面组织。审核不能只看格式通过。'''
    return text+('\n'+FACT_PRESERVATION+'\n审查已有信息是否被改写、未明信息是否被擅自确定。不要把缺少独立转场镜头、未逐镜头配音、普通微动作当硬错。visual_source_evidence仅证明引文范围，仍须逐原句判断语义。' if confirmed else '')
