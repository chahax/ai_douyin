"""Fact-led complete rewrite after old candidate anchoring; originals remain frozen."""
from copy import deepcopy
import json
from src.content_factory.creative_legal_causal_spine_v2 import build_wire as gated_wire
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_trend_bridge import complete_story_schema
from src.content_factory.creative_complete_review_ids_v1 import schema,catalog

VERSION='confirmed_legal_facts_writer/v1'

def build_wire(packet,facts,graph,scope,stage,*,now,direction,confirmation,script=None,diagnosis=None):
    # Validate original source/freshness/real human confirmation and keep same model.
    w=gated_wire(packet,facts,graph,scope,'review' if stage=='review' else 'spine',now=now,direction=direction,confirmation=confirmation,script=script)
    original=json.loads(w['messages'][1]['content']);brief=original['emotional_brief']
    ctx={k:deepcopy(original[k]) for k in ('emotional_brief','characters','confirmation','reference_fulltext','writer_expression_criteria',
        'verified_legal_context','supplemental_tag_graph_evidence','original_direction_provenance','confirmed_current_story_scope','tag_choices','account_profile')}
    old=direction['creative_brief']
    ctx['creative_brief']={'theme':scope['story_conflict'],'audience':old['audience'],'relationships':old['relationships'],
        'audience_emotion':old['audience_emotion'],'visual_style':'写实职场，两人，小会议室及相邻办公区；具体画面由故事需要决定',
        'turn':scope['story_conflict'],'ending':'当天催签被具体暂停，小林实际选择产生现场后果；案件结果不下结论',
        'duration_policy':'flexible','title_policy':'为当前故事另定标题，不要求保留原咖啡标题或其道具',
        'constraints':deepcopy(facts['creative_boundaries'])}
    ctx['confirmed_case_facts']={'company_request':'公司实际要求小林结束在公司的劳动关系，离开企业',
        'document_problem':'公司催他当天签自愿离职申请，但小林没有主动提出自愿离职',
        'worker_choice':'先核对真实离职原因，再决定是否签字；当场暂缓',
        'limits':'双人；不改成岗位调动或转岗入职；不以没章文件决定输赢；无固定赔偿或咨询结尾'}
    ctx['stage_assignment']={'current_stage':stage,'writer':'完整发生的事件与普通话对白、因果、情绪',
        'later':'整片导演、逐拍表演时窗、确定性编译分别完成','old_failed_drafts':'frozen diagnostic originals, not active templates or instructions'}
    ctx['diagnosed_previous_content_failures']=deepcopy(diagnosis)
    if stage=='draft':
        w['structured_schema']=complete_story_schema(direction);w['parameters']['max_completion_tokens']=8000
        w['messages'][0]['content']='从confirmed_case_facts和已确认范围创作一个完整双人原创法律剧本。公司要求结束劳动关系必须在正文当面明确说出，然后看见催签自愿离职的矛盾、今天完成的压力、小林先犹疑再核对、对方继续劝签、小林坚持、当天催签具体暂停及结尾释放。公司要求离开企业，不能改成调到新岗位。压力不靠无关重大威胁；先核对再决定不是保证维权胜利。可用少量必要道具，每个道具的起态与去向明确，删除无叙事作用的操作；仅两人，action里也不能藏第三人的对白。event/trigger只描述steps中真正发生的事。保持普通话与写实画风，拍数时长由完整故事需要决定，本阶段不排秒数和机位。完整R01只借表达机制。返回完整新稿，不返回分析、补丁或旧稿拼接。唯一工具名称submit_creative_json。'
    elif stage=='review':
        ctx['script']=deepcopy(script);c=catalog(script)
        ctx['source_evidence_directory']={k:{'path':v['path'],'excerpt':v['quote'][:100]} for k,v in c['entries'].items()}
        ctx['evidence_catalog_sha256']=digest(c);w['structured_schema']=schema(script,brief)
        w['messages'][0]['content']='全文审查当前双人法律剧本，以已确认事实、完整参考及法律边界为准，不代写。公司要求离开企业须在steps明确发生；催签、核对、阻力、选择和当天可见后果必须有真正正文证据。检查回指前文、event/trigger与正文一致、必要道具取得和归属、action内隐藏第三人对白。今日催签具体暂停可以是阶段后果，不要求案件终局或保证未来岗位。角色请求书面说明不自动成为普遍法律条件；不得把没章当胜负。四项情绪问题与全文必修issues一致，提出的修复备选遵守双人范围。evidence_refs每项仅{ref_id:目录ID}，选择完整当前正文叶子，导航excerpt不是审查范围。保留所有真实问题；只调用submit_creative_json工具返回完整审查，不代写，不自创引用，不用旧稿错误代替当前证据。'
    else:raise ValueError('draft or review stage required')
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
    w['input_provenance'].update(source_context_sha256=digest(ctx),confirmed_case_facts_sha256=digest(ctx['confirmed_case_facts']),
        original_direction_sha256=digest(direction),old_failed_templates_consumed=False)
    w['operator_version']=VERSION
    return w
