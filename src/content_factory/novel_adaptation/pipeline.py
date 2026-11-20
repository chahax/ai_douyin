"""Independent card pipeline with bounded, record-scoped repair.

Not a replacement for the deployed serial workflow. Raw supplier responses and
the source remain immutable. A card passing structural checks remains unreviewed.
"""
from dataclasses import asdict
from pathlib import Path
from ..corpus_screenplay_v1 import read, freeze, digest
from ..serial_story_transport_v6 import Ledger, NativeClient
from . import contracts as c
from .patching import bind_patches


POLICY='''你是小说改编资料整理员。原文是事实依据，输出服务于后续场景，不重述整章。
本次只完成指定的一个资料类型。保留人物说话/内心/叙述的区别，过去/当下/原书未来/计划的区别。
只选真实source_id；程序自动附原段，不需要抄写长引文。原段编号匹配不代表结论正确，请按上下文判断。
不确定信息保留为unknown，不用想象补全事实。影视美术设计由独立阶段完成。
'''

TASKS={
 'identity':'''仅登记原文实际出现或被提及的人物、地点、关键道具，不输出事迹传记。
id是稳定的内部编号；display_name是简短显示名称，可以整理，不要求在原文连续出现。
source_ids选择能够确认该实体身份的必要原段即可，不穷举其每一次出现；程序自动附上完整原段，不抄写称呼表。
哥哥、爸爸等依上下文归属，不把称呼机械当成独立人物。原主与穿书者共用身体的表演角色可用同一ID，身份差异留待事实卡按时间描述。
不要把形容词、叙述者或原书书名登记成人物；地点名称不夹带未经证实的居住分配。''',
 'character':'''只提取人物身份、关系、年龄与角色知情等必要材料。每条一个清楚事实，不混多个事件，不写环境或剧情梗概。
使用提供的实体ID。临时称呼的归属按上下文；内心信息不转成已说出口。每条标出时间层与明确/推断/未知。''',
 'environment':'''只提取世界生活背景、地点空间、环境及关键道具的原文事实。每条一个清楚事实，不复述人物剧情。
地点包含、同处场所、居住关系分别判断。原文外观比喻保留其限定，条件句保留条件。
原文没有的家具颜色、灯光和布局不填到事实里；这些后面会作为影视设计单独做。''',
 'event':'''只整理改编必需的事件卡：谁做什么、对谁/什么、发生或计划、先后与因果。每条一个事件，不重复人物传记/环境列表。
每条注明时间层。叙述、内心和说出口的动作要分清。完整原章作上下文，source_ids只指向真正支持当前事件的原段。
编号可按原文出现次序，但叙述插叙不代表实际发生次序，请在必要处明确先后。'''}


def extract_cards(run, source, plan, client=None):
    run=Path(run)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0}
    ledger=Ledger(run,plan,state,client if client is not None else NativeClient(run,plan));ledger.save()
    artifacts={};error=None
    sources={'complete_chapters':c.indexed_chapters(source)}
    try:
        for kind in ('identity','character','environment','event'):
            schema=c.entity_schema(source) if kind=='identity' else c.fact_schema(source,artifacts['identity'],kind)
            validate=(lambda x:c.validate_entities(x,source)) if kind=='identity' else (
                lambda x,k=kind:c.validate_facts(x,source,artifacts['identity'],k))
            payload={**sources,'task_kind':kind}
            if kind!='identity':payload['entities']=artifacts['identity']
            raw=ledger.call(kind.upper(),'writer',POLICY+TASKS[kind],payload,schema)
            try:validate(raw)
            except c.ContractError as exc:
                freeze(run/(kind+'_ISSUES.json'),[asdict(e) for e in exc.issues])
                root='entities' if kind=='identity' else 'facts'
                rows=raw.get(root,[]) if isinstance(raw,dict) else []
                allowed=set()
                for issue in exc.issues:
                    parts=issue.path.strip('/').split('/')
                    if len(parts)<2 or parts[0]!=root or not parts[1].isdigit():raise
                    idx=int(parts[1])
                    if idx>=len(rows) or not isinstance(rows[idx].get('id'),str):raise
                    allowed.add(rows[idx]['id'])
                patch_schema=c.obj(patches=c.array(c.obj(id=c.choices(sorted(allowed)),
                    replacement=schema['properties'][root]['items']),1))
                repair=ledger.call(kind.upper()+'_PATCH','writer',POLICY+
                    '只返修allowed_records中的记录。未选记录不返回，不重写整份材料。保持id；只返回id和replacement，校验值由程序绑定。',
                    {**payload,'issues':[asdict(e) for e in exc.issues],
                     'allowed_records':[{'record':row} for row in rows if row['id'] in allowed]},patch_schema)
                problems=c.schema_issues(repair,patch_schema,kind)
                if problems:raise c.ContractError(problems)
                bound=bind_patches(raw,repair['patches'],allowed,digest(raw))
                raw=c.apply_record_patches(raw,bound,allowed,digest(raw),validate)
                freeze(run/(kind+'_PATCHED.json'),raw)
            artifacts[kind]=raw
            freeze(run/(kind+'_BOUND.json'),{'candidate':raw,'candidate_sha256':digest(raw),
                'semantic_status':'unreviewed'} if kind=='identity' else c.bind_evidence(raw,source))
            print(kind+' structurally bound',flush=True)
        state['status']='cards_ready_awaiting_semantic_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        error={'type':type(exc).__name__,'message':str(exc)[:2000]}
        if isinstance(exc,c.ContractError):error['issues']=[asdict(e) for e in exc.issues]
    finally:
        ledger.save();freeze(run/'RESULT.json',{'state':state,'error':error,
            'completed_cards':list(artifacts),'semantic_accepted':False,'media_ready':False})
    return artifacts
