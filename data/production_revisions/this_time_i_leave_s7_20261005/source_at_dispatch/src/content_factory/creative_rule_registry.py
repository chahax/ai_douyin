"""Offline rule governance. This inventory is explicitly scoped, not exhaustive."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION='creative_rule_registry/v1'
RULE_SCHEMA={'type':'object','required':['rule_id','category','root_cause','priority','severity','stage','trigger','field_paths','authority_field','source_refs','checker','checker_kind','failure_code','positive_case_ids','negative_case_ids','version','replaces','replacement_rule_ids','status','repair_owner','unknown_disposition','change_action'],
 'properties':{'rule_id':{'type':'string','minLength':1},'category':{'enum':['action','interaction','space','camera','source','interface','handoff']},
 'root_cause':{'type':'string'},'priority':{'enum':['P0','P1','P2']},'severity':{'enum':['blocking','major','advisory']},'stage':{'type':'array','items':{'type':'string'},'minItems':1},
 'trigger':{'type':'object','required':['any_features'],'properties':{'any_features':{'type':'array','items':{'type':'string'}}},'additionalProperties':False},
 'field_paths':{'type':'array','items':{'type':'string'}},'authority_field':{'type':['string','null']},'source_refs':{'type':'array','minItems':1,'items':{'type':'object','required':['path','sha256','anchor'],'properties':{'path':{'type':'string'},'sha256':{'type':'string'},'anchor':{'type':'string'}},'additionalProperties':False}},
 'checker':{'type':['string','null']},'checker_kind':{'enum':['deterministic','semantic','manual']},'failure_code':{'type':'string'},'positive_case_ids':{'type':'array','items':{'type':'string'}},'negative_case_ids':{'type':'array','items':{'type':'string'}},'version':{'type':'string'},'replaces':{'type':'array','items':{'type':'string'}},'replacement_rule_ids':{'type':'array','items':{'type':'string'}},'status':{'enum':['proposed','active','deprecated','retired']},'repair_owner':{'type':'string'},'unknown_disposition':{'enum':['advisory_pending','review_required','blocked']},'change_action':{'enum':['retain','merge','move_to_code','move_to_cases','deprecate','propose']}},'additionalProperties':False}
REGISTRY_SCHEMA={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['schema_version','source_hash','created_at','implementation_status','inventory_scope','rules'],
 'properties':{'schema_version':{'const':SCHEMA_VERSION},'source_hash':{'type':'string'},'created_at':{'type':'string'},'implementation_status':{'type':'string'},
 'inventory_scope':{'type':'object','required':['coverage_denominator','mapped','excluded','unmapped','repository_wide_complete','exclusions'],'properties':{'coverage_denominator':{'type':'integer','minimum':0},'mapped':{'type':'integer','minimum':0},'excluded':{'type':'integer','minimum':0},'unmapped':{'type':'integer','minimum':0},'repository_wide_complete':{'const':False},'exclusions':{'type':'array','items':{'type':'object'}}}},'rules':{'type':'array','items':RULE_SCHEMA}},'additionalProperties':False}


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_fields(context,path):
    parts=path.replace('[*]','.*').split('.');nodes=[context]
    for part in parts:
        output=[]
        for node in nodes:
            if part=='*':
                if isinstance(node,dict):output.extend(node.values())
                elif isinstance(node,list):output.extend(node)
            elif isinstance(node,dict) and part in node:output.append(node[part])
            elif isinstance(node,list) and part.isdigit() and int(part)<len(node):output.append(node[int(part)])
        nodes=output
    return nodes


def validate_registry(registry,root,context,case_ids):
    from jsonschema import Draft202012Validator
    errors=[str(e.message) for e in Draft202012Validator(REGISTRY_SCHEMA).iter_errors(registry)]
    if errors:raise ValueError('REGISTRY_SCHEMA: '+ '; '.join(errors))
    ids=[r['rule_id'] for r in registry['rules']]
    if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_RULE_ID')
    scope=registry['inventory_scope']
    if scope['mapped']+scope['excluded']+scope['unmapped']!=scope['coverage_denominator'] or scope['mapped']!=len(ids):raise ValueError('INVENTORY_DENOMINATOR_MISMATCH')
    for rule in registry['rules']:
        for source in rule['source_refs']:
            path=(Path(root)/source['path']).resolve()
            if not path.is_relative_to(Path(root).resolve()) or not path.is_file():raise ValueError('SOURCE_PATH_INVALID: '+source['path'])
            if file_hash(path)!=source['sha256']:raise ValueError('SOURCE_CHANGED: '+source['path'])
            if source['anchor'] not in path.read_text(encoding='utf-8-sig'):raise ValueError('SOURCE_ANCHOR_MISSING')
        if any(i not in case_ids for i in rule['positive_case_ids']+rule['negative_case_ids']):raise ValueError('UNKNOWN_CASE_ID')
        if rule['status']=='active':
            if not rule['positive_case_ids'] or not rule['negative_case_ids']:raise ValueError('ACTIVE_RULE_NEEDS_BOTH_CASES')
            if not rule['checker'] or rule['checker'].startswith('proposed:'):raise ValueError('ACTIVE_CHECKER_UNIMPLEMENTED')
            file,symbol=rule['checker'].split(':',1)
            tree=ast.parse((Path(root)/file).read_text(encoding='utf-8-sig'))
            if symbol not in {n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}:raise ValueError('CHECKER_SYMBOL_MISSING')
            for field in rule['field_paths']:
                if not resolve_fields(context,field):raise ValueError('ACTIVE_FIELD_UNRESOLVED: '+field)
        if rule['status']=='deprecated' and not rule['replacement_rule_ids']:raise ValueError('DEPRECATED_REPLACEMENT_MISSING')
    return {'schema_valid':True,'inventory_complete_within_declared_scope':scope['unmapped']==0,'repository_wide_complete':False,'rule_count':len(ids)}


def validate_ownership(rows,context):
    seen={}
    for row in rows:
        field=row['field_path']
        if field in seen:raise ValueError('MULTIPLE_FIELD_AUTHORITIES: '+field)
        seen[field]=row['authority']
        if row['status']=='active' and not resolve_fields(context,field):raise ValueError('OWNERSHIP_FIELD_UNRESOLVED: '+field)
        if not row['authority'] or not row.get('owner'):raise ValueError('OWNERSHIP_MISSING')
    return {'unique_fields':len(seen),'conflicting_fields':0}


def select_rules(registry,stage,features,*,semantic_limit=12):
    selected=[];excluded=[]
    for rule in registry['rules']:
        reason=None
        if rule['status']!='active':reason='status_'+rule['status']
        elif stage not in rule['stage']:reason='different_stage'
        elif rule['trigger']['any_features'] and not set(features)&set(rule['trigger']['any_features']):reason='trigger_absent'
        if reason:excluded.append({'rule_id':rule['rule_id'],'reason':reason})
        else:selected.append(rule)
    semantic=sum(r['checker_kind']=='semantic' for r in selected)
    return {'active_rule_ids':[r['rule_id'] for r in selected],'excluded':excluded,'semantic_rule_count':semantic,
            'semantic_limit':semantic_limit,'requires_split_or_merge':semantic>semantic_limit,
            'serialized_characters':len(json.dumps(selected,ensure_ascii=False)), 'token_count':None,
            'token_count_status':'not_tokenized; characters_are_not_tokens','silently_truncated':False}


def resolve_constraints(constraints,*,expression_supported=True):
    if not expression_supported:return {'status':'blocked','code':'EXPRESSION_UNSUPPORTED','conflicts':[]}
    conflicts=[]
    for i,left in enumerate(constraints):
        for right in constraints[i+1:]:
            if left['key']==right['key'] and left['value']!=right['value'] and left['priority']==right['priority'] and left['priority'] in ('P0','P1'):
                conflicts.append({'key':left['key'],'sources':[left['source'],right['source']]})
    if conflicts:return {'status':'blocked','code':'REQUIREMENT_CONFLICT','conflicts':conflicts}
    chosen={}
    for row in sorted(constraints,key=lambda x:x['priority']):chosen.setdefault(row['key'],deepcopy(row))
    return {'status':'resolved','constraints':list(chosen.values()),'conflicts':[]}


def validate_transition(old,new):
    allowed={'proposed':{'proposed','active'},'active':{'active','deprecated'},'deprecated':{'deprecated','retired'},'retired':{'retired'}}
    if new['status'] not in allowed[old['status']]:raise ValueError('INVALID_RULE_STATUS_TRANSITION')
    if old['rule_id']!=new['rule_id']:raise ValueError('RULE_ID_CHANGED')
    if new['status']=='deprecated' and not new['replacement_rule_ids']:raise ValueError('DEPRECATED_REPLACEMENT_MISSING')
    if old!=new and old['version']==new['version']:raise ValueError('RULE_CHANGE_REQUIRES_NEW_VERSION')
    return True


def bind_registry(root,registry_dir):
    """Bind a frozen scoped registry; callers store this in new task state only."""
    root=Path(root).resolve();directory=Path(registry_dir)
    if not directory.is_absolute():directory=root/directory
    directory=directory.resolve()
    if not directory.is_relative_to(root):raise ValueError('REGISTRY_OUTSIDE_WORKSPACE')
    manifest=json.loads((directory/'artifact_manifest.json').read_text(encoding='utf-8'))
    binding={'schema_version':'creative_rule_registry_binding/v1','registry_dir':str(directory.relative_to(root)).replace('\\','/'),
             'artifact_manifest_sha256':file_hash(directory/'artifact_manifest.json'),'rules_sha256':file_hash(directory/'rules.json'),
             'repository_wide_complete':False,'automatic_rule_activation':False}
    validate_registry_binding(binding,root)
    return binding


def validate_registry_binding(binding,root,stage=None,features=None):
    root=Path(root).resolve();directory=(root/binding['registry_dir']).resolve()
    if not directory.is_relative_to(root):raise ValueError('REGISTRY_OUTSIDE_WORKSPACE')
    if binding.get('schema_version')!='creative_rule_registry_binding/v1':raise ValueError('REGISTRY_BINDING_VERSION')
    if file_hash(directory/'artifact_manifest.json')!=binding['artifact_manifest_sha256'] or file_hash(directory/'rules.json')!=binding['rules_sha256']:raise ValueError('REGISTRY_BINDING_CHANGED')
    manifest=json.loads((directory/'artifact_manifest.json').read_text(encoding='utf-8'))
    for row in manifest['artifacts']:
        path=(directory/row['path']).resolve()
        if not path.is_relative_to(directory) or file_hash(path)!=row['sha256']:raise ValueError('REGISTRY_ARTIFACT_CHANGED:'+row['path'])
    registry=json.loads((directory/'rules.json').read_text(encoding='utf-8'));context=json.loads((directory/'fixtures/frozen_context.json').read_text(encoding='utf-8'))['context']
    if (directory/'fixtures/p1_checker_context.json').exists():context={**context,'p1_checker':json.loads((directory/'fixtures/p1_checker_context.json').read_text(encoding='utf-8'))['context']}
    cases=json.loads((directory/'dataset_manifest.json').read_text(encoding='utf-8'))['cases']
    validation=validate_registry(registry,root,context,{c['case_id'] for c in cases})
    validation['runtime_sources']=validate_runtime_sources(directory,root)
    return {'binding':deepcopy(binding),'validation':validation,
            'activation':select_rules(registry,stage,features or []) if stage is not None else None}


def validate_runtime_sources(directory, root):
    """Versioned runtime binding is separate from the scoped rule inventory."""
    path=Path(directory)/'runtime_sources.json'
    if not path.exists():return {'status':'legacy_pack_without_runtime_binding','source_count':0}
    document=json.loads(path.read_text(encoding='utf-8'));root=Path(root).resolve()
    if document.get('schema_version')!='creative_runtime_sources/v1':raise ValueError('RUNTIME_SOURCE_SCHEMA')
    for row in document['sources']:
        source=(root/row['path']).resolve()
        if not source.is_relative_to(root) or not source.is_file():raise ValueError('RUNTIME_SOURCE_MISSING: '+row['path'])
        if file_hash(source)!=row['sha256']:raise ValueError('RUNTIME_SOURCE_CHANGED: '+row['path'])
    return {'status':'verified','source_count':len(document['sources']),'rule_inventory_coverage_claim':False}
