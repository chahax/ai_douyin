"""One complete native parent; mechanical identity views never become native."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from src.content_factory import creative_screenplay_world_v1 as base
from src.content_factory import creative_screenplay_world_source_repair_v2 as repair

VERSION='creative_joint_world_screenplay/v3'
ZONES=['Z1_后仓通道','Z2_值班室门口','Z3_值班室工作区']
PROPS=[f'P{i}' for i in range(1,8)]
P4_INITIAL='周桂芳深绿围裙右侧口袋内，折叠，未取出。'


def joint_schema(brief,cast):
    world=repair.world_schema(brief,cast)
    world['properties']['space_map']['minItems']=3;world['properties']['space_map']['maxItems']=3
    world['properties']['space_map']['items']['properties']['zone_id']={'enum':ZONES}
    world['properties']['space_map']['items']['allOf']=[{'if':{'properties':{'zone_id':{'const':ZONES[2]}}},
        'then':{'properties':{'description':{'const':'既有值班室：仅一张小方桌；唯一黑色椅子在地面桌旁；白天窗光与白色顶灯；桌边原有纸杯和暖水壶。无第二桌、监控、公告板、挂钩、黄色地面标线。'}}}}]
    prop_schema=world['properties']['props'];prop_schema['minItems']=7;prop_schema['maxItems']=7
    prop_schema['items']['properties']['prop_id']={'enum':PROPS}
    prop_schema['items']['allOf']=[{'if':{'properties':{'prop_id':{'const':'P4'}}},
        'then':{'properties':{'initial_custody':{'const':P4_INITIAL}}}}]
    template={'props':[{'prop_id':p} for p in PROPS],'space_map':[{'zone_id':z} for z in ZONES],
        'planned_duration_seconds':170}
    script=repair.script_schema(brief,template)
    script['properties'].pop('world_sha256');script['required'].remove('world_sha256')
    script['properties']['total_duration_seconds']={'type':'number','minimum':150,'maximum':180}
    return base.obj({'world':world,'screenplay':script})


def identity_mapping(parent):
    return {'schema':VERSION+'/mechanical_identity','native_parent_canonical_sha256':base.digest(parent),
        'world_pointer':'/world','script_pointer':'/screenplay','world_canonical_sha256':base.digest(parent['world']),
        'script_canonical_sha256':base.digest(parent['screenplay']),
        'derived_validation_view_added_fields':['/screenplay/world_sha256'],
        'native_content_modified':False,'identity_view_is_native':False}


def validation_view(parent):
    body=deepcopy(parent['screenplay']);body['world_sha256']=base.digest(parent['world'])
    return body


def validate_joint(parent,brief,cast):
    Draft202012Validator(joint_schema(brief,cast)).validate(parent)
    world_result=repair.validate_world(parent['world'],brief,cast)
    if {p['prop_id'] for p in parent['world']['props']}!=set(PROPS):raise ValueError('joint native props must be exactP1..P7')
    if {z['zone_id'] for z in parent['world']['space_map']}!=set(ZONES):raise ValueError('joint native zones must be exactZ1..Z3')
    body_result=repair.validate_script(validation_view(parent),brief,parent['world'])
    return {'valid':world_result['valid'] and body_result['valid'],'world_validation':world_result,
        'script_validation':body_result,'mechanical_identity':identity_mapping(parent),
        'necessary_conditions_only':True,'semantic_approval':False,'native_content_modified':False}


def prepare_joint(brief,seed,profile,history,facts):
    system='''你是MiniMax编剧。当前最后一份完整正文容量，一次原生工具结果同时提交完整world和完整screenplay，不返回补丁或只写一段。世界框架是本剧本组成部分，须与表演同步解决，不能照错误旧world写正文。两部分brief_sha256照工具常量；screenplay不要写world_sha256，不要求计算刚生成世界的哈希。先世界框架、再150–180秒完整连续剧本，首段15秒、其余<=15.083秒，每段1–3个粗自然时间窗口，完整人物动作/神情/视线/段首段尾道具状态/前后因果，所有events覆盖整段，台词都在其所属event秒区间内且不重叠，通常3–3.5中文字/秒、上限4.2。仅C01周桂芳/C02马涛说话，没有旁白、第三人喊话、电话语音或门外班长。清晨08:00:00开始，世界arc相对秒连到planned_duration_seconds与clock_end，正文总秒数同世界。按固定背景一桌一黑椅（椅在地面桌旁）/白天窗光/既有门与走廊/桌边纸杯暖壶；不能夜景、监控、第二桌或任何镜外新建筑。桂芳原本坐在室内对普通生鲜交班库存记录，左手压本、右手笔；P4个人缴费材料0秒在围裙右袋，后来明确取出、展开、去向，不占用初始左手。P1库存工作记录、P2个人原因离职申请、P3明日排班确认、P4个人打印件、P5未签协商提议、P6既有暖壶纸杯、P7经理文件夹，各初态只有一处静态位置，未来动作不塞入initial_custody。演员图ID/SHA/既有脸衣着逐字固定。第一event第一对白C02从0秒跨门就说清门店减员/要她离职签字的实际消息，而不是仅叫名字/宣布自己调走；她被这条信息打断工作后在同段自然回话。人物不能一直坐着又被要求先坐。经理与她对次日出勤的争执都指向同一天：今天报明日班表、明日验货某环节删她后没人能顶，由她当面指出具体工作缺口刺激他权衡；他有现实损失与签字留下责任的代价才确认明日出勤，不能用第三人喊话或今天卸货缺人跳到明天。具体自然台词你完整创作，不抄‘班次写到岗，签字栏我签门店’、‘带走的是纸，不是结果’等流程口号。不夸大法律结论、补偿或签字授权，未签提议不等于接受，排班签字不代表所有争议解决。旧637、638、639及全部原生失败仅作完整修订来源，勿复制其矛盾。正文start_state逐值接上一end_state，首段props逐值等新world初态（同一结果内直接保持文字一致）；每个人每个event的动作神情视线均可表演，不能只在摘要声称。一次完整原生稿，不自动返修，不伪称用户采用/导演通过/视频批准。'''
    return base.request('complete_script',profile,system,{'new_user_brief':brief,'fixed_casting':seed['fixed_casting'],
        'selected_scene_visible_facts':facts,'verified_legal_context':seed['verified_legal_context'],
        'complete_native_history_and_precise_rejections':history,
        'capacity':{'remaining_complete_body_slots':1,'full_review_limit':1,'world_component_history_including_this':3,
            'old_director_capacity':{'used':7,'limit':7,'remaining':0},'old_budget_reset':False}},joint_schema(brief,seed['fixed_casting']))


def review_schema(brief,parent):
    schema=base.review_schema(brief,parent['world'],parent['screenplay'])
    bindings={'native_parent_sha256':{'const':base.digest(parent)},'world_pointer':{'const':'/world'},'script_pointer':{'const':'/screenplay'}}
    schema['properties'].update(bindings);schema['required']+=list(bindings)
    return schema


def prepare_review(brief,parent,seed,profile,history,facts):
    system='''你是DeepSeek全文审查员，审查唯一完整原生父结果world与screenplay（/world和/screenplay），不得把它拆改或引用旧失败当新证据。逐段与跨段全文读全部内容，9项全局和每段都用本次正文连续原句quotes给证据（不是规则口号）。重点：首段经理0秒传达影响她的实际离职/人员调整信息，她听到后才打断库存工作回话；全片只两人说话，白天单桌地面椅，P4初始口袋且显式拿取，无双手/文件瞬移；经理初始要她签个人原因，后因她当面指出明日验货缺口承担代价才调整明日班，时间与动机要同一天且可见。排班表、确认单、离职申请、协商提议身份/用途/签字/最后持有与台词一致。自然职场口语、合适语速/反应，不能坐着又叫先坐，不能抄流程说明。世界与正文时间/空间/人物/道具相容，法律未作越界结论，结尾承接交锋。真实问题写fail及完整修订需求，不确定unknown，不能为交付硬判pass；总status unknown优先、其次fail、否则pass。新world标题/摘要声称不算实际演出。native_parent_sha256表示父JSON canonical digest；world/script哈希指父内真实投影，script没有world_sha256是合同明确不要求模型算哈希，不应当作缺陷。此次仅机器文本审查，永不表示用户审美/视频批准。'''
    return base.request('full_review',profile,system,{'new_user_brief':brief,'native_parent_result':parent,
        'native_parent_canonical_sha256':base.digest(parent),'world_pointer':'/world','script_pointer':'/screenplay',
        'selected_scene_facts':facts,'fixed_casting':seed['fixed_casting'],'original_failure_context':history},review_schema(brief,parent))


def validate_review(document,brief,parent):
    Draft202012Validator(review_schema(brief,parent)).validate(document)
    view=deepcopy(document)
    for key in ('native_parent_sha256','world_pointer','script_pointer'):view.pop(key)
    result=base.validate_review(view,brief,parent['world'],parent['screenplay'])
    return {**result,'native_parent_canonical_sha256':base.digest(parent),'same_original_parent_bound':True,
        'native_report_modified':False}
