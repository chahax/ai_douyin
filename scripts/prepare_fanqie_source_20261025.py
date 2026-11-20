"""Freeze this newly acquired book, preserving prior campaigns and failures."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.operations_accounts.fanqie_account_control import write_json

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'data/novel_platform_trials/20261025_six_children'


def binding(path):
    raw=path.read_bytes()
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def main():
    if RUN.exists():
        raise RuntimeError('原来源目录已存在，只能读取原记录，不能覆盖重领')
    source=ROOT/'data/fanqie_account_control/commands/91aa14597bac4e3193799bc2fd1aed27/BOOK_INSPECTION.json'
    v=json.loads(source.read_text(encoding='utf-8'))
    assert binding(source)['sha256']=='4ebbb22c50acc64031f4500164184c5338b548a5952fad7599dde4a5f6d8886f'
    assert v['status']=='inspected' and v['aigc_available'] and v['book_id']==v['chapter']['book_id']
    assert v['detail']['title']==v['book_name'] and len(v['chapter']['text'])>1000
    RUN.mkdir(parents=True)
    chapter=RUN/'source/chapter_001.txt';chapter.parent.mkdir()
    chapter.write_text(v['chapter_selection']['title']+'\n\n'+v['chapter']['text']+'\n',encoding='utf-8')
    receipt={'schema':'novel_source_acquisition/v1','status':'source_saved',
      'source':{'book_name':v['book_name'],'book_id':v['book_id'],'author':v['detail']['author'],
        'chapters':[dict(binding(chapter),title=v['chapter_selection']['title'],item_id=v['chapter']['item_id'],url=v['chapter']['url'])],
        'metadata_path':str(source),'metadata_sha256':binding(source)['sha256']},
      'platform_evidence':binding(source),'platform_command_id':'91aa14597bac4e3193799bc2fd1aed27',
      'resource_id':'fanqie:52ce7e06afc9451b8a81bfd9269ad94e',
      'eligibility':{'aigc_option_available':True,'promotion_task_active':False,'promotion_submitted':False},
      'scope_note':'实际取得第1章，非整本；本次仅为文本改编，未申请推广词或发布'}
    write_json(RUN/'ACQUISITION_RECEIPT.json',receipt)
    source_run=RUN/'writer'
    campaign=RUN/'campaign'
    # v10's frozen campaign envelope has ten slots. This new source is restricted
    # to one director round; this command runs writer/review only (no director).
    campaign_file=write_json(campaign/'AUTHORIZATION.json',{
      'max_rounds':10,'review_interval_rounds':5,'max_calls_per_round':3,
      'media_authorized':False,'automatic_transport_retry':False,
      'user_statement':'获取可以可以推书的小说内容然后生成剧本',
      'authorized_source_runs':[str(source_run)],'executable_scope':'本次仅此新书编剧及全文审核，最多一轮自然导演容量但不执行；不是追加旧十轮测试',
      'other_source_dispatch_authorized':False})
    write_json(RUN/'AUTHORIZATION.json',{'parent_run':str(source_run),
      'campaign_authorization':campaign_file,'campaign_dir':str(campaign),
      'max_rounds':1,'review_interval_rounds':5,'max_calls_per_round':3,
      'old_total_limits':{'calls':6,'reported_tokens':250000},
      'new_media_authorized':False,'automatic_transport_retry':False,
      'user_statement':'获取可以可以推书的小说内容然后生成剧本',
      'execution_scope':'本次限此真实新书的完整编剧与DeepSeek同源审核，已知内容问题沿原机制有界修订；不执行导演、媒体或推广提交',
      'prior_runs':'旧渡口、婚礼现场与十轮campaign均保留；不转移或重置其消耗'})
    write_json(RUN/'BRIEF.json',{
      'target_duration_seconds':90,
      'format':'约90秒竖屏剧情短片的完整自然剧本，先交付剧本；不是逐句摘要或画外音读小说',
      'adaptation_scope':'仅第1章开头：苏墨醒来、叶南护着叶西决递面包、苏墨想制止偷窃却表达含糊、孩子误解并离开，苏墨意识到一句话改变不了旧日恐惧。后半兄妹上药、辍学与双胞胎归来不挪进这次主线，也不编造后续已经和解。',
      'cast':'画面核心只用苏墨、老二叶南、老六叶西决。苏墨是六名孩子的继父，不能误写亲生父子。叶西决六七岁，叶南的具体年龄原文未明，写少年并标注外观补足。',
      'world_and_continuity':'先交代穿书世界、原主恶劣继父身份、新苏墨的改变意图及孩子不信任的原因。过去伤害与未来报复仅压缩为理解所需背景，不具象演出虐打或酷刑。原文床与脏旧床单保留，贫困破旧住宅不能改为温馨豪宅。时间和窗户灯光、门床相对位置可合理补足但须明确区分。',
      'performance':'每个时段明确地点、人物初态与前后衔接、说话对象、双方视线神情和可见动作；拿面包、护弟与说话并行。孩子的恐惧通过退让、护挡、捏面包等行为可读，不用长时间静站或重复反应。',
      'dialogue':'改写为自然短对白而非长段照搬原文；保留关键误解的因果。普通话，无无关旁白，必要短主观内心声用于交代穿书前提。信息完成就收段，不硬塞空尾。',
      'camera':'镜头切换由新信息触发，建立门、床、三人位置后沿同轴使用中近景和反应特写，人物位置道具状态连贯。',
      'promotion_boundary':'只核实该书有AIGC申请选项，本账号没有生效任务；剧本结尾不虚构已申请的推广关键词、收益或推广路径。',
      'source_provenance':receipt})
    print(json.dumps({'run':str(RUN),'source':receipt['source'],'model_calls_started':0},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
