"""Record concrete editorial failures without replacing the native pass. Once."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import natural_director_pipeline_v10 as p
from src.content_factory.editorial_writer_return_v1 import request_revision

root=Path(__file__).resolve().parents[1]/'data/novel_platform_trials/20261025_six_children'
run=root/'writer'
b,s=p.parent._verify(run)
diagnosis={
 'reviewer':'assistant_editorial_review','decision':'revise',
 'draft':s['active']['writer_full']['file'],'source_binding':b['source']['binding_id'],
 'issues':[
  {'quote':'# 《六个反派儿子杀爹》','reason':'这是原文中的书中书名称，不是实际推广书《你敢惹我？我有六个反派儿子》。片名可以原创但必须在抬头准确写真实小说/作者/书籍ID/章节来源，不能把书中书冒充来源。'},
  {'quote':'**合计约90秒。**','reason':'可拍剧本仅保守抽取48处标注对白就约593个汉字，正常语速已超过150秒，还未计做饭、逐人夹肉、反应和转场。各场标时与实际内容不符。返修为真正约90秒：从肉已分到碗里起拍，舍去醒来、厨房加工和逐人分肉过场。对白/内心声总量以约200至260字作排时参考，不作机械合格线；逐场按实际朗读和并行动作给出诚实时长。不要五场都留而催念。'},
  {'quote':'叶东和叶南守在床边','reason':'第1章该时点是叶南和叶西决，叶东此前不在床边；本次范围已明确晚饭为主线，去掉这场即可避免加人和稀释冲突。'},
  {'quote':'叶南也停下削好的土豆','reason':'此时已煮好上桌，叶南不应重新削土豆。需整稿核对道具从加工、成菜到碗里的连续状态。'},
  {'quote':'吃肉以前先说价钱','reason':'前文没有人报过价钱，这句凭空制造新因果。直接从原主曾想卖孩子和这次反常分肉的恐惧推进。'},
  {'quote':'让他继续上学','reason':'小六尚未入学，第1章写明原主拖延入学。应为让小六能上学，不能写继续上学。'},
  {'quote':'谁不让他上学了？我说的是你不能辍学！','reason':'过于明确地澄清了原文持续误会，随后仍全体认定卖孩子缺乏新依据。原作关键是苏墨只强硬拒绝/命令写作业，未说清本意。保留观众理解但孩子未理解的信息差。'},
  {'quote':'明天你就知道要卖谁了。','reason':'原文无此反威胁，语义也不清，改变孩子的动机。叶东只想用辍学换小六安全，不策划卖其他人。'},
  {'quote':'明天我们一起出门。别落单。','reason':'原第3章是哥哥姐姐先去学校，小六随后偷偷跟去，才发生独自落单；同出门会改写后续因果。结尾应由叶南压低声音嘱咐小六等大孩子走后跟上、躲体育馆。'},
  {'quote':'明天我送你们上学。','reason':'新编苏墨送学直接破坏第二天孩子独自行动的原文因果，应删去，苏墨留在收碗画外，不知孩子计划。'},
 ],
 'revision_request':'输出一份新的完整自然稿。短世界框架准确区分原文与布景补足；实际拍摄正文控制两个连续场景：餐桌肉已经分好、孩子房间偷偷商量。七人座位/出入口要固定，核心台词给苏墨叶嫣儿叶东叶南叶西决，双胞胎无须增词。开始就有新信息和互动，无做饭过程、长时间静站。只用必要一句苏墨主观声交代穿书继父前提。故事维持晚饭善意被误读→哥哥交换→强硬拒绝→暗中避开继父的因果。不要新增未来救人或和解。保留原生审核通过记录，不声称它已发现这些问题。'
}
path=root/'EDITORIAL_DIAGNOSIS_001.json'
p.core._write(path,diagnosis)
result=request_revision(run,path)
print(result['status'],result['stage'],result['calls_started'])
