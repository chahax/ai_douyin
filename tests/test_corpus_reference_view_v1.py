from copy import deepcopy
import json
import pytest

from src.content_factory import corpus_reference_view_v1 as view
from src.content_factory import corpus_chapter_materials_v6 as materials
from src.content_factory import corpus_production_v9 as pipeline
from tests.test_corpus_production_v9 import configured, prepared
from tests.test_corpus_production_v6 import Classifier


def data(tmp_path):
    run,plan=prepared(tmp_path)
    source=pipeline.read(run/'SOURCE.json')
    cp=plan['chapters'][0]
    payload=view.chapter_payload(source['chapters'],cp)
    c=Classifier()
    native=c.call('writer',[{'content':json.dumps(payload,ensure_ascii=False)}])
    return source,cp,payload,json.loads(native.text)


def test_reference_view_keeps_complete_author_chapter_and_neighbors(tmp_path,configured):
    source,cp,payload,raw=data(tmp_path)
    original=materials.chapter_payload(source['chapters'],cp)
    assert payload['core_chapter']==original['core_chapter']
    assert payload['context_chapters']==original['context_chapters']
    chapter_by_index={c['index']:c['text'] for c in source['chapters']}
    for name in ('paragraph_index','context_reference_index'):
        for row in payload[name]:
            index=int(row['id'].split('-')[0][2:])
            assert row['text']==chapter_by_index[index][row['start_offset']:row['end_offset']]
    assert view.validate(raw,source['chapters'],cp)==materials.validate(raw,source['chapters'],cp)


def test_wrong_address_gives_specific_fact_path_and_real_location_without_mutating(tmp_path,configured):
    source,cp,payload,raw=data(tmp_path)
    raw['facts'][0]['source_refs'][0]['exact_quote']=payload['paragraph_index'][1]['text'].strip()
    frozen=deepcopy(raw)
    with pytest.raises(ValueError) as caught:view.validate(raw,source['chapters'],cp)
    message=str(caught.value)
    assert 'facts.0.source_refs.0' in message and 'CH1-F001' in message
    detail=json.loads(message.split(':',1)[1])
    # The fixture repeats this sentence in its neighbour. Preserve both exact
    # matches instead of silently choosing a replacement source for the model.
    assert detail['exact_quote_found_in']==['CH1-P002','CH2-P002']
    assert raw==frozen and len(message)<500


def test_invented_quote_is_rejected_with_no_matching_address(tmp_path,configured):
    source,cp,payload,raw=data(tmp_path)
    raw['facts'][0]['source_refs'][0]['exact_quote']='原文没有这句话。'
    with pytest.raises(ValueError,match=r'"exact_quote_found_in": \[\]'):
        view.validate(raw,source['chapters'],cp)


def test_no_semantic_rewrite_or_new_fields_in_accepted_materials(tmp_path,configured):
    source,cp,payload,raw=data(tmp_path)
    raw['facts'][0]['event_time']='earlier'
    result=view.validate(raw,source['chapters'],cp)
    assert result['facts'][0]['event_time']=='earlier'
    assert result['validation']['semantic_review']=='not_performed'
    assert set(materials.raw_candidate(result)['facts'][0])==set(materials.FACT_KEYS)
