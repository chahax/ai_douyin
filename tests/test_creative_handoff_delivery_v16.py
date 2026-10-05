import pytest
from scripts import run_creative_handoff_delivery_v16 as delivery

def test_real_valid_review_selected_by_actual_version_label():
    r=delivery.latest_review();assert r['ordinal']==158
    assert r['label']=='full_review_s6_d6_view15_r1' and r['status']=='contract_valid'
    assert r['validation']['issue_count']==0

def test_finalization_requires_real_assistant_source_quotes():
    with pytest.raises(RuntimeError,match='assistant evidence'):delivery.finalize([{'path':'shots.shots.8.visible_performance','quote':'invented-source-phrase','finding':'bad'}])
