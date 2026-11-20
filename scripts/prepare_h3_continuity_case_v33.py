"""CPU real-case regression material for the four reviewed v32 source scripts.

This is an explicitly book-specific fixture, not a general semantic extractor.
The reusable v33 contract consumes source-bound structured records upstream.
No model, HTTP, input staging, video execution, or fabricated ready review.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD = ROOT / 'data/video_generation/h3_legacy_call_restore_20261108_v1'
OUT = ROOT / 'data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4'
NAMES = dict(su_mo='苏墨', ye_nan='叶南', ye_xijue='叶西决')
MAP = {
    'S01': [('ye_xijue', 'onscreen', 0, 5), ('ye_nan', 'onscreen', 5, 9), ('ye_xijue', 'onscreen', 9, 13)],
    'S02': [('su_mo', 'inner_voice', 0, 7), ('ye_xijue', 'onscreen', 7, 12)],
    'S03': [('su_mo', 'inner_voice', 0, 7), ('ye_xijue', 'inner_voice', 7, 10)],
    'S04': [('su_mo', 'onscreen', 0, 3), ('ye_xijue', 'onscreen', 3, 10), ('su_mo', 'inner_voice', 12, 15)],
}
# These are exact old directing phrases, not story facts to be repeated under
# the new per-beat camera plan. Mixed phrases are split at exact offsets.
CAMERA = ['开头立即开始对话。', '平顺切到', '面部近景', '苏墨面部近景，',
          '回到三人中近景，', '手部近景见', '的近景。', '镜头先给',
          '，再回到', '给三人手部及脸部中近景。', '结束在', '的面部近景。']
VOICE_CUES = ['成年男声心声：', '苏墨成年男声心声：',
              '叶西决的内心独白，以叶西决的画外音呈现：']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha(path.read_bytes()))


def write_new(path, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('use a new case revision: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def classify(text):
    """Partition every source character; this fixture never infers new facts."""
    kinds = ['action'] * len(text)
    timing = list(re.finditer(r'\d+—\d+秒，', text))
    if len(timing) not in (3, 4):
        raise ValueError('reviewed three or four time blocks required')
    split = text.index('\n\n') + 2
    kinds[:timing[0].start()] = ['context'] * timing[0].start()
    for match in timing:
        kinds[match.start():match.end()] = ['camera'] * len(match.group())
    quotes = list(re.finditer('“[^”]*”', text))
    for match in quotes:
        kinds[match.start():match.end()] = ['audio'] * len(match.group())
    for values, kind in [(CAMERA, 'camera'), (VOICE_CUES, 'context')]:
        for word in sorted(values, key=len, reverse=True):
            for match in re.finditer(re.escape(word), text):
                if all(k == 'action' for k in kinds[match.start():match.end()]):
                    kinds[match.start():match.end()] = [kind] * len(word)
    # "接" is an edit connector only in this exact camera clause. Elsewhere
    # "接面包/尚未伸手接" is a source action and must survive verbatim.
    for match in re.finditer(r'(?<=，)接(?=苏墨低头看面包与孩子的近景)', text):
        kinds[match.start()] = 'camera'
    # Preserve the common prefix and current-state line separately. Empty
    # separators are context, never a fake visible action.
    boundaries = {0, len(text), split, timing[0].start()}
    description_ranges = {}
    for cid, name in NAMES.items():
        match = re.search(r'^' + re.escape(name) + r'是首图中的[^\n]+', text, re.M)
        if not match:
            raise ValueError('reviewed source actor description required: ' + cid)
        boundaries.update((match.start(), match.end()))
        description_ranges[cid] = (match.start(), match.end())
    audio_context_ranges = []
    for pattern in [r'普通话对白与原生同步音轨', r'角色声线固定：[^。]+。']:
        match = re.search(pattern, text[:split])
        if not match:
            raise ValueError('reviewed source audio context required')
        boundaries.update((match.start(), match.end()))
        audio_context_ranges.append((match.start(), match.end()))
    boundaries.update(i for i in range(1, len(text)) if kinds[i] != kinds[i-1])
    spans = []
    points = sorted(boundaries)
    for lo, hi in zip(points, points[1:]):
        raw = text[lo:hi]
        kind = kinds[lo] if raw.strip() else 'context'
        spans.append(dict(id=f's{len(spans):02d}', kind=kind, start=lo, end=hi,
                          text=raw, sha256=sha(raw.encode('utf-8'))))
    state_ids = [s['id'] for s in spans if s['start'] == split]
    descriptions = {cid:[s['id'] for s in spans if (s['start'], s['end']) == extent]
                    for cid, extent in description_ranges.items()}
    if any(len(v) != 1 for v in descriptions.values()):
        raise ValueError('one exact source description span per actor required')
    audio_context = [s['id'] for s in spans if (s['start'], s['end']) in audio_context_ranges]
    if len(audio_context) != 2:
        raise ValueError('two exact audio context spans required')
    groups = []
    for i, t in enumerate(timing):
        stop = timing[i+1].start() if i+1 < len(timing) else len(text)
        groups.append([s['id'] for s in spans if s['kind'] == 'action' and t.end() <= s['start'] < stop])
    assert ''.join(s['text'] for s in spans) == text
    return spans, state_ids, descriptions, audio_context, groups, quotes


def actor(parts, pose):
    return dict(visible_parts=parts.split(), pose=pose)


def beats(sid, groups, spans):
    face = 'face torso'
    full = 'face torso hands legs'
    if sid == 'S01':
        data = [
            (0, 5, 'medium', dict(ye_xijue=actor('face torso hands', '叶西决仰头望着哥哥'), ye_nan=actor('torso hands', '叶南站在他旁边'))),
            (5, 9, 'face_close', dict(ye_nan=actor('face torso hands', '叶南微微俯身看着弟弟'), ye_xijue=actor('torso hands', '双手在胸前捧着透明塑料袋包的面包'))),
            (9, 13, 'medium', dict(ye_xijue=actor(face, '叶西决立即摇头'), ye_nan=actor(face, '叶南听着，表情变得担心'))),
            (13, 15, 'face_close', dict(su_mo=actor(face, '他眉心绷紧，呼吸稍重'))),
        ]
    elif sid == 'S02':
        last = groups.pop()
        by_id = {s['id']:s for s in spans}
        hand = [i for i in last if '小手略微发抖' in by_id[i]['text']]
        if len(hand) != 1:
            raise ValueError('exact hands action split required')
        groups.extend([hand, [i for i in last if i not in hand]])
        data = [
            (0, 7, 'face_close', dict(su_mo=actor(face, '闭眼忍着头痛'))),
            (7, 12, 'medium', dict(su_mo=actor(face, '苏墨仍躺在原床'), ye_nan=actor(face, '两个孩子站在床边'), ye_xijue=actor('face torso hands', '叶西决把透明袋装的白面包往苏墨面前递'))),
            (12, 13.5, 'hands_close', dict(ye_xijue=actor('hands', '捧着面包的小手略微发抖'))),
            (13.5, 15, 'face_close', dict(su_mo=actor(face, '苏墨低头看面包与孩子'))),
        ]
    elif sid == 'S03':
        first = groups.pop(0)
        by_id = {s['id']:s for s in spans}
        eyes = [i for i in first if '完整黑亮的双眼' in by_id[i]['text']]
        if len(eyes) != 1:
            raise ValueError('exact eyes action split required')
        groups[:0] = [eyes, [i for i in first if i not in eyes]]
        data = [
            (0, 2, 'face_close', dict(ye_xijue=actor(face, '叶西决完整黑亮的双眼'))),
            (2, 7, 'face_close', dict(su_mo=actor(face, '苏墨低头沉思，没有立刻接面包'))),
            (7, 10, 'face_close', dict(ye_xijue=actor('face torso hands', '他闭紧眼睛，肩膀缩起'))),
            (10, 13, 'medium', dict(ye_nan=actor(face, '叶南向前半步挡在弟弟身前，肩背绷紧'), ye_xijue=actor(face, '两个孩子下意识瑟缩'), su_mo=actor(face, '苏墨起身走近'))),
            (13, 15, 'medium', dict(su_mo=actor('face torso hands', '苏墨的手平稳伸到面包袋上'), ye_xijue=actor('face torso hands', '两个孩子站在他面前'), ye_nan=actor(face, '叶南警觉的脸慢慢变成震惊'))),
        ]
    else:
        data = [
            (0, 3, 'face_close', dict(su_mo=actor('face torso hands', '苏墨露出苦涩而尽量温和的表情'))),
            (3, 10, 'medium', dict(ye_xijue=actor(full, '立刻跪下'), ye_nan=actor(face, '叶南惊疑地看看苏墨，又看弟弟'))),
            (10, 12, 'wide', dict(ye_xijue=actor(full, '叶西决迅速起身'), ye_nan=actor(full, '两人一起沿床尾空出的通道向房门跑出去'))),
            (12, 15, 'face_close', dict(su_mo=actor('face torso hands', '苏墨转头看着他们离开的门口，怔住'))),
        ]
    if len(data) != len(groups):
        raise ValueError((sid, len(data), len(groups)))
    return [dict(start=a, end=b, cut=i>0, framing=framing, actors=actors, source_span_ids=ids)
            for i, ((a,b,framing,actors),ids) in enumerate(zip(data,groups))]


def build(out=OUT):
    out = Path(out).resolve()
    base = json.loads((OLD/'PLAN.json').read_text(encoding='utf-8'))
    refs = base['upstream_asset_references']
    canon = {r['entity_id']:r['image'] for r in refs if r['kind']=='character'}
    room = next(r['image'] for r in refs if r['kind']=='place' and r['view']=='front')
    shots = []
    visible = {'S01':dict(su_mo=True,ye_nan=False,ye_xijue=True),
               'S02':dict(su_mo=True,ye_nan=False,ye_xijue=False),
               'S03':dict(su_mo=False,ye_nan=False,ye_xijue=False),
               'S04':dict(su_mo=False,ye_nan=True,ye_xijue=True)}
    evidence = {
        'S01':'Actual input crops off the older brother face. Father and younger face visible; canonical identity/whole-room match not certified.',
        'S02':'Actual input is father face on pillow plus cropped boy torsos/hands; child faces absent.',
        'S03':'Actual input has cropped father face and children/head fragments; foreground head/body ownership uncertain. No full face identity certified.',
        'S04':'Actual input has two boy faces and only father sleeve/hand/torso. Father face absent although his facial performance is required next.',
    }
    for sid in MAP:
        source = OLD/'prompts'/f'{sid}.txt'
        text = source.read_text(encoding='utf-8')
        spans, states, descriptions, audio_context, groups, quotes = classify(text)
        audio = [dict(quote_index=i, quote_sha256=sha(q.group().encode('utf-8')),
                      speaker=who, mode=mode, start=a, end=b)
                 for i,(q,(who,mode,a,b)) in enumerate(zip(quotes,MAP[sid]))]
        if len(quotes) != len(MAP[sid]):
            raise ValueError('exact quote occurrences required')
        first = bind(OLD/'shots'/sid/'first_input.png')
        review = dict(schema='h3_continuity_coverage_review/v33',reviewed_by='root_actual_frame_observer',
                      completion_known=True,outcome_unknown=False,
                      target_image=first,canonical_characters=canon,canonical_room=room,
                      checks=dict(topology_coherent=None if sid=='S03' else True,
                                  room_identity=None,faces=visible[sid],
                                  identities={k:None for k in NAMES}),evidence=[evidence[sid]])
        rp = out/'reviews'/f'{sid}.json'
        write_new(rp,review)
        shots.append(dict(shot_id=sid,handoff_binding=None,source=bind(source),
                          source_scope=dict(start=0,end=len(text)),source_spans=spans,
                          duration=15,audio=audio,camera_beats=beats(sid,groups,spans),
                          character_names=NAMES,canonical_characters=canon,canonical_room=room,
                          character_description_span_ids=descriptions,
                          audio_context_span_ids=audio_context,
                          actual_first_image=first,coverage_review=bind(rp),
                          source_state_span_ids=states,postproduction_subtitles=False))
    spec=dict(schema='h3_continuity_input/v33',shots=shots,
              scope='Real source/image negative regression, all coverage reviews are actual root observations. No manufactured identity pass, no model or video calls.',
              fixture_not_general_extractor=True)
    path=out/'SPEC.json';write_new(path,spec)
    print(json.dumps(dict(spec=bind(path),shots=len(shots),quotes=sum(len(s['audio']) for s in shots),model_posts=0),ensure_ascii=False))
    return path


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=OUT)
    build(p.parse_args().out)
