"""One known-terminal cumulative plan repair; no automatic scene dispatch."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import design_repair as dr,contracts as c


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--attempt',type=Path)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json')
    design=read(a.prior/'DESIGN_COMPILED.json');review=read(a.prior/'PRIMARY_REVIEW.json')
    if review['source_sha256']!=digest(source) or review['design_sha256']!=digest(design):raise ValueError('review_stale')
    feedback=None
    if a.attempt:
        attempted=read(a.attempt/'STATE.json')
        if attempted['pending'] is not None or attempted['status'] in ('running','prepared'):raise ValueError('attempt_not_terminal')
        if digest(read(a.attempt/'BEFORE.json'))!=digest(design):raise ValueError('attempt_design_changed')
        feedback={'previous_proposal':read(a.attempt/'DESIGN_PATCH.json'),
                  'mechanical_error':read(a.attempt/'ERROR.json'),
                  'primary_review':read(a.attempt/'PRIMARY_REVIEW.json')}
        old=attempted
    plan=read(a.prior/'PLAN.json');plan['max_calls']=old['calls_started']+1
    a.run.mkdir(parents=True,exist_ok=False)
    for name,obj in [('SOURCE',source),('PACKET',packet),('BEFORE',design),('FINDINGS',review),('PLAN',plan)]:freeze(a.run/(name+'.json'),obj)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'prior_state_sha256':digest(old),'calls_carried':old['calls_started'],
        'ledger_prior':str(a.attempt or a.prior),
        'tokens_carried':old['reported_tokens'],'engineering_extension':1,'authorization':'既有MiniMax同书文本及持续重构授权；无媒体发布；保留旧未知'})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        proposal=ledger.call('DESIGN_PATCH','writer','''修复指定设计问题，保持完整第二章后续剧情范围CH2-P013至CH2-P145。只返回schema字段。
scenes替换场次规划：一个场次只对应一个空间；厨房内、门外对话、厨房做饭、饭桌可分四场或更多。厨房孩子出门后再在门外说话。结尾直接承接第三章同顿饭的争论；叶嫣儿只有兄弟，其原话是不想分开。
new_places/new_props只补确有调度需要的新实例；既有地点/物品描述、人物和开场位置由程序保留，禁止重定义旧ID。new_props含owner，填写新增物品第一帧实际归属。
planned_props登记开场尚未生成的成品；recipes给出id/action/inputs/outputs/retained_inputs/source_ids，原段编号只能来自给定正文。加工消耗inputs，retained_inputs可保留盛菜母体以便分装；outputs必须是planned新成品。登记所有实际用到的关键食材及每个需单独递交的成品实例，不以一组碗同时归六人掩盖分配。配方action是正向可表演过程，原文未细写烹饪步骤可做普通影视补足，不新增剧情事实。
container_actions=true允许取出袋中食材再加工。planned仅是预留位置，制作前不可见。既有袋内土豆关系保留，实际取出由后续unpack动作完成。
保持人物关系、对白动机、往事与当前时间隔离；不要把条件句改成已发生，也不要添加姐姐或次日转场。场次时长按信息合理估算，不延长静默。
若有previous_attempt，纠正其列明的问题；所有planned_props和配方inputs/outputs必须在旧props或new_props登记。新走廊场的place必须引用走廊编号。不要拆出重复切肉下锅的第二个做饭场。门外两句话不用两分钟，结尾两句冲突不用150秒。''',
            {'complete_chapters':c.indexed_chapters(source),
             'design':{k:v for k,v in design.items() if k not in ('source_constraints','world_framework')},
             'reviewed_facts':packet['facts'],'entities':packet['entities'],
             'findings':review['issues'],'previous_attempt':feedback},dr.schema(design,packet))
        result=dr.apply(design,proposal,packet,source,digest(design));freeze(a.run/'DESIGN_COMPILED.json',result)
        state['status']='design_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
