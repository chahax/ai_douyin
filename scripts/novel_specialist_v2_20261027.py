"""Source-ID evidence and independently grounded, content-preserving rewrites."""
from novel_specialist_review_20261027 import *
class Ref(Strict):source_id:str
class RefPatch(Strict):
    fact_id:str
    bad_span:str=Field(min_length=1)
    reason:str=Field(min_length=1)
    evidence:list[Ref]=Field(min_length=1)
    replacements:list[Fact]
class RefAudit(Strict):
    checked_fact_ids:list[str]
    patches:list[RefPatch]
class RefCheck(Strict):
    check_id:str
    decision:Literal['supported','rejected','uncertain']
    reason:str=Field(min_length=1)
    evidence:list[Ref]=Field(min_length=1)
class RefChecks(Strict):checks:list[RefCheck]
def ground(value,source,key):
    index={p['id']:p['text'] for p in source};result=json.loads(json.dumps(value))
    for row in result[key]:
        for e in row['evidence']:
            if e['source_id'] not in index:raise ValueError('unknown_source_id')
            e['quote']=index[e['source_id']]
    return result
def content_tasks(patches,material):
    facts={f['id']:f for f in bind(material)};tasks=[]
    for p in patches:
        # Reviewer diagnosis/prose deliberately excluded from the source-grounding checks.
        context={'patch_id':p['id'],'original':facts[p['fact_id']],'replacement_facts':p['replacements']}
        tasks.append({'check_id':p['id']+'/retention','kind':'retention',**context})
        for i,f in enumerate(p['replacements']):tasks.append({'check_id':p['id']+f'/replacement/{i}','kind':'replacement','replacement':f,**context})
        if not p['replacements']:tasks.append({'check_id':p['id']+'/scope_removal','kind':'scope_removal',**context})
    return tasks
NEW_REVIEW=REVIEW.replace('并逐字引用原段','并选择原段编号')+' 本版evidence只输出固定source_id，不抄引文。程序会按ID附上完整原段用于核验。'
NEW_JUDGE='''独立比较原文、原条目和候选替换，不看审核者对错误的定性。只在替换内容本身有原文依据且保留全部正确重要信息时supported。合理猜测不能强行写成确定；原条目的无依据细节可以去掉，但已被原文确定的信息不能淡化或删掉。
retention：原条目中原文支持的每项重要内容是否都被保留，改动是否仅纠正错误/删除无据细节/拆分语气？
replacement：这一替换条目每个主体、动作、对象、限定、时间及mode是否被原文支持？一部分不成立就不能supported。
scope_removal：整条是否仅为邻章背景，移至上下文不会丢失目标章事件？
evidence只选固定source_id，由程序附完整原段。每个check_id都判断，依据不足用rejected或uncertain。这不等于审核者的原诊断正确。'''
def drive_v2(initial,source,call,save,cached):
    current=validate_material(initial,source);save('MATERIAL_0',current)
    for iteration in range(3):
        common={'complete_source':source,'target_chapters':[9,10],'candidate':bind(current),'candidate_sha256':sha(current)};patches=[]
        for role,focus in ROLES.items():
            name=f'R{iteration}_{role}'
            if iteration==0 and role in cached:review=validate_audit(cached[role],current,source)
            else:
                raw=call(name,NEW_REVIEW+' 专项：'+focus,common,RefAudit)
                review=validate_audit(ground(raw,source,'patches'),current,source)
                save(name+'_PROGRAM_GROUNDED',{'evidence_origin':'program_full_source_paragraph_not_model_quote','value':review})
            save(f'AUDIT_{iteration}_{role}',{'candidate_sha256':sha(current),'review':review})
            patches.extend({'id':f'{role}-{i:03}','role':role,**p} for i,p in enumerate(review['patches'],1))
        if not patches:return current,'unresolved_scope' if any(not is_target(f,source) for f in current['facts']) else 'machine_pass_pending_primary',iteration
        if iteration==2:return current,'repair_limit',iteration
        tasks=content_tasks(patches,current)
        raw=call(f'R{iteration}_content_check',NEW_JUDGE,{'complete_source':source,'target_chapters':[9,10],'checks':tasks,'candidate_sha256':sha(current)},RefChecks)
        checks=validate_checks(ground(raw,source,'checks'),tasks,source)
        save(f'CHECKS_{iteration}',{'candidate_sha256':sha(current),'evidence_origin':'program_full_source_paragraph_not_model_quote','tasks':tasks,'checks':checks})
        new,changes=apply_patches(current,patches,tasks,checks)
        save(f'CHANGES_{iteration}',{'before_sha256':sha(current),'after_sha256':sha(new),'policy':'grounded_content_preserving_rewrite_not_diagnosis_endorsement',**changes})
        if not changes['applied']:return current,'no_grounded_rewrite',iteration
        current=validate_material(new,source);save(f'MATERIAL_{iteration+1}',current)
    raise AssertionError('unreachable')
def main(arm):
    run=BASE/(arm+'_v2');parent=BASE/arm;continuation=BASE/(arm+'_continued')
    if run.exists():raise ValueError('no_replay')
    parents=[read(p/'RESULT.json') for p in (parent,continuation)]
    if any(r['pending'] is not None for r in parents):raise ValueError('unknown_parent')
    used=sum(r['calls'] for r in parents);source=read(BASE/'SOURCE.json');initial=read(BASE/(arm+'_INITIAL.json'));cached={};receipts=[]
    for role in ROLES:
        for p in (continuation,parent):
            path=p/f'AUDIT_0_{role}.json'
            if path.exists():
                value=read(path);validate_audit(value['review'],initial,source)
                if value['candidate_sha256']!=sha(initial):raise ValueError('cached_candidate_mismatch')
                cached[role]=value['review'];receipts.append({'path':str(path),'sha256':sha(value)});break
    run.mkdir();dump(run/'PLAN.json',{'parents':[str(parent),str(continuation)],'prior_calls':used,'remaining_calls':13-used,'total_limit_unchanged':13,'prior_new_repairs':0,'max_additional_repairs':2,'source_sha256':sha(source),'candidate_sha256':sha(initial),'cached_reviews':receipts,'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pins':pins(),'policy':'审核理由不自动采纳；只采用有原文依据并完整保留正确内容的重述；三路复审。','evidence':'模型只选择固定原段ID；完整引文由程序附上，原模型旧错引不改、不冒充模型逐字引文。'})
    session=Session(run);session.save();error=None;status='needs_attention';iterations=0
    def call(name,prompt,payload,output):
        if session.calls+used>=13:raise ValueError('cumulative_engineering_limit')
        return session.call(name,prompt,payload,output)
    try:
        final,status,iterations=drive_v2(initial,source,call,lambda n,v:dump(run/(n+'.json'),v),cached);dump(run/'FINAL_MATERIAL.json',final)
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:600]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'pending':session.pending,'error':error,'new_repairs':iterations,'prior_calls':used,'acceptance':'pending_primary_review'})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main(sys.argv[1])
