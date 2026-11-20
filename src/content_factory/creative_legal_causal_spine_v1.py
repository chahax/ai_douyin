"""Narrative causality before complete dialogue; bound compact tag metadata."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from scripts.run_creative_emotion_revision_v1 import obj,text
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_complete_review_ids_v1 import build_wire as review_wire
from src.content_factory.creative_confirmed_case_active_scope_v2 import build_wire as source_wire
from src.content_factory.creative_trend_bridge import complete_story_schema

VERSION='legal_causal_spine/v1'

def compact_graph(g):
    out={k:deepcopy(g[k]) for k in ('schema','collection_run_id','source_sha256','full_graph_sha256','whole_batch_summary','interpretation')}
    c=g['candidate'];out['candidate']={k:deepcopy(v) for k,v in c.items() if k not in ('supporting_documents','support_document_ids','related_tags','support_video_ids','selected_item_ids')}
    out['selected_nodes']=[{k:deepcopy(v) for k,v in n.items() if k in ('tag_id','label','role','batch_support_video_count','candidate_support_video_count','visible_author_count')} for n in g['selected_nodes']]
    out['selected_edges']=[{k:deepcopy(v) for k,v in e.items() if k in ('edge_id','source','target','relation_kind','relation_basis','support_video_count','visible_author_count')} for e in g['selected_edges']]
    out['support_document_ids']=[d['video_id'] for d in g['supporting_documents']]
    out['full_context_sha256']=digest(g);out['stage_role']='bounded topic evidence; original full graph and documents frozen; not plot instructions'
    return out

def spine_schema(direction):
    names=[c['name'] for c in direction['characters']]
    event=obj({'id':text(),'caused_by':{'type':'string'},'actor':{'enum':names},'observable_event':text(),
        'new_information':text(),'other_character_response':text()})
    return obj({'title':text(),'confirmed_conflict':text(),'events':{'type':'array','minItems':4,'maxItems':6,'items':event},
                'visible_consequence':text(),'audience_release':text(),'case_outcome_unresolved':{'const':True}})

def validate_spine(v,direction):
    Draft202012Validator(spine_schema(direction)).validate(v)
    seen=[]
    for i,e in enumerate(v['events']):
        if e['id'] in seen:raise ValueError('duplicate spine event')
        if (i==0 and e['caused_by']!='') or (i>0 and e['caused_by'] not in seen):raise ValueError('spine cause must be an earlier event, first cause empty')
        seen.append(e['id'])
    return {'structure_valid':True,'causal_links_resolved':True,'creative_quality_passed':False,'not_final_script':True}

def build_wire(packet,facts,graph,scope,stage,*,now,direction,confirmation,script=None,spine=None,diagnosis=None):
    base_stage='review' if stage=='review' else 'draft'
    w=(review_wire if stage=='review' else source_wire)(packet,facts,graph,scope,base_stage,now=now,direction=direction,confirmation=confirmation,script=script)
    ctx=json.loads(w['messages'][1]['content']);g=ctx['supplemental_tag_graph_evidence'];ctx['supplemental_tag_graph_evidence']=compact_graph(g)
    if stage=='spine':
        ctx['diagnosed_previous_failures']=deepcopy(diagnosis)
        w['structured_schema']=spine_schema(direction);w['parameters']['max_completion_tokens']=3500
        w['messages'][0]['content']='为已确认双人法律案例重新设计4至6个实际可演出的事件，只写整片事件因果骨架，不写分析和逐秒动作。必须让公司要求劳动者离开的事实在场上明确发生，再出现催签自愿离职的矛盾、具体阻力、劳动者选择、对方回应与可见后果。没有法律胜负或固定赔偿。两个人，克制但有冲突；不要反复列举解除类型或材料清单。事件引用前一事件的ID作因果来源。旧失败只用于诊断，不是模板。参考R01表达机制，保留用户核心，具体设计由你选择。调用工具提交完整事件链。'
    elif stage=='draft':
        if spine is None:raise ValueError('accepted current causal spine required')
        validate_spine(spine,direction);ctx['current_model_authored_causal_spine']=deepcopy(spine)
        ctx['creative_brief']['title']=spine['title']
        ctx['current_stage_contract']={'stage':'complete story expansion','source_spine_sha256':digest(spine),
            'event_order':'every spine event must occur in played steps; event/trigger describe those same steps',
            'old_failed_script_role':'immutable diagnostic source, not current template; complete new draft required',
            'later_stages':['whole-film direction','local performance windows','deterministic compilation']}
        w['structured_schema']=complete_story_schema(direction)
        w['messages'][0]['content']='根据当前模型创作的完整事件因果链和已确认简报，写一份完整原创剧本，不写计划或分析。让每个事件在steps动作和普通话对白中真正发生，尤其公司要求离开这一事实，人物面对催签的迟疑、坚持、对方反应和结束后的释放。不按旧失败稿逐句修补；不过度罗列材料、解除类型、章或道具微操作。可以精简，无叙事作用的咖啡、额外同事无需出现；标题由当前事件链确定。event和trigger不能另写正文中没发生的动作；人物只能是已确认两人，必要道具起态/取得/去向一致。时长浮动，本阶段不排秒数和机位。引用法律事实边界而不裁定案件结果。保留R01机制不抄情节，调用工具提交完整正文。'
    elif stage!='review':raise ValueError('unknown spine workflow stage')
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
    w['input_provenance'].update(source_context_sha256=digest(ctx),full_graph_context_sha256=digest(g),compact_graph_context_sha256=digest(ctx['supplemental_tag_graph_evidence']))
    if spine is not None:w['input_provenance']['model_authored_spine_sha256']=digest(spine)
    w['operator_version']=VERSION
    return w
