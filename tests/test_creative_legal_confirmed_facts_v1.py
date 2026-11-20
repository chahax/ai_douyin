import json
from copy import deepcopy
from pathlib import Path
from src.content_factory.creative_legal_confirmed_facts_v1 import build_wire
from src.content_factory.creative_complete_review_ids_v1 import expand
from test_creative_confirmed_case_graph_context_v1 import inputs

def test_fact_led_context_preserves_evidence_without_failed_template():
    (p,f,g,s,d,c),now=inputs();before=deepcopy(d)
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,diagnosis={'known':'source-bound failures'})
    x=json.loads(w['messages'][1]['content'])
    assert d==before and x['reference_fulltext']==p['inputs']['reference_fulltext']
    assert '结束' in x['confirmed_case_facts']['company_request'] and '调岗' not in x['confirmed_case_facts']['company_request']
    assert x['confirmation']==c and x['confirmed_current_story_scope']==s
    assert 'script' not in x and 'complete_content_revision' not in x and 'current_model_authored_causal_spine' not in x
    assert all('story_relevance' not in v for v in x['tag_choices']) and len(x['writer_expression_criteria'])==6
    assert x['supplemental_tag_graph_evidence']['candidate']['support_video_count']==14 and w['model']=='MiniMax-M3'
    assert w['input_provenance']['old_failed_templates_consumed'] is False

def test_full_review_is_bound_to_actual_script_and_active_emotion():
    (p,f,g,s,d,c),now=inputs()
    root=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_07'
    script=json.loads((root/'DRAFT_r5.json').read_text(encoding='utf-8'))
    w=build_wire(p,f,g,s,'review',now=now,direction=d,confirmation=c,script=script)
    x=json.loads(w['messages'][1]['content']);assert x['script']==script and x['source_evidence_directory']
    assert w['structured_schema']['properties']['emotion_review']['properties']['script_sha256']['const']==__import__('src.content_factory.creative_story_emotion',fromlist=['digest']).digest(script)
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and not w['automatic_retry']
