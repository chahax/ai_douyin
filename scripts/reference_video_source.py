"""Verify reference-director sources for the existing serial media executor."""
import json
from pathlib import Path
from scripts.build_reference_video_bundle import compile_bundle,reviewed_file
from scripts.run_reference_director import read,digest,check

SCHEMA='reference_director_video_script/v1'

def identity(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':digest(path)}

def build_script(source,prompts):
    source=Path(source).resolve();prompts=Path(prompts).resolve()
    compiled=compile_bundle(source)
    check(compiled==read(prompts/'bundle.json'),'Compiled prompt bundle changed')
    reviewed_file(prompts/'bundle.json',prompts/'review.json')
    plan=read(source/'delivery/execution_plan.json');casting=read(source/'casting/candidate.json')
    shots=[];offset=0
    for shot,segment in zip(compiled['shots'],plan['segments']):
        check((prompts/(shot['shot_id']+'.txt')).read_text(encoding='utf-8')==shot['model_prompt_zh'],'Prompt file changed')
        performance=segment['performance']
        speakers=[casting['characters'][l['speaker']]['name'] for l in performance['lines']]
        rows={**shot,'start_seconds':offset,'end_seconds':offset+shot['duration_seconds'],
              'dialogue_speaker':'、'.join(dict.fromkeys(speakers)),
              'dialogue':'\n'.join(n+'：'+l['text'] for n,l in zip(speakers,performance['lines'])),
              'action':json.dumps(performance['actions'],ensure_ascii=False,sort_keys=True)}
        shots.append(rows);offset+=shot['duration_seconds']
    chars=[{'name':c['name'],'identity':c['name'],'appearance':c['appearance'],'voice':c['voice']} for c in casting['characters'].values()]
    start=plan['space']['layout']+'\n'+json.dumps(plan['space']['opening_positions'],ensure_ascii=False)+'\n'+json.dumps(casting,ensure_ascii=False)
    return {'schema':SCHEMA,'title':compiled['title'],'target_duration_seconds':offset,'characters':chars,'shots':shots,
            'version':{'shots':[{k:s[k] for k in ('shot_id','duration_seconds','dialogue_speaker','dialogue','action')} for s in shots]},
            'opening_state':start,'source_review':identity(prompts/'review.json'),'source_bindings':compiled['sources']}

def make_bundle(source,prompts,output):
    value=build_script(source,prompts);output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'script.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    binding={'schema':'reference_director_video_bundle/v1','source':str(Path(source).resolve()),'prompts':str(Path(prompts).resolve()),
             'review':value['source_review'],'script':identity(output/'script.json')}
    (output/'bundle.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2),encoding='utf-8')
    verify_bundle(output)
    return str(output)

def verify_bundle(output):
    output=Path(output).resolve();binding=read(output/'bundle.json')
    check(binding['schema']=='reference_director_video_bundle/v1','Wrong reference bundle')
    value=build_script(binding['source'],binding['prompts'])
    check(binding['script']==identity(output/'script.json') and read(output/'script.json')==value,'Source projection changed')
    check(binding['review']==value['source_review'],'Source review changed')
    return binding,value
