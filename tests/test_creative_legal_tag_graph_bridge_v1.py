"""Evidence actually reaches the existing client boundary; no paid requests."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_story_emotion import digest
from src.content_factory import creative_legal_tag_graph_bridge_v1 as bridge
from src.trend_intelligence.legal_tag_graph_v1 import build_graph
from test_creative_trend_bridge import source_fixture, direction_fixture, confirmation_fixture, NOW, REFERENCE, STANDARDS
from test_trend_creative_text_trial_v1 import runtime_case, response


def bundle():
    source = source_fixture()
    source['account_profile']['domain_strategy_id'] = 'legal_services'
    source['account_profile']['allowed_formats'] = ['案例拆解','律师真人口播']
    source['account_profile']['seed_keywords'] = ['劳动','法律']
    for k in ('collection_run','opportunity'):
        source[k]['domain_strategy_id'] = 'legal_services'
    source['opportunity']['title'] = '被迫离职'
    for i,r in enumerate(source['observations']):
        r.update(hashtags=['被迫离职','劳动仲裁','经济补偿金','抖来普法2026','北京劳动律师'],
                 author='模拟作者'+str(i%4), keyword='被迫离职' if i%2 else '劳动仲裁')
    source['observations'].append(deepcopy(source['observations'][0]))
    graph = build_graph(source)
    packet = bridge.build_packet(source,graph,REFERENCE.read_text(encoding='utf-8'),
        json.loads(STANDARDS.read_text(encoding='utf-8')),now=NOW,focus_label='被迫离职')
    facts = json.loads(Path('data/qa/legal_new_batch_script_flow_20261007/round_01/LABOUR_LEGAL_FACTS.json').read_text(encoding='utf-8'))
    direction = direction_fixture(packet)
    direction['account_fit']['proposed_format'] = '案例拆解'
    return source,graph,packet,facts,direction


def test_multiple_sources_and_no_campaign_or_creator_in_story_catalog():
    source,graph,packet,facts,_ = bundle()
    candidate = packet['candidate']
    assert candidate['support_video_count'] == 20
    assert candidate['visible_author_count'] == 4
    assert len(candidate['selected_item_ids']) == 20
    assert len(packet['tag_catalog']) >= 2
    assert not {'抖来普法2026','北京劳动律师'} & {t['label'] for t in packet['tag_catalog']}
    assert packet['human_direction_confirmation_inherited'] is False
    assert source['opportunity']['selected_item_ids'] == ['i'+str(i) for i in range(20)]
    preview = bridge.build_preview(packet,facts,now=NOW)
    context = json.loads(preview['messages'][1]['content'])
    assert context['tag_graph_evidence']['candidate'] == candidate
    assert context['tag_graph_evidence']['full_graph_sha256'] == digest(graph)
    assert len(context['tag_graph_evidence']['supporting_documents']) == 20
    assert context['stage_assignment']['publisher_later']['workflow_profile'] == source['account_profile']['workflow_profile']
    assert 'workflow_profile' not in context['account_profile']
    assert preview['submitted'] is False and preview['dispatch_allowed'] is False


@pytest.mark.parametrize('fault',['graph','source','derived_selection','catalog','stale'])
def test_tampering_or_stale_evidence_refused_before_client(fault):
    _,_,packet,facts,_ = bundle()
    if fault == 'graph': packet['graph']['nodes'][0]['support_video_count'] += 1
    elif fault == 'source': packet['graph_source']['account_profile']['profile_version'] += 1
    elif fault == 'derived_selection': packet['candidate']['selected_item_ids'] = ['invented']
    elif fault == 'catalog': packet['tag_catalog'].append({'tag_id':'fake'})
    with pytest.raises(ValueError):
        bridge.build_wire(packet,facts,now='2026-10-12T04:00:00Z' if fault=='stale' else NOW)


@pytest.mark.parametrize('fault',['missing','old_packet','changed_direction','wrong_format'])
def test_graph_reselection_never_inherits_old_human_confirmation(fault):
    _,_,packet,facts,direction = bundle()
    confirmation = confirmation_fixture(packet,direction)
    if fault == 'missing': confirmation = None
    elif fault == 'old_packet': confirmation['packet_sha256'] = digest(packet['base_packet'])
    elif fault == 'changed_direction': direction['creative_brief']['turn'] = '未经确认的变化'
    else:
        direction['account_fit']['proposed_format'] = '律师真人口播'
        confirmation = confirmation_fixture(packet,direction)
    with pytest.raises(ValueError):
        bridge.build_wire(packet,facts,now=NOW,stage='draft',direction=direction,confirmation=confirmation)


def test_graph_reference_and_confirmation_preserved_in_complete_writer():
    _,graph,packet,facts,direction = bundle()
    confirm = confirmation_fixture(packet,direction)
    confirm['user_statement'] = '模拟确认：不用没盖章当违法依据，仅测试'
    wire = bridge.build_wire(packet,facts,now=NOW,stage='draft',direction=direction,confirmation=confirm)
    c = json.loads(wire['messages'][1]['content'])
    assert c['confirmation'] == confirm and c['creative_brief'] == direction['creative_brief']
    assert c['reference_fulltext'] == REFERENCE.read_text(encoding='utf-8')
    assert c['verified_legal_context'] == facts
    assert c['tag_graph_evidence']['full_graph_sha256'] == digest(graph)
    assert wire['model']=='MiniMax-M3' and wire['parameters']['thinking']=='disabled'
    assert not wire['submitted'] and not wire['automatic_retry']


def test_existing_runtime_receives_graph_once_and_preserves_inherited_ledger(tmp_path):
    _,graph,packet,facts,direction = bundle()
    rt,calls,provider = runtime_case(tmp_path)
    received = []
    def fake(*a,**kw):
        received.append((a,kw))
        return response(direction)
    provider.handler = fake
    wire = bridge.build_wire(packet,facts,now=NOW)
    result = rt.dispatch('graph_direction_offline_only',wire,lambda v:bridge.validate_direction(v,packet))
    replay = rt.dispatch('graph_direction_offline_only',wire,lambda v:bridge.validate_direction(v,packet))
    assert result['status']=='contract_valid' and replay['ordinal']==result['ordinal']
    assert len(calls)==1
    args,kwargs=received[0]
    # Same prepared messages pass through the actual runtime's client.call boundary.
    messages = kwargs.get('messages')
    if messages is None:
        messages = next(x for x in args if isinstance(x,list) and x and isinstance(x[0],dict) and 'role' in x[0])
    c=json.loads(messages[1]['content'])
    assert c['tag_graph_evidence']['full_graph_sha256']==digest(graph)
    assert c['reference_fulltext']==REFERENCE.read_text(encoding='utf-8')
    ledger=json.loads(rt.ledger.read_text(encoding='utf-8'))
    assert ledger['starting_spend']['calls_started']==276
    assert ledger['starting_spend']['reported_tokens']==4642952
    assert ledger['starting_spend']['unknown_token_reservations']==93117


def test_non_anchor_edges_are_not_mistaken_for_selected_story_evidence():
    source,_,_,facts,_ = bundle()
    for i in range(20,30):
        source['observations'].append(dict(source['observations'][0], item_id='i'+str(i),
            video_id='v'+str(i), author='extra'+str(i), hashtags=['劳动仲裁','经济补偿金']))
    graph=build_graph(source)
    packet=bridge.build_packet(source,graph,REFERENCE.read_text(encoding='utf-8'),
        json.loads(STANDARDS.read_text(encoding='utf-8')),now=NOW,focus_label='被迫离职')
    context=json.loads(bridge.build_preview(packet,facts,now=NOW)['messages'][1]['content'])
    evidence=context['tag_graph_evidence']
    anchor=packet['candidate']['anchor_tag_id']
    vids=set(packet['candidate']['support_video_ids'])
    assert len(evidence['supporting_documents'])==20
    assert all(anchor in (e['source'],e['target']) and set(e['support_video_ids'])<=vids
               for e in evidence['selected_edges'])
    n=next(n for n in evidence['selected_nodes'] if n['label']=='劳动仲裁')
    assert n['batch_support_video_count']==30 and n['candidate_support_video_count']==20
