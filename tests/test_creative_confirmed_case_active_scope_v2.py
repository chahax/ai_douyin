"""Unadopted source details must not be active instructions; native tool avoids double encoding."""
from copy import deepcopy
import json
from src.content_factory.creative_confirmed_case_active_scope_v2 import build_wire,active_context
from test_creative_confirmed_case_graph_context_v1 import inputs


def test_active_corrected_scope_preserves_original_and_native_schema():
    (p,f,g,s,d,c),now=inputs();before=deepcopy(d)
    active=active_context(p,f,s,d)
    assert d==before
    assert '没盖章' not in active['creative_brief']['turn']
    assert '盖章' not in active['emotional_brief']['choice']
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c)
    ctx=json.loads(w['messages'][1]['content'])
    assert ctx['creative_brief']==active['creative_brief']
    assert 'source_direction' not in ctx
    assert ctx['original_direction_provenance']['original_direction_sha256']==c['direction_sha256']
    assert ctx['reference_fulltext']==p['inputs']['reference_fulltext']
    assert 'payload_json' not in w['structured_schema']['properties']
    assert 'beats' in w['structured_schema']['properties']
    assert 'output_transport' not in w
    assert w['model']=='MiniMax-M3' and w['parameters']['thinking']=='disabled'
    assert ctx['supplemental_tag_graph_evidence']['candidate']['support_video_count']==14


def test_complete_revision_preserves_entire_prior_text_and_real_review():
    (p,f,g,s,d,c),now=inputs()
    revision={'previous_complete_script':{'title':'simulated','beats':[{'id':'B1','steps':[{'text':'完整前稿模拟原文'}]}]},
              'review':{'full_text_review':{'issues':[{'impact':'模拟真实必修反馈'}]}}}
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,revision=revision)
    ctx=json.loads(w['messages'][1]['content'])
    assert ctx['complete_content_revision']==revision
