"""Thin explicit native-performance / encoded-frame bridge. No submit method."""
import argparse
import json
import math
from pathlib import Path
import sys
from dataclasses import asdict
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0,str(PROJECT))
from scripts import creative_world_scene_media_probe_v1 as base
from scripts.creative_resume_dispatch_v3 import digest

VERSION='creative_world_scene_media_probe/v2'
Config=base.Config


def encoding_identity(production):
    return {k:production[k] for k in ('native_source_duration_seconds','native_integer_duration_seconds',
        'encoded_duration_seconds','encoding_hold_seconds','frame_length','video_prompt_sha256','production_review_context_sha256')}


def verify_encoding(production):
    p=encoding_identity(production)
    for k in ('native_source_duration_seconds','native_integer_duration_seconds','encoded_duration_seconds','encoding_hold_seconds'):
        base.check(type(p[k]) in (int,float) and math.isfinite(p[k]),'finite explicit native/encoded timing required')
    frames=p['frame_length']; native=p['native_source_duration_seconds']; hold=p['encoding_hold_seconds']; encoded=p['encoded_duration_seconds']
    base.check(type(frames) is int and 5<=frames<=362 and frames%17==5,'actual H3 frame grid required')
    base.check(0<native<=15 and p['native_integer_duration_seconds']==max(4,math.ceil(round(native,6))),
        'original compiled performance source duration must remain explicit')
    base.check(abs(encoded-frames/24)<1e-8 and abs(encoded-native-hold)<1e-8 and 0<=hold<=17/24+1e-8,
        'encoding hold must equal the bounded upward grid remainder, never hide extra acting')
    base.check(production['duration_seconds']==encoded and production.get('encoding_hold_reviewed') is True
        and production.get('encoding_certificate_sha256')==digest(p),
        'same-native actual prompt and production review must bind the explicit encoding hold')
    return {'schema':VERSION+'/native_encoding','identity':p,'encoding_certificate_sha256':digest(p),
        'encoding_hold_reviewed':True,'new_substantive_action_allowed':False,'speech_speed_changed':False}


def prepare(config,**kwargs):
    if 'encoding_verifier' in kwargs:raise ValueError('v2 uses its fixed explicit encoding verifier')
    base.check(Path(config.project).resolve()==base.PROJECT.resolve(),'actual project workspace required')
    prepared=base.prepare(config,encoding_verifier=verify_encoding,**kwargs)
    root=Path(config.output_root).resolve()
    base.dump(root/'MEDIA_CONFIG_V2.json',asdict(config))
    result={'schema':VERSION+'/prepared','status':'prepared_requires_root_review_and_single_submitter',
        'config_path':str(root/'MEDIA_CONFIG_V2.json'),'config_sha256':base.sha(root/'MEDIA_CONFIG_V2.json'),
        'base_prepared_path':str(root/'PREPARED.json'),'base_prepared_sha256':base.sha(root/'PREPARED.json'),
        'native_encoding':prepared['timing']['native_encoding'],'graph_sha256':prepared['graph_sha256'],
        'production_handoff_sha256':prepared['production_handoff_sha256'],'text_handoff_sha256':prepared['text_handoff_sha256'],
        'synthetic':prepared['synthetic'],'eligible_for_root_single_submit_review':prepared['eligible_for_root_single_submit_review'],
        'media_submissions':0,'media_claim_created':False,'submit_supported_here':False,'review_status':'awaiting_human_review'}
    base.dump(root/'PREPARED_V2.json',result)
    return result


def verify_prepared(root):
    """Rebuild the real native graph and references, without GET/POST or claims."""
    root=base._inside(root,base.PROJECT)
    v2=base.read(root/'PREPARED_V2.json'); old=base.read(root/'PREPARED.json')
    base.check(v2.get('schema')==VERSION+'/prepared' and v2.get('synthetic') is False
        and v2.get('eligible_for_root_single_submit_review') is True and old.get('synthetic') is False,
        'synthetic/offline preparation is never a live media certificate')
    base.check(v2.get('base_prepared_path')==str(root/'PREPARED.json')
        and v2.get('base_prepared_sha256')==base.sha(root/'PREPARED.json')
        and v2.get('config_path')==str(root/'MEDIA_CONFIG_V2.json')
        and v2.get('config_sha256')==base.sha(root/'MEDIA_CONFIG_V2.json'), 'original prepared/config identities changed')
    config=Config(**base.read(root/'MEDIA_CONFIG_V2.json'))
    base.check(Path(config.project).resolve()==base.PROJECT.resolve(),'actual project workspace required')
    base.check(Path(config.output_root).resolve()==root,'media preparation belongs to another output root')
    text,production,native,paths,timing=base.verified_sources(config,encoding_verifier=verify_encoding)
    base.check(digest(base.read(root/'TEXT_VERIFIED.json'))==digest(text) and digest(base.read(root/'PRODUCTION_VERIFIED.json'))==digest(production),
        'original real text/production proof differs from preparation')
    base.check(v2['native_encoding']==old['timing']['native_encoding']==timing['native_encoding']
        and old['timing']==timing,'original native/encoded timing certificate changed')
    expected_refs=base.reference_bindings(config,production,native['goal'])
    unique='world_scene_'+base.text_sha(str(root))[:20]; prefix='world_scene_live/'+unique
    files={}
    def bind(path):
        path=base._inside(path,config.project);files[str(path)]=base.sha(path);return path
    for index,row in enumerate(expected_refs,1):
        target=Path(config.service_root).resolve()/'input'/unique/('reference_'+str(index)+'.png')
        row.update(input_path=str(target),input_relative_path=target.relative_to(Path(config.service_root).resolve()/'input').as_posix())
        base.check(base.sha(target)==row['source_sha256'],'original staged still bytes changed')
        bind(target);bind(row['source_path'])
        if 'asset_gender_evidence' in row:bind(row['asset_gender_evidence']['path'])
    base.check(base.read(root/'REFERENCE_MAP.json')==expected_refs,'actual ordered actor/reference bindings changed')
    template=bind(config.template_path); ledger=bind(config.ledger_path)
    base.check(old['template']['file_sha256']==base.sha(template) and old['failure_ledger']['file_sha256']==base.sha(ledger),
        'original template or same-story failure ledger changed before submission')
    expected_graph=base.build_graph(base.read(template),production['actual_video_prompt'],expected_refs,timing,prefix,config.seed)
    actual_graph=base.read(root/'workflow_api.json')
    base.check(digest(actual_graph)==digest(expected_graph) and base.sha(root/'workflow_api.json')==old['graph_sha256']==v2['graph_sha256'],
        'actual graph differs from original native prompt/reference/encoding compilation')
    base.check((root/'PROMPT.txt').read_text('utf-8')==production['actual_video_prompt']
        and base.sha(root/'PROMPT.txt')==old['prompt_sha256'],'actual reviewed prompt bytes changed')
    base.check(old['output_prefix']==prefix and old['reference_map_sha256']==base.sha(root/'REFERENCE_MAP.json')
        and old['native_identity']==text['identity'] and old['source_refs']==production['source_refs']
        and old['text_handoff_sha256']==v2['text_handoff_sha256']==text['handoff_sha256']
        and old['production_handoff_sha256']==v2['production_handoff_sha256']==production['production_handoff_sha256'],
        'same-native prepared source or output namespace changed')
    for row in old['source_paths'].values():
        base.check(base.sha(row['path'])==row['file_sha256'],'original native source file changed');bind(row['path'])
    for row in production['proof_files']:
        base.check(base.sha(row['path'])==row['file_sha256'],'original production proof file changed');bind(row['path'])
    for path,expected in text.get('source_files',{}).items():
        base.check(base.sha(path)==expected,'original verified text dependency changed');bind(path)
    for name in ('PREPARED.json','PREPARED_V2.json','MEDIA_CONFIG_V2.json','workflow_api.json','PROMPT.txt',
            'REFERENCE_MAP.json','TEXT_VERIFIED.json','PRODUCTION_VERIFIED.json','SERVICE_READONLY.json'):bind(root/name)
    bind(__file__);bind(base.__file__);bind(config.catalog_path)
    bind(base.PROJECT/'scripts/creative_world_scene_text_handoff_verifier_v1.py')
    return {'schema':VERSION+'/verified_prepared','valid':True,'accepted':True,'prepared_root':str(root),'config':asdict(config),
        'paths':{'text_root':config.text_root,'production_root':config.production_root},'base_prepared':old,'prepared_v2':v2,
        'graph':actual_graph,'reference_map':expected_refs,'text_verified':text,'production_verified':production,
        'source_files':files,'media_submissions':0,'media_claim_created':False,'authorizes_media_dispatch':False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--text-root',required=True);p.add_argument('--production-root',required=True)
    p.add_argument('--output-root',required=True);p.add_argument('--seed',required=True,type=int);a=p.parse_args(argv)
    try:result=prepare(Config(a.text_root,a.production_root,a.output_root,a.seed))
    except (base.PreparationBlocked,ImportError,OSError,KeyError,TypeError,ValueError,base.ValidationError) as e:
        print(json.dumps({'schema':VERSION+'/blocked','status':'blocked_before_media_preparation','reason':str(e),
            'media_submissions':0,'media_claim_created':False},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
