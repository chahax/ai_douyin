"""Small source-repair extension; immutable v1 and all native results preserved."""
from copy import deepcopy
import datetime as dt
import json
from jsonschema import Draft202012Validator
from src.content_factory import creative_screenplay_world_v1 as prior

VERSION='creative_screenplay_world_source_repair/v2'


def world_schema(brief,casting):
    schema=prior.world_schema(brief,casting)
    schema['properties']['schema']={'const':VERSION+'/world'}
    additions={'clock_start':{'const':'08:00:00'},'clock_end':prior.S,
        'planned_duration_seconds':{'type':'integer','minimum':150,'maximum':180}}
    schema['properties'].update(additions);schema['required']+=list(additions)
    arc=schema['properties']['dramatic_arc']['items']
    arc['properties'].update(start_seconds=prior.N,end_seconds=prior.N)
    arc['required']+=['start_seconds','end_seconds']
    schema['properties']['time_of_day']={'const':'清晨，既有白天窗光与白色顶灯。'}
    return schema


def validate_world(document,brief,casting):
    Draft202012Validator(world_schema(brief,casting)).validate(document)
    # The native source remains untouched; only the necessary old fields are
    # checked through its original validator as an explicitly derived view.
    view=deepcopy(document);view['schema']=prior.VERSION+'/world'
    for key in ('clock_start','clock_end','planned_duration_seconds'):view.pop(key)
    for arc in view['dramatic_arc']:
        arc.pop('start_seconds');arc.pop('end_seconds')
    prior.validate_world(view,brief,casting)
    cursor=0;issues=[]
    for i,arc in enumerate(document['dramatic_arc']):
        if arc['start_seconds']!=cursor or arc['end_seconds']<=arc['start_seconds']:
            issues.append(f'dramatic_arc.{i}: non-contiguous/non-positive interval')
        cursor=arc['end_seconds']
    if cursor!=document['planned_duration_seconds']:issues.append('arc total differs from planned duration')
    start=dt.datetime.strptime(document['clock_start'],'%H:%M:%S')
    expected=(start+dt.timedelta(seconds=document['planned_duration_seconds'])).strftime('%H:%M:%S')
    if document['clock_end']!=expected:issues.append('clock_end differs from same continuous relative timeline')
    return {'valid':not issues,'diagnostics':issues,'necessary_conditions_only':True,'semantic_approval':False,
        'primary_world_review_required':True,'native_world_sha256':prior.digest(document)}


def script_schema(brief,world):
    schema=prior.script_schema(brief,world)
    schema['properties']['total_duration_seconds']={'const':world['planned_duration_seconds']}
    segment=schema['properties']['segments']['items']
    segment['properties']['events']['maxItems']=3
    first=deepcopy(segment);first['properties']['duration_seconds']={'const':15.0}
    first_event=deepcopy(first['properties']['events']['items'])
    first_event['properties']['start_s']={'const':0}
    first_event['properties']['dialogue']['minItems']=1
    first_line=deepcopy(first_event['properties']['dialogue']['items'])
    first_line['properties']['speaker']={'const':'C02'};first_line['properties']['start_s']={'const':0}
    first_event['properties']['dialogue']['prefixItems']=[first_line]
    first['properties']['events']['prefixItems']=[first_event]
    schema['properties']['segments']['prefixItems']=[first]
    return schema


def validate_script(document,brief,world):
    Draft202012Validator(script_schema(brief,world)).validate(document)
    return prior.validate_script(document,brief,world)


def prepare_world(brief,seed,profile,rejected_world,rejection,facts):
    system='''你是MiniMax编剧。提交一份完整原生世界框架修订，调用给定工具。不是修改补丁。原637完整但源内容被明确拒绝，不能逼正文迁就错误世界。以新用户brief和选定固定场景事实为最高本轮来源。清晨08:00:00起，150–180秒连续时间，clock_end与每个dramatic_arc相对起止和总时长完全一致；stage名称不要另外手写冲突的钟点或时长。只保留既有一张小方桌、一黑椅、纸杯与暖壶、白天窗光/白色顶灯/同一门和走廊。禁止夜景、第二桌/饮水台、监控、公告板、挂钩和黄线；不能用“镜外存在”绕过事实。桂芳已在屋内唯一桌前核普通生鲜库存/交班工作记录，不是门店企业考勤社保管理员；经理从通道跨门0秒开口。演员ID、SHA与衣着照给定固定cast逐字保持，不新增年龄或发型。经理起初要她在个人原因表签字，之后才因当场明确刺激/现实成本改变策略。剧情要自然但不能把自查记录等法律结论强行当因果胜利。只列必要便携工作记录/笔/文件夹/纸张，道具每个initial_custody只写0秒时静态的一处位置/持有人/未签状态，不含之后抽出、递交、放置等动作；未来动作放剧情arc。每个末态和ending必须对应同一最终持有位置；打印件要么口袋要么拿在手上，只选一种且全世界一致；结尾经理留室内而桂芳走出，不能又称两人离开。请认真修全部637原生具体拒绝，而不只修一个字段。世界合同必要字段过关后仍须主agent读全文内容决定，不能声称批准、自动正文或导演通过。'''
    system+=''' 原638还有因果和口语失败，必须从本世界重建：经理首段要明确说门店人员调整、要桂芳离职/签字的消息，她听到后才停工作和质问；仅“桂芳/我下个月也调走/先跟你说一句”不足以触发她问店里是不是换人。桂芳已经坐着，不能让经理又叫她“先坐”而无起身动作。经理从不排明日班变成要她保次日出勤，必须有明确当场新刺激、策略转换理由、实际代价和变动时间，不能先后硬反转。“班次写到岗，签字栏我签门店”“带走的是纸，不是结果”不是自然职场口语，别把流程规则换成角色台词。'''
    return prior.request('goal_plan',profile,system,{'new_user_brief':brief,'fixed_casting':seed['fixed_casting'],
        'selected_scene_visible_facts':facts,'old_complete_native_world637':rejected_world,
        'primary_content_rejection637':rejection,'verified_legal_context':seed['verified_legal_context'],
        'old_complete_native_screenplay638':seed['old_complete_native_screenplay638'],
        'primary_body638_content_diagnosis':seed['primary_body638_additional_failures'],
        'same_story_failures_and_capacity_preserved':True},world_schema(brief,seed['fixed_casting']))


def prepare_script(brief,world,seed,profile,oldbody,diagnostics,facts):
    item=prior.prepare_script(brief,world,seed,profile,oldbody,diagnostics)
    item['request']['structured_schema']=script_schema(brief,world)
    item['request']['messages'][0]['content']+=''' 本次只有一份剩余完整正文槽，不自动再返修。原638完整正文和四处诊断已提供，按经过主agent实际内容采用的新world完整原生重写，不手拼旧稿。首段第一个event从0开始，其第一条对白必须C02马涛从0秒开始；C01桂芳本来在唯一桌前工作，当段自然接话。每段event粗分1–3个完整自然窗口，不要碎分到对白超出所属event。清晨单桌场景严格按事实，不新增第二桌/监控/夜景。世界和固定图不能反向迁就正文。'''
    item['request']['messages'][0]['content']+=''' 尤其修638真正内容失败：经理首段先明确传递门店要调整人员/要她离职签字的实际消息，桂芳才因这个刺激停手并回应；只说自己下月调走不能凭空触发她质问。她若一直坐着不得又让她“先坐”。经理改排班策略必须由新刺激、现实损失、承担的代价和明确变动生效时间推动，不能“明天不许来/店里缺人所以你又来”互相冲突。用两人当面自然口语，禁把“班次写到岗，签字栏我签门店”“带走的是纸，不是结果”之类规则说明当表演。'''
    payload=json.loads(item['request']['messages'][1]['content']);payload['selected_scene_visible_facts']=facts
    item['request']['messages'][1]['content']=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    item['request_sha256']=prior.digest(item['request'])
    return item


def render_world(world):
    return prior.render_world(world)+'\n\n连续时钟：'+world['clock_start']+'—'+world['clock_end']+f"，总计{world['planned_duration_seconds']}秒。\n"


def render_script(document,world):return prior.render_script(document,world)
