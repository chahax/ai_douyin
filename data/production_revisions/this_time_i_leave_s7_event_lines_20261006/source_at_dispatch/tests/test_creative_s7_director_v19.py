from pathlib import Path
import pytest
from scripts import run_creative_s7_director_v19 as r


def test_new_director_cannot_start_without_real_full_reviewed_script(monkeypatch,tmp_path):
    monkeypatch.setattr(r.parent,'ROOT',tmp_path/'missing_parent')
    monkeypatch.setattr(r,'ROOT',tmp_path/'new_direction')
    with pytest.raises(FileNotFoundError):r.prepare()
    assert not (r.ROOT/'CALL_LEDGER.json').exists()


def test_new_source_and_all_reference_preserved_old_direction_cannot_rebind(monkeypatch):
    monkeypatch.setattr(r,'require_reviewed_source',lambda:{'offline_fixture_only':True})
    ctx=r.context()
    assert ctx['raw_linear_script']==r.parent.latest('draft_s7_r')['output']
    assert ctx['reference_pack']==r.source.original()['reference_pack']
    assert len(ctx['static_visual_manifest']['characters'])==2
    old=r.control.read(r.parent.parent.parent.ROOT/'DELIVERABLE_s6_d6/WHOLE_FILM_DIRECTION.json')
    with pytest.raises(Exception):r.physical.validate_direction(old,ctx)
