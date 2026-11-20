"""Unapproved offline format draft; pure functions, no dispatch or claims."""
from copy import deepcopy
import re
from jsonschema import Draft202012Validator
from src.content_factory import creative_screenplay_world_v1 as request_base

VERSION='creative_compact_screenplay_draft/v1'


def output_schema():
    return request_base.obj({'schema':{'const':VERSION+'/native_text'},'title':request_base.S,
        'total_seconds':{'type':'number','minimum':150,'maximum':180},
        'timeline':request_base.arr(request_base.obj({'segment_id':{'type':'string','pattern':'^S[0-9]{2}$'},
            'start_seconds':request_base.N,'end_seconds':request_base.N}),10,14),
        'screenplay_markdown':{'type':'string','minLength':500}})


def prepare_request(brief,casting,facts,story_core,known_failures,profile):
    system='''你是MiniMax编剧。一次工具结果提交完整新稿，完整正文只写在screenplay_markdown这一字符串中，另给10–14行轻数字timeline。全文150–180秒，每段<=15.083秒，首段15秒；timeline数字覆盖从0到total_seconds，按S01、S02顺排，不能数字字符串、空对象、只写4段或用“后续略”占位。不要计算任何SHA，不重复每段七个道具JSON和逐字相等的自由状态；重要持有/拿取/交还/签字/未签状态在正文动作中清楚写出，尤其纸张身份与结尾实际去向一致。
screenplay_markdown依次有'# 世界框架'、'# 连续时间总表'、'# 分段剧本'。先自然说明故事时代、两人身份关系/欲望/顾虑、固定空间与主要物件、全片清晨时钟起止和冲突走向。总表与数字timeline一致。分段用独立行'## S01'至最后一段；每段正文写剧中钟点/全片起止秒、地点/环境光声、C01/C02每人当时工作动作/手/神情/视线、带本段相对秒的自然对白、刺激与反应、承前启后和实际道具变化。可用自然段或简表，不以机械标签代替表演，也不把世界摘要当已演出。
固定已有两张演员脸/衣着与白天单桌场景，不生造第三人喊话/旁白、监控/第二桌/夜景。桂芳已坐在地面桌旁的黑椅上，左手压库存交班记录、右手持笔，个人打印件原在围裙右袋；经理跨门第0秒即把门店要减员/要她离职签字的具体消息说出来，她才停笔、抬眼、当段自然回话。不是只叫名字或先宣布自己调走，也不留固定3秒开场/6秒尾空等。动作可与对白并行，通常3–3.5中文字/秒，留可读反应，不超4.2字/秒。
冲突围绕谁提出离职及明日工作安排。经理想她签个人原因；桂芳指出删她后明日具体验货环节缺人，今天要报的正是明日班表，使他对同一天的工作缺口和留下书面责任的代价作当面权衡，再确认她次日到岗。自然台词由你完整创作，不抄流程说明。持续坐着不能又被叫先坐；所有物件每刻只有一个实际位置，打印件拿出须演出。法律与补偿不作个案定论，未签提议不等于接受、排班签字不解决全部争议。交稿前自查所有段完整写到结尾，但不要用自我声明代替完整正文。'''
    payload={'new_user_brief':brief,'fixed_casting':casting,'selected_scene_visible_facts':facts,
        'story_core':story_core,'known_failures_to_avoid':known_failures,
        'source_authority':'Current user brief, fixed existing references and explicit assistant design constraints; not model-generated adopted screenplay.'}
    return request_base.request('complete_script',profile,system,payload,output_schema())


def validate_necessary(document):
    """Coverage/section presence only; never semantic or aesthetic acceptance."""
    Draft202012Validator(output_schema()).validate(document)
    issues=[];cursor=0;ids=[]
    for index,row in enumerate(document['timeline'],1):
        sid=row['segment_id'];ids.append(sid)
        if sid!=f'S{index:02}':issues.append(f'{sid}: segment IDs not contiguous')
        if abs(row['start_seconds']-cursor)>.001:issues.append(f'{sid}: timeline gap/overlap')
        seconds=row['end_seconds']-row['start_seconds']
        if not 0<seconds<=15.083333334:issues.append(f'{sid}: invalid duration')
        if index==1 and abs(seconds-15)>.001:issues.append(f'{sid}: first segment must be15seconds')
        cursor=row['end_seconds']
    if abs(cursor-document['total_seconds'])>.001:issues.append('timeline total differs')
    text=document['screenplay_markdown']
    for marker in ('# 世界框架','# 连续时间总表','# 分段剧本'):
        if marker not in text.splitlines():issues.append('missing section '+marker)
    found=re.findall(r'^## (S[0-9]{2})\s*$',text,re.MULTILINE)
    if found!=ids:issues.append('native full text segment sections differ from numeric timeline')
    return {'valid':not issues,'diagnostics':issues,'necessary_presence_only':True,
        'full_semantic_review_still_required':True,'human_quality_approved':False,'creative_quality_passed':False,
        'native_text_modified':False}


def render_native_markdown(document):
    """Return exact native string, without adding prose or reconstructing shots."""
    if not isinstance(document.get('screenplay_markdown'),str):raise ValueError('native Markdown string required')
    return document['screenplay_markdown']


def prepare_full_review_request(brief,native_document,profile):
    # Deliberately still a design preview; no production review runner or approval.
    check=request_base.evidence_check_schema()
    schema=request_base.obj({'schema':{'const':VERSION+'/full_text_review'},
        'native_document_sha256':{'const':request_base.digest(native_document)},
        'script_markdown_sha256':{'const':request_base.digest(native_document['screenplay_markdown'])},
        'global_checks':request_base.obj({k:deepcopy(check) for k in request_base.CHECKS}),
        'segments':request_base.obj({r['segment_id']:deepcopy(check) for r in native_document['timeline']}),
        'overall_status':{'enum':['pass','fail','unknown']}})
    return request_base.request('full_review',profile,
        '阅读全文原生Markdown与其数字时轴，逐段及跨段引用原句核对用户brief、刺激反应、两人自然口语/动作、时间空间与纸张连续、让步因果及法律边界。标题/标记存在不证明内容完整；每段须实际演完并作用后段。给真实原句quotes和fail/unknown，不能为交付判pass。不改原生正文，不把机器审查称用户视频批准。',
        {'new_user_brief':brief,'complete_native_document':native_document},schema)
