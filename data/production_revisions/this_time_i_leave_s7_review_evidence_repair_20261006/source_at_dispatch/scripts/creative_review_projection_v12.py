"""Deterministic review view; no new creative actions or timing."""
from copy import deepcopy
import json
from scripts.creative_joint_source_binding_v10 import schedule_action_plan
VERSION='creative_review_projection/v12'

def project_storyboard(original,ctx):
    result=deepcopy(original)
    scheduled,report=schedule_action_plan(ctx['state_plan'],ctx['execution_script'],ctx['static_visual_manifest'])
    offset=0.
    for i,(shot,row,script) in enumerate(zip(result['shots'],scheduled['beats'],ctx['execution_script']['beats'])):
        events=[]
        spoken=[e for e in row['events'] if e['dialogue_index']>=0]
        shared=len(spoken)>1
        if shared:
            # One model-authored shot-wide paragraph, not repeated actor actions.
            events.append('本镜共用表演原文（整镜只执行一遍；下列两个窗口各说其对应原句）：'+ctx['state_plan']['beats'][i]['dialogue_performance'])
        for event in row['events']:
            start,end=offset+event['start'],offset+event['end']
            prefix=f'全片{start}–{end}秒；镜内{event["start"]}–{event["end"]}秒'
            if event['dialogue_index']>=0:
                line=script['dialogue'][event['dialogue_index']]
                prefix+=f'；对白：{line["speaker"]}：{line["text"]}'
            performance=('引用本镜共用表演原文；本窗口仅对应上述原句，不重复整段表演' if shared and event['dialogue_index']>=0 else event['performance'])
            events.append(prefix+'；实际表演：'+performance+'；实际操作：'+json.dumps(event['operations'],ensure_ascii=False,separators=(',',':')))
        windows=[w for w in ctx['declared_performance_window_checks'] if offset-1e-8<=w['start'] and w['end']<=offset+script['duration_seconds']+1e-8]
        events.extend('声明表演窗口：'+json.dumps(w,ensure_ascii=False,separators=(',',':')) for w in windows)
        shot['visible_performance']='\n'.join(events)
        # Current S6 has no affect operations. Fail rather than erase a new one.
        if any(op['kind']=='affect' for b in ctx['state_plan']['beats'] for g in b['groups'] for op in g['operations']):
            raise ValueError('affect operations require an explicit supported view contract')
        for key in ('start_state','end_state'):
            state=json.loads(shot[key])
            for entity in state.values():entity.pop('affect',None)
            shot[key]=json.dumps(state,ensure_ascii=False,sort_keys=True)
        shot['state_semantics_note']='此视图首尾仅展示物理状态。未建模情绪初态在原编译保留；实际情绪以未改动表演全文审查，未验证媒体。'
        shot['declared_performance_windows']=deepcopy(windows)
        shot['prompt']='构图：'+shot['composition']+'\n机位：'+shot['camera']+'\n首态：'+shot['start_state']+'\n'+shot['visible_performance']+'\n尾态：'+shot['end_state']
        offset+=script['duration_seconds']
    return result

def validate_projection(original,projected,ctx):
    if projected!=project_storyboard(original,ctx):raise ValueError('review view is not the complete deterministic projection')
    return {'lossless_scheduled_events':True,'original_script_plan_and_seconds_unchanged':True,'only_declared_reaction_windows':True,'untracked_affect_not_media_instruction':True,'media_quality_verified':False}
