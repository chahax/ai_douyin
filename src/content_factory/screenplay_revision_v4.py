"""Source-first writing and independent, numerically checked segment timing.

Failed prose is evidence, never a first-draft template. Native model reports
remain unchanged; measured constraints are separate and cannot be voted away.
"""
import json
import re
from .screenplay_review_cycle_v2 import REVIEW, text_sha, validate_review
from .screenplay_revision_v3 import (
    CONTRACT, REBUILD, source_sha, validate_contract, locate_contract_evidence,
    draft_quote_anchors,
)

VERSION='screenplay_revision/v4'


def policy():
    return {'version':VERSION,'max_revisions':1,'source_first_rebuild':True,
            'independent_timing_audit':True,'protocol_repairs':1}


def segments(draft):
    headings=list(re.finditer(r'(?m)^[#*【\[ \t]*(\d+(?:\.\d+)?)\s*[—–\-~～至]\s*(\d+(?:\.\d+)?)\s*秒[^\n]*$',draft))
    result=[]
    for n,h in enumerate(headings):
        body=draft[h.end():headings[n+1].start() if n+1<len(headings) else len(draft)]
        # New v4 contract: spoken lines alone, quoted; scene metadata outside
        # time blocks is not dialogue. Unformatted in-block quotes are counted
        # conservatively rather than silently losing an inline spoken line.
        spoken=re.findall(r'[“「"]([^”」"\n]+)[”」"]',body)
        units=sum(len(re.findall(r'[\u3400-\u9fff0-9]|[A-Za-z]+',s)) for s in spoken)
        result.append({'range':h[1]+'—'+h[2],'start':float(h[1]),'end':float(h[2]),
            'duration_seconds':float(h[2])-float(h[1]),'text':body,'spoken_quotes':spoken,
            'spoken_units':units,'speech_seconds_at_5':units/5,
            'evidence':[{'id':f'S{n+1}-P{i+1}','text':p.strip()} for i,p in enumerate(re.split(r'\n\s*\n',body)) if p.strip()]})
    if not result or result[0]['start']!=0:raise ValueError('timing_segment_coverage_missing')
    for n,row in enumerate(result):
        if row['duration_seconds']<=0 or (n and row['start']!=result[n-1]['end']):
            raise ValueError('timing_segment_gap_or_overlap')
    return result


def speech_constraints(measured):
    """Reject speech-alone overflow before spending on semantic reviewers."""
    return [{'check':'dialogue_timing','location':s['range'],'draft_quote':s['text'].strip()[:350],
        'source_evidence':[],'reason':f"仅对白已有{s['spoken_units']}语音单位，按每秒5单位需{s['speech_seconds_at_5']:g}秒，超过{s['duration_seconds']:g}秒。",
        'required_change':'删去重复对白或重新分配全片时长；保持必要事实，给停顿及动作留时，不得催念。'}
        for s in measured if s['speech_seconds_at_5']>s['duration_seconds']]


TIMING=REVIEW.replace('timing_assessment:[{segment,spoken_estimate_seconds,serial_actions,parallel_actions,reason}],summary',
    'timing_assessment:[{segment,spoken_estimate_seconds,serial_actions,parallel_actions,reason}],segment_timing:[{range,serial_actions:[{evidence_id,seconds}],parallel_actions:[{evidence_id,seconds}],reason}],summary')+'''
顶层segment_timing必须严格逐项覆盖measured_segments的range，不漏结尾。
serial_actions指不能与该段对白同时完成的必要动作、转场、停顿、信息阅读；parallel_actions指能在对白期间完成的动作。每段至少列一个真实动作或停顿，evidence_id必须使用该段evidence里对应原文段落的id；不要抄写或改写引文。
同一段落含多个串行动作时把总时间计一次，真正同时发生的动作作为同一并行组计时，不重复计时间。seconds必须正数，是合理演出估计，不能为凑时长填零。程序按每秒5语音单位与串行动作相加，并与并行动作时长比较。
审查每段所有必要动作的依赖：到达再接触、开门后进出、通知后获知、交接后持有、从站立到就座/进餐等。剪掉常规过程可以，但须实际写出剪辑省略和新镜头初态，不把长串动作称为全部并行。
逐句读对白实际含义，检查否定词和代词是否把“受冤后澄清”说成“从未受冤”等相反意思。合理改编不用照搬原文的动作顺序；当前稿已有替代动作时不能漏读后强行要求加戏。
审核是独立阅读全文，不接收其他审核结论。用量化数据和当前具体状态找问题，不能按上轮意见消失就判通过。'''


def validate_timing(value,draft,measured):
    rows=value.get('segment_timing')
    if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows) or [r.get('range') for r in rows]!=[s['range'] for s in measured]:
        raise ValueError('timing_audit_coverage_invalid')
    constraints=[];assessments=[]
    for row,segment in zip(rows,measured):
        serial=[];parallel=[];seen=set();evidence={e['id'] for e in segment['evidence']}
        for key,dest in [('serial_actions',serial),('parallel_actions',parallel)]:
            items=row.get(key)
            if not isinstance(items,list):raise ValueError('timing_actions_missing')
            for item in items:
                if not isinstance(item,dict):raise ValueError('timing_action_evidence_invalid')
                seconds=item.get('seconds')
                key=item.get('evidence_id')
                if type(seconds) not in (int,float) or not 0<seconds<600 or key not in evidence or key in seen:
                    raise ValueError(f"timing_action_evidence_invalid: range={row['range']}, item={item!r}")
                seen.add(key)
                dest.append(seconds)
        if not serial and not parallel:raise ValueError('timing_actions_empty')
        if not isinstance(row.get('reason'),str) or not row['reason'].strip():raise ValueError('timing_reason_missing')
        required=max(segment['speech_seconds_at_5']+sum(serial),sum(parallel))
        assessments.append({'range':row['range'],'required_seconds':round(required,3),
            'available_seconds':segment['duration_seconds'],'spoken_units':segment['spoken_units']})
        if required>segment['duration_seconds']:
            constraints.append({'check':'dialogue_timing','location':row['range'],
                'draft_quote':segment['text'].strip()[:350],'source_evidence':[],
                'reason':f"逐段核算至少{required:.2f}秒，已分配{segment['duration_seconds']:g}秒；对白{segment['spoken_units']}语音单位加串行动作。",
                'required_change':'重新分配本段及全片时间或删去重复信息；不得靠赶念或省略必要状态变化。'})
    return {'assessments':assessments,'blocking_issues':constraints}


def run_cycle(call,context,stats,*,initial_draft=None,configured=None,remaining_calls=None,
              record_constraints=None,validation_recovery=None):
    if (configured or policy())!=policy():raise ValueError('unsupported_revision_policy')
    if validation_recovery:raise ValueError('previous_policy_recovery_not_supported')
    chapters=context['selected_original_chapters']
    facts=locate_contract_evidence(call('FACT_CONTRACT','director',CONTRACT,
        {'selected_original_chapters':chapters,'source_sha256':source_sha(chapters)}),chapters)
    facts=validate_contract(facts,chapters)
    # No failed script, suggested ending or old seconds in the first creation.
    base={k:v for k,v in context.items() if k not in {'selection','global_analysis'}}
    base['source_fact_contract']=facts
    instruction=REBUILD+'''
从原文重新创作，不延用旧稿模板。只选一个能在target_seconds内讲清并完成关系变化的事件；原文上下文章节供核对，不要求把所有场景塞进来。结尾允许停在该事件有意义的动作，不为凑完整硬添第二场戏。
人物名单与正文的年龄、排行、关系必须相容；来源未确认的数字不要补写。逐句检查否定词是否表达了相反意思。每段道具状态承接前段，不能在手中和口袋之间无交接跳变。
所有段落用“### 【0—12秒】”这样的连续秒数标题；每句对白单独一行，角色名：“实际台词”。非对白不用双引号。场景人物等元数据放在该场第一秒段之前。每段正文包含具体动作、视线和镜头，动作省略必须写出明确剪辑和新镜头初态。
全片按自然语速不超过每秒5语音单位核算，为必要停顿和串行动作留时；禁止整片平均掩盖结尾超时。剧情描述不要写成规则清单。'''
    draft=call('SCREENPLAY_FRESH','writer',instruction,base,False)
    unresolved=[]
    for number in range(policy()['max_revisions']+1):
        measured=segments(draft)
        early=speech_constraints(measured)
        if record_constraints:record_constraints(f'SPEECH_PREFLIGHT_{number:02}',{'draft_sha256':text_sha(draft),
            'segments':[{k:v for k,v in s.items() if k not in {'text','evidence'}} for s in measured], 'blocking_issues':early})
        if early:
            if number==policy()['max_revisions']:raise ValueError('speech_preflight_revision_limit_reached')
            if remaining_calls and remaining_calls()<3:raise ValueError('insufficient_capacity_for_writer_review_audit')
            if record_constraints:record_constraints(f'REVISION_REQUEST_{number:02}',{'draft_sha256':text_sha(draft),'required_revisions':early,'stage':'speech_preflight'})
            draft=call(f'SCREENPLAY_REVISION_{number+1:02}','writer',instruction,
                {**base,'previous_draft':draft,'required_revisions':early,'measured_segments':measured},False)
            continue
        payload={**base,'screenplay':draft,'reviewed_draft_sha256':text_sha(draft),
            'required_reviewed_chapter_indices':[c['index'] for c in chapters],
            'measured_segments':measured,'measured_dialogue':stats(draft)}
        def review(name,prompt,timing=False):
            def valid(value):
                validate_review(value,draft,chapters,draft_quote_validator=draft_quote_anchors)
                if timing:validate_timing(value,draft,measured)
                return value
            value=call(name,'director',prompt,payload)
            try:return valid(value)
            except ValueError as error:
                return valid(call(name+'_REPAIR','director',prompt+'\n修正协议错误后返回完整报告；不能隐去真实问题。',
                    {**payload,'previous_invalid_review':value,'validation_error':str(error)}))
        first=review(f'REVIEW_{number:02}',REVIEW)
        temporal=review(f'REVIEW_TIMING_{number:02}',TIMING,True)
        constraints=validate_timing(temporal,draft,measured)
        if record_constraints:record_constraints(f'TIMING_CONSTRAINTS_{number:02}',{'draft_sha256':text_sha(draft),**constraints})
        required=first['blocking_issues']+temporal['blocking_issues']+constraints['blocking_issues']
        if not required:
            return draft,{'version':VERSION,'draft_sha256':text_sha(draft),'revisions':number,
                'review_name':f'REVIEW_{number:02}','audit_name':f'REVIEW_TIMING_{number:02}',
                'fact_contract_sha256':text_sha(json.dumps(facts,ensure_ascii=False,sort_keys=True)),
                'media_acceptance':False}
        unresolved=required
        if record_constraints:record_constraints(f'REVISION_REQUEST_{number:02}',{'draft_sha256':text_sha(draft),'required_revisions':required,'stage':'full_review'})
        if number==policy()['max_revisions']:raise ValueError('review_cycle_revision_limit_reached')
        if remaining_calls and remaining_calls()<3:raise ValueError('insufficient_capacity_for_writer_review_audit')
        draft=call(f'SCREENPLAY_REVISION_{number+1:02}','writer',instruction,
            {**base,'previous_draft':draft,'required_revisions':unresolved,
             'measured_segments':measured,'timing_constraints':constraints},False)
