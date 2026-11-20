"""Derived paragraph-address view; never splits author chapters or edits output."""
from copy import deepcopy
import json
from . import corpus_chapter_materials_v6 as materials

VERSION='corpus_reference_view/v1'


def chapter_payload(chapters,plan,book_name=''):
    payload=materials.chapter_payload(chapters,plan,book_name)
    by_id={part['id']:part for chapter in [payload['core_chapter'],*payload['context_chapters']]
           for part in materials.chapters_v4.chapter_passages(chapter)}
    for name in ('paragraph_index','context_reference_index'):
        payload[name]=[{**row,'text':by_id[row['id']]['text']} for row in payload[name]]
    payload['reference_address_policy']={
        'version':VERSION,'complete_chapter_text_unchanged':True,
        'instruction':'原段编号由目录固定，直接按目录text选取ID和连续引文。一个自然段可以含多句话、多条事实；拆分事实不能顺延或重建自然段编号。先完整阅读原章，目录仅为来源地址对照。'}
    return payload


def validate(raw,chapters,plan):
    # Same schema and source acceptance. A bad address gains actionable feedback,
    # never an automatically corrected ID or silently accepted quotation.
    try:
        return materials.validate(raw,chapters,plan)
    except ValueError as exc:
        if str(exc) != 'fact_evidence_quote_not_in_original':raise
        payload=chapter_payload(chapters,plan)
        catalog={row['id']:row['text'] for name in ('paragraph_index','context_reference_index') for row in payload[name]}
        for i,fact in enumerate(raw['facts']):
            for j,ref in enumerate(fact['source_refs']):
                if ref['exact_quote'] not in catalog.get(ref['paragraph_id'],''):
                    matches=[pid for pid,text in catalog.items() if ref['exact_quote'] in text]
                    detail={'fact_id':fact['id'],'path':f'facts.{i}.source_refs.{j}',
                        'claimed_paragraph':ref['paragraph_id'],'exact_quote_found_in':matches,
                        'instruction':'引用地址不匹配；按目录复核该事实的source_refs、叙述锚点和coverage。不要改写原文。'}
                    raise ValueError('fact_evidence_quote_not_in_original:'+json.dumps(detail,ensure_ascii=False)) from exc
        raise
