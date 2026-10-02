"""Apply exact, model-authored editorial replacements with retained provenance; no media."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.author_narrative_readable import verify_editorial
from scripts.run_narrative_workflow import new_output, now, save
from src.trend_intelligence.narrative_workflow import identity, read, digest, fields


def apply_replacements(body, patches):
    fields(patches, {'replacements'}, 'editorial edits')
    if not isinstance(patches['replacements'],list) or not patches['replacements']:raise ValueError('Empty edits')
    for row in patches['replacements']:
        fields(row,{'before','after','reason'},'replacement')
        if any(not isinstance(v,str) or not v.strip() for v in row.values()):raise ValueError('Empty replacement text')
        if body.count(row['before'])!=1:raise ValueError('Replacement must match exactly once')
        body=body.replace(row['before'],row['after'],1)
    return body


def main():
    p=argparse.ArgumentParser()
    for name in ('parent-run','feedback-file','output-dir'):p.add_argument('--'+name,required=True)
    args=p.parse_args();parent,body=verify_editorial(args.parent_run)
    out=new_output(args.output_dir)
    prompt='你是项目剧本编辑。只对原稿执行反馈要求的局部修正，不重写其他段落。返回严格JSON：{"replacements":[{"before":"原文唯一逐字匹配的子串","after":"修复后的文本","reason":"修复理由"}]}。使用JSON正确转义换行和引号；before选择足以唯一定位的完整句子或段落。每条修复后的after由你创作，但不要新增支线。不能宣称已审核通过。'
    feedback=Path(args.feedback_file).read_text(encoding='utf-8-sig')
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'screenplay':body,'feedback':feedback},ensure_ascii=False)}]
    save(out/'request.json',messages);(out/'prompt.md').write_text(prompt,encoding='utf-8')
    run={'schema':'narrative_editorial_revision/v1','status':'running','model_calls':1,'media_calls':0,
        'started_at_bjt':now(),'kind':parent['kind'],'workflow':parent['workflow'],
        'parent_editorial':identity(Path(args.parent_run)/'run.json'),'feedback':identity(args.feedback_file),
        'model':'MiniMax-M3','thinking':'disabled','execution_status':'not_compiled_no_video_handoff','artifacts':{}}
    save(out/'run.json',run)
    reservation=Path(parent['workflow']['path']).parent/'author_reservations'/(digest(out/'request.json')+'.json')
    with reservation.open('x',encoding='utf-8') as stream:json.dump({'run_dir':str(out),'reserved_at_bjt':now()},stream)
    from src.shared.llm_client import LLMClient
    client=LLMClient(model='MiniMax-M3',max_tokens=8000,max_retries=0,timeout_seconds=300,
        extra_body={'thinking':{'type':'disabled'},'reasoning_split':True},preserve_invalid_json=True)
    try:
        if client.provider_name=='mock':raise ValueError('Real model required')
        try:raw=client.chat_completion_tracked(messages,caller='narrative_editorial_patch',temperature=.2,json_mode=True,use_cache=False)
        finally:save(out/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (out/'model_output.json').write_text(raw or 'null',encoding='utf-8')
        if read(out/'response.json').get('finish_reason')=='length':raise ValueError('Truncated edits')
        result=apply_replacements(body,read(out/'model_output.json'))
        (out/'screenplay.md').write_text(result,encoding='utf-8')
        for name in ('request.json','prompt.md','response.json','model_output.json','screenplay.md'):run['artifacts'][name]=identity(out/name)
        run['status']='editorial_candidate_pending_actual_review'
    except Exception as exc:run.update(status='failed',error=str(exc));raise
    finally:run['finished_at_bjt']=now();save(out/'run.json',run)
    print(out)


if __name__=='__main__':main()
