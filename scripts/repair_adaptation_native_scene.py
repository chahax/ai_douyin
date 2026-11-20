"""Scoped native beat repair followed by mechanical replay, no automatic semantic pass."""
import argparse,sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c,scenes as sc
from src.content_factory.novel_adaptation.blocking import blocking_schema,compile_blocking,action_contract_prompt
from src.content_factory.novel_adaptation.repair_context import reconstruct,REPAIR_PROMPT
from src.content_factory.novel_adaptation.workflow import scene_evidence_ids,compact_design
from src.content_factory.novel_adaptation.context_projection import encode_state
from src.content_factory.novel_adaptation.patching import schedule_audio
from src.content_factory.novel_adaptation.events import validate_requirements
from src.content_factory.novel_adaptation.reference_repair import checkpoint
from src.content_factory.novel_adaptation.repair_dependencies import expand_transform_shots
from src.content_factory.novel_adaptation.schema_projection import compact_enums
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeClient,EnvelopeWireLedger,WIRE_PROMPT,decode as decode_envelope


def decode_blocking_arrays(proposal):
    """Unwrap only an exact native {item: [...]} array envelope; no prose edits."""
    out=deepcopy(proposal);changed=[]
    for key,row in out.get('records',{}).items():
        value=row.get('blocking')
        if isinstance(value,dict) and set(value)=={'item'} and isinstance(value['item'],list):
            row['blocking']=value['item'];changed.append(key)
    return out,changed


def apply(scene,records,scope):
    if c.digest(scene)!=scope['native_sha256']:raise ValueError('native_scope_stale')
    if set(records)!=set(scope['records']):raise ValueError('repair_record_coverage')
    result=deepcopy(scene);rows={b['id']:b for b in result['beats']}
    for key,changes in records.items():
        owned=scope['records'][key]
        expected=set(owned.get('fields',[]))|({'audio_texts'} if owned.get('audio_indexes') else set())
        if set(changes)!=expected:raise ValueError('native_field_scope')
        for field,value in changes.items():
            if field=='audio_texts':
                if set(value)!={str(i) for i in owned['audio_indexes']}:raise ValueError('audio_index_scope')
                for index,text in value.items():rows[key]['audio'][int(index)]['text']=text
            else:rows[key][field]=deepcopy(value)
    if scope.get('preserve_selected_audio_content'):
        def lines(value):
            return Counter((a['kind'],a['speaker'],a['text']) for b in value['beats'] if b['id'] in scope['records'] for a in b['audio'])
        if lines(result)!=lines(scene):raise ValueError('selected_audio_content_changed')
    return result


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run','scope','native'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--compact-schema',action='store_true')
    p.add_argument('--string-envelope',action='store_true')
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json');design=read(a.prior/'DESIGN_COMPILED.json')
    initial=read(a.prior/'INITIAL_STATE.json');previous=initial;native=read(a.native);scope=read(a.scope)
    if scope['native_sha256']!=digest(native) or scope['source_sha256']!=digest(source):raise ValueError('scope_stale')
    original_scope=deepcopy(scope)
    scope,dependency_changes=expand_transform_shots(native,scope,design)
    if dependency_changes:
        scope['dependency_expansion']=dependency_changes
        scope.setdefault('issues',[]).append('Dependency-added fields: shot subjects must exist after transform timing changes; after_audio anchors must match the revised audio array. If no audio remains, anchor actions to start/end according to their intended order. Preserve unrelated actions, framing and all unselected fields.')
    spec=next(s for s in design['scenes'] if s['id']==native['id']);entities={'entities':packet['entities']}
    contract=read(a.prior/'SOURCE_EVENTS.json');events=[e for e in contract['events'] if e['scene_id']==spec['id']]
    previous,context=reconstruct(design,entities,source,previous,spec['id'],lambda name:read(a.prior/name),contract['events'])
    if scope.get('previous_sha256')!=digest(previous):raise ValueError('repair_scope_previous_state_mismatch')
    facts=[f for f in packet['facts'] if f['id'] in spec['fact_ids']]
    schema=blocking_schema(design,entities,spec['fact_ids'],source,previous,scene_evidence_ids(facts,events,source))
    properties=schema['properties']['beats']['items']['properties'];fields={}
    for key,row in scope['records'].items():
        props={field:({'$ref':'#/$defs/blocking'} if field=='blocking' else properties[field]) for field in row.get('fields',[])}
        if row.get('audio_indexes'):props['audio_texts']=c.obj(**{str(i):c.TEXT for i in row['audio_indexes']})
        fields[key]=c.obj(**props)
    patch_schema=c.obj(records=c.obj(**fields));patch_schema['$defs']={'blocking':deepcopy(properties['blocking'])}
    if a.compact_schema:patch_schema=compact_enums(patch_schema)
    plan=read(a.prior/'PLAN.json')
    # Continue within the outstanding engineering window, never reset it.
    if old['calls_started']>=plan['max_calls']:raise ValueError('engineering_window_exhausted')
    a.run.mkdir(parents=True,exist_ok=False)
    freeze(a.run/'ORIGINAL_SCOPE.json',original_scope)
    freeze(a.run/'REPAIR_CONTEXT.json',context)
    freeze(a.run/'SCENE_PREVIOUS_STATE.json',previous)
    for row in context['replayed']:
        for suffix in ('_FINAL.json','_END_STATE.json'):
            freeze(a.run/(row['scene_id']+suffix),read(a.prior/(row['scene_id']+suffix)))
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('DESIGN_COMPILED',design),('INITIAL_STATE',initial),
                       ('BEFORE_NATIVE',native),('SCOPE',scope),('SOURCE_EVENTS',contract),('SOURCE_EVENTS_REVIEW',read(a.prior/'SOURCE_EVENTS_REVIEW.json')),
                       ('PREVIOUS_EPISODE_HANDOFF',read(a.prior/'PREVIOUS_EPISODE_HANDOFF.json')),('BRIEF',read(a.prior/'BRIEF.json'))]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'calls_carried':old['calls_started'],
        'tokens_carried':old['reported_tokens'],'max_calls_preserved':plan['max_calls']})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    client=StringEnvelopeClient(a.run,plan) if a.string_envelope else NativeClient(a.run,plan)
    ledger=(EnvelopeWireLedger if a.string_envelope else Ledger)(a.run,plan,state,client);ledger.save()
    try:
        proposal=ledger.call('NATIVE_FIELD_PATCH','writer',REPAIR_PROMPT+action_contract_prompt(design)+(WIRE_PROMPT if a.string_envelope else ''),
            {'complete_chapters':c.indexed_chapters(source),'candidate':native,'design':compact_design(design,spec['id']),
             'previous_state':encode_state(previous,design,compact_events=a.string_envelope),'scope':scope},patch_schema)
        if a.string_envelope:
            proposal=decode_envelope(proposal)
            freeze(a.run/'ENVELOPE_DECODED.json',proposal)
        proposal,decoded=decode_blocking_arrays(proposal)
        if decoded:freeze(a.run/'PROTOCOL_DECODE.json',{'operation':'exact_item_array_unwrap','records':decoded,'decoded':proposal})
        errors=c.schema_issues(proposal,patch_schema,'native_patch')
        if errors:raise c.ContractError(errors)
        fixed=apply(native,proposal['records'],scope);freeze(a.run/'NATIVE_FIXED.json',fixed)
        scene=compile_blocking(fixed,design,entities,schema);scene,timing=schedule_audio(scene)
        execution_spec={**spec,'duration_seconds':timing['duration_seconds']};effects=[]
        end=sc.advance(scene,execution_spec,design,entities,spec['fact_ids'],source,previous,effects=effects)
        validate_requirements({'scenes':[scene]},{'events':events},transition_effects=effects)
        freeze(a.run/'COMPILED_SCENE.json',scene);freeze(a.run/'END_STATE.json',end)
        freeze(a.run/(spec['id']+'_FINAL.json'),scene);freeze(a.run/(spec['id']+'_END_STATE.json'),end)
        freeze(a.run/'NATIVE_CHECKPOINTS.json',{fixed['id']:checkpoint(fixed,source,design,previous)})
        state['status']='scene_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
