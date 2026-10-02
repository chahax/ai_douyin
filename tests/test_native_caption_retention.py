import pytest
from scripts.render_clean_script_captions import retain_native_cues


def test_existing_word_is_retained_without_duplicate_overlay():
    cues=[{'text':'等等','start':.29,'end':.81},{'text':'先核清楚','start':1.6,'end':3}]
    review={'native_caption_free':False,'native_caption_spans':[{'text':'等等','start':.3,'end':.9,'notes':'Viewed full span'}]}
    remaining,retained=retain_native_cues(cues,review,7)
    assert remaining==[cues[1]] and retained==[cues[0]]
    review['native_caption_spans'][0]['end']=2
    with pytest.raises(ValueError,match='overlaps'):retain_native_cues(cues,review,7)
    review['native_caption_spans'][0]['text']='等一下'
    with pytest.raises(ValueError,match='match one full'):retain_native_cues(cues,review,7)
