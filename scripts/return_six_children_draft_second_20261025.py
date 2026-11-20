"""Last permitted full-draft revision within the original six-call limit."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import natural_director_pipeline_v10 as p
from src.content_factory.editorial_writer_return_v1 import request_revision
root=Path(__file__).resolve().parents[1]/'data/novel_platform_trials/20261025_six_children';run=root/'writer'
b,s=p.parent._verify(run)
d={'reviewer':'assistant_editorial_review','decision':'revise','draft':s['active']['writer_full']['file'],
 'source_binding':b['source']['binding_id'],'issues':[
 {'quote':'**预计成片时长约90秒。**','reason':'上一轮要求真实90秒但仍有大量反复对白和逐个反应，几乎没有实质压缩。不要在长稿顶部贴90秒标签。请彻底重新构思，不在旧稿上换同义词。主要矛盾只有分肉引发卖人恐惧、哥哥提交换、苏墨拒绝、门内商量避开，四次信息变化足够。'},
 {'quote':'七人全部离开餐桌，只剩苏墨坐在原位','reason':'人数自相矛盾。应为六个孩子离桌，苏墨一人留在原座；所有动作状态应核对同一个七人空间。'},
 {'quote':'母亲离开后留下的旧房','reason':'第2章母亲留下的房产已被原主抵押失去，当前是另行住进的城中村住所。不能把两处房产混为一处。'},
 {'quote':'第三天巷子中的危机','reason':'是次日，不是第三天。第3章编号不是故事时间。'},
 {'quote':'手里捏着一小块没吃完的面包','reason':'这段此前没有交代面包来自何处，第一章面包被苏墨拿走。既无本场信息作用就删去这一道具，别为情绪额外补物件。'},
 {'quote':'我留在家里，不拖累你们','reason':'原文小六最害怕的正是与苏墨单独留家，不是主动舍己。用害怕次日独处的一个短问句承接叶南安排，不反转动机。'},
 {'quote':'我是不想你拿自己的命去换！','reason':'新增牺牲生命话题和兄弟争吵占时间、升级无据。叶南直接扶稳椅背或拉住哥哥，形成对继父的同一防线即可。'},
 ],
 'revision_request':'这是最后一份完整稿候选，请从头写。保留必要世界框架/角色/主线/规划，但不要把分析段重复演进拍摄正文。可拍正文用两个场景、约90秒四个时间块（各段时长按内容合理分配），每块都同时推进对白和动作。真正说出口的对白与内心声合计大约200至250个汉字、约12至15个发言轮次即可完成四次信息变化，这是排时参考而非审核替代。先在脑中以自然中文语速读一遍再给时间；不要新增解释前史的对白。人物不需轮流发表态度，双胞胎用同桌反应而非对白即可。叶嫣儿一次问是否要卖、一次说不要分开；苏墨一次否认但语气仍硬；叶东一次提出辍学交换；苏墨简短拒绝并命令回房；内心声一句交代穿书和保护意图；房间内小六一次担心明日独处，叶南一次安排先走后跟体育馆，弟弟点头。以上只是事件职责，不要照抄成工具指令。删去所有再次重复卖人恐惧、重复催促、反复站坐、挨个看人的空耗。自然语速与动作可见性优先。给出实际对白字数估算与排时依据，若真的无法90秒请如实说明，而非继续宣称已达90。保持真实来源抬头、母亲原房已失去、当前城中村贫困住所、次日时间及六孩子离桌苏墨留桌的连续性。'
}
path=root/'EDITORIAL_DIAGNOSIS_002.json';p.core._write(path,d)
r=request_revision(run,path);print(r['status'],r['stage'],r['calls_started'])
