"""Contract for faithful audiovisual transcription; no automatic semantic release."""
from . import contracts as c

COMMON = '''目标：将小说内容忠实转写为可生产视频的剧本，不重新创作故事。
保留人物关系、关键事件顺序与因果、行动主体对象、对白含义、条件否定和知情范围。
允许口语化及不新增剧情信息的日常对白，允许自然微动作、机位和一般布景。
不补具体年龄、经历、承诺、事件结果或有剧情含义的道具来历。
前情只用于承接，不再次当作目标事件演出；推测和未决信息不得升级为事实。
不强制反转、爽点、固定场数、人物上限或固定秒数。旁白、心声和对白明确区分。
输入的原文是依据；模型前序分析仅是待核材料，发现与原文冲突应纠正并注明。
'''

STAGES = {
 'understanding': '读取完整连续章节，输出当前事件、人物关系、时间地点和必要歧义；不要补全人物传记，不写剧本。原著事实与视觉设计建议分开。',
 'scene_plan': '按自然事件组织全部场景。每场说明来源范围、开始时间地点与在场人物、行动与声音要点、结束状态。完整覆盖目标剧情，不将输入章节数等同集数。',
 'screenplay': '输出完整剧本：基础背景说明、对应原文范围、逐场时间地点人物、动作神情和明确署名的对白/心声/旁白。关键信息必须可见或可听；避免重复解释。不先按15秒拆剧情。',
 'continuity_review': '对照完整原文与完整剧本，检查人物进出、地点时间、重要道具及知情衔接。列具体候选引文、来源、原因；合理表演补足不作错误。不要直接改稿。',
 'fidelity_review': '检查剧情是否准确清楚地表现出来，区分真实剧情错误、来源歧义和文风建议。台词不必逐字相同。每条问题必须给候选引文和原文依据，不为追求逐字一致而否定合理视听表达。不要直接改稿。',
 'handoff': '仅记录最终候选结束时的关键时间地点、在场/去向、重要道具、知情和未发生事项，绑定候选版本。不是重述整章；不得加入新推断。此结果仍待主助手验收。',
}

def prompt(stage):
    return COMMON + '\n本阶段职责：' + STAGES[stage]

def stage_inputs(packet, results, stage, iteration):
    inputs=dict(packet)
    if iteration == 1:
        if stage=='scene_plan':inputs['analysis_unverified']=results['understanding']
        if stage=='screenplay':inputs.update(analysis_unverified=results['understanding'],scene_plan_unverified=results['scene_plan'])
    else:
        # Exact source paragraphs, not model-generated facts or rewritten summaries.
        inputs['source_index']=[{'chapter':ch['index'],'role':role,'paragraphs':[
            {'id':f"CH{ch['index']}-P{i:03}",'text':s} for i,s in enumerate(ch['text'].split('\n\n'),1)]}
            for role,key in [('context_only','context_only'),('target','target_complete_chapters')] for ch in packet[key]]
        if stage=='screenplay':inputs['scene_plan_reference_only']=results['scene_plan']
    if stage in ['continuity_review','fidelity_review','handoff']:inputs['complete_candidate']=results['screenplay']
    if stage=='handoff':inputs['warning']='承接为未验收候选，不能作为已核事实传播。'
    return inputs

def stage_prompt(stage, iteration):
    text=prompt(stage)
    if iteration<2:return text
    text+='\n程序source_index的chapter/role是原文归属，模型不得更改。目标章首段即使承接前章也属于目标剧情。出场顺序不是年龄排行，原文没有明确矛盾时保留原称谓。未指定交通方式的正常省略转场，不等于交通矛盾。'
    if stage=='scene_plan':text+='\n直接从原文按顺序规划，逐场列程序段号范围（可跨章），并核对目标章首尾都得到表达；心理与对白也属于剧情。不要重新发明段号或以摘要取代原文。'
    if stage=='screenplay':text+='\n场次规划仅供参考，写前自行顺序核对目标原文首尾，发现遗漏须补足。段号作为制作注释，不让角色念出。心声用角色自然第一人称；动作栏只写可见动作，必要心理使用可听心声。'
    if stage.endswith('_review'):text+='\n必须先核对目标章首尾和各事件是否有对应表达。报告矛盾必须给出互斥的两项明确依据；未写过渡、未指定年龄、没有逐项演出普通生活步骤，都不能单独证明错误。不要把猜测的年龄用于否定称谓。区分剧情错误、制作注释错误和可选文风。'
    if stage=='handoff':text+='\n只列结束时对后场有影响的状态和正文证据引句，不列食物是否吃光、背景传记或读者视角元信息；没有明确改变的重要状态保留未定。创作布景/光线标为演出设计，不冒充原著事实。'
    return text

def source_packet(source, context_chapters, target_chapters):
    if set(context_chapters)&set(target_chapters):raise ValueError('context_target_overlap')
    chapters={x['index']:x for x in source['chapters']}
    if not target_chapters or any(i not in chapters for i in context_chapters+target_chapters):raise ValueError('missing_complete_chapter')
    return {'source_sha256':c.digest(source),
      'context_only':[chapters[i] for i in context_chapters],
      'target_complete_chapters':[chapters[i] for i in target_chapters]}

def bind_review(candidate, review):
    return {'candidate_sha256':c.digest(candidate),'review':review,'semantic_acceptance':False}

def release(candidate, reviews, primary):
    sha=c.digest(candidate)
    if any(x['candidate_sha256']!=sha for x in reviews):raise ValueError('stale_review')
    if primary.get('candidate_sha256')!=sha or primary.get('decision')!='accepted':raise ValueError('primary_acceptance_required')
    if primary.get('unresolved_plot_issues'):raise ValueError('unresolved_plot_issues')
    return {'candidate_sha256':sha,'accepted':True}

def next_iteration(previous_run, diagnosis, version):
    if previous_run.get('pending') is not None:raise ValueError('unknown_no_replay')
    if not diagnosis.get('cause') or not diagnosis.get('change'):raise ValueError('causal_change_required')
    if version==previous_run.get('version'):raise ValueError('iteration_requires_revision')
    return {'same_source_sha256':previous_run['source_sha256'],'previous_run':previous_run['id'],
            'cause':diagnosis['cause'],'change':diagnosis['change'],'version':version}
