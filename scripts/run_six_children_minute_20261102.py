"""Explicit four-shot Seedance minute; immutable inputs and one POST per shot."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig,SeedanceReference,ARK_BASE_URL,ARK_MINI_MODEL
from src.content_factory.assistant_seedance_batch import durable,process_lock

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/video_generation/six_children_seedance_60s_20261102'
SOURCE=ROOT/'data/corpus_production_trials/20261102_continuity_cards_first_three/chapter_001_script/SCREENPLAY.md'
COMMON='''真人写实中国家庭短剧，竖屏9:16，普通话对白与原生同步音轨。承接输入首帧的同一组人物面貌、身材、服装、道具和房间空间。
现代城中村旧出租屋，傍晚，左侧靠墙旧木床，后侧旧木桌，右后方门口，昏黄电灯。同一场景的灯、床、桌、门维持同一位置。苏墨是穿深色夹克、灰色内搭的成年男子；叶南是穿蓝灰短袖、深色长裤的学龄男孩；叶西决是穿浅米色旧短袖、灰色短裤的六岁男孩，双眼完整明亮。
角色声线固定：苏墨自然中低男声，叶南稚嫩但较稳的男童声，叶西决更轻更稚嫩的男童声。所有明确对白为自然普通话、对应说话人口型；心声为指定角色的独立画外音，该角色保持思考神态、嘴唇自然闭合。镜头平顺切换中景、面部近景和手部近景，动作与对白同步推进，最后一个有信息的反应完成即收束。画面以纯剧情影像呈现，叙事信息通过表演和声音传达。声音以人声、轻微衣物及脚步、安静房间底噪为主。
'''
SHOTS=[
dict(id='S01',duration=15,title='兄弟低声商量',source_ids=['CH1-P001','CH1-P002','CH1-P003','CH1-P004','CH1-P005'],
text='''起点：苏墨闭眼躺在床上，叶西决双手在胸前捧着透明塑料袋包的面包，叶南站在他旁边，三人位置以输入首帧为准。
开头立即开始对话。0—5秒，叶西决仰头望着哥哥，压低声音：“二哥，今天没偷到钱，怎么办呀？”他捏紧袋口，脸上紧张。
5—9秒，叶南微微俯身看着弟弟，轻声安抚：“哥哥发传单挣了十块，先给你。”他的手轻落在弟弟肩侧。
9—13秒，叶西决立即摇头，急而小声地说：“不行，你没交上钱，他会打你的。”叶南听着，表情变得担心。
13—15秒，平顺切到苏墨闭着眼的面部近景。他眉心绷紧，呼吸稍重，听懂了床边对话。结束时他仍闭眼躺着，两个孩子仍在床边，面包在叶西决双手中。'''),
dict(id='S02',duration=15,title='穿书与面包',source_ids=['CH1-P006','CH1-P007','CH1-P008','CH1-P009','CH1-P014','CH1-P015','CH1-P016','CH1-P017'],
text='''紧接前段，苏墨仍躺在原床，两个孩子站在床边，叶西决捧着面包。
0—7秒，苏墨面部近景，闭眼忍着头痛，成年男声心声：“我竟然穿成了六个孩子的恶毒继父。书里，他们长大后会报复我。”画面始终表现此刻床边的真实身体与表情，脸色发白，最后睁开眼睛。
7—12秒，回到三人中近景，两个孩子被他睁眼吓得轻轻一缩，随即围近床沿。叶西决把透明袋装的白面包往苏墨面前递，怯怯开口：“爸爸，这是好心人给我的面包。”
12—15秒，手部近景见捧着面包的小手略微发抖，接苏墨低头看面包与孩子的近景。他尚未伸手接。结束时面包仍在叶西决手中，苏墨已醒，叶南守在弟弟旁边。'''),
dict(id='S03',duration=15,title='伸手前的恐惧',source_ids=['CH1-P020','CH1-P022','CH1-P023','CH1-P024','CH1-P025','CH1-P026','CH1-P027','CH1-P028','CH1-P030','CH1-P031','CH1-P032','CH1-P033'],
text='''紧接前段。面包仍由叶西决举在苏墨面前，苏墨醒着在床沿，叶南在弟弟身侧。
0—7秒，镜头先给叶西决完整黑亮的双眼，再回到苏墨凝视他的脸。苏墨成年男声心声：“这孩子后来成了独眼神医。还好，现在他的眼睛还是完好的。”苏墨低头沉思，没有立刻接面包。
7—10秒，叶西决的小手抖得更明显，眼里泛起泪光，男童心声：“他一定在想怎么打我。”他闭紧眼睛，肩膀缩起。
10—13秒，叶南向前半步挡在弟弟身前，肩背绷紧；苏墨起身走近。两个孩子下意识瑟缩，叶南仍挡着弟弟。
13—15秒，给三人手部及脸部中近景。苏墨的手平稳伸到面包袋上，只把面包从叶西决手里拿走，叶南警觉的脸慢慢变成震惊。结束时苏墨站着拿面包，两个孩子站在他面前。'''),
dict(id='S04',duration=15,title='好意被误解',source_ids=['CH1-P033','CH1-P034','CH1-P036','CH1-P037','CH1-P038','CH1-P039','CH1-P040','CH1-P041'],
text='''紧接前段，苏墨站在床沿，手里拿着刚接过来的面包，叶南护在叶西决身侧。房门仍位于右后方，退开的路径清楚。
0—3秒，苏墨露出苦涩而尽量温和的表情，轻声说：“做得很好，下次不要了。”
3—10秒，叶西决误会了他的意思，立刻跪下，急切地说：“好的爸爸，我下次一定不会只带个面包，我会偷很多钱回来。”叶南惊疑地看看苏墨，又看弟弟。
10—12秒，叶西决迅速起身，拉住叶南的手，两人一起沿床尾空出的通道向右后方房门跑出去，苏墨站在原处拿着面包。
12—15秒，苏墨转头看着他们离开的门口，怔住，成年男声心声：“我说的是，不要再出去偷东西啊！”结束在他握着面包、无奈又懊恼的面部近景。''')]

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def event(run,message):
    with (run/'LOG.md').open('a',encoding='utf-8') as f:f.write(f'{now()} {message}\n')
def binding(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))

def trusted_opening(run):
    provenance=read(run/'assets/PROVENANCE.json')
    receipt_path=Path(provenance['receipt']['path'])
    if sha(receipt_path)!=provenance['receipt']['sha256']:raise ValueError('asset_receipt_changed')
    receipt=read(receipt_path);request_path=receipt_path.parent/'request.json';request=read(request_path)
    if receipt.get('status')!='downloaded' or receipt.get('model')!='doubao-seedream-5-0-pro-260628' or receipt.get('reference_image') is not None or 'image' in request:raise ValueError('native_text_to_image_required')
    if sha(request_path)!=receipt['request_sha256']:raise ValueError('asset_request_changed')
    opening=run/'assets/opening.original.jpeg'
    if sha(opening)!=receipt['image_sha256'] or sha(receipt['image'])!=receipt['image_sha256']:raise ValueError('native_original_changed')
    return opening,provenance

def prepare(run=RUN):
    if (run/'PLAN.json').exists():raise ValueError('already_prepared')
    opening,provenance=trusted_opening(run)
    prompts=[]
    for shot in SHOTS:
        folder=run/'segments'/shot['id'];folder.mkdir(exist_ok=False)
        p=folder/'PROMPT.txt';p.write_text(COMMON+'\n'+shot['text'],encoding='utf-8')
        prompts.append(dict(**shot,prompt=binding(p)))
    plan=dict(version='six_children_seedance_minute/v1',source=binding(SOURCE),opening=binding(opening),
        model=ARK_MINI_MODEL,provider='ark_api',resolution='720p',ratio='9:16',generate_audio=True,
        shots=prompts,max_video_submissions=4,automatic_retry=False,code=binding(__file__),asset_provenance=binding(run/'assets/PROVENANCE.json'))
    durable(run/'PLAN.json',plan,immutable=True)
    durable(run/'AUTHORIZATION.json',dict(user_request='先来个一分钟的视频分段生成',
        user_route='Seedance：优先出片速度，使用现有云接口',scope='本次4段约60秒，统一开场图和原生尾帧连续生成，完成后合成供用户审片',
        new_video_submissions=4,new_opening_images=1,source_script_hand_edited=False,editorial_excerpt_by='primary_assistant',
        per_segment_content_status='awaiting_human_review',publication=False,automatic_media_retry=False,prior_attempt=provenance.get('prior_attempt')),immutable=True)
    durable(run/'ASSET_MANIFEST.json',dict(asset_id='six_children.opening.20261102.v1',type='opening_frame_and_identity_reference',
        original_source='same_account_seedream_text_to_image',provenance=provenance,local=binding(opening),current_use='first_shot_first_frame',
        casting_is_production_design=True,source_facts='六岁叶西决，学龄儿童叶南，成年苏墨；三个虚构人物',
        reuse_search='personal_catalog_v1无当前人物/出租屋适配资产',video_content_approved=False),immutable=True)
    durable(run/'STATE.json',dict(status='prepared',created_at=now(),segments={},video_posts=0,content_status='awaiting_human_review'))
    (run/'SCREENPLAY_60S.md').write_text('# 一分钟试片：下次不要了\n\n第一章开场摘编；前情、制作备注不朗读。四段各15秒；对白/心声原生生成，时长以实际回执为准。\n\n'+ '\n\n'.join(f"## {s['id']} {s['title']}（{(i)*15}—{(i+1)*15}秒）\n\n{s['text']}" for i,s in enumerate(SHOTS)),encoding='utf-8')
    event(run,'PREPARED 4 shots; first chapter opening; explicit Seedance choice; original scripts unchanged')
    return plan

def validate(run):
    plan=read(run/'PLAN.json')
    for row in [plan['source'],plan['opening'],plan['code'],plan['asset_provenance']]+[s['prompt'] for s in plan['shots']]:
        if sha(row['path'])!=row['sha256']:raise ValueError('frozen_input_changed')
    if len(plan['shots'])!=4 or sum(s['duration'] for s in plan['shots'])!=60:raise ValueError('minute_scope_changed')
    trusted_opening(run)
    return plan

def image_uri(path):
    raw=Path(path).read_bytes()
    if raw.startswith(b'\x89PNG'):mime='image/png'
    elif raw.startswith(b'\xff\xd8'):mime='image/jpeg'
    else:raise ValueError('invalid_original_frame')
    return 'data:'+mime+';base64,'+base64.b64encode(raw).decode()

def metadata(path):
    result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',check=True)
    value=json.loads(result.stdout)
    if not any(s['codec_type']=='video' for s in value['streams']) or not any(s['codec_type']=='audio' for s in value['streams']):raise ValueError('video_or_audio_missing')
    return value

def execute(run=RUN,client=None,sleep=time.sleep,probe=metadata):
    with process_lock(run/'.process.lock'):
        plan=validate(run);state=read(run/'STATE.json');owned=client is None
        if owned:
            config=SeedanceConfig.from_env('ark_api')
            if config.base_url!=ARK_BASE_URL or config.model!=plan['model']:raise ValueError('configured_provider_changed')
            client=SeedanceClient(config)
        try:
            for index,shot in enumerate(plan['shots']):
                sid=shot['id'];folder=run/'segments'/sid;row=state['segments'].get(sid,{})
                if row.get('status')=='complete':
                    if sha(folder/'video.mp4')!=row['video']['sha256'] or sha(folder/'last_frame.original')!=row['tail']['sha256']:raise ValueError('saved_output_changed')
                    continue
                if row.get('status') in ('submit_outcome_unknown','request_rejected','failed','cancelled','expired'):raise ValueError('existing_attempt_not_resubmitted')
                if not row:
                    first=Path(plan['opening']['path']) if index==0 else run/'segments'/plan['shots'][index-1]['id']/'last_frame.original'
                    if index and state['segments'][plan['shots'][index-1]['id']]['status']!='complete':raise ValueError('parent_not_complete')
                    payload=client.build_task_payload(Path(shot['prompt']['path']).read_text(encoding='utf-8'),duration=shot['duration'],
                        ratio=plan['ratio'],resolution=plan['resolution'],generate_audio=True,return_last_frame=True,
                        seed=2026110200+index,references=[SeedanceReference('image',image_uri(first),'first_frame')],task_type='first_frame')
                    durable(folder/'INPUT_BINDING.json',dict(first_frame=binding(first),kind='authored_opening' if index==0 else 'provider_original_tail',parent_id=None if index==0 else state['segments'][plan['shots'][index-1]['id']]['task_id']),immutable=True)
                    durable(folder/'REQUEST.actual.json',payload,immutable=True)
                    row=dict(status='submit_outcome_unknown',task_id=None,submitted_at=now());state['segments'][sid]=row
                    state['video_posts']+=1
                    if state['video_posts']>plan['max_video_submissions']:raise ValueError('submission_bound')
                    state['status']='running';durable(run/'STATE.json',state);event(run,f'SUBMIT_INTENT {sid} once')
                    response=client.create_task(payload)
                    durable(folder/'SUBMISSION_RESPONSE.json',response,immutable=True)
                    row.update(status='submitted',task_id=response['id']);durable(run/'STATE.json',state)
                    with (run/'job_ids.txt').open('a',encoding='utf-8') as f:f.write(sid+' '+response['id']+'\n')
                    event(run,f'SUBMITTED {sid} {response["id"]}');print(sid+' submitted '+response['id'],flush=True)
                deadline=time.monotonic()+3600
                while True:
                    task=client.get_task(row['task_id']);durable(folder/'TASK.latest.json',task)
                    if task['status']!=row['status']:
                        row['status']=task['status'];durable(run/'STATE.json',state);event(run,f'{sid} {task["status"]}')
                    if task['status']=='succeeded':break
                    if task['status'] in ('failed','cancelled','expired'):raise ValueError('provider_terminal_failure')
                    if time.monotonic()>deadline:raise TimeoutError('query_timeout_keep_original_id')
                    sleep(20)
                client.download_video(task,folder/'video.mp4');client.download_last_frame(task,folder/'last_frame.original')
                info=probe(folder/'video.mp4');image_uri(folder/'last_frame.original')
                durable(folder/'METADATA.json',info,immutable=True)
                row.update(status='complete',video=binding(folder/'video.mp4'),tail=binding(folder/'last_frame.original'),usage=task.get('usage'),content_status='awaiting_human_review')
                durable(run/'STATE.json',state);event(run,f'SAVED {sid} original video/audio/tail; awaiting_human_review');print(sid+' saved',flush=True)
            state['status']='all_segments_saved';durable(run/'STATE.json',state)
        except Exception as exc:
            if 'row' in locals() and row.get('status')=='submit_outcome_unknown' and isinstance(getattr(exc,'status_code',None),int) and 400<=exc.status_code<500:
                row['status']='request_rejected';row['http_status']=exc.status_code
            state['status']='stopped';state['error']=dict(type=type(exc).__name__,message=str(exc)[:600]);durable(run/'STATE.json',state)
            event(run,'STOP '+type(exc).__name__+'; original attempt retained');raise
        finally:
            if owned:client.close()

def assemble(run=RUN):
    plan=validate(run);state=read(run/'STATE.json')
    if not all(state['segments'].get(s['id'],{}).get('status')=='complete' for s in plan['shots']):raise ValueError('segments_incomplete')
    paths=[run/'segments'/s['id']/'video.mp4' for s in plan['shots']]
    for shot,path in zip(plan['shots'],paths):
        if sha(path)!=state['segments'][shot['id']]['video']['sha256']:raise ValueError('video_changed')
    listing=run/'concat.txt';listing.write_text(''.join("file '"+p.resolve().as_posix()+"'\n" for p in paths),encoding='utf-8')
    output=run/'deliverables/six_children_opening_60s_review.mp4'
    if output.exists():raise ValueError('assembly_already_exists')
    command=['ffmpeg','-nostdin','-v','warning','-f','concat','-safe','0','-i',str(listing),'-map','0:v:0','-map','0:a:0',
        '-c:v','copy','-c:a','aac','-b:a','160k','-af','aresample=async=1:first_pts=0','-movflags','+faststart',str(output)]
    durable(run/'ASSEMBLY_COMMAND.json',command,immutable=True)
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    (run/'assembly.stderr.log').write_text(result.stderr,encoding='utf-8');result.check_returncode()
    info=metadata(output);durable(run/'DELIVERY.json',dict(video=binding(output),metadata=info,content_status='awaiting_human_review',video_content_reviewed=False,original_video_packets_preserved=True),immutable=True)
    state.update(status='delivered_awaiting_human_review',delivery=str(output.resolve()));durable(run/'STATE.json',state);event(run,'ASSEMBLED original video packets + continuous AAC; awaiting_human_review')
    print(str(output.resolve()),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute','assemble']);p.add_argument('--run',type=Path,default=RUN);a=p.parse_args()
    globals()[a.command](a.run)
