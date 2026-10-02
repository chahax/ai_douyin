"""Explicit reviewed screenplay segments, gated by actual adjacent-tail approval.

The legacy plan remains S01-only. A continuation needs its own shot-specific
text review and an approved original predecessor; no pair approval is invented.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_screenplay_stage import read_previous_production
from scripts.revise_script_candidate import _source_input
from src.trend_intelligence.script_screenplay import validate_screenplay,verify_story_review
from src.trend_intelligence.script_outline import build_outline_messages
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig,SeedanceAPIError,SeedanceReference
from src.content_factory import video_campaign as campaign
from src.content_factory.script_video_review import REVIEW_CHECKS

read=campaign.read
write=campaign.write
sha=campaign.file_sha


def execution_duration(plan, shot):
    seconds = plan.get('execution_duration_seconds', shot['duration_seconds'])
    if 'execution_duration_seconds' in plan:
        review = read(Path(plan['bindings']['trial_review']['path']))
        if (type(seconds) is not int or not 4 <= seconds <= shot['duration_seconds']
                or review.get('execution_duration_seconds') != seconds
                or not review.get('duration_rationale')):
            raise ValueError('Execution duration requires an explicit reviewed timing projection')
    return seconds


def prompt_for(story,production,shot_id='S01',execution_recipe='legacy'):
    v=story['version']; index=next(i for i,s in enumerate(v['shots']) if s['shot_id']==shot_id)
    s=v['shots'][index]; photo=production['shots'][index]
    if photo['shot_id']!=shot_id: raise ValueError('Production shot order differs')
    start=v['initial_state'] if index==0 else v['shots'][index-1]['end_state']
    if execution_recipe=='screenplay_continuation/v3':
        if index==0: raise ValueError('Continuation recipe requires a preceding shot')
        speaker=next(c for c in story['characters'] if c['name']==s['dialogue_speaker'])
        parts=['接续输入原始尾帧，不重新摆场。保持两个人的脸、衣服、座位、纸笔、灯光和机位。',
               '角色辨认：'+'；'.join(c['name']+'，'+c['appearance']+'，'+c['wardrobe'] for c in story['characters']),
               '本镜声音只有'+speaker['name']+'。固定音色：'+speaker['voice'],
               '声音和表演重点：'+photo['emotion_and_performance'],
               '唯一原生对白，只说一遍：'+s['dialogue'],
               '与对白同时推进的动作，只执行一遍：'+s['action'],
               '摄影：'+photo['composition'],
               '固定焦距与取景，不推近、不切镜，纸笔及双方双手始终入画。保留纸面已有文字纹理，不生成新签名。',
               '最后停在：'+json.dumps(s['end_state'],ensure_ascii=False),
               '另一人全程不出声、不跟说。声音和正在说话的嘴同步；无旁白、音乐、解说、字幕、标题。']
        prompt='\n'.join(parts)
        for prop in v['props']:prompt=prompt.replace(prop['id'],prop['name'])
        return prompt
    parts=([v['scene'],v['spatial_layout'],production['scene_design']['composition'],production['scene_design']['lighting']]
           if index==0 else ['从输入首帧连续推进本镜；输入是紧邻上一段审核通过的原始尾帧。保持其中人物、服装、座位、机位、灯光、纸笔及手部现状，不重置场景、不重复上一段动作。'])
    if execution_recipe not in ('legacy','screenplay_continuation/v2'):
        raise ValueError('Unknown execution recipe')
    if execution_recipe=='screenplay_continuation/v2':
        if index==0: raise ValueError('Continuation recipe requires a preceding shot')
        parts += ['摄影：'+production['scene_design']['shot_size']+'，'+production['scene_design']['camera_movement']+'；'+photo['composition'],
                  '整个片段固定焦距和取景，保持输入首帧的画幅边界，不推近、不拉远、不变焦、不切镜、不裁掉纸笔和双手；只让已有动作发生。保留纸面已有印刷纹理，不重写合同标题，不在纸上生成角色姓名或新签名。']
    for c in story['characters']:
        voice=('；固定声线：'+c['voice'] if execution_recipe=='legacy' or c['name']==s['dialogue_speaker']
               else '；本镜不发声，嘴部静止')
        parts.append(c['name']+'：'+c['identity']+'，'+c['appearance']+'，'+c['wardrobe']+voice)
    if execution_recipe=='screenplay_continuation/v2':
        speaker=next(c for c in story['characters'] if c['name']==s['dialogue_speaker'])
        parts.append('本段音轨只有'+speaker['name']+'的原生声音：'+speaker['voice']+'另一人不说话，不给另一人分配台词。')
    parts += ['开场状态：'+json.dumps(start,ensure_ascii=False),
              '依序动作：'+s['action'],'表演：'+photo['emotion_and_performance'],
              '仅'+s['dialogue_speaker']+'说以下一句原生对白，不重复：'+s['dialogue'],
              '另一角色全程不说话，嘴部静止。说话人说话时口型匹配其固定声线，结束后自然闭嘴。无旁白，无配音解说，无背景音乐。不生成字幕、标题、水印或制作编号。',
              '结束状态：'+json.dumps(s['end_state'],ensure_ascii=False)]
    prompt='\n'.join(parts)
    for prop in v['props']: prompt=prompt.replace(prop['id'],prop['name'])
    return prompt


def verify_inputs(plan):
    for row in plan['bindings'].values():
        path=Path(row['path']).resolve()
        if not path.is_relative_to(ROOT/'data') or sha(path)!=row['sha256']:
            raise ValueError('Trial source bytes changed')
    paths={k:Path(v['path']) for k,v in plan['bindings'].items()}
    workflow,full=_source_input(read(paths['workflow']),paths['sources'])
    if full is None: raise ValueError('Complete source evidence required')
    build_outline_messages(workflow,'First-shot trial only',reference_source_ids=plan['references'])
    sources=json.loads(workflow[1]['content'])['source_evidence']
    story=read(paths['story']); raw=paths['story'].read_bytes()
    verify_story_review(raw,read(paths['story_review']),workflow_sha=sha(paths['workflow']),source_sha=sha(paths['sources']))
    validate_screenplay(story,'short',45,sources,plan['references'])
    production,_=read_previous_production(paths['production'],'short',story=story,
        screenplay_identity=plan['bindings']['story'],review_identity=plan['bindings']['story_review'],
        workflow_sha=sha(paths['workflow']),source_sha=sha(paths['sources']),reference_source_ids=plan['references'])
    shot_id=plan.get('shot_id','S01')
    prompt=prompt_for(story,production,shot_id,plan.get('execution_recipe','legacy'))
    review=read(paths['trial_review'])
    schema='screenplay_first_shot_review/v1' if shot_id=='S01' else 'screenplay_segment_text_review/v1'
    if (review.get('schema')!=schema or review.get('shot_id')!=shot_id
        or review.get('decision')!='passed' or review.get('story_sha256')!=sha(paths['story'])
        or review.get('production_sha256')!=sha(paths['production'])
        or review.get('prompt_sha256')!=hashlib.sha256(prompt.encode()).hexdigest()
        or not review.get('findings') or review.get('scope')!='text_only_'+shot_id):
        raise ValueError('Trial needs an independent S01 text review of this exact prompt')
    return story,production,prompt


def preceding_reference(plan,client=None):
    shot_id=plan.get('shot_id','S01')
    if shot_id=='S01':
        if plan.get('previous_run'): raise ValueError('Opening shot cannot borrow a video tail')
        return [],{}
    folder=Path(plan['previous_run']).resolve()
    if not folder.is_relative_to(ROOT/'data/video_generation'): raise ValueError('Local preceding run required')
    manifest=read(folder/'production.json');data=read(manifest['campaign_path'])
    index=data['shots'].index(shot_id)
    if index<1: raise ValueError('Continuation must follow S01')
    previous=data['shots'][index-1]
    record=read(folder/(previous+'.json'))
    campaign._run_series(data,manifest,folder)
    attempt=next((a for a in reversed(data['attempts']) if a['id']==record.get('campaign_attempt_id')),None)
    if (not attempt or not campaign.attempt_allows_continuation(data,attempt) or attempt['shot']!=previous
        or attempt.get('series_id')!=data['current_series_id']
        or record.get('status')!='downloaded' or record['script_sha256']!=plan['bindings']['story']['sha256']
        or sha(record['local_video'])!=record['video_sha256'] or sha(record['last_frame'])!=record['last_frame_sha256']
        or sha(attempt['review_path'])!=attempt['review_sha256']):
        raise ValueError('Only the immediately preceding approved original tail may continue')
    review=read(attempt['review_path'])
    if not campaign.review_allows_continuation(data, data['current_series_id'], review):
        raise ValueError('Preceding audio/video review is incomplete')
    response=record['latest_response']
    if client is not None:
        if client.config.model!=manifest['api_model'] or client.config.base_url!=manifest['api_base_url']:
            raise ValueError('Preceding reference provider differs')
        response=client.get_task(record['submit_id'])
    if response.get('status')!='succeeded': raise ValueError('Native source task is not successful')
    created=response.get('created_at')
    if type(created) not in (int,float) or not 0<=datetime.now(timezone.utc).timestamp()-created<86400:
        raise ValueError('Preceding native media URL is outside its 24-hour window')
    url=response['content']['last_frame_url']
    return [SeedanceReference('image',url,'first_frame')],{
        'first_frame_sha256':record['last_frame_sha256'],'first_frame':record['last_frame'],
        'preceding_task_id':record['submit_id'],'preceding_review_sha256':attempt['review_sha256']}


def opening_reference(folder,config,manifest):
    from src.content_factory.ark_opening_frame import _run_inputs,trusted_opening_reference
    image=Path(manifest['opening_image']); review_path=Path(manifest['opening_review'])
    if sha(review_path)!=manifest['opening_review_sha256']: raise ValueError('Opening review changed')
    review=read(review_path)
    if (review.get('decision')!='passed' or review.get('image_sha256')!=sha(image)
        or review.get('story_sha256')!=manifest['script_sha256']
        or set(review.get('checks',{}))!={'identity','spatial_layout','props_and_hands','initial_state'}
        or any(v is not True for v in review['checks'].values()) or not review.get('observations')):
        raise ValueError('Opening image requires actual complete visual review')
    _,actual,direction,_=_run_inputs(folder)
    reference,proof=trusted_opening_reference(folder,image,config,actual,direction)
    return [reference],{'first_frame':str(image),'first_frame_sha256':sha(image),'opening_proof':proof,
                        'opening_review_sha256':sha(review_path)}


def bind_opening(folder,image,review_path):
    folder=Path(folder).resolve();manifest=read(folder/'production.json')
    if manifest.get('test_shot')!='S01' or (folder/'S01.json').exists():
        raise ValueError('Bind before any S01 submission')
    if manifest.get('opening_image'): raise ValueError('Opening is already bound')
    image=Path(image).resolve();review_path=Path(review_path).resolve()
    if not image.is_relative_to(folder) or not review_path.is_relative_to(folder):
        raise ValueError('Opening evidence must stay inside the current run')
    manifest.update(opening_image=str(image),opening_review=str(review_path),opening_review_sha256=sha(review_path))
    with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
        refs,binding=opening_reference(folder,client.config,manifest)
        plan=read(folder/'trial_plan.json')
        if manifest.get('trial_schema')=='reviewed_reference_director_segment/v1':
            from scripts.run_director_video import verify_bundle
            _,story=verify_bundle(manifest['bundle'])
            if story!=read(folder/'locked_script.json'):raise ValueError('Reference source changed')
            prompt=story['shots'][0]['model_prompt_zh']
            if (folder/'S01.prompt.txt').read_text(encoding='utf-8')!=prompt:raise ValueError('Reference prompt changed')
        else:
            story,_,prompt=verify_inputs(plan)
        payload=client.build_task_payload(prompt,duration=story['version']['shots'][0]['duration_seconds'],
                                         references=refs,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    (folder/'request.before_opening.json').write_bytes((folder/'request.preview.json').read_bytes())
    write(folder/'request.preview.json',payload)
    manifest.update(reference_binding=binding,request_sha256=sha(folder/'request.preview.json'))
    write(folder/'production.json',manifest)


def verify_production_retry(folder, manifest, record, previous):
    """A real model production revision can retry unchanged story text."""
    folder=Path(folder).resolve()
    if manifest.get('trial_schema') not in {'reviewed_screenplay_first_shot/v1','reviewed_screenplay_segment/v1'}:
        raise ValueError('Only explicit reviewed screenplay revisions are supported')
    old_folder=Path(previous['run_dir']).resolve()
    old_manifest=read(old_folder/'production.json')
    if old_manifest.get('trial_schema')!=manifest['trial_schema']:
        raise ValueError('Trial cannot inherit unrelated retry provenance')
    if sha(folder/'trial_plan.json')!=manifest['trial_plan_sha256'] or sha(old_folder/'trial_plan.json')!=old_manifest['trial_plan_sha256']:
        raise ValueError('Trial plan changed')
    current_plan=read(folder/'trial_plan.json');old_plan=read(old_folder/'trial_plan.json')
    if current_plan.get('shot_id','S01')!=record['shot'] or old_plan.get('shot_id','S01')!=record['shot']:
        raise ValueError('Retry must revise the same failed shot')
    _,_,prompt=verify_inputs(current_plan)
    _,_,old_prompt=verify_inputs(old_plan)
    if prompt==old_prompt or hashlib.sha256(prompt.encode()).hexdigest()!=record['prompt_sha256']:
        raise ValueError('Retry must change the reviewed execution text')
    if hashlib.sha256(old_prompt.encode()).hexdigest()!=previous['prompt_sha256']:
        raise ValueError('Previous trial request binding changed')
    current=Path(current_plan['bindings']['production']['path'])
    run=read(current.with_name('run.json'))
    parent=run.get('inputs',{}).get('previous_production',{})
    expected=old_plan['bindings']['production']
    if run.get('stage')!='production-revise' or any(parent.get(k)!=v for k,v in expected.items()):
        raise ValueError('Retry requires a project model revision of the last failed production')
    if not previous.get('review_path') or sha(previous['review_path'])!=previous.get('review_sha256'):
        raise ValueError('Previous failed review changed')
    return {'method':'model_production_revision_for_failed_trial','production':str(current),
            'production_sha256':sha(current),'run_sha256':sha(current.with_name('run.json')),
            'previous_review_sha256':previous['review_sha256'],'story_unchanged':True}


def prepare(folder,plan_path,authorization):
    folder=Path(folder).resolve()
    if folder.exists(): raise ValueError('Use a new trial output directory')
    plan=read(plan_path); story,production,prompt=verify_inputs(plan)
    shot_id=plan.get('shot_id','S01')
    shot=next(s for s in story['version']['shots'] if s['shot_id']==shot_id)
    references,reference_binding=preceding_reference(plan)
    if not authorization.strip(): raise ValueError('Explicit trial authorization required')
    with SeedanceClient(SeedanceConfig.from_env('ark_api',require_key=False)) as client:
        payload=client.build_task_payload(prompt,duration=execution_duration(plan,shot),references=references,
                                          resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
        if client.config.model!='doubao-seedance-2-0-mini-260615': raise ValueError('Trial is limited to Seedance 2.0 Mini')
        endpoint=client.config.base_url
    folder.mkdir(parents=True)
    (folder/'locked_script.json').write_bytes(Path(plan['bindings']['story']['path']).read_bytes())
    write(folder/'trial_plan.json',plan)
    write(folder/'request.preview.json',payload)
    (folder/(shot_id+'.prompt.txt')).write_text(prompt,encoding='utf-8')
    manifest={'schema':'script_video_run/v1','trial_schema':('reviewed_screenplay_first_shot/v1' if shot_id=='S01' else 'reviewed_screenplay_segment/v1'),
        'title':story['version']['title']+' · 情绪首段试片','provider':'ark_api','api_model':payload['model'],
        'api_base_url':endpoint,'source_screenplay':plan['bindings']['story']['path'],
        'source_script':plan['bindings']['story']['path'],'script_sha256':sha(folder/'locked_script.json'),
        'shots':[s['shot_id'] for s in story['version']['shots']],'allowed_shots':[shot_id],'test_shot':shot_id,
        'target_duration_seconds':45,'test_duration_seconds':payload['duration'],
        'execution_duration_seconds':payload['duration'],'source_shot_duration_seconds':shot['duration_seconds'],
        'authorization':authorization,'created_at':campaign.now(),'status':'prepared','review_result':'pending',
        'video_generation_submitted':False,'published':False,
        'trial_plan_sha256':sha(folder/'trial_plan.json'),'request_sha256':sha(folder/'request.preview.json'),
        'reference_binding':reference_binding}
    write(folder/'production.json',manifest)
    return manifest


def submit(folder,client):
    folder=Path(folder).resolve(); manifest=read(folder/'production.json')
    shot_id=manifest.get('test_shot','S01'); receipt=folder/(shot_id+'.json')
    if receipt.exists(): raise ValueError('Existing receipt: query only; never resubmit')
    if (manifest.get('trial_schema') not in {'reviewed_screenplay_first_shot/v1','reviewed_screenplay_segment/v1'}
        or manifest.get('allowed_shots')!=[shot_id] or not manifest.get('campaign_path')):
        raise ValueError('Attached S01-only trial required')
    if sha(folder/'trial_plan.json')!=manifest['trial_plan_sha256'] or sha(folder/'request.preview.json')!=manifest['request_sha256']:
        raise ValueError('Prepared trial changed')
    plan=read(folder/'trial_plan.json');story,_,prompt=verify_inputs(plan)
    if plan.get('shot_id','S01')!=shot_id: raise ValueError('Prepared shot differs from reviewed plan')
    if sha(folder/'locked_script.json')!=manifest['script_sha256']: raise ValueError('Locked story changed')
    if client.config.model!=manifest['api_model'] or client.config.base_url!=manifest['api_base_url']:
        raise ValueError('Configured endpoint/model changed')
    references,binding=(opening_reference(folder,client.config,manifest) if manifest.get('opening_image')
                        else preceding_reference(plan,client))
    if binding!=manifest.get('reference_binding',{}): raise ValueError('Preceding reference binding changed')
    shot=next(s for s in story['version']['shots'] if s.get('shot_id',shot_id)==shot_id)
    expected=client.build_task_payload(prompt,duration=execution_duration(plan,shot),references=references,resolution='480p',ratio='9:16',generate_audio=True,return_last_frame=True)
    if expected!=read(folder/'request.preview.json'): raise ValueError('Request differs from reviewed sources')
    record={'shot':shot_id,'provider':'ark_api','status':'submitting','created_at':campaign.now(),
        'script_sha256':manifest['script_sha256'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
        'request':expected,'references':[],**binding}
    campaign.reserve(folder,manifest,record)
    write(receipt,record)
    manifest.update(video_generation_submitted=True,status='generating');write(folder/'production.json',manifest)
    try:
        result=client.create_task(expected)
    except Exception as exc:
        record.update(status='submission_unknown',error_type=type(exc).__name__)
        if isinstance(exc,SeedanceAPIError) and exc.status_code and 400<=exc.status_code<500:
            record.update(status='request_rejected',provider_error_code=exc.error_code)
        write(receipt,record)
        campaign.reconcile_rejection(manifest,record)
        raise
    record.update(status='submitted',submit_id=result['id'],provider_response=result,submitted_at=campaign.now())
    write(receipt,record)
    return {'status':'submitted','shot':shot_id,'submit_id':result['id']}


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['prepare','submit','query'])
    p.add_argument('--run-dir',required=True);p.add_argument('--plan');p.add_argument('--authorization',default='')
    args=p.parse_args();folder=Path(args.run_dir).resolve()
    if not folder.is_relative_to(ROOT/'data/video_generation'): raise ValueError('Project video directory required')
    if args.operation=='prepare': result=prepare(folder,Path(args.plan),args.authorization)
    else:
        with SeedanceClient(SeedanceConfig.from_env('ark_api')) as client:
            if args.operation=='submit': result=submit(folder,client)
            else:
                from scripts.run_script_video import query_ark
                record=read(folder/(read(folder/'production.json')['test_shot']+'.json'))
                result={'status':'downloaded'} if record.get('status')=='downloaded' else query_ark(folder,record,client)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
