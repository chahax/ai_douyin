import importlib.util
from pathlib import Path
import re

import pytest


spec = importlib.util.spec_from_file_location('spatial_pack', Path(__file__).parents[1]/'scripts/prepare_spatial_reference_pack_v24.py')
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


@pytest.mark.parametrize('sid', ['S01','S02','S03','S04'])
def test_actual_source_retains_dialogue_order_and_all_action_text(sid):
    original = (pack.SOURCE/'sources'/(sid+'.prompt.txt')).read_text(encoding='utf-8')
    text, changes = pack.adapted(original)
    assert re.findall('“[^”]*”', text) == re.findall('“[^”]*”', original)
    recovered = text
    for c in reversed(changes):
        recovered = recovered.replace(c['new'], c['old'])
    assert recovered == original
    assert '<Picture 2>' in text and '<Picture 3>' in text
    if sid == 'S03':
        assert '叶西决的内心独白，以叶西决的画外音呈现：' in text
        assert '男童心声：' not in text


def test_ambiguous_source_cannot_be_rewritten_silently():
    with pytest.raises(ValueError, match='expected original'):
        pack.adapted('Unrecognized input')


def test_freeze_does_not_overwrite_previous_revision(tmp_path):
    p = tmp_path/'audit.json'
    pack.freeze(p, {'source': 'a'})
    pack.freeze(p, {'source': 'a'})
    with pytest.raises(ValueError, match='new revision'):
        pack.freeze(p, {'source': 'b'})
    assert pack.read(p) == {'source':'a'}
