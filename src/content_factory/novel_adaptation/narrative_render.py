"""Lossless readable view of an unaccepted narrative candidate."""


def render(candidate, *, estimated_timing=False):
    timing=None
    if estimated_timing:
        from .narrative_timing import schedule
        timing=schedule(candidate)
    header=['# '+candidate['title'], '', '> 未验收候选；时间为模型估计，尚非成片时长。']
    if timing:
        header=['# 剧本规划排期（未验收）', '',
                f"> 本视图统一使用派生排期，总计 {timing['total_seconds']:g} 秒；不是实测成片时长。对白与画面可并行。",
                '', '原稿标题（保留原估时）：'+candidate['title'], '',
                '原稿标题、段落原估时和压缩说明仅用于来源追溯；制作排期以本视图段落标题时间轴为准。']
    rows={r['segment_id']:r for r in timing['segments']} if timing else {}
    lines=header+['',
           '## 世界与关系', '', candidate['world_and_relationships'], '',
           '## 视觉方向', '', candidate['visual_direction']]
    elapsed=0
    for scene in candidate['scenes']:
        lines += ['', '## '+scene['id']+' · '+scene['place'], '',
                  '入场承接：'+scene['entry_continuity']]
        for segment in scene['segments']:
            end=elapsed+segment['seconds']
            if timing:
                row=rows[segment['id']];elapsed=row['start'];end=row['end']
            lines += ['', f"### {segment['id']} · {elapsed:g}–{end:g}秒", '',
                      '画面人物：'+', '.join(segment['visible_people']),
                      '动作：'+segment['action'], '神情：'+segment['expression'],
                      '镜头：'+segment['camera']]
            if timing:lines += [f"原稿段落估时：{segment['seconds']:g}秒；当前排期：{row['scheduled_seconds']:g}秒。"]
            for audio in segment['audio']:
                lines += [f"音轨（{audio['kind']} / {audio['speaker']}）：{audio['text']}"]
            lines += ['来源：'+', '.join(segment['source_ids'])]
            for key,label in [('visual_additions','影视补足'),('continuity_obligations','连续性待核')]:
                lines += [label+'：'+text for text in segment[key]]
            elapsed=end
        lines += ['', '出场承接：'+scene['exit_continuity']]
    lines += ['', '## 压缩说明', '']
    for note in candidate['condensation_notes']:
        lines += [', '.join(note['source_ids'])+'：'+note['treatment']]
    return '\n\n'.join(lines)+'\n'
