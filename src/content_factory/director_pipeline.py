"""Text-only staged directing, deterministic prop state and dialogue rendering."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re

DURATIONS = (7, 7, 8, 8, 7, 8)
CHECKS = ('causality', 'emotion', 'physical_actions', 'dialogue', 'continuity', 'filmability')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_outline(value, allowed):
    require(text(value.get('title')) and text(value.get('scene')), 'title/scene required')
    require(set(value['characters']) == {'A', 'B'}, 'Two defined characters required')
    for person in value['characters'].values():
        require(all(text(person.get(k)) for k in ('name','identity','appearance','voice','want','vulnerability')), 'Incomplete character')
    require(len(value['props']) <= 2, 'At most two movable props')
    require(len(set(value['locations'])) == len(value['locations']), 'Duplicate locations')
    # With no movable props, there are no prop-location edges to enumerate.
    if value['props']:
        require(all(k in value['locations'] for k in ('A.left','A.right','B.left','B.right')), 'Hand locations required')
    require(all(text(k) and text(v) for k,v in value['state'].items()), 'State must use nonempty string values')
    require(all(k in value['state'] for k in ('A.position','B.position')), 'Positions required')
    require(4 <= len(value['events']) <= 6, 'Four to six events required')
    require(24 <= sum(e['duration'] for e in value['events']) <= 45, 'Story must be 24 to 45 seconds')
    for i, event in enumerate(value['events']):
        require(event['id'] == f'S{i+1:02}' and type(event['duration']) is int and 4 <= event['duration'] <= 10, 'Event timing/order changed')
        require(all(text(event.get(k)) for k in ('action','new_information','emotion_trigger','emotional_change','causal_link')), 'Incomplete event')
    # Research provenance is bound by the orchestrator; creative text must not invent citations.
    require('source_use' not in value, 'Research bindings belong to orchestrator, not invented author citations')
    state = initial_state(value)
    check_hands(state)
    return state


def initial_state(outline):
    for p in outline['props'].values():
        require(text(p['name']) and p['location'] in outline['locations'], 'Undefined initial prop location')
    return {'props': {k:v['location'] for k,v in outline['props'].items()}, 'state':copy.deepcopy(outline['state'])}


def check_hands(state):
    hands = [p for p in state['props'].values() if p in ('A.left','A.right','B.left','B.right')]
    require(len(hands) == len(set(hands)), 'One hand holds multiple props')


def fit_speech_windows(outline, value):
    """Deterministic timing projection, never changes speech/action/state text."""
    result=copy.deepcopy(value);changes=[]
    durations={e['id']:e['duration'] for e in outline['events']}
    for shot in result['shots']:
        lines=shot['lines']
        if not lines:continue
        for line in lines:
            require(number(line['start']) and number(line['end']) and line['end']>line['start'],'Invalid authored speech time')
        counts=[len(re.sub(r'[^\w\u4e00-\u9fff]','',l['text'])) for l in lines]
        if all(n/(l['end']-l['start'])<=6 for n,l in zip(counts,lines)):continue
        span=[max(l['end']-l['start'],n/5.0) for n,l in zip(counts,lines)]
        start=min(lines[0]['start'],0.5);duration=durations[shot['id']]
        require(start+sum(span)+0.2*(len(lines)-1)+0.2<=duration,'Dialogue cannot fit naturally; revise authored text')
        before=copy.deepcopy(lines);anchors=[(0.0,0.0)]
        for l,length in zip(lines,span):
            end=round(start+length,6)
            anchors.extend([(l['start'],start),(l['end'],end)])
            l.update(start=start,end=end);start=round(end+0.2,6)
        anchors.append((float(duration),float(duration)))
        unique=[]
        for x,y in anchors:
            if unique and x==unique[-1][0]:
                require(abs(y-unique[-1][1])<1e-6,'Ambiguous timing anchor')
            else:unique.append((x,y))
        require(all(x2>x1 and y2>y1 for (x1,y1),(x2,y2) in zip(unique,unique[1:])),'Non-monotone timing projection')
        def mapped(t):
            for (x1,y1),(x2,y2) in zip(unique,unique[1:]):
                if x1<=t<=x2:return round(y1+(t-x1)*(y2-y1)/(x2-x1),6)
            raise ValueError('Action outside shot')
        for a in shot['actions']:
            left,right=mapped(a['start']),mapped(a['end'])
            if a['transfers'] or a['updates']:
                require(abs(left-a['start'])<1e-6 and abs(right-a['end'])<1e-6,'Cannot retime state-changing action; revise authoring')
            a.update(start=left,end=right)
        changes.append({'shot':shot['id'],'before':before,'after':copy.deepcopy(lines),'anchors':unique})
    return result,{'recipe':'speech_window_fit/v1','changes':changes}


def replay(outline, value, initial=None, ids=None):
    state=copy.deepcopy(initial if initial is not None else initial_state(outline))
    events={e['id']:e for e in outline['events']}
    ids=ids if ids is not None else list(events)
    require([s['id'] for s in value['shots']] == ids, 'Missing/reordered shot')
    trace=[]
    for shot in value['shots']:
        duration=events[shot['id']]['duration']; before=copy.deepcopy(state); cursor=0
        actor_ends={};changing_end=0;previous_start=-1
        require(shot['actions'], 'Actions required')
        for action in sorted(shot['actions'],key=lambda a:(a['start'],a['end'],a['actor'])):
            require(number(action['start']) and number(action['end']) and 0<=action['start']<action['end']<=duration, 'Invalid action time')
            require(action['actor'] in outline['characters'] and text(action['description']), 'Unknown actor/empty action')
            require(action['start']>=previous_start,'Action ordering')
            require(action['start']>=actor_ends.get(action['actor'],0),'Same actor has overlapping action rows')
            actor_ends[action['actor']]=action['end'];previous_start=action['start'];cursor=max(cursor,action['end'])
            if action['transfers'] or action['updates']:
                require(action['start']>=changing_end,'State-changing actions must be serialized')
                changing_end=action['end']
            for transfer in action['transfers']:
                require(transfer['prop'] in state['props'] and state['props'][transfer['prop']]==transfer['from'], 'Impossible prop origin')
                require(transfer['to'] in outline['locations'] and transfer['from']!=transfer['to'], 'Invalid prop destination')
                state['props'][transfer['prop']]=transfer['to'];check_hands(state)
            for update in action['updates']:
                require(update['key'] in state['state'] and state['state'][update['key']]==update['from'], 'Impossible state origin')
                require(text(update['to']) and update['from']!=update['to'], 'Invalid state change')
                state['state'][update['key']]=update['to']
        # Pose and inventory persist between authored actions. No invented filler gestures.
        end=0
        for line in shot['lines']:
            require(line['speaker'] in outline['characters'] and text(line['text']), 'Speaker/text missing')
            require(number(line['start']) and number(line['end']) and end<=line['start']<line['end']<=duration, 'Dialogue overlap/outside shot')
            chars=len(re.sub(r'[^\w\u4e00-\u9fff]','',line['text']))
            cps=chars/(line['end']-line['start'])
            require((chars<=3 and line['end']-line['start']<=1.5 or cps>=1.8) and cps<=6.0, f"Unnatural dialogue budget {shot['id']}: {cps:.2f} chars/s")
            end=line['end']
        require(set(shot['emotion'])=={'A','B'} and all(text(v) for v in shot['emotion'].values()), 'Emotion coverage missing')
        trace.append({'id':shot['id'],'duration':duration,'before':before,'after':copy.deepcopy(state)})
    return trace


def validate_photography(outline, value):
    require(set(value)=={'master','shots'}, 'One shared photography setup required')
    master=value['master']
    require(set(master)=={'framing','angle','light_source'}, 'Static photography slots only')
    require(master['framing']=='full_body_two_shot' and master['angle']=='same_side_oblique', 'Continuous visible master required')
    require(master['light_source'] in ('door_daylight','ceiling_and_door_daylight'),'Unknown light source')
    require(master['light_source']!='ceiling_and_door_daylight' or '顶灯' in outline['scene'],'Cannot invent a ceiling light')
    require([s['id'] for s in value['shots']]==[e['id'] for e in outline['events']], 'Photography order mismatch')
    require(all(set(s)=={'id','focus'} and text(s['focus']) for s in value['shots']), 'Only editorial focus may vary between segments')


def compile_cards(outline, script, photography):
    trace=replay(outline,script);validate_photography(outline,photography)
    def names(s):
        for key,c in outline['characters'].items():
            for suffix,label in (('.left_hand','左手'),('.right_hand','右手'),('.left','左手'),('.right','右手'),('.position','位置')):
                s=s.replace(key+suffix,c['name']+label)
            s=re.sub(r'(?<![A-Za-z0-9_])'+key+r'(?![A-Za-z0-9_])',c['name'],s)
        return s
    def natural(value):
        s=json.dumps(value,ensure_ascii=False)
        for key,person in outline['characters'].items():
            s=s.replace(key+'.left',person['name']+'左手').replace(key+'.right',person['name']+'右手').replace(key+'.position',person['name']+'位置')
        for key,prop in outline['props'].items():s=s.replace('"'+key+'"','"'+prop['name']+'"')
        return s
    cards=[]
    for i,(s,p,t) in enumerate(zip(script['shots'],photography['shots'],trace)):
        lines='\n'.join(f"{outline['characters'][l['speaker']]['name']}：{l['text']}" for l in s['lines']) or '本段无对白。'
        voices='；'.join(f"{c['name']}：{c['voice']}" for c in outline['characters'].values())
        timing='；'.join(f"{l['start']}—{l['end']}秒 {outline['characters'][l['speaker']]['name']}说上列第{n+1}句" for n,l in enumerate(s['lines']))
        characters='；'.join(f"{c['name']}，{c['identity']}，{c['appearance']}" for c in outline['characters'].values())
        cards.append({'schema':'director_card/v1','shot_id':s['id'],'duration_seconds':t['duration'],
          'continuity':'opening' if i==0 else 'raw_tail_continuation',
          'story_lock':(outline['scene']+'\n'+characters+'\n' if i==0 else '')+'本镜唯一对白：\n'+lines,
          'intent':names(outline['events'][i]['new_information']), 'start_state':names(natural(t['before'])),
          'composition':'全场共用同侧斜侧面全身双人主镜头，两张脸均可辨认，双手、双脚及已审移动范围始终在画内。足够景深保持两人清晰；利用场景已有门框、人物与屋内空间形成前中后景。站位、身体朝向和移动只服从动作表及首末态，不因摄影重新摆位。',
          'lighting':('保留场景已有玄关顶灯为主光，门外自然光为柔和侧光。' if photography['master']['light_source']=='ceiling_and_door_daylight' else '门外已有自然光为柔和侧光。')+'仅用现有室内表面反射补足脸部阴影，不新增灯具或道具。脸和双手曝光清楚，不形成剪影；光源、曝光和色温全场恒定。',
          'camera':'全段固定机位、焦距、景别与光源。后续段从已审核原始尾帧接续，禁止重新建立构图、越轴或切镜；只让已审演员动作改变画面。',
          # Executable gestures have one authority: the reviewed action track.
          # Author emotion prose remains audit material, not a second action/speech instruction.
          'performance':'情绪触发：'+names(outline['events'][i]['emotion_trigger'])+'；情绪变化：'+names(outline['events'][i]['emotional_change'])+'。眼神、呼吸、面部与身体动作按下列动作时间表执行，不追加发声或截断完整对白。',
          'beats':'\n'.join(f"{a['start']}—{a['end']}秒，{outline['characters'][a['actor']]['name']}：{names(a['description'])}" for a in sorted(s['actions'],key=lambda a:(a['start'],a['end'],a['actor']))),
          'audio':voices+'。'+timing+'。只说已列对白，口型与对应声音同步；无旁白、无新增人声。',
          'end_state':names(natural(t['after'])),
          'constraints':'只执行已审动作，不新增道具和发声，不重演上一动作；无字幕、水印或突然切镜。'})
    return cards


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
