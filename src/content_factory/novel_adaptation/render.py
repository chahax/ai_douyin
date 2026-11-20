"""Readable view of immutable model output; never substitutes edited prose."""
from .presentation import display_names
def episode_markdown(candidate,entities,status='待独立验收',production_views=None,include_audit=True):
    names=display_names(candidate['design'],entities)
    names['NARRATOR']='旁白'
    design=candidate['design'];specs={r['id']:r for r in design['scenes']}
    views={v['scene_id']:v for v in (production_views or [])}
    lines=[f'# {design["title"]}', '', f'状态：{status}。以下展示原生正文与程序编译的资料，未手改正文。','',
        '## 世界框架','',design['world_framework'],'','## 视觉设计','']
    for v in design['visual_design']:lines.extend([f'- {v["aspect"]}（{v["basis"]}）：{v["description"]}'])
    offset=0
    for scene in candidate['scenes']:
        spec=specs[scene['id']]
        lines.extend(['',f'## {scene["id"]}｜{spec["place"]}｜{offset}—{offset+spec["duration_seconds"]}秒',''])
        for b in scene['beats']:
            derived=next((x for x in views.get(scene['id'],{}).get('beats',[]) if x['id']==b['id']),{})
            lines.extend([f'### {offset+b["start"]:g}—{offset+b["end"]:g}秒 · {b["id"]}','',
                '对白期间在场：'+'、'.join(names.get(x,x) for x in derived.get('present_during_audio',derived.get('present_after_moves',b.get('present',[])))),
                '',f'镜头：{b["camera"]}',f'\n动作：{b["action"]}',f'\n神情：{b["emotion"]}',''])
            if 'present_after_moves' in derived:
                lines.extend(['段末在场：'+'、'.join(names.get(x,x) for x in derived['present_after_moves']),''])
            per_audio={row['audio_index']:row['present'] for row in derived.get('audio_presence',[])}
            for audio_index,a in enumerate(b['audio']):
                lines.append(f'- {offset+a["start"]:g}—{offset+a["end"]:g}秒 {names.get(a["speaker"],a["speaker"])} [{a["kind"]}]：{a["text"]}')
                if len({tuple(v) for v in per_audio.values()})>1:
                    lines.append('  此句在场：'+'、'.join(names.get(x,x) for x in per_audio.get(audio_index,[])))
            for m in b.get('moves',[]):lines.append(f'- 位置变化（{m.get("phase","start")}，音轨索引{m.get("after_audio_index","—")}）：{names.get(m["person"],m["person"])} {m["origin"]} → {m["destination"]}；{m["action"]}')
            for t in b.get('transfers',[]):lines.append(f'- 道具交接：{t["prop"]} {t["origin"]} → {t["destination"]}；{t["action"]}')
            if include_audit:lines.extend(['',f'改编补足：{b["adaptation_detail"]}',f'\n原段：{", ".join(b["source_ids"])}',''])
        offset+=spec['duration_seconds']
    return '\n'.join(lines)+'\n'
