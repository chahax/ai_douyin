"""Expose actual compiled request text to existing reviews; no model calls."""
from copy import deepcopy
import hashlib
import json
from .creative_seedance_segments import _shot_prompt

SCHEMA = 'creative_narrative_transfer/v1'

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def enabled(binding):
    return bool(binding and binding.get('review_final_prompts') is True)

def compile_review_prompts(shots):
    return [{'shot_id':shot['id'],'beat_id':shot['beat_id'],
             'text':_shot_prompt(shots['style'],shot)}
            for shot in shots['shots']]

def enrich_review_context(binding,name,context):
    if not enabled(binding) or not name.startswith('writer_check') or not context.get('shots'):
        return context
    result=deepcopy(context)
    expected=compile_review_prompts(result['shots'])
    if 'final_video_prompts' in result and result['final_video_prompts']!=expected:
        raise ValueError('NARRATIVE_FINAL_PROMPTS_CHANGED')
    result['final_video_prompts']=expected
    return result

def playback_rows(beat):
    if isinstance(beat.get('events'),list):
        return deepcopy(beat['events'])
    rows=[]
    def action(slot):
        if beat.get(slot):
            rows.append({'kind':'action','speaker':'','text':beat[slot],'source_slot':slot})
    lines=beat.get('dialogue',[])
    action('before')
    if lines: rows.append({'kind':'dialogue',**deepcopy(lines[0])})
    action('during')
    rows.extend({'kind':'dialogue',**deepcopy(line)} for line in lines[1:])
    action('after')
    return rows

def build_transfer(binding,brief,script,shots,segment_plan):
    if not enabled(binding):
        raise ValueError('NARRATIVE_TRANSFER_NOT_BOUND')
    compiled=compile_review_prompts(shots)
    if len(segment_plan['segments'])!=len(compiled):
        raise ValueError('NARRATIVE_SEGMENT_COVERAGE_MISMATCH')
    rows=[]
    for shot,final,segment in zip(shots['shots'],compiled,segment_plan['segments']):
        if segment['shot_id']!=shot['id'] or segment['beat_id']!=shot['beat_id']:
            raise ValueError('NARRATIVE_SEGMENT_SOURCE_MISMATCH')
        payload=segment.get('payload_template')
        if payload:
            actual=''.join(item['text'] for item in payload['content'] if item.get('type')=='text')
            if actual!=final['text']:
                raise ValueError('NARRATIVE_FINAL_PROMPTS_CHANGED')
        rows.append({'shot_id':shot['id'],'beat_id':shot['beat_id'],
                     'duration_seconds':shot['duration_seconds'],
                     'purpose':shot.get('purpose',''),'composition':shot['composition'],
                     'performance':shot['visible_performance'],'cut_reason':shot.get('cut_reason',''),
                     'authored_prompt':shot.get('prompt',''),'compiled_prompt':final['text'],
                     'request_available':bool(payload),'media_content_status':'not_generated'})
    return {'schema':SCHEMA,'narrative_policy_version':binding['version'],
            'brief_sha256':digest(brief),'script_sha256':digest(script),
            'shots_sha256':digest(shots),'segment_plan_sha256':digest(segment_plan),
            'creative_brief':deepcopy(brief),
            'beats':[{'id':b['id'],'playback':playback_rows(b)} for b in script['beats']],
            'shots':rows,'review_final_prompts_sha256':digest(compiled),
            'semantic_approval':False,'automatic_submit':False,'additional_model_calls':0,
            'status':'text_sources_mapped_for_existing_review',
            'review_policy':'actual_video_review_by_user'}
