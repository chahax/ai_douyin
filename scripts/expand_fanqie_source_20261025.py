"""User-approved three-chapter expansion before the first model call. Run once."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import natural_director_pipeline_v10 as pipe
from src.content_factory.unstarted_source_amendment_v1 import amend
from src.operations_accounts.browser_control import BrowserControlStore

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/novel_platform_trials/20261025_six_children'


def main():
    folder=RUN/'source_expanded'
    if folder.exists():raise RuntimeError('已准备扩展；不得重复执行')
    command=BrowserControlStore(ROOT/'data/account_browser_control.db').get('b5c2709e89354518aa37e2cd33e966f9')
    assert command['state']=='succeeded'
    source=Path(command['result']['book_evidence']['path'])
    raw=source.read_bytes()
    assert pipe.core._sha(raw)==command['result']['book_evidence']['sha256']
    v=json.loads(raw);assert len(v['chapters'])==3 and v['aigc_available']
    old=pipe.core._read(RUN/'writer/BINDING.json')
    assert old['source']['book_id']==v['book_id']
    folder.mkdir()
    chapters=[]
    for i,c in enumerate(v['chapters'],1):
        p=folder/f'chapter_{i:03}.txt';p.write_text(c['title']+'\n\n'+c['text']+'\n',encoding='utf-8')
        chapters.append({**pipe.core._binding(p),'title':c['title'],'item_id':c['item_id'],'url':c['url']})
    assert Path(chapters[0]['path']).read_bytes()==(RUN/'source/chapter_001.txt').read_bytes()
    receipt={'status':'source_saved','source':{'book_name':v['book_name'],'book_id':v['book_id'],
      'author':v['detail']['author'],'chapters':chapters,'metadata_path':str(source),'metadata_sha256':pipe.core._sha(raw)},
      'platform_command_id':command['command_id'],'aigc_option_available':True,'promotion_task_active':False}
    receipt_path=folder/'ACQUISITION_RECEIPT.json';pipe.core._write(receipt_path,receipt)
    authorization=folder/'USER_SCOPE_AND_EXTERNAL_SERVICES.json'
    pipe.core._write(authorization,{'run_dir':str(RUN/'writer'),
      'question':'是否允许将这本小说已获取的第1章正文及创作要求发送给MiniMax生成剧本、交给DeepSeek全文审核？本次最多6次文本调用，不生成视频或发布。',
      'user_statement':'可以获取多个章节别就1章','external_text_services':['MiniMax','DeepSeek'],
      'source_scope':'按本次回复扩展为同书前3章正文及改编要求','max_text_calls':6,
      'original_calls_started':0,'media_authorized':False,'publication_authorized':False,
      'prior_dispatch':'第一次外部调用被自动审批拦截，进程未创建，未产生模型请求；原一章准备保留快照后在同一owner和预算内扩展'})
    brief=old['brief'].copy()
    brief.update(
      adaptation_scope='以已获取第1至3章校正人物动机，约90秒以第2章晚饭误会为主线：苏墨分肉、孩子误以为要被卖、叶东提出辍学挣钱换小六安全、苏墨拒绝造成更深误会，收至第3章前半孩子决定明早带小六离开家跟去学校。穿书和恶劣继父前史用简短主观内心声交代。第三章后半巷子救人作为后续，不抢演为本片已和解。',
      cast='苏墨是继父，六名孩子包括叶东、叶南、双胞胎叶北叶寻、女孩叶嫣儿和六七岁叶西决。晚饭场面共七人，开场建立人数和座位；主要对白给苏墨、叶东、叶嫣儿，叶南的护拦及小六的依附要可见，双胞胎可以无台词但位置连续。名字、亲属关系保持原文。',
      world_and_continuity='第2章明确城中村破旧贫困住宅、母亲离开四年、原主长期压榨孩子。原书实有五花肉、白菜土豆、餐桌；晚饭后到孩子房间连续同一傍晚。家庭空间布局、日落光和旧家具属于合理视觉补足并标注，不改豪宅，不把子女戒备套成温暖和解。过去虐待、未来报复及第三章人贩子伤害不具象呈现。',
      camera='先建立餐桌、厨房门、孩子房门和七人座位，镜头沿轴线；切特写跟随分肉、护弟、提出交换等新信息，不让人物、碗筷突然出现，不强制运镜。',
      source_provenance=receipt)
    result=amend(RUN/'writer',receipt_path,brief,authorization)
    pipe.core._write(folder/'AMEND_RESULT.json',result)
    print(json.dumps({'status':result['status'],'calls_started':result['calls_started'],
      'chapters':[{'title':c['title'],'item_id':c['item_id']} for c in chapters]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
