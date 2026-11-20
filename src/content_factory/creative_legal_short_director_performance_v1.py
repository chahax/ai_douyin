"""Source-preserving direction, per-beat performance and deterministic schedule.
Coarse physical state is explicit; finger geometry and true audio remain media checks.
"""
from copy import deepcopy
import json,re
from jsonschema import Draft202012Validator
from scripts.creative_resume_dispatch_v3 import digest
VERSION="legal_short_direction_performance/v1"
CHARACTERS=["小林（虚构劳动者）","周姐（虚构人事主管）"]
STATE_VALUES={
 "badge_location":["xiaolin_neck"],
 "paper_location":["zhou_table_side","table_middle","zhou_folder"],
 "paper_facing":["face_up","inside_folder"],
 "paper_signed":["unsigned"],
 "pen_location":["zhou_table_side","table_middle","zhou_folder"],
 "folder_location":["zhou_table_side","zhou_carried"],
 "zhou_position":["seated_opposite","standing","outside_room"],
 "xiaolin_position":["seated"],
 "xiaolin_hands":["table_edge","knees_tense","knees_relaxed"]}
INITIAL={"badge_location":"xiaolin_neck","paper_location":"zhou_table_side","paper_facing":"face_up","paper_signed":"unsigned","pen_location":"zhou_table_side","folder_location":"zhou_table_side","zhou_position":"seated_opposite","xiaolin_position":"seated","xiaolin_hands":"table_edge"}

def obj(p):return {"type":"object","additionalProperties":False,"properties":p,"required":list(p)}
def text():return {"type":"string","minLength":1}
def arr(item,minimum=0,maximum=None):
 s={"type":"array","items":item,"minItems":minimum}
 if maximum is not None:s["maxItems"]=maximum
 return s
def state_schema():return obj({k:{"enum":v} for k,v in STATE_VALUES.items()})
def catalog(script):return {f"{b['id']}.S{i+1:02}":deepcopy(s) for b in script['beats'] for i,s in enumerate(b['steps'])}
def own_refs(script,beat):return [k for k in catalog(script) if k.startswith(beat+'.')]
def direction_schema(script):
 refs=list(catalog(script));shot=obj({"shot_id":text(),"beat_id":{"enum":[b['id'] for b in script['beats']]},"source_refs":arr({"enum":refs},1),"new_information":text(),"observation_target":text(),"framing":text(),"stimulus_and_response":text(),"cut_reason":text()})
 window=obj({"source_ref":{"enum":refs},"phase":{"enum":["before","during","after"]},"observer":{"enum":CHARACTERS},"minimum_seconds":{"type":"number","minimum":0.5,"maximum":6},"purpose":text()})
 return obj({"emotional_arc":text(),"causal_chain":text(),"ending_intent":text(),"spatial_design":text(),"initial_state":state_schema(),"assets":arr(obj({"id":text(),"definition":text(),"story_function":text()}),1),"shots":arr(shot,4,6),"reaction_windows":arr(window,4,12)})
def validate_direction(d,script):
 Draft202012Validator(direction_schema(script)).validate(d)
 if d['initial_state']!=INITIAL:raise ValueError('opening prerequisites inconsistent with original source')
 allrefs=list(catalog(script));covered=[];ids=[]
 for shot in d['shots']:
  ids.append(shot['shot_id']);covered+=shot['source_refs']
  if any(r not in own_refs(script,shot['beat_id']) for r in shot['source_refs']):raise ValueError('shot crosses beat ownership')
 if covered!=allrefs or len(ids)!=len(set(ids)):raise ValueError('all original source steps must occur once, in order')
 pairs=[(w['source_ref'],w['phase'],w['observer']) for w in d['reaction_windows']]
 if len(pairs)!=len(set(pairs)):raise ValueError('duplicate window')
 if set(w['source_ref'].split('.')[0] for w in d['reaction_windows'])!=set(b['id'] for b in script['beats']):raise ValueError('each beat needs a purposeful reaction requirement')
 return {'source_steps':len(allrefs),'shots':len(ids),'initial_prerequisites_valid':True,'creative_quality_passed':False}
def performance_schema(script,beat):
 rows=[];c=catalog(script)
 for ref in own_refs(script,beat):
  changes=arr(obj({'field':{'enum':list(STATE_VALUES)},'from':text(),'to':text()}))
  if c[ref]['kind']=='dialogue':changes.update(maxItems=0)
  rows.append(obj({'source_ref':{'const':ref},'before_seconds':{'type':'number','minimum':0,'maximum':3},'before_performance':text(),'active_seconds':{'type':'number','exclusiveMinimum':0,'maximum':12},'active_performance':text(),'after_seconds':{'type':'number','minimum':0,'maximum':3},'after_performance':text(),'state_changes':changes}))
 return obj({'beat_id':{'const':beat},'start_state':state_schema(),'rows':{'type':'array','prefixItems':rows,'items':False,'minItems':len(rows),'maxItems':len(rows)},'end_state':state_schema()})
def apply_changes(state,row):
 fields=[]
 for c in row['state_changes']:
  k=c['field'];fields.append(k)
  if c['from']!=state[k] or c['to'] not in STATE_VALUES[k] or c['from']==c['to']:raise ValueError('impossible state precondition/transition: '+k)
  state[k]=c['to']
 if len(fields)!=len(set(fields)):raise ValueError('ambiguous repeated state change')
 if (state['paper_location']=='zhou_folder') != (state['paper_facing']=='inside_folder'):raise ValueError('paper face/location inconsistency')
 return state
# Obligations are checks derived from original textual events, never action additions.
SOURCE_STATE_OBLIGATIONS={
 'B1.S01':INITIAL,
 'B1.S03':{'paper_location':'table_middle','pen_location':'table_middle'},
 'B2.S04':{'xiaolin_hands':'table_edge'},
 'B3.S01':{'paper_location':'table_middle','xiaolin_hands':'knees_tense'},
 'B4.S01':{'paper_location':'zhou_folder','paper_facing':'inside_folder','pen_location':'zhou_folder','folder_location':'zhou_carried','zhou_position':'standing'},
 'B4.S03':{'zhou_position':'outside_room','xiaolin_position':'seated'},
 'B4.S04':{'xiaolin_hands':'knees_relaxed','xiaolin_position':'seated'}}

def compile_prefix(script,d,performances):
 validate_direction(d,script);state=deepcopy(d['initial_state']);clock=0.;out=[];checks=[];sources=catalog(script)
 expectedbeats=[b['id'] for b in script['beats']][:len(performances)]
 if [p['beat_id'] for p in performances]!=expectedbeats:raise ValueError('beat order/duplicate invalid')
 shotfor={r:s for s in d['shots'] for r in s['source_refs']}
 for p in performances:
  Draft202012Validator(performance_schema(script,p['beat_id'])).validate(p)
  if p['start_state']!=state:raise ValueError('cross-beat state mismatch')
  for row in p['rows']:
   ref=row['source_ref'];src=sources[ref];before=deepcopy(state)
   if src['kind']=='dialogue':
    speech=len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',src['text']))/5
    if row['active_seconds']+1e-9<speech:raise ValueError('dialogue compressed above five spoken characters/second: '+ref)
   for w in d['reaction_windows']:
    if w['source_ref']==ref:
     field={'before':'before_seconds','during':'active_seconds','after':'after_seconds'}[w['phase']]
     if row[field]+1e-9<w['minimum_seconds']:raise ValueError('reaction window too short: '+ref+' '+w['phase'])
     checks.append({'source_ref':ref,'phase':w['phase'],'observer':w['observer'],'minimum_seconds':w['minimum_seconds'],'actual_seconds':row[field],'mechanical_status':'satisfied','actual_media_readability':None})
   if src['kind']=='dialogue' and row['state_changes']:raise ValueError('state operation embedded in dialogue')
   state=apply_changes(state,row)
   for key,val in SOURCE_STATE_OBLIGATIONS.get(ref,{}).items():
    if state[key]!=val:raise ValueError('original action state missing: '+ref+' '+key)
   active_start=clock+row['before_seconds'];active_end=active_start+row['active_seconds'];end=active_end+row['after_seconds']
   out.append({'source_ref':ref,'shot_id':shotfor[ref]['shot_id'],'beat_id':p['beat_id'],'source_kind':src['kind'],'speaker':src['speaker'],'original_text':src['text'],'start':round(clock,6),'active_start':round(active_start,6),'active_end':round(active_end,6),'end':round(end,6),'before_performance':row['before_performance'],'active_performance':row['active_performance'],'after_performance':row['after_performance'],'start_state':before,'end_state':deepcopy(state),'original_performance_row_sha256':digest(row)})
   clock=end
  if state!=p['end_state']:raise ValueError('end state must equal compiled transitions')
 shots=[]
 for s in d['shots']:
  found=[r for r in out if r['shot_id']==s['shot_id']]
  if found:shots.append({**deepcopy(s),'start':found[0]['start'],'end':found[-1]['end'],'duration':round(found[-1]['end']-found[0]['start'],6)})
 if clock > 180:raise ValueError('short remake exceeds 180 seconds; revise complete performance')
 return {'schema':VERSION,'script_sha256':digest(script),'direction_sha256':digest(d),'performance_sha256s':[digest(p) for p in performances],'complete':len(performances)==len(script['beats']),'total_duration_seconds':round(clock,6),'shots':shots,'schedule':out,'reaction_window_checks':checks,'final_state':state,'real_audio_or_video_verified':False,'physical_scope':'coarse source state; small paper realignment remains within table_middle; native-frame continuity and real sound/readability await human review'}
def compile_complete(script,d,performances):
 c=compile_prefix(script,d,performances)
 if not c['complete'] or len(c['schedule'])!=len(catalog(script)):raise ValueError('complete performance required')
 return c
def evidence_catalog(context):
 out={}
 def walk(v,path):
  if isinstance(v,dict):
   for k,x in v.items():walk(x,path+'.'+str(k) if path else str(k))
  elif isinstance(v,list):
   for i,x in enumerate(v):walk(x,path+'.'+str(i))
  elif isinstance(v,str) and v:out['E'+str(len(out)+1)]={'path':path,'quote':v}
 walk(context,'');return out
def review_schema(context):
 ids=list(evidence_catalog(context));refs=arr({'$ref':'#/$defs/Evidence'},1,6)
 rows=[]
 for b in context['script']['beats']:
  rows.append(obj({'beat_id':{'const':b['id']},'emotion':text(),'causality_and_state':text(),'dialogue_and_reaction_timing':text(),'evidence_refs':deepcopy(refs)}))
 s=obj({'story_preserved':{'type':'boolean'},'coverage':{'type':'array','prefixItems':rows,'items':False,'minItems':len(rows),'maxItems':len(rows)},'issues':arr(obj({'id':text(),'owner':{'enum':['director','performance','script']},'source_refs':arr({'enum':list(catalog(context['script']))},1),'problem':text(),'required_revision':text(),'evidence_refs':deepcopy(refs)})),'suggestions':arr(text()),'assessment':text()})
 s['$defs']={'Evidence':{'enum':ids}};return s
def validate_review(v,context):
 Draft202012Validator(review_schema(context)).validate(v);cat=evidence_catalog(context);expanded=deepcopy(v)
 for row in expanded['coverage']+expanded['issues']:row['evidence_refs']=[deepcopy(cat[e]) for e in row['evidence_refs']]
 for row in expanded['coverage']:
  beatindex=[b['id'] for b in context['script']['beats']].index(row['beat_id'])
  if not any(e['path'].startswith(f'script.beats.{beatindex}.') for e in row['evidence_refs']):raise ValueError('coverage lacks original current beat evidence')
  refs=own_refs(context['script'],row['beat_id']);indexes=[i for i,r in enumerate(context['compiled']['schedule']) if r['source_ref'] in refs]
  if not any(any(e['path'].startswith(f'compiled.schedule.{i}.') for i in indexes) for e in row['evidence_refs']):raise ValueError('coverage lacks actual performance evidence')
 if len({i['id'] for i in v['issues']})!=len(v['issues']):raise ValueError('duplicate issue ids')
 return expanded,{'whole_film_review_valid':True,'issues':len(v['issues']),'story_preserved':v['story_preserved'],'creative_quality_passed':False}
