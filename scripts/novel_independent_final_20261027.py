"""Independent configured DeepSeek final review; original responses retained."""
from novel_production_probe_20261027 import *
class FinalIssue(Strict):
    unit_id:str
    severity:Literal['must_fix','suggestion']
    reason:str
    source_ids:list[str]=Field(min_length=1)
class FinalReview(Strict):
    checked_unit_ids:list[str]
    issues:list[FinalIssue]
def main():
    run=PROD.with_name(PROD.name+'_deepseek_final')
    if run.exists():raise ValueError('no_replay')
    source=read(PROD/'SOURCE.json');parent=PROD.with_name(PROD.name+'_echo_continued');episode=read(parent/'E1_FINAL.json');foundation=read(PROD.with_name(PROD.name+'_repair')/'FOUNDATION.json')
    units=[{'unit_id':f'WORLD{i:03}','path':f'foundation.world_facts.{i}','value':f} for i,f in enumerate(foundation['world_facts'])]+[{'unit_id':s['id'],'path':f'episode.shots.{i}','value':s} for i,s in enumerate(episode['shots'])]
    run.mkdir();dump(run/'PLAN.json',{'authorization':'既有真实小说相关原文及前两集完整稿交DeepSeek终审；用户要求持续修复测试；本次首集完整稿与相关原文','provider':'deepseek','max_calls':1,'source_sha256':sha(source),'candidate_sha256':sha({'episode':episode,'foundation':foundation}),'no_previous_review_provided':True})
    sys.path.insert(0,str(ROOT))
    from creative_deepseek_tool_client_v1 import CreativeDeepSeekToolClients
    from src.content_factory.creative_workflow_roles import RoleResponseError,role_config
    cfg=role_config('director')
    prompt='''独立终审完整小说改编首集及其基础，不接收其他审核意见。逐项核对原文、当前/原书未来、人物行为与对白归属、条件频率、时序道具与在场状态；跨镜头不能无依据出现/消失、重复获得道具。合理美术补足允许，角色“哥哥”自称允许，不要把正常中文自称误认成另一个人。未明确退出仍在场与镜头看不见是两回事。原文“如果A则B”不能改写成“A经常发生”。结合完整上下文核查证据，不能只凭单段存在相同字词。检查90秒是否可演出（仅文本估计，不宣称实际配音）。只报真实问题，建议不升级硬错。checked_unit_ids覆盖所有输入units，不输出改写稿。每问题对应unit_id并引用原段编号。'''
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'complete_source':source,'foundation':foundation,'episode':episode,'units':units},ensure_ascii=False)}]
    dump(run/'REQUEST.json',{'messages':messages,'schema':FinalReview.model_json_schema(),'model':cfg.model,'thinking':'disabled','max_tokens':12000,'retries':0});dump(run/'STATE_001.json',{'calls':1,'pending':1,'tokens':0})
    error=None;tokens=0;status='needs_attention';pending=1;model=None
    try:
        result=CreativeDeepSeekToolClients().call('director',messages,max_tokens=12000,temperature=0.4,thinking='disabled',structured_schema=FinalReview.model_json_schema())
        dump(run/'RESPONSE.json',{'metadata':result.metadata,'native':result.response_payload,'text':result.text});pending=None;tokens=result.metadata.get('total_tokens',0);model=result.metadata.get('response_model')
        value=FinalReview.model_validate_json(result.text).model_dump();ids={u['unit_id'] for u in units}
        if len(value['checked_unit_ids'])!=len(ids) or set(value['checked_unit_ids'])!=ids:raise ValueError('unit_coverage')
        if any(i['unit_id'] not in ids for i in value['issues']):raise ValueError('unknown_unit')
        verify_refs(value,source);dump(run/'REVIEW.json',value);status='needs_revision' if any(i['severity']=='must_fix' for i in value['issues']) else 'machine_pass_pending_primary'
    except RoleResponseError as exc:
        dump(run/'RESPONSE_REJECTED.json',{'metadata':exc.response_metadata,'native':exc.response_payload,'text':exc.response_text});pending=None;tokens=exc.response_metadata.get('total_tokens',0);error=type(exc).__name__
    except Exception as exc:
        error=type(exc).__name__
        if getattr(exc,'provider_dispatch_started',None) is False:pending=None
    dump(run/'RESULT.json',{'status':status,'calls':1,'tokens':tokens,'pending':pending,'error':error,'response_model':model});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
