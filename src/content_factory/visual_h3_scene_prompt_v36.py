"""Deterministic source-bound Chinese performance prompts, without model rewrite.

Only source/text protocol is checked. No image/face/semantic approval is issued;
the new source images and finished movie remain for the user's review.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

PROJECT=Path(__file__).resolve().parents[2]
SOURCE=PROJECT/'data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4/SPEC.json'
OUT=PROJECT/'data/video_generation/h3_scene_performance_minute_20261109_v2/source_prompts'
SCHEMA='h3_scene_performance_prompts/v36'
IDS=('S01','S02','S03','S04')
QUOTE=re.compile(r'“[^”]*”|「[^」]*」')
TIME=re.compile(r'(\d+(?:\.\d+)?)\s*[—–-]\s*(\d+(?:\.\d+)?)秒')
MODES={'onscreen','inner_voice','voiceover','offscreen_dialogue'}
STYLE='真人写实中国家庭短剧，竖屏9:16，普通话对白与原生同步音轨。人物造型、衣服和同一房间的细节沿用本段输入画面。'
PERFORMANCE='人物睁眼交流时看向场景中的对话对象或面包，离场时看向行进方向或房门；对话以自然侧面和三分之二侧面表演。开场从本段第一项动作或第一句声音直接进入。'
TEXT_POLICY='画面是纯摄影剧情影像，不出现字幕或其他屏幕文字；所有台词仅作为声音播放。'


class PromptError(ValueError):pass


def sha(text):return hashlib.sha256(text.encode('utf8')).hexdigest()
def digest(value):return sha(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')))
def binding(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:raise PromptError('source_or_artifact_bytes_changed')
    return Path(value['path'])
def read(value):return json.loads(check(value).read_text(encoding='utf8'))
def _freeze(path,value):
    path=Path(path);raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')
    _bytes(path,raw)
def _bytes(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise PromptError('frozen_v36_artifact_changed_use_new_namespace')
    else:
        with path.open('xb') as stream:stream.write(raw)
def _number(v):return type(v) in (int,float) and v==v and abs(v)!=float('inf')


def _materials(entry):
    sid=entry.get('shot_id');duration=entry.get('duration')
    if sid not in IDS or not _number(duration) or not 0<duration<=15:raise PromptError('explicit_short_source_segment_required')
    source=check(entry['source']).read_text(encoding='utf8');scope=entry['source_scope'];a,b=scope['start'],scope['end']
    if type(a) is not int or type(b) is not int or not 0<=a<b<=len(source):raise PromptError('source_scope_positions_required')
    by={};cursor=a
    for span in entry['source_spans']:
        x,y=span['start'],span['end'];key=span['id']
        if (key in by or not isinstance(key,str) or not key or type(x) is not int or type(y) is not int
                or x!=cursor or not x<y<=b or source[x:y]!=span['text'] or sha(source[x:y])!=span['sha256']
                or span.get('kind') not in ('context','action','audio','camera')):
            raise PromptError('complete_exact_source_spans_required')
        by[key]=span;cursor=y
    if cursor!=b:raise PromptError('source_partition_incomplete')
    times=[m for m in TIME.finditer(source,a,b)]
    if not times:raise PromptError('source_time_blocks_required')
    previous=0
    for m in times:
        start,end=map(float,m.groups())
        if start!=previous or not start<end<=duration:raise PromptError('contiguous_local_source_clock_required')
        previous=end
    if previous!=duration:raise PromptError('source_clock_does_not_cover_segment')
    body_start=times[0].start();body=source[body_start:b]
    if any(s['kind']=='action' and s['start']<body_start for s in by.values()):
        raise PromptError('current_actions_must_be_in_source_body')
    quotes=list(QUOTE.finditer(source,a,b));audio=entry['audio'];names=entry['character_names']
    if [x.get('quote_index') for x in audio]!=list(range(len(quotes))) or not quotes:raise PromptError('original_ordered_audio_coverage_required')
    emitted=[]
    for item,q in zip(audio,quotes):
        if (item.get('speaker') not in names or item.get('mode') not in MODES or item.get('quote_sha256')!=sha(q.group())
                or not _number(item.get('start')) or not _number(item.get('end')) or not 0<=item['start']<item['end']<=duration
                or q.start()<body_start):raise PromptError('audio_identity_timing_or_quote_changed')
        emitted.append(dict(speaker_id=item['speaker'],speaker_name=names[item['speaker']],mode=item['mode'],
                            quote_index=item['quote_index'],text=q.group(),spoken_text=q.group()[1:-1],
                            quote_sha256=sha(q.group()),start=item['start'],end=item['end'],
                            source_range=dict(start=q.start(),end=q.end())))
    def selected(ids):
        if not isinstance(ids,list) or len(ids)!=len(set(ids)) or any(key not in by for key in ids):raise PromptError('bound_context_span_ids_required')
        return [by[key] for key in ids]
    states=selected(entry['source_state_span_ids'])
    descriptions=[]
    for cid,ids in entry['character_description_span_ids'].items():
        if cid not in names:raise PromptError('source_character_mapping_required')
        descriptions+=selected(ids)
    voice=selected(entry['audio_context_span_ids'])
    if not states or not descriptions or not voice:raise PromptError('source_start_cast_and_voice_material_required')
    if any(s['start']>=body_start or QUOTE.search(s['text']) for s in states+descriptions+voice):raise PromptError('context_cannot_duplicate_body_or_speech')
    return source,by,body_start,body,states,descriptions,voice,emitted


def compile_segment(entry):
    """Retain the complete timed source body; add only requested presentation cues.

    Deliberately does not call v33.validate_entry/evaluate or consume its face
    coverage review. Image production and user inspection are independent.
    """
    source,by,body_start,body,states,descriptions,voice,audio=_materials(entry)
    parts=[STYLE,PERFORMANCE,TEXT_POLICY]
    mapped=[]
    def append_source(span,role):
        start=sum(len(p)+1 for p in parts);parts.append(span['text'])
        mapped.append(dict(role=role,span_id=span['id'],source_range=dict(start=span['start'],end=span['end']),
                           prompt_range=dict(start=start,end=start+len(span['text'])),sha256=span['sha256']))
    for span in descriptions:append_source(span,'character_description')
    for span in voice:
        # The short generic audio phrase already occurs literally in STYLE.
        if span['text'] in STYLE:continue
        append_source(span,'source_voice_and_cinematography')
    for span in states:append_source(span,'opening_state')
    offset=sum(len(p)+1 for p in parts);parts.append(body);text='\n'.join(parts)
    for span in by.values():
        if span['start']>=body_start:
            mapped.append(dict(role='source_'+span['kind'],span_id=span['id'],source_range=dict(start=span['start'],end=span['end']),
                               prompt_range=dict(start=offset+span['start']-body_start,end=offset+span['end']-body_start),sha256=span['sha256']))
    if [m.group() for m in QUOTE.finditer(text)]!=[a['text'] for a in audio]:raise PromptError('compiled_quotes_changed_duplicated_or_reordered')
    for m in mapped:
        a,b=m['prompt_range']['start'],m['prompt_range']['end'];x,y=m['source_range']['start'],m['source_range']['end']
        if text[a:b]!=source[x:y] or sha(text[a:b])!=m['sha256']:raise PromptError('source_to_prompt_map_changed')
    actions=[s['id'] for s in by.values() if s['kind']=='action']
    if {m['span_id'] for m in mapped if m['role']=='source_action'}!=set(actions):raise PromptError('source_action_coverage_incomplete')
    return dict(id=entry['shot_id'],source=entry['source'],source_entry_sha256=digest(entry),duration=entry['duration'],
                prompt_text=text,prompt_utf8_sha256=sha(text),audio=audio,source_map=mapped,
                audit=dict(original_quote_count=len(audio),compiled_quote_count=len(list(QUOTE.finditer(text))),
                           ordered_quotes_exact=True,all_source_actions_copied=True,source_body_verbatim=True,
                           source_body_range=dict(start=body_start,end=entry['source_scope']['end']),
                           prompt_body_range=dict(start=offset,end=len(text))),
                subtitle_control='one_explicit_prompt_sentence',native_text_absence_guaranteed=False,
                model_calls=0,media_POSTs=0,user_review_pending=True,production_approved=False)


def prepare(source_file=SOURCE,output_dir=OUT,*,node_capability=None):
    source_binding=binding(source_file);spec=read(source_binding);entries=spec.get('shots',[])
    if tuple(s.get('shot_id') for s in entries)!=IDS:raise PromptError('original_four_ordered_segments_required')
    rows=[compile_segment(entry) for entry in entries]
    if sum(len(r['audio']) for r in rows)!=10:raise PromptError('all_ten_original_quotes_required')
    output=Path(output_dir).resolve();segments=[]
    for row in rows:
        path=output/(row['id']+'.prompt.txt');_bytes(path,row['prompt_text'].encode('utf8'))
        segments.append(dict({k:deepcopy(v) for k,v in row.items() if k!='prompt_text'},prompt=binding(path)))
    if node_capability is not None:check(node_capability)
    plan=dict(schema=SCHEMA,source_case=source_binding,implementation=binding(__file__),segments=segments,
              audio_quote_count=10,node_capability=node_capability,
              native_negative_prompt_used=False,native_fields={},user_review_pending=True,
              native_text_absence_guaranteed=False,postproduction_subtitles=False,
              model_calls=0,media_POSTs=0,production_approved=False,publication=False)
    target=output/'PROMPT_PLAN.json';_freeze(target,plan)
    return binding(target)


def validate(plan_binding):
    plan=read(plan_binding)
    if (plan.get('schema')!=SCHEMA or plan.get('audio_quote_count')!=10 or plan.get('user_review_pending') is not True
            or plan.get('production_approved') is not False or plan.get('publication') is not False
            or plan.get('native_text_absence_guaranteed') is not False or plan.get('native_negative_prompt_used') is not False
            or plan.get('native_fields')!={} or plan.get('model_calls')!=0 or plan.get('media_POSTs')!=0):
        raise PromptError('source_bound_user_review_pending_plan_required')
    check(plan['implementation']);spec=read(plan['source_case'])
    if [r.get('id') for r in plan['segments']]!=list(IDS):raise PromptError('four_prompt_files_required')
    for entry,row in zip(spec['shots'],plan['segments']):
        expected=compile_segment(entry);text=check(row['prompt']).read_bytes().decode('utf8')
        if text!=expected.pop('prompt_text') or {k:v for k,v in row.items() if k!='prompt'}!=expected:raise PromptError('compiled_prompt_or_audit_changed')
    if plan.get('node_capability') is not None:check(plan['node_capability'])
    return plan
