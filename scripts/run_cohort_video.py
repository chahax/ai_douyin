"""Source-bound cohort screenplay -> sequential Seedance trial; no publishing."""
import argparse,copy,itertools,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_cohort_scene_flow import read,save,identity,verify_file,signature,context,require_actual_review
from src.trend_intelligence.cohort_scene_flow import replay,fit_dialogue_timing,apply_direction_revision,render,check_direction_quotes
from src.content_factory import video_campaign as campaign
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig,SeedanceAPIError

FINAL_CHECKS=('dialogue_action_alignment','source_fidelity','emotional_delivery','causal_ending','physical_feasibility','legal_bounds')
TEXT_CHECKS=('source_fidelity','spatial_continuity','voice_and_timing')
GROUPS=((0,),(1,),(2,3),(4,5),(6,),(7,8))


def source(workflow):
    p=Path(workflow).resolve();run=read(p/'run.json')
    if run['status']!='ready_for_user_review':raise ValueError('Actual accepted cohort script required')
    for value in run['artifacts'].values():verify_file(value)
    require_actual_review(verify_file(run['screenplay_review']),verify_file(run['artifacts']['screenplay']),FINAL_CHECKS)
    _,allowed,cards,_=context(Path(run['trial_dir']),Path(run['summary']['path']).parent,run['summary_review']['path'])
    if signature(cards)!=signature(read(verify_file(run['cohort_cards']))):raise ValueError('Cohort evidence changed')
    c=read(verify_file(run['contract']));d=read(verify_file(run['artifacts']['dialogue']));t=replay(c,allowed)
    t=apply_direction_revision(t,read(verify_file(run['direction_revision'])),d) if run.get('direction_revision') else t
    t=fit_dialogue_timing(c,t,d)
    if check_direction_quotes(t,d) or render(c,t,d)!=verify_file(run['artifacts']['screenplay']).read_text(encoding='utf-8'):raise ValueError('Reviewed screenplay no longer matches source')
    if signature(t)!=signature(read(verify_file(run['artifacts']['scheduled_trace']))):raise ValueError('Source timing changed')
    return run,c,d,t


def pack_segments(c,d,t,allow_integer_extension=False):
    if len(t['beats'])!=9 or c['kind']!='short':raise ValueError('Explicit six-segment trial requires this nine-beat short structure')
    options=[]
    for group in GROUPS:
        rows=[copy.deepcopy(t['beats'][i]) for i in group]
        # Give the last actual payment operation 0.8 s more, never pad empty silence.
        if group==GROUPS[-1]:rows[0]['minimum_action_seconds']+=.8
        choices={}
        for seconds in range(4,16):
            try:choices[seconds]=fit_dialogue_timing(c,dict(t,beats=rows,duration=seconds),[d[i] for i in group])
            except ValueError:pass
        options.append(choices)
    combinations=[v for v in itertools.product(*(x.keys() for x in options)) if sum(v)==45]
    if not combinations and allow_integer_extension:
        possible=[v for v in itertools.product(*(x.keys() for x in options)) if 45<sum(v)<=48]
        if possible:
            nearest=min(map(sum,possible));combinations=[v for v in possible if sum(v)==nearest]
    if not combinations:raise ValueError('No valid 45-second integer segment schedule; revise production timing')
    preferred=[sum(t['beats'][i]['duration'] for i in group) for group in GROUPS]
    chosen=min(combinations,key=lambda v:sum((a-b)**2 for a,b in zip(v,preferred)))
    return [(group,options[i][seconds]) for i,(group,seconds) in enumerate(zip(GROUPS,chosen))]


def natural(text,c):
    for aid,actor in c['characters'].items():
        for loc,label in [('left','左手'),('right','右手'),('bag','包内'),('pocket','衣袋内')]:text=text.replace(aid+':'+loc,actor['name']+label)
    for pid,prop in c['props'].items():text=text.replace(pid,prop['name'])
    return text.replace('table','桌面')


def build_script(workflow,design,execution_revision=None,recipe='v1'):
    if recipe not in ('v1','v2'):raise ValueError('Unknown cohort projection recipe')
    run,c,d,t=source(workflow);parts=pack_segments(c,d,t,recipe=='v2');shots=[];cursor=0
    for i,(group,segment) in enumerate(parts):
        shot_id=f'S{i+1:02d}';duration=int(segment['duration'])
        opening=('这是第一段，建立以下虚构人物和开场，手机仍在包与衣袋中。' if i==0 else
                 '从紧邻上一段已审核原始尾帧接着演，不复位人物、道具，不重演已完成动作。')
        continued=recipe=='v2' and i>0
        text=[opening,c['space'],('人物外貌、衣着、包的位置和站姿承接首帧，按本段动作推进。' if continued else design['opening_composition']),design['lighting'],
              '人物与声线：'+json.dumps(({k:{'voice':v['voice']} for k,v in design['characters'].items()} if continued else design['characters']),ensure_ascii=False),
              '角色对应：'+json.dumps(({k:{'name':v['name']} for k,v in c['characters'].items()} if continued else c['characters']),ensure_ascii=False),
              '本段初始持物：'+natural(json.dumps(segment['beats'][0]['before']['props'],ensure_ascii=False),c),
              (execution_revision['camera_instruction'] if execution_revision and i==0 else '片内允许按已审分镜切换同轴侧的中景和物件特写；说话时回到人物镜头，嘴部清晰可见。')]
        for row,j in zip(segment['beats'],group):
            b=row['beat'];text += [f'本段内{row["start"]:.2f}-{row["end"]:.2f}秒：'+b['framing'],'情绪与表演：'+b['emotion']]
            text += [natural(a,c) for a in row['actions']]
            spoken=sum(sum(ch.isalnum() for ch in line['text']) for line in d[j]['lines'])
            budget=row['duration']-row['minimum_action_seconds']-b['pause'];time=row['start']+row['minimum_action_seconds']
            for line in d[j]['lines']:
                length=sum(ch.isalnum() for ch in line['text']);end=time+budget*length/spoken
                text.append(f'{time:.2f}-{end:.2f}秒，仅{c["characters"][line["speaker"]]["name"]}本人说一次：{line["text"]}');time=end
            if not d[j]['lines']:text.append('这一小段不说话，专心完成上述实际操作。')
        text += ['末态持物：'+natural(json.dumps(segment['beats'][-1]['after']['props'],ensure_ascii=False),c),
                 '原生中文对白，无旁白、解说、配乐、字幕或制作编号。不说话的人自然闭嘴，禁止抢对方台词或声线交换。动作利落，保留必要核对，不放慢拖时间。']
        if execution_revision:text.append('本段末尾保持双人中景，两人嘴部、双手及当前持物均可见，供下一段原始尾帧接续。')
        dialogue=[(c['characters'][line['speaker']]['name'],line['text']) for j in group for line in d[j]['lines']]
        shots.append({'shot_id':shot_id,'duration_seconds':duration,'start_seconds':cursor,'end_seconds':cursor+duration,
            'dialogue_speaker':'、'.join(dict.fromkeys(name for name,_ in dialogue)),
            'dialogue':'\n'.join(name+'：'+line for name,line in dialogue),
            'action':json.dumps([t['beats'][j]['beat']['ops'] for j in group],ensure_ascii=False),
            'source_beats':[t['beats'][j]['beat']['id'] for j in group],
            'model_prompt_zh':'\n'.join(text),'segment_trace':segment})
        cursor+=duration
    return {'schema':'cohort_video_script/v1','title':c['title'],'target_duration_seconds':cursor,
        'characters':[{'name':v['name'],'identity':v['name']} for v in c['characters'].values()],
        'version':{'shots':[{k:s[k] for k in ('shot_id','duration_seconds','dialogue_speaker','dialogue','action')} for s in shots]},
        'shots':shots,'source_screenplay':run['artifacts']['screenplay'],'source_review':run['screenplay_review'],
        'timing_note':'Integer API durations preserve all authored lines and operations; final transfer operation gets 0.8 seconds additional action time.'}


def verify_bundle(bundle):
    p=Path(bundle).resolve();b=read(p/'bundle.json')
    for item in b['bindings'].values():verify_file(item)
    require_actual_review(b['bindings']['design_review']['path'],b['bindings']['design']['path'],('identity','opening_state','voice'))
    revision=None
    if b['bindings'].get('camera_provenance'):
        provenance=read(b['bindings']['camera_provenance']['path'])
        for v in provenance.values():verify_file(v)
        revision=read(provenance['model_candidate']['path'])
        if set(revision)!={'camera_instruction'} or not isinstance(revision['camera_instruction'],str):raise ValueError('Invalid model camera revision')
    expected=build_script(b['workflow'],read(b['bindings']['design']['path']),revision,b.get('projection_recipe','v1'))
    if expected!=read(verify_file(b['script'])):raise ValueError('Mechanical video script changed')
    return b,expected


def make_bundle(workflow,design,review,output,camera_provenance=None,recipe='v1'):
    p=Path(output).resolve();p.mkdir(parents=True,exist_ok=False)
    revision=read(read(camera_provenance)['model_candidate']['path']) if camera_provenance else None
    script=build_script(workflow,read(design),revision,recipe);save(p/'script.json',script)
    bindings={'design':identity(design),'design_review':identity(review)}
    if camera_provenance:bindings['camera_provenance']=identity(camera_provenance)
    save(p/'bundle.json',{'schema':'cohort_video_bundle/v1','projection_recipe':recipe,'workflow':str(Path(workflow).resolve()),
        'bindings':bindings,'script':identity(p/'script.json')})
    verify_bundle(p);return p


def prepare(bundle,shot_id,folder,authorization,previous=None):
    b,script=verify_bundle(bundle);p=Path(folder).resolve()
    if p.exists():raise ValueError('New output folder required')
    shot=next(s for s in script['shots'] if s['shot_id']==shot_id)
    from scripts.run_screenplay_trial import preceding_reference
    plan={'shot_id':shot_id,'previous_run':str(Path(previous).resolve()) if previous else None,'bindings':{'story':b['script']}}
    refs,reference=preceding_reference(plan)
    config=SeedanceConfig.from_env('ark_api',require_key=False)
    if config.model!='doubao-seedance-2-0-mini-260615':raise ValueError('Trial requires configured Seedance 2.0 Mini')
    with SeedanceClient(config) as client:payload=client.build_task_payload(shot['model_prompt_zh'],duration=shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    p.mkdir(parents=True);save(p/'locked_script.json',script);save(p/'request.preview.json',payload);save(p/'trial_plan.json',plan)
    (p/f'{shot_id}.prompt.txt').write_text(shot['model_prompt_zh'],encoding='utf-8')
    manifest={'schema':'script_video_run/v1','trial_schema':'reviewed_cohort_segment/v1','title':script['title'],'provider':'ark_api',
        'api_model':config.model,'api_base_url':config.base_url,'source_screenplay':b['script']['path'],'source_script':b['script']['path'],
        'script_sha256':campaign.file_sha(p/'locked_script.json'),'shots':[s['shot_id'] for s in script['shots']],
        'allowed_shots':[shot_id],'test_shot':shot_id,'authorization':authorization,'status':'prepared','review_result':'pending',
        'video_generation_submitted':False,'published':False,'reference_binding':reference,'bundle':str(Path(bundle).resolve()),
        'bundle_sha256':campaign.file_sha(Path(bundle)/'bundle.json'),'request_sha256':campaign.file_sha(p/'request.preview.json'),
        'target_duration_seconds':script['target_duration_seconds'],'test_duration_seconds':shot['duration_seconds'],'created_at':campaign.beijing_now()}
    save(p/'production.json',manifest);return p


def submit(folder):
    p=Path(folder).resolve();m=read(p/'production.json');shot=m['test_shot'];receipt=p/f'{shot}.json'
    if receipt.exists():raise ValueError('Existing receipt: query only')
    if campaign.file_sha(Path(m['bundle'])/'bundle.json')!=m['bundle_sha256']:raise ValueError('Bundle binding changed')
    _,script=verify_bundle(m['bundle'])
    if script!=read(p/'locked_script.json') or campaign.file_sha(p/'locked_script.json')!=m['script_sha256']:raise ValueError('Locked source changed')
    require_actual_review(p/'text_review.json',p/f'{shot}.prompt.txt',TEXT_CHECKS)
    expected_shot=next(s for s in script['shots'] if s['shot_id']==shot)
    expected_prompt=execution_prompt(m,expected_shot)
    if (p/f'{shot}.prompt.txt').read_text(encoding='utf-8')!=expected_prompt:raise ValueError('Prompt changed')
    from scripts.run_screenplay_trial import preceding_reference
    with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
        if client.config.model!=m['api_model'] or client.config.base_url!=m['api_base_url']:raise ValueError('Provider changed')
        if m.get('opening_image'):
            from scripts.run_screenplay_trial import opening_reference
            refs,reference=opening_reference(p,client.config,m)
        else:refs,reference=preceding_reference(read(p/'trial_plan.json'),client)
        if reference!=m['reference_binding']:raise ValueError('Original tail binding changed')
        payload=client.build_task_payload(expected_prompt,duration=expected_shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
        if payload!=read(p/'request.preview.json') or campaign.file_sha(p/'request.preview.json')!=m['request_sha256']:raise ValueError('Prepared request changed')
        if not m.get('campaign_path'):raise ValueError('Attach existing campaign before paid submission')
        record={'shot':shot,'provider':'ark_api','status':'submitting','created_at':campaign.beijing_now(),'script_sha256':m['script_sha256'],
            'prompt_sha256':campaign.file_sha(p/f'{shot}.prompt.txt'),'request':payload,'references':[],**reference}
        campaign.reserve(p,m,record);save(receipt,record);m.update(status='generating',video_generation_submitted=True);save(p/'production.json',m)
        try:response=client.create_task(payload)
        except Exception as exc:
            record.update(status='submission_unknown',error_type=type(exc).__name__)
            if isinstance(exc,SeedanceAPIError) and exc.status_code and 400<=exc.status_code<500:record.update(status='request_rejected',provider_error_code=exc.error_code)
            save(receipt,record);campaign.reconcile_rejection(m,record);raise
        record.update(status='submitted',submit_id=response['id'],provider_response=response,submitted_at=campaign.beijing_now());save(receipt,record)
    return {'status':record['status'],'task_id':record['submit_id']}


def verify_retry(folder,manifest,record,previous):
    b,script=verify_bundle(manifest['bundle']);old_manifest=read(Path(previous['run_dir'])/'production.json')
    if manifest.get('execution_repair'):
        repair=read(verify_file(manifest['execution_repair']))
        # campaign.review keeps an identical canonical copy under <shot>.quality_review.json.
        if (identity(verify_file(repair['failed_review']))['sha256']!=previous['review_sha256']
                or campaign.file_sha(previous['review_path'])!=previous['review_sha256']):raise ValueError('Repair must address last failed review')
        if repair['previous_manifest']!=identity(Path(previous['run_dir'])/'production.json'):raise ValueError('Repair source changed')
        if script!=read(old_manifest['source_screenplay']):raise ValueError('Execution repair must preserve the entire script')
        expected=execution_prompt(manifest,next(s for s in script['shots'] if s['shot_id']==record['shot']))
        if (Path(folder)/f'{record["shot"]}.prompt.txt').read_text(encoding='utf-8')!=expected or record['prompt_sha256']==previous['prompt_sha256']:raise ValueError('Repair prompt not applied')
        return {'method':'model_cohort_segment_execution_repair','provenance':manifest['execution_repair'],'story_unchanged':True}
    provenance=read(verify_file(b['bindings']['camera_provenance']))
    if provenance['previous_bundle']!=identity(Path(old_manifest['bundle'])/'bundle.json'):raise ValueError('Retry must bind last failed bundle')
    if provenance['failed_review']!={'path':previous['review_path'],'sha256':previous['review_sha256']}:raise ValueError('Retry must address last actual failure')
    if record['prompt_sha256']==previous['prompt_sha256']:raise ValueError('Failed execution prompt not revised')
    if script['version']!=read(old_manifest['source_screenplay'])['version']:raise ValueError('Camera-only retry cannot rewrite screenplay')
    return {'method':'model_camera_revision_for_failed_cohort_segment','provenance':b['bindings']['camera_provenance'],'story_unchanged':True}


def execution_prompt(manifest,shot):
    if not manifest.get('execution_repair'):return shot['model_prompt_zh']
    repair=read(verify_file(manifest['execution_repair']))
    if repair['shot_id']!=shot['shot_id']:raise ValueError('Wrong repair shot')
    for key in ('failed_review','previous_manifest','model_candidate','model_run','model_raw'):verify_file(repair[key])
    from src.trend_intelligence.cohort_scene_flow import strict_json
    candidate=read(repair['model_candidate']['path'])
    if strict_json(Path(repair['model_raw']['path']).read_text(encoding='utf-8'))!=candidate:raise ValueError('Repair not original model output')
    if read(repair['model_run']['path']).get('model_calls')!=1:raise ValueError('Real model repair required')
    if set(candidate)!={'execution_constraints'} or not isinstance(candidate['execution_constraints'],str) or not candidate['execution_constraints'].strip():raise ValueError('Invalid execution constraints')
    normalized=''.join(c for c in candidate['execution_constraints'] if c.isalnum())
    for line in shot['dialogue'].splitlines():
        spoken=line.split('：',1)[-1];spoken=''.join(c for c in spoken if c.isalnum())
        if spoken and spoken in normalized:raise ValueError('Execution constraints must not repeat authored dialogue')
    base=shot['model_prompt_zh']
    recipe=repair.get('recipe','append/v1')
    if recipe=='replace_camera/v2':
        rows=[]
        for line in base.splitlines():
            if line.startswith('本段内') and '秒：' in line:
                line=line.split('秒：',1)[0]+'秒：摄影按下述已审执行修正。'
            if line.startswith('片内允许按已审分镜'):continue
            rows.append(line)
        base='\n'.join(rows)
    elif recipe!='append/v1':raise ValueError('Unknown execution repair recipe')
    return base+'\n本次针对上次失败的摄影执行修正（对白、道具归属及事件顺序不变；摄影冲突以本项为准）：\n'+candidate['execution_constraints']


def bind_execution_repair(folder,repair_path):
    from scripts.run_screenplay_trial import preceding_reference
    p=Path(folder).resolve();m=read(p/'production.json');shot_id=m['test_shot']
    if (p/f'{shot_id}.json').exists() or m.get('execution_repair'):raise ValueError('Bind once before submission')
    m['execution_repair']=identity(repair_path)
    _,script=verify_bundle(m['bundle']);shot=next(s for s in script['shots'] if s['shot_id']==shot_id);prompt=execution_prompt(m,shot)
    with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
        refs,binding=preceding_reference(read(p/'trial_plan.json'),client)
        if binding!=m['reference_binding']:raise ValueError('Adjacent tail changed')
        payload=client.build_task_payload(prompt,duration=shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    (p/'request.before_repair.json').write_bytes((p/'request.preview.json').read_bytes())
    (p/f'{shot_id}.prompt.txt').write_text(prompt,encoding='utf-8');save(p/'request.preview.json',payload)
    m['request_sha256']=campaign.file_sha(p/'request.preview.json');save(p/'production.json',m)


def bind_opening(folder,image,review):
    from scripts.run_screenplay_trial import opening_reference
    p=Path(folder).resolve();m=read(p/'production.json')
    if m['test_shot']!='S01' or (p/'S01.json').exists() or m.get('opening_image'):raise ValueError('Bind once before first submission')
    m.update(opening_image=str(Path(image).resolve()),opening_review=str(Path(review).resolve()),opening_review_sha256=campaign.file_sha(review))
    with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
        refs,binding=opening_reference(p,client.config,m)
        _,script=verify_bundle(m['bundle']);shot=script['shots'][0]
        payload=client.build_task_payload(shot['model_prompt_zh'],duration=shot['duration_seconds'],references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    (p/'request.before_opening.json').write_bytes((p/'request.preview.json').read_bytes());save(p/'request.preview.json',payload)
    m.update(reference_binding=binding,request_sha256=campaign.file_sha(p/'request.preview.json'));save(p/'production.json',m)


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['submit','query']);p.add_argument('--run-dir',required=True);a=p.parse_args()
    if a.operation=='submit':result=submit(a.run_dir)
    else:
        from scripts.run_script_video import query_ark
        folder=Path(a.run_dir);m=read(folder/'production.json');record=read(folder/f'{m["test_shot"]}.json')
        with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:result=query_ark(folder,record,client)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
