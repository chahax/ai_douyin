from copy import deepcopy
from src.content_factory.novel_adaptation.review_projection import review_projection
from src.content_factory.novel_adaptation.contracts import digest


def test_review_excludes_non_emitted_annotation_but_preserves_actual_actions_and_scope():
    candidate={'scenes':[{'id':'s','beats':[{'id':'b','action':'actual action','audio':[],
        'adaptation_detail':'audit note with conflicting yesterday claim'}]}],
        'end_state':{'props':{'bag':'a'},'information':{'a':[{'id':'old'}]}}}
    before=deepcopy(candidate)
    projected=review_projection(candidate,{'objective':'Opening only, not a full chapter','target_chapters':[2]})
    assert candidate==before and projected['candidate_sha256']==digest(before)
    b=projected['candidate']['scenes'][0]['beats'][0]
    assert 'adaptation_detail' not in b and b['action']=='actual action'
    assert projected['excluded_audit_only_fields'][0]['sha256']==digest(before['scenes'][0]['beats'][0]['adaptation_detail'])
    assert projected['review_scope']['objective']=='Opening only, not a full chapter'
