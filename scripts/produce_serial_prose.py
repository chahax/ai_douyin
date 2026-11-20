"""Authorized 69-chapter serial text trial. Native results remain review candidates."""
import argparse,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from src.content_factory.serial_story_runtime_v2 import run_lock

def decode_markdown_episode(content):
    marker='**continuity**：'
    if not isinstance(content,str) or content.count(marker)!=1:raise ValueError('unrecognized_native_prose_envelope')
    screenplay,continuity=content.split(marker)
    title=screenplay.splitlines()[0].lstrip('# ').strip()
    if not title or not screenplay.strip() or not continuity.strip():raise ValueError('empty_native_prose_field')
    return {'title':title,'screenplay':screenplay,'continuity':continuity}

def map_complete_native_prose(content,title):
    try:return decode_markdown_episode(content)
    except ValueError:
        if not isinstance(content,str) or not content.strip():raise
        return {'title':title,'screenplay':content,
            'continuity':'[程序记录：本次原生回答没有可唯一提取的连续性字段；不能据此推断人物状态，承接请回到前章原文。]'}

class SerialLedger(DirectLedger):
    def call(self,name,role,prompt,payload,schema):
        try:return super().call(name,role,prompt,payload,schema)
        except RuntimeError as exc:
            if str(exc)!='native_tool_submission_missing' or not name.startswith(('AUDIT_','EPISODE_')) or self.state['pending'] is not None:raise
            native=read(self.run/f"RESPONSE_{self.state['calls_started']:03}.json")['native']
            choice=native['choices'][0];message=choice['message'];content=message.get('content')
            if choice['finish_reason']!='stop' or message.get('tool_calls') or not isinstance(content,str) or not content.strip():raise
            # An advisory review has one free-text field. Preserve the exact
            # known native text; never reinterpret this as semantic acceptance.
            result={'review':content} if name.startswith('AUDIT_') else map_complete_native_prose(content,payload['episode']['title'])
            errors=c.schema_issues(result,schema,'native_text_adapter')
            if errors:raise c.ContractError(errors)
            freeze(self.run/(name+'_TEXT_ADAPTER.json'),{'native_sha256':digest(native),'mapping':'advisory review or exact prose; missing continuity explicitly marked as program metadata','semantic_acceptance':False})
            freeze(self.run/(name+'.json'),result)
            return result

def check_coverage(episodes,indices):
    actual=[]
    for ep in episodes:
        if type(ep['start']) is not int or type(ep['end']) is not int or not 1<=ep['end']-ep['start']+1<=3:
            raise ValueError('invalid_episode_range')
        actual.extend(range(ep['start'],ep['end']+1))
    if actual!=indices:raise ValueError('episode_coverage_gap_overlap_or_order')

def prepare(run,prior,source_path,adopt_planning=None,repair_series=None,adopt_content=None):
    old=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(source_path)
    if old['pending'] is not None or old['status'] in ('running','prepared','outcome_unknown'):raise ValueError('unsettled_prior')
    indices=[x['index'] for x in source['chapters']]
    if indices!=list(range(1,70)):raise ValueError('expected_complete_69_chapters')
    run.mkdir(exist_ok=False)
    previous=plan['max_calls']
    ceiling=plan['max_calls'] if plan.get('version')=='serial_prose_trial_v1' else old['calls_started']+110
    plan.update(version='serial_prose_trial_v1',max_calls=ceiling,
        baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],source_sha256=digest(source),chapter_indices=indices,
        user_statement='是，当前小说69章做连载剧本。仅MiniMax文本分析、规划、编剧与审查；无视频发布。')
    paths=['scripts/produce_serial_prose.py','src/content_factory/novel_adaptation/protocol_direct.py']
    plan['implementation_pin']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    for name,value in [('PLAN',plan),('SOURCE',source),('AUTHORIZATION',{'statement':plan['user_statement'],'previous_ceiling':previous,
       'new_ceiling':plan['max_calls'],'prior_state_sha256':digest(old),'prior':str(prior),'max_semantic_repairs_per_episode':2,
       'stops':['unknown receipt','protocol error','source coverage failure','engineering ceiling'],'no_automatic_semantic_acceptance':True})]:freeze(run/(name+'.json'),value)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'episodes_written':0}
    DirectLedger(run,plan,state,None).save()
    if repair_series:
        freeze(run/'REPAIR_SERIES.json',{'prior':str(repair_series.resolve()),
            'source_sha256':digest(read(repair_series/'SOURCE.json')),
            'notes':{'1':'主助手确认：开头问二哥的是老六，提供自己发传单十元的是叶南，拒收的是老六。没发生交钱。叶南先前挨打因提议辍学，不是给钱。晚饭不能写清晨中午。米袋受罚是条件不是必然，孩子私下想法不可放进苏墨心声。当前眼睛未受原书未来的伤。',
                     '2':'主助手据第3—4章确认：啊谁他么偷袭老子是被苏墨打中的人贩子，不是苏墨；苏墨不能听见胖保安心里话。不得新增读心能力。'}})
    if adopt_content:
        prior_state=read(adopt_content/'STATE.json')
        if prior_state['pending'] is not None or prior_state['status'] in ('running','prepared','outcome_unknown'):raise ValueError('content_unsettled')
        if digest(read(adopt_content/'SOURCE.json'))!=digest(source):raise ValueError('content_source_changed')
        bible_path=adopt_content/'SERIES_FRAMEWORK_DIRECT_DECODED.json'
        if not bible_path.exists():bible_path=adopt_content/'ADOPTED_SERIES_FRAMEWORK.json'
        bible=read(bible_path)
        freeze(run/'ADOPTED_SERIES_FRAMEWORK.json',bible)
        n=prior_state['calls_started'];request=read(adopt_content/f'CALL_{n:03}.json');receipt=read(adopt_content/f'RESPONSE_{n:03}.json')['native']
        if not request['stage'].startswith('EPISODE_') or receipt['choices'][0]['finish_reason']!='stop':raise ValueError('adoption_stage_or_completion')
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if audit_folder(adopt_content/f'native_{n:03}')['completion_evidence']!='known':raise ValueError('adoption_unknown_stream')
        episode_num=int(request['stage'].split('_')[-1]);saved_plan=read(adopt_content/'EPISODE_PLAN.json')
        draft=map_complete_native_prose(receipt['choices'][0]['message']['content'],saved_plan[episode_num-1]['title'])
        freeze(run/f'ADOPTED_EPISODE_{episode_num:02}.json',draft)
        adopted_rows=[]
        for i in range(1,episode_num):
            for kind in ('EPISODE','AUDIT'):
                path=adopt_content/f'{kind}_{i:02}.json'
                if not path.exists():path=adopt_content/f'ADOPTED_{kind}_{i:02}.json'
                value=read(path);freeze(run/f'ADOPTED_{kind}_{i:02}.json',value)
                adopted_rows.append({'path':str(path.resolve()),'sha256':digest(value)})
        freeze(run/'CONTENT_ADOPTION.json',{'prior':str(adopt_content),'receipt_sha256':digest(receipt),
            'framework_sha256':digest(bible),'draft_sha256':digest(draft),'mapping':'exact split on unique **continuity**：; first heading used as title; no prose changes',
            'semantic_acceptance':False,'previous_outputs':adopted_rows})
    if adopt_planning:
        predecessor=read(adopt_planning/'STATE.json')
        if predecessor['pending'] is not None or predecessor['status'] in ('prepared','running','outcome_unknown'):
            raise ValueError('adoption_unsettled')
        if digest(read(adopt_planning/'SOURCE.json'))!=digest(source):raise ValueError('adoption_source_changed')
        rows=[]
        for n in range(1,13):
            path=adopt_planning/f'PLAN_BATCH_{n:02}_DIRECT_DECODED.json';value=read(path)
            indices=list(range((n-1)*6+1,min(n*6,69)+1));check_coverage(value['episodes'],indices)
            freeze(run/f'ADOPTED_PLAN_{n:02}.json',value)
            rows.append({'path':str(path.resolve()),'sha256':digest(value)})
        freeze(run/'ADOPTED_PLANNING.json',{'source_run':str(adopt_planning),'rows':rows,'no_regeneration':True})

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json');source=read(run/'SOURCE.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh_prepared')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('implementation_changed')
        ledger=SerialLedger(run,plan,state,NativeClient(run,plan));groups=[];episodes=[];previous='尚未开始。'
        try:
            indexed=c.indexed_chapters(source)
            for offset in range(0,len(indexed),6):
                batch=indexed[offset:offset+6];indices=[x['index'] for x in batch]
                schema=c.obj(overview=c.TEXT,identities=c.TEXT,episodes=c.array(c.obj(
                    start={'type':'integer','enum':indices},end={'type':'integer','enum':indices},title=c.TEXT,focus=c.TEXT),1))
                adopted=run/f'ADOPTED_PLAN_{offset//6+1:02}.json'
                out=read(adopted) if adopted.exists() else ledger.call(f'PLAN_BATCH_{offset//6+1:02}','writer',
                    '阅读这些完整章节，为连载剧本规划自然剧情单元。每集覆盖连续1至3章，所有目标章按序且仅覆盖一次；批次只是读取单位，不是集数。'
                    'overview用约500字记录本批主线、世界背景、时间变化和未决冲突；identities用约500字记录出现人物姓名/别称/关系和首次章号，未命名人物不猜姓名。'
                    '每集focus约100字，说明起因、发展、转折、收束或悬念。区分当下、过去、原书未来、计划与猜测；不要将后文解释提前变成本章角色已知。',
                    {'chapters':batch,'prior_batch_overview':previous},schema)
                check_coverage(out['episodes'],indices);groups.append(out);episodes.extend(out['episodes']);previous=out['overview']
                print(f'Planned chapters {indices[0]}-{indices[-1]}',flush=True)
            check_coverage(episodes,list(range(1,70)));freeze(run/'EPISODE_PLAN.json',episodes)
            repair=read(run/'REPAIR_SERIES.json') if (run/'REPAIR_SERIES.json').exists() else None
            if repair and repair['source_sha256']!=digest(source):raise ValueError('repair_source_mismatch')
            bible=read(run/'ADOPTED_SERIES_FRAMEWORK.json') if (run/'ADOPTED_SERIES_FRAMEWORK.json').exists() else ledger.call('SERIES_FRAMEWORK','writer',
                '依据全69章分批读原文后的资料，写连载创作总纲。概述世界/时代/人物关系/长期冲突/阶段故事。原文事实与画风美术建议分区；未明确的年月城市或角色动机保持未定。'
                '不要杜撰未获取章节的结局；这69章不代表原小说完结。解释如何按信息推进、自然动作、温馨/紧张环境写戏，避免跳变镜头和无信息停顿。总纲约1800字。'
                '作品是《你敢惹我？我有六个反派儿子》，《六个反派儿子杀爹》是正文中的书名，不要混为作品标题或称同人。资料是未核实摘要，不能推导六孩同父异母、春天开局等。未有证据的亲缘、季节不写定论。第1章明确老三叶北、老四叶寻、老六男孩；原书未来职业不等于当下经历。',
                {'batch_readings':[{'overview':g['overview'],'identities':g['identities']} for g in groups]},c.obj(framework=c.TEXT))
            (run/'00_连载总纲与目录.md').write_text('# 连载生产试稿：待内容验收\n\n'+bible['framework']+'\n\n## 分集目录\n\n'+
               '\n'.join(f"{i:02}. {e['title']}（原第{e['start']}—{e['end']}章）：{e['focus']}" for i,e in enumerate(episodes,1)),encoding='utf-8')
            previous='本集为连载开场，无前集。';manuscripts=[];audits=[]
            for i,ep in enumerate(episodes,1):
                current=[x for x in indexed if ep['start']<=x['index']<=ep['end']]
                context=[x for x in indexed if x['index']==ep['start']-1]
                relevant=[g['identities'] for g in groups if any(e['start']<=ep['end'] and e['end']>=ep['start'] for e in g['episodes'])]
                adopted_draft=run/f'ADOPTED_EPISODE_{i:02}.json'
                draft=read(adopted_draft) if adopted_draft.exists() else ledger.call(f'EPISODE_{i:02}','writer',
                    '直接依据目标完整原文写可拍摄、可阅读的连载剧本，不先输出事件JSON。完整覆盖本集主要事件，不把三章压成几句梗概。'
                    '每场写时间层、地点、实际在场人物、自然动作神情、对白和必要内心。开头自然交代环境与关系，让信息通过动作和对话前进。'
                    '保留原文因果、条件、否定、比喻和猜测。人物觉得/应该/好像只能用该人物内心或明确主观表达，不能用确定画面证明猜测。'
                    '身份索引只辅助姓名，后章的身份解释与动机不得提前演出；正文优先。未获姓名用明确关系称呼，不造姓名。'
                    '当前场名单包含所有真实出镜者，电话声音另标不在场；回忆另标时间或只用内心，不把过去人物塞进当前场。'
                    '不能新增无据孩子受虐、钱物交接或案件结论；兼容原文的普通就座、走路可补足。进出、转场和重要道具交接清楚，不堆器具操作。'
                    '内心用角色第一人称自然短句，叙述不要硬改为角色自夸对白；禁止项和审核指令不进入剧本。'
                    '提交前逐句核对关键对白说话者，依据称呼和动作判断，不能按邻近名字机械分配。角色不能听见他人心声。时间以原文晚饭/昨晚等信息为准，未明确时只写当日，不猜清晨中午。'
                    '前集连续性也是未核实模型摘要，遇到与原文矛盾必须以原文为准；continuity仅保留本集明确实际发生的关键进展，推测及原书未来单独标注，不把拒收写成交付。'
                    '不固定秒数，不编镜头参数；每集约2000至4500中文字，依内容自然伸缩。continuity约350字记录本集末时间地点、角色所知、尚未解决冲突，标出未知；不得预测后集。',
                    {'episode':ep,'target_chapters':current,'previous_chapter_context':context,'previous_episode_continuity':previous,
                     'identity_index_unverified':relevant,'validated_prior_draft_issues':repair['notes'].get(str(i),'') if repair else ''},c.obj(title=c.TEXT,screenplay=c.TEXT,continuity=c.TEXT))
                previous=draft['continuity'];manuscripts.append(draft)
                path=run/f'{i:02}_第{ep["start"]}-{ep["end"]}章_剧本候选.md'
                path.write_text(f'# 第{i}集 {draft["title"]}\n\n> 模型原生生产稿，尚未主助手逐集验收。\n\n'+draft['screenplay']+'\n\n## 连续性记录（模型生成，待核对）\n\n'+previous,encoding='utf-8')
                state['episodes_written']=i;ledger.save();print(f'Wrote episode {i}/{len(episodes)}',flush=True)
                adopted_audit=run/f'ADOPTED_AUDIT_{i:02}.json'
                audit=read(adopted_audit) if adopted_audit.exists() else ledger.call(f'AUDIT_{i:02}','writer',
                    '独立核对当前完整剧本与原文。逐项检查姓名身份、实际出场、条件否定猜测是否被画面强化成事实、前后时间、对白信息来源、事件遗漏及无据新增。'
                    '不要把一般合理走路就座视为硬伤；对白改编措辞不同不等于事实错误。只报有原文依据的问题，逐条引用候选原句和源章号；不确定明确标记，不编替换稿。'
                    'review用自然中文给出问题及覆盖检查，不声明无人验收。',
                    {'episode':ep,'original_chapters':current,'context':context,'candidate':draft},c.obj(review=c.TEXT))
                audits.append(audit)
            (run/'全69章_连载剧本候选合集.md').write_text('# 全69章连载剧本候选合集\n\n> 全文已生成；模型审核不等于主助手内容验收，不用于自动视频发布。\n\n'+
                '\n\n---\n\n'.join(f'# 第{i}集 {d["title"]}\n\n{d["screenplay"]}' for i,d in enumerate(manuscripts,1)),encoding='utf-8')
            (run/'逐集模型审核意见_待核实.md').write_text('\n\n'.join(f'# 第{i}集\n\n{a["review"]}' for i,a in enumerate(audits,1)),encoding='utf-8')
            freeze(run/'RESULT.json',{'status':'all_chapters_drafted_awaiting_primary_review','chapters':69,'episodes':len(episodes),
                 'source_sha256':digest(source),'semantic_acceptance':False,'media_ready':False,'automatic_repairs':0})
            state['status']='all_chapters_drafted_awaiting_primary_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
            print('Stopped: '+str(exc),flush=True)
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--prior',type=Path);p.add_argument('--source',type=Path);p.add_argument('--adopt-planning',type=Path);p.add_argument('--repair-series',type=Path);p.add_argument('--adopt-content',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.source,a.adopt_planning,a.repair_series,a.adopt_content)
    else:execute(a.run)
