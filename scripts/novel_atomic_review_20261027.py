"""Isolated atomic source comparison with stable fact and unresolved issue IDs."""
from novel_specialist_v2_20261027 import *

OUT=ROOT/'data/corpus_production_trials/20261027_atomic_review'
class Atom(Strict):
    span:str=Field(min_length=1,max_length=100)
    subject:str
    action:str
    object:str
    negation_condition:str
    information_origin:str
    decision:Literal['supported','contradicted','uncertain']
    reason:str
    source_ids:list[str]=Field(min_length=1)
class Resolution(Strict):
    issue_id:str
    decision:Literal['resolved','unresolved']
    reason:str
    source_ids:list[str]=Field(min_length=1)
class Row(Strict):
    fact_id:str
    atoms:list[Atom]=Field(min_length=1)
    obligations:list[Resolution]
    replacement:Fact|None
class Batch(Strict):rows:list[Row]

PROMPT='''逐命题对照完整原文。候选不是事实真相。每条statement按原样连续片段拆成atoms，按序拼接必须逐字等于整条statement（包括标点），不能遗漏或重复。每片尽量只有一个动作/条件/判断；100字符只是结构上限，不是建议长度。对每片分别写主体、动作、对象、否定条件、信息来源，并核查supported/contradicted/uncertain。未知对象不能补人名。区分动作部位、条件中的否定、引号原话与转述、叙述者交代与人物说出、当前表态与未来发生。语义不明不能强行肯定。
本批每个fact_id输出一次。只选source_ids，程序可据此查原文，不抄造引文。任何错误都提出完整replacement，保留原条目所有有据内容、原文语气及正确字段；只有全部有据才replacement=null。不删条目，不能为统一时态改写事件。obligations必须逐一回答输入未决问题，原问题也是待检意见，不必迎合，但不能忽略；resolved表示当前候选已不再有该问题，不表示计划将来修改。所有错误需先修再复核。'''

def validate_batch(raw,facts,source,ledger):
    v=Batch.model_validate(raw).model_dump();ids={f['id']:f for f in facts};known={p['id'] for p in source}
    if len(v['rows'])!=len(ids) or {r['fact_id'] for r in v['rows']}!=set(ids):raise ValueError('fact_coverage')
    for r in v['rows']:
        f=ids[r['fact_id']]
        if ''.join(a['span'] for a in r['atoms'])!=f['statement']:raise ValueError('atom_partition_not_exact:'+r['fact_id'])
        wanted={x['issue_id'] for x in ledger if x['fact_id']==f['id'] and x['status']=='open'}
        if len(r['obligations'])!=len(wanted) or {x['issue_id'] for x in r['obligations']}!=wanted:raise ValueError('obligation_coverage')
        for a in r['atoms']+r['obligations']:
            if not set(a['source_ids'])<=known:raise ValueError('unknown_source_id')
        bad=any(a['decision']!='supported' for a in r['atoms'])
        if bad and r['replacement'] is None:raise ValueError('bad_atom_without_proposal')
        if r['replacement']:
            validate_material({'facts':[r['replacement']]},source)
            if not is_target(r['replacement'],source):raise ValueError('replacement_scope')
    return v

def update_ledger(ledger,rows,iteration):
    result=json.loads(json.dumps(ledger));by={x['issue_id']:x for x in result}
    for r in rows:
        clean=all(a['decision']=='supported' for a in r['atoms']) and r['replacement'] is None
        for resolution in r['obligations']:
            item=by[resolution['issue_id']]
            item.setdefault('history',[]).append({'round':iteration,**resolution})
            if clean and resolution['decision']=='resolved':item['status']='resolved'
        for n,a in enumerate(r['atoms']):
            if a['decision']=='supported':continue
            key=f"R{iteration}-{r['fact_id']}-A{n:02}"
            item={'issue_id':key,'fact_id':r['fact_id'],'status':'open','span':a['span'],'finding':a['reason'],'source_ids':a['source_ids'],'history':[]}
            result.append(item);by[key]=item
    return result

def drive_atomic(initial,source,ledger,call,save):
    current=initial;save('MATERIAL_0',current);save('LEDGER_0',ledger)
    for iteration in range(2):
        facts=bind(current);rows=[]
        for offset in range(0,len(facts),7):
            batch=facts[offset:offset+7];subset=[x for x in ledger if x['status']=='open' and x['fact_id'] in {f['id'] for f in batch}]
            payload={'complete_source':source,'target_chapters':[9,10],'facts':batch,'candidate_sha256':sha(current),'unresolved':subset}
            raw=call(f'R{iteration}_B{offset//7:02}',PROMPT,payload,Batch)
            value=validate_batch(raw,batch,source,ledger);save(f'AUDIT_{iteration}_{offset//7:02}',{'candidate_sha256':sha(current),**value});rows.extend(value['rows'])
        ledger=update_ledger(ledger,rows,iteration);save(f'LEDGER_AFTER_{iteration}',ledger)
        patches=[{'id':r['fact_id'],'fact_id':r['fact_id'],'replacements':[r['replacement']]} for r in rows if r['replacement'] is not None]
        if not patches:return current,ledger,'unresolved_issues' if any(x['status']=='open' for x in ledger) else 'machine_pass_pending_primary'
        if iteration==1:return current,ledger,'repair_limit'
        tasks=content_tasks(patches,current)
        raw=call('CONTENT_CHECK',NEW_JUDGE,{'complete_source':source,'target_chapters':[9,10],'checks':tasks,'candidate_sha256':sha(current)},RefChecks)
        checks=validate_checks(ground(raw,source,'checks'),tasks,source);save('CONTENT_CHECKS',{'tasks':tasks,'checks':checks})
        new,changes=apply_patches(current,patches,tasks,checks)
        save('CHANGES',{'before_sha256':sha(current),'after_sha256':sha(new),**changes})
        if not changes['applied']:return current,ledger,'no_validated_patch'
        current=validate_material(new,source);save('MATERIAL_1',current)
    raise AssertionError()

def main():
    if OUT.exists():raise ValueError('no_replay')
    parent=BASE/'fewshot_v2';state=read(parent/'RESULT.json')
    if state['pending'] is not None:raise ValueError('unknown_parent')
    source=read(BASE/'SOURCE.json');initial=read(parent/'FINAL_MATERIAL.json');review=read(parent/'PRIMARY_REVIEW.json')
    if hashlib.sha256((parent/'FINAL_MATERIAL.json').read_bytes()).hexdigest()!=review['candidate_file_sha256']:raise ValueError('parent_sha')
    ledger=[{'issue_id':f'PRIMARY-{n:02}','fact_id':f"F{x['fact_index']:03}",'status':'open','finding':x['finding'],'source_ids':[x['source_id']],'history':[]} for n,x in enumerate(review['issues'],1)]
    OUT.mkdir();dump(OUT/'PLAN.json',{'source_sha256':sha(source),'initial_sha256':sha(initial),'parent':str(parent),'historical_calls_started':112,'historical_unknown_untouched':1,'prior_specialist_calls':22,'prior_fewshot_repairs':2,'additional_call_limit':11,'additional_repair_limit':1,'authorization':'用户同意继续逐命题核对及未决问题追踪；沿原小说MiniMax文本范围','scope':'已知缺陷回归，不是盲测；不媒体/发布','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pins':pins()})
    dump(OUT/'SOURCE.json',source);session=Session(OUT);session.save();status='needs_attention';error=None
    try:
        final,ledger,status=drive_atomic(initial,source,ledger,session.call,lambda n,v:dump(OUT/(n+'.json'),v));dump(OUT/'FINAL_MATERIAL.json',final);dump(OUT/'FINAL_LEDGER.json',ledger)
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(OUT/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'pending':session.pending,'error':error,'primary_acceptance':'pending'})
    print(json.dumps(read(OUT/'RESULT.json')),flush=True)
if __name__=='__main__':main()
