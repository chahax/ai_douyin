"""Deterministic, source-bound speaker/mode grounding for diagnostic video prompts.

No language model, video API, rewrite of source actions, or inference of a speaker
from prose. Explicit structured records select original quoted occurrences.
"""
from pathlib import Path
import hashlib
import json
import re

SCHEMA='spatial_speech_grounding/v26'
PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT/'data/video_generation/spatial_minute_experiments_20261107_v1'
QUOTE=re.compile(r'“[^”]*”|「[^」]*」')
FIELDS={'quote_index','quote_sha256','speaker_id','mode'}
STYLE='plain_actor_action/v26r2'
LEGACY_STYLE='engineering_closeup/v26r1'
TRUSTED_MAP={
    'S01':(('ye_xijue','dialogue'),('ye_nan','dialogue'),('ye_xijue','dialogue')),
    'S02':(('su_mo','inner'),('ye_xijue','dialogue')),
    'S03':(('su_mo','inner'),('ye_xijue','inner')),
    'S04':(('su_mo','dialogue'),('ye_xijue','dialogue'),('su_mo','inner')),
}
TRUSTED_SOURCE_SHAS={
    'S01':'43e8c4321f9971b8d18d40bf0ff4491c76a7f063567dee3951561db180aa041a',
    'S02':'c862c10c416b2f465d8fb334b079effd9e1448b2f9b4fefed069aa47315ae2b7',
    'S03':'be5234eb336624cbe7802fe54cd09504b451b3fd698490d5d05226d1f9952f22',
    'S04':'2fb8a4148500c68643ceeb85c8b9c9a234dcfdae8ad719aaadb554db1a163f35',
}


class SpeechGroundingError(ValueError):pass


def sha(data):return hashlib.sha256(data).hexdigest()
def binding(path):
    p=Path(path).resolve();return dict(path=str(p),sha256=sha(p.read_bytes()))
def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:
        raise SpeechGroundingError('source_or_reference_file_changed')
    return Path(value['path'])
def read(path):return json.loads(Path(path).read_bytes().decode('utf-8'))
def freeze(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data:raise SpeechGroundingError('frozen_output_differs_use_new_revision')
    else:
        with path.open('xb') as stream:stream.write(data)
def freeze_json(path,value):freeze(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def spans(source):
    if not isinstance(source,str) or not source.strip():raise SpeechGroundingError('complete_source_text_required')
    values=list(QUOTE.finditer(source))
    # Ambiguous nested/unbalanced dialogue must be structured upstream, not guessed.
    remainder=QUOTE.sub('',source)
    if any(c in remainder for c in '“”「」'):raise SpeechGroundingError('unbalanced_or_nested_quotes_require_explicit_source')
    if not values:raise SpeechGroundingError('source_quoted_speech_required')
    return values


def _actors(actors):
    if not isinstance(actors,dict) or not actors:raise SpeechGroundingError('explicit_actor_mapping_required')
    slots=[]
    for actor_id,a in actors.items():
        if (not isinstance(actor_id,str) or not re.fullmatch('[A-Za-z0-9_-]+',actor_id)
                or not isinstance(a,dict) or set(a)!={'display_name','visual_description','picture_index','image'}
                or any(not isinstance(a[k],str) or not a[k].strip() or any(x in a[k] for x in '\n\r“”「」') for k in ('display_name','visual_description'))
                or type(a['picture_index']) is not int or not 1<=a['picture_index']<=9):
            raise SpeechGroundingError('complete_quote_free_actor_description_required')
        check(a['image']);slots.append(a['picture_index'])
    if len(slots)!=len(set(slots)):raise SpeechGroundingError('one_picture_identity_per_actor_required')
    return actors


def _instruction(actor,mode,style=STYLE):
    name=actor['display_name'];subject='<Picture '+str(actor['picture_index'])+'>中'+actor['visual_description']+name
    # Verification of immutable R1 artifacts remains possible. New production
    # input always uses the plain actor/action style below, without these tags.
    if style==LEGACY_STYLE:
        action=('由'+name+'本人开口说出本句台词：' if mode=='dialogue' else
                name+'本人嘴唇闭合，表情和动作承接本段原文。本句声音是'+name+'的内心独白，以'+name+'的画外音呈现：')
        return '\n【本句声画执行】镜头给'+subject+'面部近景。'+action+'\n'
    if style!=STYLE:raise SpeechGroundingError('unknown_audited_instruction_style')
    if mode=='dialogue':
        return '\n镜头明确呈现'+subject+'的面部及本段原有动作，由'+name+'本人开口说出本句台词：\n'
    else:
        return '\n镜头明确呈现'+subject+'的面部及本段原有动作。'+name+'本人嘴唇闭合，原段中的动作和表情照常演出。本句为'+name+'的内心独白，以'+name+'的画外音呈现：\n'


def compile_prompt(source,source_sha256,records,actors):
    """Insert only, with 0-based quote occurrence IDs and full quoted-span hashes."""
    if sha(source.encode('utf-8'))!=source_sha256:raise SpeechGroundingError('source_text_sha_mismatch')
    original=spans(source);_actors(actors)
    if not isinstance(records,list) or len(records)!=len(original):raise SpeechGroundingError('exact_source_quote_coverage_required')
    seen=set()
    for r in records:
        if not isinstance(r,dict) or set(r)!=FIELDS or type(r.get('quote_index')) is not int:
            raise SpeechGroundingError('explicit_structured_speaker_mode_record_required')
        index=r['quote_index']
        if index in seen or not 0<=index<len(original):raise SpeechGroundingError('unique_in_range_quote_occurrence_required')
        if r.get('speaker_id') not in actors:raise SpeechGroundingError('foreign_or_missing_speaker_rejected')
        if r.get('mode') not in ('dialogue','inner'):raise SpeechGroundingError('explicit_dialogue_or_inner_mode_required')
        if r['quote_sha256']!=sha(original[index].group().encode('utf-8')):raise SpeechGroundingError('original_audio_quote_sha_mismatch')
        seen.add(index)
    if seen!=set(range(len(original))):raise SpeechGroundingError('exact_source_quote_coverage_required')
    ordered=sorted(records,key=lambda r:r['quote_index']);pieces=[];operations=[];cursor=0;compiled_length=0
    for r in ordered:
        m=original[r['quote_index']];prefix=source[cursor:m.start()];text=_instruction(actors[r['speaker_id']],r['mode'])
        pieces.extend([prefix,text]);compiled_length+=len(prefix)
        operations.append(dict(source_char_offset=m.start(),source_utf8_byte_offset=len(source[:m.start()].encode('utf-8')),
            compiled_char_start=compiled_length,compiled_char_end=compiled_length+len(text),inserted_text=text,
            quote_index=r['quote_index'],quote_sha256=r['quote_sha256'],speaker_id=r['speaker_id'],mode=r['mode']))
        compiled_length+=len(text);cursor=m.start()
    pieces.append(source[cursor:]);compiled=''.join(pieces)
    audit=dict(schema=SCHEMA,source_utf8_sha256=source_sha256,compiled_utf8_sha256=sha(compiled.encode('utf-8')),
        source_quote_count=len(original),compiled_quote_count=len(spans(compiled)),records=ordered,insertions=operations,actors=actors,instruction_style=STYLE,
        original_text_modified=False,source_actions_and_timeline_preserved=True,model_calls=0,
        diagnostic_only=True,production_approved=False,publication=False)
    verify(source,compiled,audit)
    return compiled,audit


def restore(compiled,audit):
    if sha(compiled.encode('utf-8'))!=audit['compiled_utf8_sha256']:raise SpeechGroundingError('compiled_text_sha_mismatch')
    result=compiled
    for op in reversed(audit['insertions']):
        start,end=op['compiled_char_start'],op['compiled_char_end']
        if result[start:end]!=op['inserted_text']:raise SpeechGroundingError('audited_insertion_position_or_text_changed')
        result=result[:start]+result[end:]
    if sha(result.encode('utf-8'))!=audit['source_utf8_sha256']:raise SpeechGroundingError('restored_source_not_exact')
    return result


def verify(source,compiled,audit):
    if audit.get('schema')!=SCHEMA or sha(source.encode('utf-8'))!=audit['source_utf8_sha256']:
        raise SpeechGroundingError('audit_source_binding_mismatch')
    if restore(compiled,audit)!=source:raise SpeechGroundingError('source_actions_not_preserved')
    matches=spans(source);before=[m.group() for m in matches];after=[m.group() for m in spans(compiled)]
    if before!=after or len(before)!=audit['source_quote_count'] or len(after)!=audit['compiled_quote_count']:
        raise SpeechGroundingError('quoted_dialogue_or_occurrence_count_changed')
    if len(audit['records'])!=len(before) or len(audit['insertions'])!=len(before):
        raise SpeechGroundingError('audited_occurrence_count_changed')
    replay=[];cursor=0
    for index,(op,record) in enumerate(zip(audit['insertions'],audit['records'])):
        at=op['source_char_offset']
        if (op['quote_index']!=index or record!={k:op[k] for k in FIELDS}
                or at!=matches[index].start() or op['quote_sha256']!=sha(before[index].encode('utf-8'))
                or op['speaker_id'] not in audit['actors'] or op['mode'] not in ('dialogue','inner')
                or op['inserted_text']!=_instruction(audit['actors'][op['speaker_id']],op['mode'],audit.get('instruction_style',LEGACY_STYLE))):
            raise SpeechGroundingError('audited_speaker_mode_or_quote_mapping_changed')
        if at<cursor or len(source[:at].encode('utf-8'))!=op['source_utf8_byte_offset']:
            raise SpeechGroundingError('source_insertion_offsets_changed')
        replay.extend([source[cursor:at],op['inserted_text']]);cursor=at
    replay.append(source[cursor:])
    if ''.join(replay)!=compiled:raise SpeechGroundingError('forward_replay_failed')
    return True


def prepare(spec_path,outdir):
    spec=read(spec_path)
    if spec.get('schema')!='spatial_speech_grounding_spec/v26' or not spec.get('speaker_map_authority'):
        raise SpeechGroundingError('explicit_source_bound_speech_spec_required')
    actors=_actors(spec['actors']);segments=spec.get('segments')
    if not isinstance(segments,list) or not segments or len({s.get('id') for s in segments})!=len(segments):
        raise SpeechGroundingError('unique_source_segments_required')
    outdir=Path(outdir).resolve();documents=[]
    for row in segments:
        sid=row['id']
        if not isinstance(sid,str) or not re.fullmatch('[A-Za-z0-9_-]+',sid):raise SpeechGroundingError('safe_segment_id_required')
        path=check(row['source_prompt']);source=path.read_bytes().decode('utf-8')
        if path.parent==outdir:raise SpeechGroundingError('never_overwrite_original_source_directory')
        compiled,audit=compile_prompt(source,row['source_prompt']['sha256'],row['records'],actors)
        audit.update(segment_id=sid,source_prompt=row['source_prompt'],source_spec=binding(spec_path),actors=actors)
        documents.append((sid,compiled,audit))
    # Validate all segments before writing any output, so malformed later rows
    # cannot masquerade as a successfully prepared complete batch.
    outdir.mkdir(parents=True,exist_ok=True);reading=['# B版逐句声画演出输入（仅CPU编译）\n\n原动作、时间线和原引号内容逐字保留；仅插入逐句具名人物的面部与原有动作、开口/闭口说明。模型正文没有工程标签或示例编号，也不把整段锁为面部近景。未经视频实测，不代表口型问题已解决。\n']
    audits=[]
    for sid,text,audit in documents:
        prompt=outdir/(sid+'.prompt.txt');freeze(prompt,text.encode('utf-8'));audit['output_prompt']=binding(prompt)
        freeze_json(outdir/(sid+'.audit.json'),audit);audits.append(audit)
        reading.append('\n## '+sid+'\n\n```text\n'+text+'\n```\n')
    combined=dict(schema=SCHEMA,source_spec=binding(spec_path),speaker_map_authority=spec['speaker_map_authority'],
        segments=audits,total_original_quotes=sum(x['source_quote_count'] for x in audits),
        original_text_modified=False,instruction_style=STYLE,model_calls=0,diagnostic_only=True,production_approved=False,publication=False)
    freeze_json(outdir/'AUDIT.json',combined);freeze(outdir/'READING.md',''.join(reading).encode('utf-8'))
    return combined


def make_trusted_spec(inputs_path,outdir):
    """Book-specific trusted map from the parent task, never an NLP heuristic."""
    inputs=read(inputs_path);actors={}
    descriptions={
        'su_mo':'穿深色夹克、灰色纽扣衬衫和深色长裤的成年父亲',
        'ye_nan':'穿灰色翻领短袖上衣和深色长裤的哥哥',
        'ye_xijue':'穿米色圆领短袖上衣和灰色短裤的弟弟',
    }
    for i,ref in enumerate(inputs['references'][:3],1):
        actor=ref['entity_id']
        if actor not in descriptions:raise SpeechGroundingError('trusted_book_actor_mapping_changed')
        actors[actor]=dict(display_name=ref['display_name'],visual_description=descriptions[actor],picture_index=i,image=ref['image'])
    if list(actors)!=['su_mo','ye_nan','ye_xijue']:raise SpeechGroundingError('trusted_picture_order_changed')
    if [s['id'] for s in inputs['segments']]!=list(TRUSTED_MAP):raise SpeechGroundingError('trusted_four_source_segments_required')
    segments=[]
    for row in inputs['segments']:
        if row['adapted_prompt']['sha256']!=TRUSTED_SOURCE_SHAS[row['id']]:
            raise SpeechGroundingError('trusted_map_requires_exact_known_source_revision')
        source=check(row['adapted_prompt']).read_bytes().decode('utf-8');matches=spans(source);mapping=TRUSTED_MAP[row['id']]
        if len(matches)!=len(mapping):raise SpeechGroundingError('trusted_source_quote_count_changed')
        records=[dict(quote_index=i,quote_sha256=sha(matches[i].group().encode('utf-8')),speaker_id=actor,mode=mode)
                 for i,(actor,mode) in enumerate(mapping)]
        segments.append(dict(id=row['id'],source_prompt=row['adapted_prompt'],records=records))
    value=dict(schema='spatial_speech_grounding_spec/v26',source_inputs=binding(inputs_path),
        speaker_map_authority='Explicit trusted speaker/mode occurrence map in parent agent task; no model/NLP speaker inference.',
        actors=actors,segments=segments,diagnostic_only=True,publication=False)
    path=Path(outdir)/'INPUT_SPEC.json';freeze_json(path,value);return path
