from copy import deepcopy
import pytest
from src.content_factory.creative_legal_short_video_projection_v1 import prose,project,render_prompt

def test_current_speech_repeat_is_only_serialized_not_source_changed():
 text='这上面写的是个人原因……是我自己要辞职？';raw='小林嘴形清楚说出\\\"'+text+'\\\"，话尾稍顿。';keep=raw;value=prose(raw,[text],text);assert text not in value;assert '本句' in value;assert raw==keep

def test_future_speech_not_silently_removed():
 with pytest.raises(ValueError):prose('他说下一句', ['下一句。'], '当前句。')
def test_escaped_prop_print_is_not_treated_as_spoken_line():
 assert '个人原因' in prose('看清纸上个人原因', ['我没辞职。'])
def test_complete_source_row_cannot_be_split_to_fit():
 c={'complete':True,'total_duration_seconds':16,'schedule':[{'start':0,'end':16}]}
 with pytest.raises(ValueError,match='cannot split'):project(c)
def test_source_coverage_duration_rounding_and_five_lines():
 from scripts.run_legal_short_director_performance_v3_20261009 import sources,accepted,prefix
 from src.content_factory.creative_legal_short_director_performance_v1 import compile_complete
 c=compile_complete(sources()['full_script'],accepted('director_r1')['output'],prefix(4));ds=project(c);lines=[r['original_text'] for r in c['schedule'] if r['source_kind']=='dialogue'];prompts=[render_prompt(x,lines) for x in ds]
 assert len(lines)==5;assert [r for x in ds for r in x['source_refs']]==[r['source_ref'] for r in c['schedule']];assert sum(x['duration_seconds'] for x in ds)<180
 assert all(sum(p.count(line) for p in prompts)==1 for line in lines)
