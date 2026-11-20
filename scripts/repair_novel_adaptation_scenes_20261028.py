"""Preserve known outputs; spend the remaining scene bound on scoped repairs."""
import sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c,scenes as sc
from src.content_factory.novel_adaptation.patching import bind_patches
from src.content_factory.novel_adaptation.render import episode_markdown

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/corpus_production_trials/20261028_adaptation_scenes_design_repair'
RUN=ROOT/'data/corpus_production_trials/20261028_adaptation_scenes_scoped_repair'

def main():
    prior=read(OLD/'STATE.json')
    if prior['pending'] is not None or prior['calls_started']!=4:raise ValueError('prior_not_known')
    RUN.mkdir(exist_ok=False);plan=read(OLD/'PLAN.json');plan.update(max_calls=3,version='novel_adaptation/scenes-scoped-repair')
    source=read(OLD/'SOURCE.json');packet=read(OLD/'PACKET.json');entities={'entities':packet['entities']}
    facts=[r['id'] for r in packet['facts']];design=read(OLD/'DESIGN.json');spec1,spec2=design['scenes']
    first=read(OLD/(spec1['id']+'_FINAL.json'));second=read(OLD/('SCENE_'+spec2['id']+'.json'))
    native_patch=read(OLD/('PATCH_'+spec2['id']+'.json'))
    # Exact candidate comes from the saved request, not from a latest-file assumption.
    import json
    request=read(OLD/'CALL_004.json');requested=json.loads(request['messages'][1]['content'])['candidate']
    if requested!=second:raise ValueError('native_patch_candidate_mismatch')
    ids={p['id'] for p in native_patch['patches']}
    bound=bind_patches(second,[{'id':p['id'],'replacement':p['replacement']} for p in native_patch['patches']],ids,digest(second))
    second=c.apply_record_patches(second,bound,ids,digest(second),lambda _:None)
    freeze(RUN/'RECOVERY.json',{'original_request_sha256':digest(request),'native_patch_sha256':digest(native_patch),
        'candidate_sha256':digest(requested),'model_sha_not_used':'candidate equality verified; program binds IDs; replacement content unchanged',
        'semantic_acceptance':False})
    base={'design':design,'scenes':[first,second]};freeze(RUN/'BEFORE.json',base)
    freeze(RUN/'PLAN.json',plan);freeze(RUN/'SOURCE.json',source)
    freeze(RUN/'AUTHORIZATION.json',{'basis':'原授权MiniMax同书文本继续修复','original_scene_bound':8,
        'prior_used':5,'remaining':3,'book_prior_starts':172,'media':False})
    freeze(OLD/'BUDGET_TRANSFER.json',{'child':str(RUN),'original_scene_bound':8,'prior_total_used':5,'remaining':3})
    snapshot=RUN/'implementation';snapshot.mkdir()
    for path in [Path(__file__),Path(c.__file__),Path(sc.__file__),ROOT/'src/content_factory/novel_adaptation/patching.py']:
        (snapshot/path.name).write_bytes(path.read_bytes())
    state={'status':'prepared','calls_started':0,'reported_tokens':0,'pending':None};ledger=Ledger(RUN,plan,state,NativeClient(RUN,plan));ledger.save()
    allowed1={'b01','b02','b03','b04','b09','b10'};allowed2={'b01','b02','b03','b05','b06','b09'}
    item=sc.scene_schema(design,entities,facts,source)['properties']['beats']['items']
    schema=c.obj(world_framework={**c.TEXT,'maxLength':600},
        visual_design=c.array(c.obj(aspect=c.TEXT,description=c.TEXT,basis=c.choices(['adaptation_design','source_constraint']))),
        iodine_description=c.TEXT,
        scene1_patches=c.array(c.obj(id=c.choices(sorted(allowed1)),replacement=item)),
        scene2_patches=c.array(c.obj(id=c.choices(sorted(allowed2)),replacement=item)))
    try:
        result=ledger.call('TARGETED_PATCH','writer','''按完整原文核对后修复指定字段，不重写整集。只返回允许的beat，id保持。
世界框架不把辍学归因于本次面包误会；原因是长期伤害和入学受阻。原文事实与视觉设计分开；视觉呈现方法与补足一律adaptation_design。
碘酒初态由叶嫣儿持有，但当时老六还在苏墨屋，不写开场已经上药。
第一场b01/b02去掉可见零钱掏出/递出动作，只保留钱的原对白，避免重复取钱及额外道具状态。
第一场b03/b04压缩冗长背景各到4—6秒，通过内心一句话简洁表达穿成恶毒继父及书中未来结局；内心用第一人称。保留关键信息，避免长时间躺着灌输背景。
只对允许的beat改变时长，start设0/end设该beat时长，音轨也用本beat相对秒。程序随后按原顺序累加时间，未选beat只平移时间不改内容。
第一场b09苏墨内心用我，b10安排足够时间回床坐下闻味弹起；明确bread-gift从su-mo放到su-mo-bedroom，transfers与正文一致。
第二场所有beat保留原时长。b01鞋掉与仍挂脚矛盾，简化动作；b02碘酒放屋内桌面明确transfer后再沾布/掀衣，上药动作不能三只手同时操作。
b03伤情来源用叙述音轨，避免让幼儿自己说上贡；语速<=6字/秒。
b05原文小六不能再出去句未明署名，作为改编对白分配须在adaptation_detail标明，不冒称原文明确归属。
b06不把叙述事实自动视为全部孩子知情，旁白即可；b09叶寻跟着哥哥叶北，不是弟弟。菜袋一直叶北持有，随人移动不发生owner交接，所以transfers为空。动作几个土豆与很多土豆矛盾，保持袋内很多土豆。
所有audio相对本beat，连续清楚不重叠，每秒<=6字；present和moves仍准确，正文和结构状态一致。不要再抄SHA。''',
            {'complete_chapters':c.indexed_chapters(source),'candidate':base,'allowed1':sorted(allowed1),'allowed2':sorted(allowed2)},schema)
        errors=c.schema_issues(result,schema,'repair')
        if errors:raise c.ContractError(errors)
        after=deepcopy(base);after['design']['world_framework']=result['world_framework'];after['design']['visual_design']=result['visual_design']
        for prop in after['design']['props']:
            if prop['id']=='iodine-bottle':prop['description']=result['iodine_description']
        for n,allowed,key in [(0,allowed1,'scene1_patches'),(1,allowed2,'scene2_patches')]:
            original=base['scenes'][n];patches=result[key]
            if {p['id'] for p in patches}!=allowed:raise ValueError('missing_requested_patch')
            raw=c.apply_record_patches(original,bind_patches(original,patches,allowed,digest(original)),allowed,digest(original),lambda _:None)
            cursor=0
            for beat in raw['beats']:
                old_start=beat['start'];duration=beat['end']-old_start
                # Patched intervals are local; untouched native intervals translate losslessly.
                for audio in beat['audio']:
                    audio['start']=round(audio['start']-old_start+cursor,4);audio['end']=round(audio['end']-old_start+cursor,4)
                beat['start']=cursor;beat['end']=round(cursor+duration,4);cursor=beat['end']
            after['scenes'][n]=raw;after['design']['scenes'][n]['duration_seconds']=cursor
        previous=sc.initial_state(after['design'],entities)
        for scene,spec in zip(after['scenes'],after['design']['scenes']):
            previous=sc.advance(scene,spec,after['design'],entities,facts,source,previous)
        after['end_state']=previous;freeze(RUN/'EPISODE.json',after)
        (RUN/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(after,entities),encoding='utf-8')
        rs=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(path=c.TEXT,problem=c.TEXT,source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
        review=ledger.call('FINAL_REVIEW','writer','''独立审核同一完整候选与原文，检查世界事实、对白与内心、人物关系、动作可拍性、时间、持物与进出、旁白密度。每个问题具体指出现有文字、原文依据和为何错误。不要索取无据补写；不是要求复述全部原文。''',
            {'complete_chapters':c.indexed_chapters(source),'candidate':after,'candidate_sha256':digest(after)},rs)
        errs=c.schema_issues(review,rs,'review')
        if errs:raise c.ContractError(errs)
        state['status']='episode_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(RUN/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()

if __name__=='__main__':main()
