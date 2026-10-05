"""Version-bound original writer prompts and deterministic brief requirements."""
import json,re
from pathlib import Path
from .creative_writer_prompt_pack import build_writer_prompt
from .creative_workflow_contract import CreativeContractError
VERSION='original_events_v3'
PACK=Path(__file__).resolve().parents[2]/'config/prompts/creative_writer_modules_reviewed_v3.json'

def select_modules(brief):
    explicit=brief.get('writer_modules')
    if explicit is not None:
        if not isinstance(explicit,list) or any(not isinstance(x,str) for x in explicit):raise ValueError('writer_modules须为字符串数组')
        return explicit
    text=json.dumps(brief,ensure_ascii=False)
    result=[]
    if re.search('无对白|零对白|全片静默',text):result.append('silent')
    if re.search('悬念|前半段.*线索|揭秘|声响|误会.*物理',text):result.append('suspense')
    if re.search('三人|三名|三位',text):result.append('ensemble')
    if re.search('科幻|超能力|撤回.*一次',text):result.extend(['speculative','emotion'])
    return result or ['emotion']

def bind_original_prompt(brief):
    modules=select_modules(brief)
    return {'version':VERSION,'modules':modules,'creative_brief':brief,'prompt':build_writer_prompt(modules,pack_path=PACK)}

def validate_brief_script(script,brief):
    beats=script.get('beats',[])
    limits=brief.get('duration_seconds')
    if brief.get("duration_policy") != "flexible" and isinstance(limits,list) and len(limits)==2 and all(type(x)is int for x in limits):
        total=sum(b['duration_seconds'] for b in beats)
        if not limits[0]<=total<=limits[1]:raise CreativeContractError('总时长不在创作简报范围内')
    constraints='\n'.join(str(x) for x in brief.get('constraints',[]))
    if re.search('零对白|无对白|全片静默',constraints) and any(b['dialogue'] for b in beats):raise CreativeContractError('简报要求无对白')
    ending=re.search(r'结尾\s*(?:最多|不超过|不得超过)\s*(\d+)\s*秒',constraints)
    if ending and beats and beats[-1]['duration_seconds']>int(ending[1]):raise CreativeContractError('结尾超过简报时长上限')
    if any(len(b['dialogue'])>2 for b in beats):raise CreativeContractError('事件版每拍最多两句对白')


BRIEF_PRIORITY_VERSION = "original_brief_priority_v1"
BRIEF_PRIORITY_RULES = """原创创作优先级：creative_brief 的显式硬约束高于候选 candidate_lock、导演 brief 和历史稿中的具体实现。候选是可修正创作提案，不是小说原文或不可更改的来源事实。保留核心人物关系、因果转折及结尾意图；若道具数量、动作、操作步骤或结尾实现与用户简报冲突，删除或替换冲突实现，不得以忠实候选为由继承违规内容。不得自创简报没有的禁令。
候选分析及导演协调时逐项核对允许的道具、数量和操作；导演反馈明确指出冲突并提出符合简报的替代方案。编剧协调按现有 feedback_responses 协议明确接受候选实质调整为 accepted_candidate_change；不是靠静默修改候选绕过锁。正式剧本及返修再次核对实际动作链，premise/event/trigger 摘要必须与实际演出一致。该规则仅适用于原创，不改变小说原文锁。"""


def bind_brief_priority():
    return {"version": BRIEF_PRIORITY_VERSION, "prompt": BRIEF_PRIORITY_RULES,
            "director_execution_version": "original_director_execution_v1",
            "director_execution_prompt": (
                "原创分镜职责：省略进店、点单、普通走路等不影响因果理解的过程，不构成剧本缺失，不能强加这些操作。"
                "先在已有动作与对白顺序内分配明确的刺激、反应、台词、收束时间；可由分镜排出的反应窗口应自行安排。"
                "不得仅按动作数量断言超时。退回剧本前必须指出无法在总时长内执行的具体冲突及计时依据，"
                "区分必须修改的剧情错误与可在导演层完成的构图、表演、道具位置说明。"
            )}


def stage_summary_update_allowed(path, *, eligible):
    """Existing receipts determine their own semantics, including absent flags."""
    if not eligible:
        return False
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        messages = record.get("request", {}).get("messages", [])
        payload = json.loads(messages[-1]["content"]) if messages else {}
        return payload.get("allow_summary_update") is True
    return True
