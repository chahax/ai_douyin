"""Offline lossless paragraph coverage draft; no model calls or media submission."""
import hashlib
import json
from pathlib import Path
import re
import math

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/corpus_production_trials/20261102_continuity_cards_first_three_review_resume/SCREENPLAYS_READING.md'
RUN_CHAIN = SOURCE.with_name('RUN_CHAIN.json')
OUT = ROOT / 'data/video_generation/h3_six_children_full_script_20261102'
NAMES = ('苏墨', '叶东', '叶南', '叶北', '叶寻', '叶嫣儿', '叶西决', '高个男人', '矮个男人', '人贩子', '一名人贩子', '地上的人贩子')


def sound_spans(text, block_id):
    """Exact local character ranges with explicit channel; no generated dialogue."""
    items=[]
    opening=re.match(r'^\*\*【([^】]+)】\*\*\s*|^\*\*旁白（([^）]+)）\*\*[：:]\s*|^（([^）]*(?:心声|旁白)[^）]*)）',text)
    if opening:
        label=next(v for v in opening.groups() if v)
        channel='心声' if '心声' in label else ('画外童声' if '未署名' in label else '旁白')
        speaker=label.split('·')[-1] if '心声·' in label else ('苏墨' if label=='苏墨心声' else '叶西决' if label=='叶西决心声' else '中性旁白' if channel=='旁白' else '未署名童声')
        return [dict(start=opening.end(),end=len(text),text=text[opening.end():],channel=channel,speaker=speaker)]
    # Explicit parent attribution for this inherited-pronoun source line, not a model rewrite.
    override={'CH01_SC01_P029':'苏墨'}
    plain=text.replace('**','').lstrip()
    speaker=override.get(block_id)
    if speaker is None:
        speaker=next((n for n in ('老六',*sorted(NAMES,key=len,reverse=True)) if plain.startswith(n)),None)
    if speaker=='老六':speaker='叶西决'
    quoted=list(re.finditer(r'"([^"]*)"',text)) or list(re.finditer(r'「([^」]*)」',text))
    if quoted:
        for match in quoted:
            items.append(dict(start=match.start(1),end=match.end(1),text=match[1],
                              channel='画外对白' if '画外' in text[:match.start()] else '对白',speaker=speaker or '未署名角色'))
        return items
    names='|'.join(map(re.escape,sorted(NAMES,key=len,reverse=True)))
    for line in re.finditer(r'[^\n]+',text):
        value=line.group()
        if value.startswith('（几名孩子的共同心声）'):
            end=value.index('）')+1
            items.append(dict(start=line.start()+end,end=line.end(),text=value[end:],channel='共同心声',speaker='孩子们'));continue
        match=re.match(r'^((?:'+names+r')(?:／(?:'+names+r'))*)(?:（([^）]*)）|\s+)(.*)$',value)
        if match and match[3].strip() and not any(x in (match[2] or '') for x in ('近景','视角','特写')):
            start=line.start()+match.start(3)
            items.append(dict(start=start,end=line.end(),text=text[start:line.end()],
                              channel='心声' if any(x in (match[2] or '') for x in ('心声','内心')) else '对白',speaker=match[1]))
    return items


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def spoken_text(text):
    """Conservative planning heuristic, not an ASR/content acceptance result."""
    plain = text.replace('**', '').strip()
    if re.match(r'^(【(?:旁白|心声|未署名)[^】]*】|旁白[（(][^）)]*[）)]|[（(](?:中性旁白|.*心声)[）)])', plain):
        return re.sub(r'^(【[^】]*】|旁白[（(][^）)]*[）)]|[（(][^）)]*[）)])\s*[：:]?\s*', '', plain)
    quotes = re.findall(r'「([^」]*)」|"([^"]*)"', plain)
    if quotes:
        return ''.join(a or b for a,b in quotes)
    spoken = []
    for line in plain.splitlines():
        if line.startswith('（几名孩子的共同心声）'):
            spoken.append(line.split('）',1)[1]); continue
        names = '|'.join(map(re.escape, sorted(NAMES, key=len, reverse=True)))
        match = re.match(r'^((?:' + names + r')(?:／(?:' + names + r'))*)(?:（([^）]*)）|\s+)(.*)$', line)
        if match:
            cue, rest = match.group(2) or '', match.group(3).strip()
            if rest and not any(word in cue for word in ('近景', '视角', '特写')):
                spoken.append(rest)
    return ''.join(spoken)


def spoken_chars(text):
    return len(re.findall(r'[\u3400-\u9fffA-Za-z0-9]', text))


def split_preserving(text, limit=48):
    """Split an oversize source block at punctuation; exact text always reassembles."""
    if len(text) <= limit:
        return [text]
    pieces = []
    remaining = text
    while len(remaining) > limit:
        boundary = max([i+1 for i,c in enumerate(remaining[:limit]) if c in '。！？；，、\n'] or [limit])
        if boundary < limit // 3:
            boundary = limit
        pieces.append(remaining[:boundary])
        remaining = remaining[boundary:]
    if remaining:
        pieces.append(remaining)
    assert ''.join(pieces) == text
    return pieces


def parse(text):
    paragraphs = list(re.finditer(r'\S[^\n]*(?:\n(?!\s*\n)[^\n]+)*', text))
    scenes, references = [], []
    chapter, scene, mode = None, None, 'reference'
    i = 0
    while i < len(paragraphs):
        match = paragraphs[i]
        block, start, end = match.group(), match.start(), match.end()
        i += 1
        chapter_match = re.fullmatch(r'# 第(\d+)章', block)
        if chapter_match:
            chapter = int(chapter_match[1]); scene = None; mode = 'reference'
        if re.match(r'^#{2,3} 场[景次]', block):
            scene = dict(id=f'CH{chapter:02d}_SC{1+sum(s["chapter"]==chapter for s in scenes):02d}',
                         chapter=chapter, heading=block, source_start=start, metadata=[], blocks=[], units=[])
            scenes.append(scene); mode='performance'; continue
        if block.startswith('## ') and '制作决定' in block:
            mode='reference'
        if block.strip() == '---':
            continue
        if mode != 'performance' or scene is None:
            references.append(dict(chapter=chapter, text=block, start=start, end=end)); continue
        if re.match(r'^\*\*(时间|地点|在场人物|入场状态)\*\*', block):
            scene['metadata'].append(dict(text=block, start=start, end=end)); continue
        # Keep a standalone actor cue together with the following quoted dialogue.
        if re.match(r'^\*\*[^*]+\*\*[^\n]*[：:]$', block) and i < len(paragraphs):
            following = paragraphs[i]
            if following.group().startswith(('"', '「', '（本句')):
                end = following.end(); block=text[start:end]; i+=1
        block_id = f'{scene["id"]}_P{len(scene["blocks"])+1:03d}'
        sounds=sound_spans(block,block_id)
        count=sum(spoken_chars(a['text']) for a in sounds)
        scene['blocks'].append(dict(id=block_id,start=start,end=end,text=block,sha256=digest(block),spoken_chars_estimate=count,sound_spans=sounds))
        chunks = split_preserving(block,48) if count > 43 else [block]
        offset = start
        for index, chunk in enumerate(chunks):
            # Long spoken blocks retain the parent sound channel as binding context.
            audio_items=[]
            for sound in sounds:
                a=max(offset,start+sound['start']);z=min(offset+len(chunk),start+sound['end'])
                if a<z:
                    audio_items.append(dict(speaker=sound['speaker'],channel=sound['channel'],text=text[a:z],start=a,end=z,
                                            parent=block_id,parent_context_only=True))
            chunk_count=sum(spoken_chars(a['text']) for a in audio_items)
            estimate = (chunk_count/3.6 + 1.0) if chunk_count else max(2.0,min(7.0,spoken_chars(chunk)/13.0))
            scene['units'].append(dict(id=f'{block_id}_U{index+1:02d}',parent=block_id,start=offset,end=offset+len(chunk),
                                      text=chunk,sha256=digest(chunk),spoken_chars_estimate=chunk_count,audio_items=audio_items,
                                      estimated_seconds=round(estimate,3),split_count=len(chunks)))
            offset += len(chunk)
        assert offset == end
    return scenes,references


def plan_segments(scenes):
    segments=[]
    for scene in scenes:
        pending=[]; seconds=0
        def commit():
            if not pending:return
            duration=sum(u['estimated_seconds'] for u in pending)
            frames=max(124,min(362,5+17*math.ceil((24*(duration+.5)-5)/17)))
            segments.append(dict(id=f'F{len(segments)+1:04d}',chapter=scene['chapter'],scene=scene['id'],
                                 scene_heading=scene['heading'],units=list(pending),source_chars=sum(len(u['text']) for u in pending),
                                 spoken_chars_estimate=sum(u['spoken_chars_estimate'] for u in pending),
                                 estimated_content_seconds=round(sum(u['estimated_seconds'] for u in pending),3),
                                 native_frames=frames,fps=24,native_seconds=frames/24,
                                 reference_strategy='scene_entry_requires_asset_decision' if not any(s['scene']==scene['id'] for s in segments) else 'previous_native_tail'))
        for unit in scene['units']:
            if pending and seconds+unit['estimated_seconds']>14:
                commit();pending=[];seconds=0
            pending.append(unit);seconds+=unit['estimated_seconds']
        commit()
    return segments


def verify_coverage(text,scenes,segments):
    expected=[u for s in scenes for u in s['units']]
    actual=[u for s in segments for u in s['units']]
    if [u['id'] for u in expected] != [u['id'] for u in actual]:
        raise ValueError('missing_duplicated_or_reordered_unit')
    for scene in scenes:
        for block in scene['blocks']:
            parts=[u for u in actual if u['parent']==block['id']]
            if ''.join(u['text'] for u in parts)!=block['text'] or text[block['start']:block['end']]!=block['text']:
                raise ValueError('source_text_changed')
    return dict(performance_blocks=sum(len(s['blocks']) for s in scenes),units=len(expected),segments=len(segments),
                every_performance_block_covered_exactly_once=True,order_preserved=True,source_text_unchanged=True,
                timing='heuristic draft, must check actual speaking pace; no semantic acceptance claimed')


def main(out=OUT):
    out.mkdir(parents=True,exist_ok=True)
    text=SOURCE.read_text(encoding='utf-8')
    scenes,references=parse(text)
    segments=plan_segments(scenes)
    verification=verify_coverage(text,scenes,segments)
    report=dict(source=dict(path=str(SOURCE),sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest()),
                run_chain=dict(path=str(RUN_CHAIN),sha256=hashlib.sha256(RUN_CHAIN.read_bytes()).hexdigest()),
                source_scope='three existing final chapter scripts, not 69 chapters',scenes=scenes,references=references,
                segments=segments,coverage=verification,
                totals=dict(chapters=len(set(s['chapter'] for s in scenes)),scenes=len(scenes),segments=len(segments),
                            spoken_chars_estimate=sum(u['spoken_chars_estimate'] for s in scenes for u in s['units']),
                            native_seconds=sum(s['native_seconds'] for s in segments),render_hours_at_S01_speed=sum(s['native_frames'] for s in segments)/362*3374/3600),
                executable=False,reason='scene references/identity cards and timing require production mapping; no media dispatched')
    (out/'COVERAGE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 前三章完整稿逐段视频覆盖草案','',f"来源：{SOURCE}",'',
           '背景与制作决定保存为上下文约束，不整体朗读。连续场景正文的动作、对白、旁白逐原段编号，全部原文按顺序保留。',
           '下面是离线时长规划，不等于已经生成视频或完成对白语义审核。现有一分钟摘编不计作完整覆盖。','',
           f"共 {len(scenes)} 场、{len(segments)} 个5–15秒可变时长段，排片约 {report['totals']['native_seconds']/60:.1f} 分钟。",
           f"按S01单段56分14秒粗估本机生成约 {report['totals']['render_hours_at_S01_speed']:.1f} 小时，不是完成时间承诺。",'',
           '| 场次 | 分段 | 原段数 | 声音字符估计 | 排片分钟 | 场景 |','|---|---|---:|---:|---:|---|']
    for scene in scenes:
        ss=[s for s in segments if s['scene']==scene['id']]
        lines.append(f"| {scene['id']} | {ss[0]['id']}—{ss[-1]['id']} | {len(scene['blocks'])} | {sum(s['spoken_chars_estimate'] for s in ss)} | {sum(s['native_seconds'] for s in ss)/60:.2f} | {scene['heading'].lstrip('# ')} |")
    lines+=['','## 全文分段覆盖（原文不重写）','']
    for segment in segments:
        lines += [f"### {segment['id']} · {segment['scene']} · 声音估计{segment['spoken_chars_estimate']}字",'',
                  f"参考策略：{segment['reference_strategy']}；来源："+', '.join(u['id'] for u in segment['units']),'',
                  '\n\n'.join(u['text'] for u in segment['units']),'']
    (out/'COVERAGE.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(totals=report['totals'],coverage=verification),ensure_ascii=False))
    return report


if __name__=='__main__':main()
