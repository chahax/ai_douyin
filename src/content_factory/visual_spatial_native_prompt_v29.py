"""Source-bound English Ref2VA prompt compiler, official six-section format.

English visual events are explicit reviewable input, not NLP speaker guesses.
Original Chinese quoted words are inserted only from source occurrence records.
No media API, model request, production-plan mutation or language-model rewrite.
"""
from pathlib import Path
from copy import deepcopy
import json
import re
from . import visual_spatial_speech_grounding_v26 as speech

ROOT=speech.ROOT
FORMAT='official_ref2va_v29'
SECTIONS=('subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music')
SUBJECTS={'su_mo':1,'ye_nan':2,'ye_xijue':3}
PERSON={
 'su_mo':'Su Mo, the adult father in a dark jacket, gray buttoned shirt and dark trousers',
 'ye_nan':'Ye Nan, the older boy in a gray short-sleeved polo shirt and dark long trousers',
 'ye_xijue':'Ye Xijue, the younger boy in a beige crew-neck T-shirt and gray shorts',
}
VOICE={'su_mo':'a natural medium-low adult male Mandarin voice','ye_nan':'a gentle, relatively steady young boy Mandarin voice','ye_xijue':'a lighter, younger-sounding boy Mandarin voice'}
REFERENCES_URL='https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt'
BASE_URL='https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt'


class NativePromptError(ValueError):pass


def _english(value):
    if not isinstance(value,str) or not value.strip() or re.search('[\u3400-\u9fff“”「」]',value):
        raise NativePromptError('english_visual_input_required_dialogue_only_from_source')
    return value


def _timestamp(ms):
    if type(ms) is not int or not 0<=ms<15000:raise NativePromptError('within_fifteen_seconds_integer_cut_required')
    return f'{ms//60000:02d}:{ms//1000%60:02d}.{ms%1000:03d}'


def _refs(refs):
    expected=[('character','su_mo'),('character','ye_nan'),('character','ye_xijue'),('place','su_mo_room'),('place','su_mo_room')]
    if not isinstance(refs,list) or [(r.get('kind'),r.get('entity_id')) for r in refs]!=expected:
        raise NativePromptError('five_actual_reference_slots_in_named_order_required')
    for r in refs:speech.check(r['image'])


def _fragment(source,start,end):
    return dict(char_start=start,char_end=end,utf8_byte_start=len(source[:start].encode('utf-8')),
        text=source[start:end],sha256=speech.sha(source[start:end].encode('utf-8')))


def validate_native_prompt(text,expected_quotes=None):
    """Pure format check for the later explicit delivery opt-in; no file access."""
    if not isinstance(text,str):raise NativePromptError('native_prompt_text_required')
    headings=re.findall(r'(?m)^([a-z_]+):\s*$',text)
    if headings!=list(SECTIONS):raise NativePromptError('exact_six_english_sections_required')
    dblocks=re.findall(r'<d>\[Mandarin Chinese\] (.*?)</d>',text,re.S)
    if text.count('<d>')!=len(dblocks) or text.count('</d>')!=len(dblocks):raise NativePromptError('only_complete_Mandarin_dialogue_blocks_allowed')
    if not dblocks or any(len(speech.spans(block))!=1 or speech.spans(block)[0].group()!=block for block in dblocks):
        raise NativePromptError('one_original_quote_per_Mandarin_dialogue_block_required')
    if expected_quotes is not None and dblocks!=expected_quotes:raise NativePromptError('original_quote_order_or_words_changed')
    outside=re.sub(r'<d>.*?</d>','',text,flags=re.S)
    if re.search('[\u3400-\u9fff“”「」]',outside):raise NativePromptError('non_english_outside_dialogue')
    if set(map(int,re.findall(r'<Picture (\d+)>',text)))!={1,2,3,4,5} or re.search(r'<(?:Audio|Video)\s',text):
        raise NativePromptError('invented_or_missing_reference_asset_tag')
    if set(map(int,re.findall(r'<Subject (\d+)>',text)))!={1,2,3,4}:
        raise NativePromptError('stable_three_people_and_room_subjects_required')
    body=text.split('detailed_description:\n',1)[1].split('\noverall_soundscape:',1)[0]
    shots=re.findall(r'\[Shot (\d+)\](?: At (\d\d:\d\d\.\d{3}),)?',body)
    if len(re.findall(r'\[Shot \d+\]',text))!=len(shots):raise NativePromptError('shot_markers_only_in_detailed_description')
    if not shots or [int(x[0]) for x in shots]!=list(range(1,len(shots)+1)) or shots[0][1] or any(not x[1] for x in shots[1:]):
        raise NativePromptError('first_shot_untimed_later_shots_exact_cut_timestamps')
    times=[int(x[1][:2])*60000+int(x[1][3:5])*1000+int(x[1][6:]) for x in shots[1:]]
    if times!=sorted(set(times)) or any(not 0<t<15000 for t in times):raise NativePromptError('strictly_increasing_cut_times_required')
    if re.search(r'\(S\d+\)',text.split('retention_analysis:\n',1)[1].split('\ndetailed_description:',1)[0]):
        raise NativePromptError('speaker_ids_not_in_retention_analysis')
    for inner in re.finditer(r'(<Subject \d+>) \(S\d+\)[^\n]*?says in an off-screen voiceover: <d>.*?</d>',body):
        if not body[inner.end():].startswith(' while '+inner.group(1)+"'s lips remain completely closed."):
            raise NativePromptError('inner_voice_immediately_requires_same_subject_closed_lips')
    return True


def compile_segment(source,source_binding,records,events,refs,summary_en,tradeoff=None,task_type='reference generation'):
    if speech.sha(source.encode('utf-8'))!=source_binding['sha256']:raise NativePromptError('source_text_sha_changed')
    _refs(refs);original=speech.spans(source)
    if len(records)!=len(original) or [r.get('quote_index') for r in records]!=list(range(len(original))):
        raise NativePromptError('complete_ordered_explicit_speech_records_required')
    speaker_map={}
    for r,m in zip(records,original):
        if (set(r)!=speech.FIELDS or r['speaker_id'] not in SUBJECTS or r['mode'] not in ('dialogue','inner')
                or r['quote_sha256']!=speech.sha(m.group().encode('utf-8'))):raise NativePromptError('source_bound_speaker_mode_quote_mismatch')
        speaker_map.setdefault(r['speaker_id'],len(speaker_map)+1)
    if not events or events[0]['start_ms']!=0 or events[-1]['end_ms']!=15000:
        raise NativePromptError('complete_fifteen_second_event_timeline_required')
    pieces=[];seen=[];audit_events=[];last_end=0
    for i,event in enumerate(events):
        start,end=event['start_ms'],event['end_ms']
        if type(start) is not int or type(end) is not int or start!=last_end or not start<end<=15000:
            raise NativePromptError('contiguous_original_event_timeline_required')
        last_end=end;visual=_english(event['visual_en']);fragments=event['source_fragments']
        for fragment in fragments:
            a,b=fragment['char_start'],fragment['char_end']
            if (type(a) is not int or type(b) is not int or not 0<=a<b<=len(source)
                    or _fragment(source,a,b)!=fragment):raise NativePromptError('source_event_offset_or_quote_evidence_changed')
        clocks=[(int(a)*1000,int(b)*1000) for fragment in fragments for a,b in re.findall(r'(?:^|\n)(?:开头立即开始对话。)?(\d+)—(\d+)秒',fragment['text'])]
        if clocks!=[(start,end)]:raise NativePromptError('source_event_clock_must_match_original_timed_span')
        indices=event['quote_indices'];slots=re.findall(r'\{speech:(\d+)\}',visual)
        if slots!=[str(x) for x in indices]:raise NativePromptError('exact_event_speech_placeholder_order_required')
        for index in indices:
            if type(index) is not int or not 0<=index<len(records) or index in seen:raise NativePromptError('duplicate_or_foreign_speech_occurrence')
            m=original[index]
            if not any(x['char_start']<=m.start()<m.end()<=x['char_end'] for x in fragments):raise NativePromptError('speech_not_in_current_source_event')
            record=records[index];actor=record['speaker_id'];subject='<Subject '+str(SUBJECTS[actor])+'> (S'+str(speaker_map[actor])+')'
            voice=PERSON[actor]+' with '+VOICE[actor]
            utterance='<d>[Mandarin Chinese] '+m.group()+'</d>'
            if record['mode']=='inner':spoken=subject+', '+voice+', says in an off-screen voiceover: '+utterance+' while '+subject.split(' (')[0]+"'s lips remain completely closed."
            else:spoken=subject+', '+voice+', '+_english(event.get('delivery_en','speaks naturally'))+': '+utterance
            visual=visual.replace('{speech:'+str(index)+'}',spoken);seen.append(index)
        prefix='[Shot '+str(i+1)+'] '+('At '+_timestamp(start)+', ' if i else '')
        pieces.append(prefix+visual);audit_events.append(deepcopy(event))
    if seen!=list(range(len(records))):raise NativePromptError('all_original_speech_events_once_required')
    definitions=[]
    for actor,number in SUBJECTS.items():definitions.append('<Subject '+str(number)+'> is '+PERSON[actor]+' from <Picture '+str(number)+'>. The identity and clothing come from that portrait.')
    definitions.append('<Subject 4> is the same modest room shown from two viewpoints in <Picture 4> and <Picture 5>, with its single bed, small wooden table and existing door and window openings.')
    retention=[]
    for number in (1,2,3):retention.append('<Subject '+str(number)+'>: fully_preserved - retain the portrait identity and clothing throughout visible appearances; poses and expressions follow the current action.')
    retention.append('<Subject 4>: fully_preserved - preserve one common room layout and the same furniture through changing views.')
    if task_type not in ('reference generation','reference generation + keyframe completion'):raise NativePromptError('explicit_supported_reference_task_type_required')
    text='subject_definitions:\n'+'\n'.join(definitions)+'\n\nsummary:\n['+task_type+'] '+_english(summary_en)+'\n\nretention_analysis:\n'+'\n'.join(retention)
    text+='\n\ndetailed_description:\nLive-action Chinese family drama, vertical 9:16. Daylight and room appearance follow <Subject 4>; facial and hand detail remain photographic.\n'+'\n'.join(pieces)
    text+='\n\noverall_soundscape:\nQuiet room tone with soft breathing, clothing rustles, light footsteps and the plastic bread bag moving when handled.\n\nnon_diegetic_music:\nN/A\n'
    validate_native_prompt(text,[m.group() for m in original])
    audit=dict(schema='native_ref2va_prompt_audit/v29',source_prompt=source_binding,compiled_utf8_sha256=speech.sha(text.encode('utf-8')),
        original_quotes=[dict(quote_index=r['quote_index'],quote_sha256=r['quote_sha256'],speaker_id=r['speaker_id'],mode=r['mode'],local_vocal_id='S'+str(speaker_map[r['speaker_id']]),global_subject=SUBJECTS[r['speaker_id']]) for r in records],
        English_visual_events=audit_events,original_quote_count=len(original),picture_slot_count=5,subject_ids=SUBJECTS,
        local_speaker_map=speaker_map,latent_guides_are_not_reference_slots=True,diagnostic_camera_tradeoff=tradeoff,
        source_actions_english_translation_requires_root_semantic_review=True,model_calls=0,production_approved=False,publication=False)
    if task_type!='reference generation':audit['task_type']=task_type
    return text,audit


EVENTS={
 'S01':[
  (0,5000,'A medium view establishes the bed and the three people in <Subject 4>. <Subject 1>, the adult father in his dark jacket and gray shirt, lies asleep with his eyes closed. Beside the bed, <Subject 3>, the younger boy in beige, holds one transparent bag containing bread in both hands at his chest; <Subject 2>, the taller older boy in a gray polo, stands next to him. The younger boy looks up at his brother and tightens his grip on the bag, his face tense. {speech:0}',[0],'says in a low, anxious whisper'),
  (5000,9000,'the camera cuts to <Subject 2>, keeping his gray polo, face, younger brother and their relative positions clear. He bends slightly toward the younger boy and gently rests one hand at the side of his shoulder. {speech:1} The younger boy listens while holding the bag. The father remains asleep on the bed.',[1],'says gently to reassure his younger brother'),
  (9000,13000,'the camera cuts to <Subject 3> in beige as he immediately shakes his head and speaks urgently in a small voice. {speech:2} <Subject 2> listens, his expression becoming worried. The bag stays in the younger boy\'s hands beside the bed.',[2],'says urgently and quietly'),
  (13000,15000,'the camera cuts smoothly to the face of <Subject 1> on the bed. His eyes remain closed, his brow tightens and his breathing becomes heavier as he understands what he has heard. Finish on his closed-eyed face; the two boys remain beside the bed and the younger one still holds the bread bag.',[],'')],
 'S02':[
  (0,7000,'Begin with <Subject 1> still on the same bed in <Subject 4>, wearing his dark jacket and gray shirt. The boys remain beside the bed and <Subject 3> holds the bread. The camera comes close to the father\'s pale face as he endures a headache with his eyes closed. {speech:0} By the end of this beat, he opens his eyes.',[0],''),
  (7000,12000,'the camera cuts to a medium-close view of all three. Both boys flinch slightly when the father opens his eyes, then move nearer the bedside. <Subject 3>, the younger boy in beige and gray shorts, offers his transparent bag of white bread toward the father, speaking timidly. {speech:1} <Subject 2> stays beside his younger brother.',[1],'says timidly'),
  (12000,15000,'the camera cuts to the younger boy\'s slightly trembling hands holding the bag, then frames <Subject 1> looking down toward the bread and the child. The father is awake but has not reached out to take it. The bread remains in <Subject 3>\'s hands, with <Subject 2> guarding his side.',[],'')],
 'S03':[
  (0,7000,'Continue in <Subject 4> with <Subject 1> awake at the bed edge, <Subject 3> presenting the bread bag and <Subject 2> beside his younger brother. First show the younger boy\'s intact dark eyes, then the father studying his face. {speech:0} The father lowers his gaze in thought and does not take the bread yet.',[0],''),
  (7000,10000,'the camera cuts toward <Subject 3>, the younger boy in beige. His hands tremble more, tears gather in his eyes, and his shoulders draw inward. {speech:1} He squeezes his eyes shut while keeping hold of the bag.',[1],''),
  (10000,13000,'the camera cuts to a view that includes the boys\' movement and the father. <Subject 2>, the older boy in gray, steps half a pace forward to shield his younger brother, his shoulders and back tense. <Subject 1> rises and approaches. The boys recoil instinctively, but the older boy keeps himself in front of the younger one.',[],''),
  (13000,15000,'the camera cuts closer to their hands and faces. <Subject 1> reaches calmly to the bag and takes the bread from <Subject 3>\'s hands. The older boy\'s wary expression gradually turns to shock. As this handover finishes, ease back to a full-body view of the three people standing: the father stands holding the single bread bag, and both boys stand before him.',[],'')],
 'S04':[
  (0,3000,'<Subject 1> stands beside the bed in <Subject 4>, holding the bread he has just received. <Subject 2> protects <Subject 3> at his side, and the route around the bed toward the same room door is clear. The father looks bitter but tries to be gentle. {speech:0}',[0],'says softly'),
  (3000,10000,'the camera cuts to the younger boy\'s face and body as <Subject 3> misunderstands the father and immediately drops to his knees. Keep the kneeling action visible while he speaks urgently. {speech:1} <Subject 2> looks from the father to his younger brother in surprise and uncertainty. The father keeps the bread.',[1],'says urgently'),
  (10000,12000,'the camera cuts to include the clear passage and doorway. <Subject 3> quickly gets up, takes <Subject 2> by the hand, and the two boys run out together along the open route around the foot of the bed. <Subject 1> remains where he is, holding the bread.',[],''),
  (12000,15000,'the camera cuts to <Subject 1> turning toward the doorway through which the boys have left. He freezes in disbelief. {speech:2} End with a close view of his helpless, frustrated face while he grips the bread.',[2],'')],
}
SUMMARIES={
 'S01':'Two brothers beside their sleeping father discuss the missing money, ending on the father listening with his eyes closed.',
 'S02':'The father realizes his new identity in an inner voice, opens his eyes, and the younger boy offers him bread.',
 'S03':'The father studies the frightened younger boy, the older brother shields him, and the father calmly takes the offered bread.',
 'S04':'The father\'s gentle words are misunderstood; the younger boy kneels, the brothers run out, and the father reacts in an inner voice.'}


def make_spec(inputs_path,speech_spec_path,reference_spec_path,out):
    inputs=speech.read(inputs_path);speakers=speech.read(speech_spec_path);reference=speech.read(reference_spec_path);refs=reference['references'];_refs(refs)
    if [s['id'] for s in speakers['segments']]!=list(EVENTS):raise NativePromptError('explicit_four_segment_speaker_map_required')
    segments=[]
    for original,row in zip(inputs['segments'],speakers['segments']):
        sid=row['id'];bound=row['source_prompt']
        if sid!=original['id'] or bound!=original['adapted_prompt']:raise NativePromptError('trusted_speech_map_source_revision_mismatch')
        source=speech.check(bound).read_bytes().decode('utf-8');lines=source.splitlines(keepends=True);timeline=[];offset=0;context=[]
        for line in lines:
            frag=_fragment(source,offset,offset+len(line))
            if re.match(r'^(?:开头立即开始对话。)?\d+—\d+秒',line):timeline.append(frag)
            elif line.startswith(('起点：','紧接前段')):context.append(frag)
            offset+=len(line)
        if len(timeline)!=len(EVENTS[sid]):raise NativePromptError('source_timed_action_span_count_changed')
        events=[]
        for i,(start,end,visual,indices,delivery) in enumerate(EVENTS[sid]):
            events.append(dict(start_ms=start,end_ms=end,source_fragments=(context if i==0 else [])+[timeline[i]],visual_en=visual,quote_indices=indices,delivery_en=delivery))
        tradeoff=('The final framing in [Shot 4] partially_preserved: after the source hand-and-face handover view, the diagnostic terminal guide widens to the approved standing three-person state; this is an explicit camera tradeoff, not a new story event.' if sid=='S03' else None)
        segments.append(dict(id=sid,source_prompt=bound,records=row['records'],events=events,summary_en=SUMMARIES[sid],camera_tradeoff=tradeoff))
    spec=dict(schema='native_ref2va_prompt_spec/v29',prompt_format=FORMAT,source_inputs=speech.binding(inputs_path),trusted_speech_spec=speech.binding(speech_spec_path),reference_spec=speech.binding(reference_spec_path),references=refs,segments=segments,official_guides=[REFERENCES_URL,BASE_URL],model_calls=0,production_approved=False)
    path=Path(out)/'INPUT_SPEC.json';speech.freeze_json(path,spec);return path


def prepare(spec_path,out):
    spec=speech.read(spec_path)
    if spec.get('schema')!='native_ref2va_prompt_spec/v29' or spec.get('prompt_format')!=FORMAT:raise NativePromptError('official_native_spec_required')
    for name in ('source_inputs','trusted_speech_spec','reference_spec'):speech.check(spec[name])
    trusted=speech.read(spec['trusted_speech_spec']['path']);reference=speech.read(spec['reference_spec']['path'])
    if spec['references']!=reference['references']:raise NativePromptError('actual_reference_spec_mapping_changed')
    if len(spec['segments'])!=4 or [s['id'] for s in spec['segments']]!=[s['id'] for s in trusted['segments']]:raise NativePromptError('trusted_four_segment_order_required')
    for row,original in zip(spec['segments'],trusted['segments']):
        if row['source_prompt']!=original['source_prompt'] or row['records']!=original['records']:raise NativePromptError('trusted_speaker_mode_source_binding_changed')
    _refs(spec['references']);documents=[]
    for s in spec['segments']:
        source=speech.check(s['source_prompt']).read_bytes().decode('utf-8')
        text,audit=compile_segment(source,s['source_prompt'],s['records'],s['events'],spec['references'],s['summary_en'],s.get('camera_tradeoff'),s.get('task_type','reference generation'))
        audit.update(segment_id=s['id'],source_spec=speech.binding(spec_path));documents.append((s['id'],text,audit))
    out=Path(out);out.mkdir(parents=True,exist_ok=True);all_audits=[];reading=['# B native Ref2VA v29 — review candidate, no media calls\n\nEnglish event input is explicitly source-bound. Chinese speech is extracted once from original quotes. Model acceptance and video quality remain untested.\n\nDelivery opt-in required: `spec.prompt_format = official_ref2va_v29`; do not append the legacy Chinese reference list.\n']
    if spec.get('revision_note'):reading.append('\nRevision: '+spec['revision_note']+'\n')
    for sid,text,audit in documents:
        path=out/(sid+'.prompt.txt');speech.freeze(path,text.encode('utf-8'));audit['output_prompt']=speech.binding(path);speech.freeze_json(out/(sid+'.audit.json'),audit);all_audits.append(audit)
        reading+=['\n## '+sid+'\n\n```text\n'+text+'\n```\n\n### Source-action correspondence\n']
        for i,event in enumerate(audit['English_visual_events'],1):
            reading.append('\n- Shot '+str(i)+' / '+str(event['start_ms'])+'–'+str(event['end_ms'])+' ms\n\n```text\n'+''.join(x['text'] for x in event['source_fragments'])+'\n```\n')
    result=dict(schema='native_ref2va_prompt_audit_set/v29',prompt_format=FORMAT,source_spec=speech.binding(spec_path),segments=all_audits,total_original_quotes=sum(x['original_quote_count'] for x in all_audits),model_calls=0,production_approved=False,publication=False)
    speech.freeze_json(out/'AUDIT.json',result);speech.freeze(out/'READING.md',''.join(reading).encode('utf-8'));return result
