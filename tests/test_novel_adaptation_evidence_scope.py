from src.content_factory.novel_adaptation.workflow import scene_evidence_ids
from src.content_factory.novel_adaptation.contracts import catalog


def test_selected_span_includes_intermediate_lines_and_required_event_only():
    source={'chapters':[{'index':1,'text':'first\nsecond\nthird\nfourth\nfifth'},
                        {'index':2,'text':'unrelated'}]}
    ids=list(catalog(source))
    result=scene_evidence_ids([{'source_ids':[ids[1],ids[3]]}],[{'source_ids':[ids[0]]}],source)
    assert result==ids[:4] and ids[4] not in result and ids[5] not in result
