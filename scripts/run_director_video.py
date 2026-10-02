"""Source-bound accepted director cards -> serial Seedance candidates."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_cohort_scene_flow import read,save,identity,verify_file,require_actual_review
from scripts.test_director_pipeline import reviewed,protocol
from scripts.build_director_workbench import node
from src.content_factory.director_pipeline import compile_cards,CHECKS,require
from src.content_factory import video_campaign as campaign
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig,SeedanceAPIError

TEXT_CHECKS=('source_fidelity','spatial_continuity','voice_and_timing')

def build_script(source):
    p=Path(source).resolve();trial=read(p/'trial.json');final=read(p/'final.review.json')
    require(trial['status']=='accepted_text_only' and trial['protocol']==protocol(),'Current accepted director protocol required')
    require(final['decision']=='passed' and final['unresolved']==[] and set(final['checks'])==set(CHECKS),'Actual full review required')
    require(all(v['passed'] is True and v['evidence'] and v['finding'] for v in final['checks'].values()),'Incomplete full review')
    expected={'outline':p/'outline/candidate.json','script':p/'script.json','photography':p/'photography/candidate.json','delivery':p/'delivery/SCREENPLAY.md'}
    require(final['artifacts']=={k:identity(v) for k,v in expected.items()},'Final reviewed source changed')
    verify_file(trial['sources'])
    outline=reviewed(p,'outline');first=reviewed(p,'script_a');last=reviewed(p,'script_b');photo=reviewed(p,'photography')
    script={'shots':first['shots']+last['shots']}
    require(script==read(p/'script.json'),'Reviewed action/dialogue changed')
    shots=[];offset=0
    for card,s in zip(compile_cards(outline,script,photo),script['shots']):
        prompt,_=node.compile_card(card)
        require(prompt==(p/'delivery'/card['shot_id']/'prompt.txt').read_text(encoding='utf-8'),'Reviewed prompt changed')
        lines=[(outline['characters'][l['speaker']]['name'],l['text']) for l in s['lines']]
        duration=card['duration_seconds']
        shots.append({'shot_id':card['shot_id'],'duration_seconds':duration,'start_seconds':offset,'end_seconds':offset+duration,
            'dialogue_speaker':'、'.join(dict.fromkeys(a for a,_ in lines)),
            'dialogue':'\n'.join(a+'：'+t for a,t in lines),'action':json.dumps(s['actions'],ensure_ascii=False,sort_keys=True),
            'model_prompt_zh':prompt,'director_card':card})
        offset+=duration
    return {'schema':'director_video_script/v1','title':outline['title'],'target_duration_seconds':offset,
        'characters':[{'name':c['name'],'identity':c['identity']} for c in outline['characters'].values()],
        'version':{'shots':[{k:s[k] for k in ('shot_id','duration_seconds','dialogue_speaker','dialogue','action')} for s in shots]},
        'shots':shots,'source_trial':str(p),'source_review':identity(p/'final.review.json')}

def verify_bundle(folder):
    p=Path(folder).resolve();b=read(p/'bundle.json')
    if b.get('schema')=='reference_director_video_bundle/v1':
        from scripts.reference_video_source import verify_bundle as verify_reference
        return verify_reference(p)
    require(b['schema']=='director_video_bundle/v1','Wrong bundle schema')
    verify_file(b['review']);actual=build_script(b['source'])
    require(actual==read(verify_file(b['script'])),'Director video projection changed')
    require(actual['source_review']==b['review'],'Review binding changed')
    return b,actual

def make_bundle(source,output):
    script=build_script(source);p=Path(output).resolve();p.mkdir(parents=True,exist_ok=False)
    save(p/'script.json',script)
    save(p/'bundle.json',{'schema':'director_video_bundle/v1','source':str(Path(source).resolve()),'review':script['source_review'],'script':identity(p/'script.json')})
    verify_bundle(p);return str(p)

def execution_prompt(manifest,shot):
    if not manifest.get('execution_repair'):return shot['model_prompt_zh']
    repair=read(verify_file(manifest['execution_repair']))
    if repair.get('schema') in {'reference_action_visibility_repair/v1','reference_action_visibility_repair/v2','reference_blocking_repair/v1'}:
        for key in ('source_script','previous_manifest','failed_review','model_candidate','model_raw','model_run'):
            verify_file(repair[key])
        script=read(repair['source_script']['path'])
        previous=read(repair['previous_manifest']['path'])
        rejected=read(repair['failed_review']['path'])
        require(repair['source_script']['sha256']==manifest['script_sha256']==previous['script_sha256'], 'Action repair changed source')
        require(repair['shot_id']==shot['shot_id']==previous['test_shot'] and rejected['script_sha256']==manifest['script_sha256'], 'Action repair changed segment')
        require(script.get('schema')=='reference_director_video_script/v1' and shot in script['shots'], 'Action repair needs locked reference source')
        blocking=repair['schema']=='reference_blocking_repair/v1'
        require(rejected['decision']=='failed' and (rejected['checks'].get('action_pace') is False
                or (blocking and rejected['checks'].get('spatial_layout') is False)), 'Actual action failure or blocking spatial failure required')
        from src.trend_intelligence.cohort_scene_flow import strict_json
        value=read(repair['model_candidate']['path'])
        require(value==strict_json(Path(repair['model_raw']['path']).read_text(encoding='utf-8')), 'Repair differs from original model text')
        require(read(repair['model_run']['path'])['model_calls']==1, 'Actual author repair required')
        fields={'composition','father_action','father_end_state'} if blocking else {'composition'}
        require(set(value)==fields and all(isinstance(v,str) and v.strip() for v in value.values()), 'Invalid action visibility repair')
        if blocking:
            # This narrowly scoped repair changes only the rejected father's blocking,
            # while retaining the original segment, dialogue, timing and daughter's action.
            feedback=read(verify_file(repair['user_rejection']))
            user_rejected=read(verify_file(repair['user_rejected_review'])) if repair.get('user_rejected_review') else rejected
            require(feedback.get('decision')=='rejected' and feedback.get('source_sha256')==user_rejected['source_sha256']
                    and user_rejected['decision']=='failed' and user_rejected['script_sha256']==manifest['script_sha256'], 'Blocking repair needs source-bound user rejection')
            require(shot['shot_id']=='S04' and '本段无对白。' in shot['model_prompt_zh'], 'Wrong blocking repair scope')
            require(all('\n' not in value[k] and '\r' not in value[k] for k in ('father_action','father_end_state')), 'Blocking fields cannot add action rows')
        require(all(c.get('appearance','').strip() for c in script['characters']), 'Missing reviewed appearance')
        appearance='\n所有重新入画人物沿用原稿外貌与服装：\n'+'\n'.join(c['name']+'：'+c['appearance'] for c in script['characters'])
        if repair['schema'] in {'reference_action_visibility_repair/v2','reference_blocking_repair/v1'}:
            start='摄影时间表（本段局部秒数，只规定观察与构图）：\n'
            end='\n人物动作时间表：'
            original=shot['model_prompt_zh']
            require(original.count(start)==1 and original.count(end)==1 and original.index(start)<original.index(end), 'Ambiguous reference camera section')
            before,section=original.split(start)
            _,after=section.split(end)
            if blocking:
                rows=after.splitlines()
                prefix='0—1.5秒，父亲：'
                require(sum(row.startswith(prefix) for row in rows)==1, 'Ambiguous father action')
                require(sum(row.startswith('末态：') for row in rows)==1, 'Ambiguous ending state')
                ending=next(row for row in rows if row.startswith('末态：'))
                state=json.loads(ending[len('末态：'):])
                require('父亲' in state and '女儿' in state, 'Missing reviewed ending actors')
                state['父亲']=value['father_end_state']
                after='\n'.join(prefix+value['father_action'] if row.startswith(prefix) else
                    '末态：'+json.dumps(state,ensure_ascii=False) if row==ending else row for row in rows)
            return before+start+value['composition']+end+after+appearance
        return shot['model_prompt_zh']+appearance+'\n摄影与原动作落点的可见性补充（动作顺序、时长与情绪不变）：\n'+value['composition']
    if repair.get('schema')=='reference_identity_continuation/v1':
        script_path=verify_file(repair['source_script']); script=read(script_path)
        previous=read(verify_file(repair['preceding_manifest']))
        review=read(verify_file(repair['preceding_review']))
        require(identity(script_path)['sha256']==manifest['script_sha256']==previous['script_sha256'], 'Continuation changed source')
        ids=[s['shot_id'] for s in script['shots']]
        require(repair['shot_id']==shot['shot_id'] and shot in script['shots']
                and ids.index(shot['shot_id'])>0 and ids[ids.index(shot['shot_id'])-1]==previous['test_shot'], 'Not adjacent continuation')
        complete = (review['decision']=='passed' and all(review['checks'].get(k) is True for k in campaign.REVIEW_CHECKS))
        if not complete and previous.get('campaign_path'):
            data = read(previous['campaign_path'])
            campaign._run_series(data, previous)
            complete = campaign.review_allows_continuation(data, previous['campaign_series_id'], review)
        require(complete and review['script_sha256']==manifest['script_sha256'], 'Preceding review incomplete')
        require(script.get('schema')=='reference_director_video_script/v1', 'Wrong continuation source')
        require(all(c.get('appearance','').strip() for c in script['characters']), 'Missing reviewed appearance')
        return shot['model_prompt_zh']+'\n所有重新入画人物沿用原稿外貌与服装：\n'+'\n'.join(c['name']+'：'+c['appearance'] for c in script['characters'])+'\n只补充身份，不重置原始尾帧状态，不增加动作或对白。'
    if repair.get('schema')=='reference_identity_restore/v1':
        require(repair['shot_id']==shot['shot_id'] and shot['shot_id']!='S01','Wrong identity repair scope')
        previous=read(verify_file(repair['previous_manifest']))
        rejected=read(verify_file(repair['failed_review']))
        script_path=verify_file(repair['source_script'])
        script=read(script_path)
        require(identity(script_path)['sha256']==manifest['script_sha256']==previous['script_sha256'],'Identity repair changed source')
        require(previous['test_shot']==shot['shot_id'] and rejected['script_sha256']==previous['script_sha256'],'Identity repair changed segment')
        require(rejected['decision']=='failed' and rejected['checks'].get('identity') is False,'Actual identity failure required')
        require(script.get('schema')=='reference_director_video_script/v1' and shot in script['shots'],'Identity repair needs locked reference source')
        descriptions=[]
        for character in script['characters']:
            require(bool(character.get('appearance','').strip()),'Missing reviewed appearance')
            descriptions.append(character['name']+'：'+character['appearance'])
        framing = ''
        if repair.get('reviewed_visual'):
            visual_path = verify_file(repair['reviewed_visual'])
            bound = script['source_bindings']['visual']
            require(str(Path(visual_path).resolve())==str(Path(bound['candidate_path']).resolve())
                    and identity(visual_path)['sha256']==bound['candidate_sha256'], 'Visual repair source changed')
            subjects = {s['subject'] for s in read(visual_path)['shots'] if s['beat_id']==shot['beat_id']}
            if subjects in ({'A'}, {'B'}):
                actor = next(iter(subjects))
                # Names come from the verified source bundle, never free-form repair text.
                source_binding, _ = verify_bundle(previous['bundle'])
                casting = read(Path(source_binding['source'])/'casting/candidate.json')
                framing = '\n本段所有镜头只拍'+casting['characters'][actor]['name']+'，其他人物保持画外；不要新增双人镜头或反打。'
        return shot['model_prompt_zh']+'\n重新入画的人物仍是同一人，沿用已审外貌与服装：\n'+'\n'.join(descriptions)+'\n以上仅固定外貌，不重置首帧姿态、不增加人物动作或对白。'+framing
    require(repair['schema']=='director_composition_repair/v1' and repair['shot_id']==shot['shot_id'],'Wrong repair scope')
    for k in ('previous_manifest','failed_review','model_candidate','model_raw','model_run'):verify_file(repair[k])
    from src.trend_intelligence.cohort_scene_flow import strict_json
    value=read(repair['model_candidate']['path'])
    require(value==strict_json(Path(repair['model_raw']['path']).read_text(encoding='utf-8')),'Repair differs from original model text')
    require(read(repair['model_run']['path'])['model_calls']==1,'Actual author repair required')
    require(set(value)=={'composition'} and isinstance(value['composition'],str) and value['composition'].strip(),'Invalid composition repair')
    previous=read(repair['previous_manifest']['path'])
    require(previous['script_sha256']==manifest['script_sha256'] and previous['test_shot']==shot['shot_id'],'Repair changed story or shot')
    rejected=read(repair['failed_review']['path'])
    require(rejected['decision']=='failed' and rejected['checks'].get('spatial_layout') is False,'Actual spatial failure required')
    return '\n'.join('【composition】'+value['composition'] if row.startswith('【composition】') else row for row in shot['model_prompt_zh'].splitlines())

def verify_retry(folder,manifest,record,previous):
    repair=read(verify_file(manifest['execution_repair']))
    require(repair['previous_manifest']==identity(Path(previous['run_dir'])/'production.json'),'Repair not for last failed run')
    require(repair['failed_review']['sha256']==previous['review_sha256'] and campaign.file_sha(previous['review_path'])==previous['review_sha256'],'Repair not for last failed review')
    _,script=verify_bundle(manifest['bundle'])
    require(script==read(Path(previous['run_dir'])/'locked_script.json'),'Composition repair changed full story')
    prompt=execution_prompt(manifest,next(s for s in script['shots'] if s['shot_id']==record['shot']))
    require((Path(folder)/f"{record['shot']}.prompt.txt").read_text(encoding='utf-8')==prompt and record['prompt_sha256']!=previous['prompt_sha256'],'No applied upstream repair')
    method={'reference_identity_restore/v1':'restore_reviewed_identity','reference_action_visibility_repair/v1':'actual_model_action_visibility_repair','reference_action_visibility_repair/v2':'actual_model_reference_camera_replacement','reference_blocking_repair/v1':'actual_model_father_blocking_repair'}.get(repair.get('schema'),'actual_model_composition_repair')
    return {'method':method,'provenance':manifest['execution_repair'],'story_unchanged':repair.get('schema')!='reference_blocking_repair/v1','source_script_unchanged':True,'same_script_failure_budget':True}

def prepare(bundle,shot_id,folder,authorization,previous=None,repair=None):
    from scripts.run_screenplay_trial import preceding_reference
    b,script=verify_bundle(bundle);p=Path(folder).resolve()
    require(p.is_relative_to(ROOT/'data/video_generation'),'Production folder required')
    shot=next(s for s in script['shots'] if s['shot_id']==shot_id)
    plan={'shot_id':shot_id,'previous_run':str(Path(previous).resolve()) if previous else None,'bindings':{'story':b['script']}}
    refs,binding=preceding_reference(plan)
    config=SeedanceConfig.from_env('ark_api',require_key=False)
    require(config.model=='doubao-seedance-2-0-mini-260615','Configured Mini model required')
    repair_binding={'execution_repair':identity(repair)} if repair else {}
    prompt=execution_prompt({'script_sha256':b['script']['sha256'],**repair_binding},shot)
    with SeedanceClient(config) as client:
        payload=client.build_task_payload(prompt,duration=shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    p.mkdir(parents=True,exist_ok=False)
    save(p/'locked_script.json',script);save(p/'request.preview.json',payload);save(p/'trial_plan.json',plan)
    (p/f'{shot_id}.prompt.txt').write_text(prompt,encoding='utf-8')
    trial_schema='reviewed_reference_director_segment/v1' if script.get('schema')=='reference_director_video_script/v1' else 'reviewed_director_segment/v1'
    opening_mode={'opening_mode':shot.get('reference_requirement','reviewed_opening_image')} if trial_schema=='reviewed_reference_director_segment/v1' and shot_id=='S01' else {}
    save(p/'production.json',{'schema':'script_video_run/v1','trial_schema':trial_schema,'title':script['title'],
      'provider':'ark_api','api_model':config.model,'api_base_url':config.base_url,'source_screenplay':b['script']['path'],'source_script':b['script']['path'],
      'script_sha256':campaign.file_sha(p/'locked_script.json'),'shots':[s['shot_id'] for s in script['shots']],
      'allowed_shots':[shot_id],'test_shot':shot_id,'authorization':authorization,'status':'prepared','review_result':'pending',
      'video_generation_submitted':False,'published':False,'reference_binding':binding,'bundle':str(Path(bundle).resolve()),
      'bundle_sha256':campaign.file_sha(Path(bundle)/'bundle.json'),'request_sha256':campaign.file_sha(p/'request.preview.json'),
      'target_duration_seconds':script['target_duration_seconds'],'test_duration_seconds':shot['duration_seconds'],'created_at':campaign.beijing_now(),**repair_binding,**opening_mode})
    return str(p)

def verify_opening_mode(manifest,shot):
    if manifest['trial_schema']!='reviewed_reference_director_segment/v1' or manifest['test_shot']!='S01':
        return
    mode=shot.get('reference_requirement','reviewed_opening_image')
    require(mode in {'text_only','reviewed_opening_image'},'Unknown opening reference requirement')
    require(manifest.get('opening_mode','reviewed_opening_image')==mode,'Opening mode differs from reviewed source')
    if mode=='text_only':
        require(not manifest.get('opening_image') and manifest.get('reference_binding')=={},'Text-only opening cannot contain an image reference')
    else:
        require(bool(manifest.get('opening_image')),'Reference-directed S01 requires an actually reviewed original opening image')

def submit(folder):
    from scripts.run_screenplay_trial import preceding_reference
    p=Path(folder).resolve();m=read(p/'production.json');sid=m['test_shot'];receipt=p/f'{sid}.json'
    require(not receipt.exists(),'Existing receipt: query only')
    require(m['trial_schema'] in {'reviewed_director_segment/v1','reviewed_reference_director_segment/v1'},'Wrong production schema')
    if m['trial_schema']=='reviewed_reference_director_segment/v1' and sid=='S01' and m.get('opening_mode')!='text_only':
        require(bool(m.get('opening_image')),'Reference-directed S01 requires an actually reviewed original opening image')
    require(campaign.file_sha(Path(m['bundle'])/'bundle.json')==m['bundle_sha256'],'Bundle changed')
    _,script=verify_bundle(m['bundle'])
    require(script==read(p/'locked_script.json') and campaign.file_sha(p/'locked_script.json')==m['script_sha256'],'Locked script changed')
    shot=next(s for s in script['shots'] if s['shot_id']==sid)
    verify_opening_mode(m,shot)
    prompt=execution_prompt(m,shot)
    require((p/f'{sid}.prompt.txt').read_text(encoding='utf-8')==prompt,'Execution text changed')
    require_actual_review(p/'text_review.json',p/f'{sid}.prompt.txt',TEXT_CHECKS)
    require(bool(m.get('campaign_path')),'Attach original campaign before submitting')
    with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
        require(client.config.model==m['api_model'] and client.config.base_url==m['api_base_url'],'Provider changed')
        if m.get('opening_image'):
            from scripts.run_screenplay_trial import opening_reference
            refs,binding=opening_reference(p,client.config,m)
        else:
            refs,binding=preceding_reference(read(p/'trial_plan.json'),client)
        require(binding==m['reference_binding'],'Adjacent tail changed')
        payload=client.build_task_payload(prompt,duration=shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
        require(payload==read(p/'request.preview.json') and campaign.file_sha(p/'request.preview.json')==m['request_sha256'],'Prepared request changed')
        record={'shot':sid,'provider':'ark_api','status':'submitting','created_at':campaign.beijing_now(),'script_sha256':m['script_sha256'],
            'prompt_sha256':campaign.file_sha(p/f'{sid}.prompt.txt'),'request':payload,'references':[],**binding}
        campaign.reserve(p,m,record);save(receipt,record)
        m.update(status='generating',video_generation_submitted=True);save(p/'production.json',m)
        try:response=client.create_task(payload)
        except Exception as exc:
            record.update(status='submission_unknown',error_type=type(exc).__name__)
            if isinstance(exc,SeedanceAPIError) and exc.status_code and 400<=exc.status_code<500:
                record.update(status='request_rejected',provider_error_code=exc.error_code)
            save(receipt,record);campaign.reconcile_rejection(m,record);raise
        record.update(status='submitted',submit_id=response['id'],provider_response=response,submitted_at=campaign.beijing_now());save(receipt,record)
    return {'status':record['status'],'task_id':record['submit_id']}

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['bundle','prepare','submit','query'])
    for name in ('source','output','bundle','run-dir','shot','authorization','previous','repair'):ap.add_argument('--'+name)
    a=ap.parse_args()
    if a.operation=='bundle':result=make_bundle(a.source,a.output)
    elif a.operation=='prepare':result=prepare(a.bundle,a.shot,a.run_dir,a.authorization,a.previous,a.repair)
    elif a.operation=='submit':result=submit(a.run_dir)
    else:
        from scripts.run_script_video import query
        with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:result=query(Path(a.run_dir).resolve(),a.shot,client)
    print(json.dumps(result,ensure_ascii=False))
