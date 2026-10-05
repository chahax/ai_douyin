"""Bind narrative intent to new original runs without changing old receipts."""
VERSION = 'narrative_expression_v3'
COMMON = '''叙事表达优先：先兑现本次简报的人物处境、关系、选择及转折，再处理动作/道具/结构细节。仅从实际播放的动作和对白判断观众能够获得什么信息，premise/event/trigger、目的说明及情绪标签不算额外演出。“总是/习惯/第一次/终于”等前史或变化不能仅靠一次开本子、握包或伸手推知；可用自然且具体的对白、可见后果或对照建立，不强制闪回、旁白、字幕。建立关键事实应早于依赖该事实的情绪转折。观众感受是创作目标，不是已经测得的效果。'''
WRITER = '''编剧：只顺读实际事件，判断人物此刻想得到什么、什么阻碍、选择会改变什么、什么新事实使关系变化；依据题材表达，不强加吵架、煽情事故或统一反转。不给每拍机械分配相等时长，不用走路/拿放/停顿凑够总长。若只能依赖摘要解释核心前提，先修正文；若只是可选审美，保留为建议。'''
DIRECTOR = '''导演：将已写出的关键信息和反应落实到最终生成prompt中的可见构图、具体刺激及时间窗口。purpose不能独自承载叙事。微表情须有可读的脸部景别；连续尾帧限制不能静默删除重要近景或换机位，应明确所需适配。资产与首帧使用简报指定媒介；真人质感需新建或选择兼容的写实人物/场景/首帧，动画尾帧不作为真人版首帧。不得自行改对白、补前史；表达无法落实时指出上游具体缺口。'''
REVIEW = '''文本审查：在既有requirements项先对照简报检查核心信息是否真正进入实际动作/对白，再比较分镜和最终prompt是否保留它。摘要与演出脱节、必要铺垫缺失、重要反应被构图/提示词删掉且违反明确要求时，用原字段证据报告给writer或director；不得用“动作规范/无矛盾”代替需求兑现。冲突不够刺激、是否感动等主观改善进suggestions，不臆测成片表演或口型失败，不给观众感受写passed。沿用现有输出合同，不新增评分、审核轮次或字段。'''
STAGE_ROLES = {
    'writer_analysis': 'writer', 'writer_script': 'writer', 'writer_revise': 'writer',
    'writer_director_feedback': 'writer', 'director_brief': 'director',
    'director_shots': 'director', 'director_revise': 'director',
    'director_state_plan': 'director', 'director_production_design': 'director',
    'script_review': 'review', 'writer_check': 'review',
}
FINAL_PROMPT_REVIEW = '''联合审查同时核对final_video_prompts中的实际编译文本与剧本、shots.prompt和结构字段；编译文本才是视频请求将发送的表演内容。解释性目的、事件摘要不能弥补实际表演缺失。引用来源差异而非猜测生成效果；缺少信息归编剧，镜头与最终提示词丢失表达归导演。'''
PLAN_GUIDANCE = '''全片动作计划也承担叙事摄影：为核心信息选择可读构图和明确反应窗口。不能为了原始尾帧全片固定一个中景，也不能为状态契约删掉剧本的重要表达。无法兼容的机位或切点应明确反馈，不自行改剧情。'''
CONTENT_PRIORITY = """创作及文本审查以情感表达、事件表达、画面表达为主要顺序。情感：人物被什么具体刺激触动、怎样犹豫/选择、对方如何回应、结尾情绪是否由行动收束；看刺激前、中、后的表演是否可读。事件：前因、信息变化、选择与后果能否仅从实际动作/对白理解。画面：关键事实与反应有没有在分镜及最终提示词中可见的主体、景别、构图和窗口，是否保留题材与画风。三者可以由自然动作、对照、沉默或对白成立，不强迫角色口头解释感情，不把多写情绪标签当改进。duration_policy=flexible时总长是参考，依据内容安排，可长可短；不能仅因偏离参考或候选估计时长判必修，也不按相等时长切拍或增删剧情迁就接口。语速、刺激反应顺序与真实操作需要的时间仍须成立。与明确需求相冲突的表达缺失用证据报issue；情绪强弱、自然程度、美感等判断给出具体依据与建议，不伪称观众感受通过。媒体内容仍由用户人工审查。"""

def bind_narrative_focus():
    return {'version': VERSION, 'common': COMMON + CONTENT_PRIORITY, 'writer': WRITER,
            'director': DIRECTOR + PLAN_GUIDANCE, 'review': REVIEW + FINAL_PROMPT_REVIEW,
            'stage_roles': dict(STAGE_ROLES), 'review_final_prompts': True,
            'review_priorities': ['emotion_expression', 'event_expression', 'visual_expression']}
def prompt_for_stage(binding, name):
    if not binding:
        return ''
    if 'stage_roles' in binding:
        role = next((role for prefix, role in binding['stage_roles'].items()
                     if name.startswith(prefix)), None)
        return '\n' + binding['common'] + '\n' + binding[role] if role else ''
    # v1 bindings keep their exact original dispatch and saved prompt text.
    if name.startswith(('script_review', 'writer_check')):
        role = 'review'
    elif name.startswith(('writer_analysis', 'writer_script', 'writer_revise', 'writer_director_feedback')):
        role = 'writer'
    elif name.startswith(('director_brief', 'director_shots', 'director_revise', 'director_production_design')):
        role = 'director'
    else:
        return ''
    return '\n' + binding['common'] + '\n' + binding[role]
