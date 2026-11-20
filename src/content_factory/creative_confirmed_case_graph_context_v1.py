"""Keep a confirmed story source intact while attaching exact-batch graph evidence."""
from copy import deepcopy
import json
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_trend_writer_context_v3 import build_confirmed_case_wire
from src.content_factory.creative_legal_tag_graph_bridge_v1 import validate_packet as validate_graph_packet, _evidence

VERSION='confirmed_case_graph_context/v1'


def build_wire(packet,facts,graph_packet,scope,stage,*,now,direction,confirmation,script=None,revision=None):
    if stage not in ('draft','review'):
        raise ValueError('complete script or whole-text review required')
    validate_graph_packet(graph_packet,now=now)
    if digest(packet['inputs']['source']) != digest(graph_packet['graph_source']):
        raise ValueError('supplemental graph must use the exact original source batch')
    if (confirmation.get('supplemental_graph_packet_sha256') != digest(graph_packet)
        or confirmation.get('content_scope_sha256') != digest(scope)
        or scope.get('source_direction_sha256') != digest(direction)
        or scope.get('confirmation_event_id') != confirmation.get('message_id')):
        raise ValueError('actual confirmation must bind original direction, disclosed scope and supplemental graph')
    if len(direction['characters']) != 2:
        raise ValueError('confirmed legal case requires original two characters')
    wire=build_confirmed_case_wire(packet,facts,stage,now=now,direction=direction,confirmation=confirmation,script=script)
    context=json.loads(wire['messages'][1]['content'])
    context['supplemental_tag_graph_evidence']=_evidence(graph_packet)
    context['confirmed_current_story_scope']=deepcopy(scope)
    context['source_direction']=deepcopy(direction)
    context['evidence_roles']['supplemental_tag_graph_evidence']='exact same batch audience-question evidence only; not a replacement direction, law or story validation'
    context['stage_assignment']['direction_priority']='原方向为不可变来源；按已披露并在当前继续创作指令下采用的冲突范围写完整新稿；未采用细节不成为复审强制条件。'
    context['stage_assignment']['ending_policy']='现场有可见后果和情绪释放；不以咨询CTA或没盖章、拒签即必胜、固定赔偿作为收束。'
    if revision is not None:
        if stage!='draft' or not revision.get('previous_complete_script') or not revision.get('review'):
            raise ValueError('complete prior script and source-bound review required for intentional content revision')
        context['complete_content_revision']=deepcopy(revision)
    wire['messages'][1]['content']=json.dumps(context,ensure_ascii=False)
    wire['input_provenance'].update(source_context_sha256=digest(context),
        supplemental_graph_packet_sha256=digest(graph_packet),supplemental_graph_sha256=graph_packet['graph_sha256'],
        confirmed_content_scope_sha256=digest(scope),confirmation_sha256=digest(confirmation))
    if revision is not None: wire['input_provenance']['complete_revision_sha256']=digest(revision)
    wire['operator_version']=VERSION
    return wire
