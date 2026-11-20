"""Offline proposal for the three existing chapters. Does not call generation services."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.h3_asset_admission_v2 import PERSON_VIEWS, PLACE_VIEWS, fingerprint, voice_items

COVERAGE=ROOT/'data/video_generation/h3_six_children_full_script_20261102/COVERAGE.json'
OUT=ROOT/'data/video_generation/h3_asset_proposal_v2_20261105'
SU,D,N,B,X,Y,L,T,S='苏墨 叶东 叶南 叶北 叶寻 叶嫣儿 叶西决 高个男人 矮个男人'.split()
ALIASES={'原主苏墨':SU,'老大':D,'老二':N,'老三':B,'老四':X,'老五':Y,'老六':L,'小六':L,'爸爸':SU}
KIDS=[D,N,B,X,Y,L]
FAMILY=[SU,*KIDS]
STORY='前三章 SCREENPLAYS_READING.md'
PEOPLE=[
 (SU,'成年人，确切岁数未明示',STORY,'深色夹克、素色衬衫和深色长裤，头发略乱'),
 (D,'11岁','第5章 CH5-P018—P019，核对记录 docs/SPEC_FIRST_THREE_TRIAL_20261101.md','瘦小，洗白的旧短袖'),
 (N,'老二，具体年龄未明示',STORY,'儿童身形，旧短袖挽袖，神情谨慎'),
 (B,'约七八岁，外观估计',STORY+' 第一章场景三','双胞胎，尖瘦精致脸，同款洗旧素色短袖与旧长裤'),
 (X,'约七八岁，外观估计',STORY+' 第一章场景三','双胞胎，同款洗旧素色短袖与旧长裤；用本人的参考和走位区分'),
 (Y,'老五，具体年龄未明示',STORY,'儿童身形，整齐小辫、浅碎花连衣裙、白袜和旧皮鞋'),
 (L,'六岁','原文 CH3-P046，首章“六七岁”仅为外观估计','矮小，黑亮双眼，破洞旧短袖、旧短裤、旧布鞋'),
 (T,'成年，确切岁数未明示',STORY+' 第三章巷内场','较高，深灰旧夹克'),
 (S,'成年，确切岁数未明示',STORY+' 第三章巷内场','较矮，土黄色旧夹克')]
PLACES={'adult_room':'靠墙窄木床、旧床单、木桌与门；固定从床到门的动线',
 'child_room':'独立拥挤小屋、共用床铺、木凳和碘酒；固定门与床相对位置',
 'kitchen':'灶台、铁锅、切菜砧板、墙角米袋、木柜与厨房门；固定灶台和柜子位置',
 'kitchen_door':'从门外看紧闭厨房门，明确门内外的视线和人物位置',
 'dinner_table':'晚饭摆一盆白菜炖土豆、少量薄肉；需先解决第三章厨房木桌与客厅桌指代并审核布局',
 'room_door':'孩子房门缝可看见苏墨洗碗的位置，校对视线与水盆位置',
 'breakfast_table':'次晨餐桌、白面包、盒装牛奶；先核晚餐与早餐的桌位和光线',
 'home':'客厅、通往孩子房间的门与屋门、扫帚、地面碎屑',
 'stall':'清晨街边小摊，面包和盒装牛奶；作短插入镜头',
 'street':'住宅区街巷，通向学校方向与偏僻巷口',
 'alley':'两侧旧灰墙、墙根阴影、窄巷出口，救援前后沿用布局'}
# These are proposed shot compositions, never a character-mention extractor.
RANGES=[(1,9,[SU]),(10,22,[SU,N,L]),(23,25,[SU]),(26,28,[Y,L]),(29,30,[D,N,Y,L]),(31,37,[D,N,Y,L]),
 (38,38,KIDS),(39,40,[B,X]),(41,42,[B,X,Y,L]),(43,44,[]),(45,45,KIDS),(46,46,[D,L]),
 (47,59,[D,N,SU]),(60,62,[D,N]),(63,72,[SU]),(73,77,FAMILY),(78,79,[Y,D,SU]),(80,80,[Y,SU,D]),(81,83,[SU]),
 (84,90,FAMILY),(91,91,[SU,Y,B,L]),(92,92,[L,N]),(93,93,[N,L]),(94,94,[X,D]),(95,97,FAMILY),
 (98,98,[SU,L]),(99,102,[SU]),(103,103,[L]),(104,104,[S]),(105,111,[T,S]),(112,112,[]),
 (113,113,[SU]),(114,114,[SU,L]),(115,117,[SU,L,T,S]),(118,118,[SU,T,S,L]),(119,119,[SU,L])]
SCENES=['adult_room','adult_room','child_room','child_room','kitchen','kitchen_door','kitchen','dinner_table',
        'dinner_table','room_door','breakfast_table','home','street','alley','alley']
# Only independently written visual directions are sent to generation. Other rows require staging.
DIRECTIONS={
 1: '苏墨闭眼躺在旧木板床上，脸部近景。',
 2: '苏墨闭着眼咬紧牙关，在床上听门边的童声。',
 3: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 4: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 5: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 6: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 7: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 8: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 9: '旧屋床边，保持苏墨脸部近景，神情随回忆变化。',
 10: '苏墨脸色发白，猛地睁眼，床边两个孩子被惊动，围上来。',
 11: '叶西决举起袋装白面包，近景落在开裂的小手和面包袋。',
 12: '苏墨看着被递到面前的白面包。',
 13: '孩子捧着面包等苏墨反应。',
 14: '苏墨的目光从面包移到矮小的叶西决。',
 15: '近景保持叶西决低垂的脸。',
 16: '苏墨观察孩子眼睛的外观。',
 17: '在当下的孩子与苏墨之间切反应近景。',
 18: '苏墨打量叶西决明亮的双眼。',
 19: '苏墨低头沉思，捧面包的小手抖得更明显。',
 20: '叶西决闭眼，叶南上前挡住弟弟，苏墨从床边走近。',
 21: '叶南肩背绷紧，苏墨接走面包，孩子们愣住。',
 22: '叶西决跪下，随即拉着叶南跑出门，苏墨望向门缝。',
 23: '孩子离开后苏墨留在床边，看向空门口。',
 24: '苏墨靠上旧枕头又弹起，站在床边皱眉。',
 25: '他低头看袋装面包，片刻后把面包放在旧木桌上。',
 26: '叶嫣儿扶着弟弟，用棉签点碘酒；叶西决咬牙、背部轻颤。',
 27: '保持在姐弟身边，叶嫣儿照顾弟弟，镜头落在叶西决忍痛的表情。',
 28: '保持在姐弟身边，叶嫣儿照顾弟弟，镜头落在叶西决忍痛的表情。',
 29: '叶东握拳转身，叶南上前挡住他。',
 30: '叶嫣儿抬头附和，叶东垂眼看弟弟妹妹。',
 31: '在叶东与弟妹瘦小的身影间切近景。',
 32: '叶东低下头，脸色紧绷。',
 33: '镜头停在叶东压住怒意的表情上。',
 34: '叶东默默看着弟妹。',
 35: '切到叶西决瘦小的侧影。',
 36: '叶东看向叶西决，神色沉重。',
 37: '叶东咬紧牙，提出不再念书。',
 38: '叶南掀开衣角，叶嫣儿放下弟弟的破衣摆。叶东仍坚持；门响，双胞胎走进来。',
 39: '叶北拎着塑料袋进门，叶寻找位置在旁站定。',
 40: '给塑料袋和兄弟侧影近景，画外童声响起。',
 41: '叶北举起装土豆的袋子，叶寻停在他身旁。',
 42: '叶嫣儿理好弟弟衣摆，伸手接过塑料袋。',
 43: '俯拍塑料袋中发绿发芽的土豆。',
 44: '俯拍塑料袋中发绿发芽的土豆。',
 45: '六个孩子围着袋子，叶东伸手接袋、摸弟弟的头。',
 46: '叶东看着仰头望他的叶西决。',
 47: '旧砧板上叶东切烂白菜，叶南剜土豆芽；苏墨从厨房门口走入，叶东抬眼又低头。',
 48: '叶南继续剜土豆芽，苏墨往前一步。',
 49: '苏墨开口，叶东手里的刀顿住，叶南的小刀也停下。',
 50: '在苏墨与两个孩子迟疑的脸之间切换近景。',
 51: '叶南停顿后开口，苏墨站在砧板旁，叶东守着菜刀。',
 52: '苏墨抬眉指着砧板和盆，仔细看烂菜叶和发芽的土豆。',
 53: '近景苏墨面对灶台上发黄的菜叶，神情变沉。',
 54: '叶东、叶南低头切菜剜芽，苏墨望着两人。',
 55: '叶南迟疑后开口，苏墨扯了扯嘴角。',
 56: '叶东的指节握得发白，叶南拉住他的衣角。',
 57: '镜头保留苏墨听完回答后无奈的反应。',
 58: '苏墨抬手，把叶东、叶南推出厨房。',
 59: '苏墨在厨房门口挥手，叶东、叶南被推出门外。',
 60: '叶南盯着厨房门，压低声音；叶东听着，刚要点头。',
 61: '叶南摇头改口，叶东咽了咽口水。',
 63: '苏墨拉开旧木柜，从深处找到半块泛褐的五花肉，提起端详并皱眉。',
 64: '厨房中保持苏墨面对木柜、端详半块旧肉的近景，以他的神情承接画外往事。',
 65: '厨房中保持苏墨面对木柜、端详半块旧肉的近景，以他的神情承接画外往事。',
 66: '厨房中保持苏墨面对木柜、端详半块旧肉的近景，以他的神情承接画外往事。',
 67: '厨房中保持苏墨面对木柜、端详半块旧肉的近景，以他的神情承接画外往事。',
 68: '厨房中保持苏墨面对木柜、端详半块旧肉的近景，以他的神情承接画外往事。',
 69: '苏墨把半块肉放到旧砧板上，切出薄片。',
 70: '苏墨看向砧板上刚切好的肉片。',
 71: '保持苏墨灶台旁的侧脸与木砧板，神情随心绪变化。',
 72: '苏墨把薄肉片放进锅里，盖上盖子，在灶边垂眼。',
 73: '苏墨端上一只缺口搪瓷盆。六个孩子睁大眼睛，看清汤表面仅浮着几片薄肉。',
 74: '六个孩子视线落在汤面薄肉上，眼睛睁圆。',
 75: '孩子们相互看了一眼，筷子停着；苏墨握筷开口。',
 76: '苏墨将薄肉一片片夹到孩子的碗里。',
 77: '孩子们拿着筷子迟迟不动，叶东刚要开口。',
 78: '叶嫣儿抢先开口，鼻尖发红，叶东停住。',
 79: '镜头靠近叶嫣儿的脸，眼眶发红。',
 80: '叶嫣儿含泪看着苏墨，苏墨张嘴又收住。',
 81: '特写苏墨的脸，眉头渐皱。',
 82: '特写苏墨的脸，眉头渐皱。',
 83: '苏墨叹气压低声音，试着安抚。',
 84: '苏墨提高声音；孩子们开始埋头吃饭，叶东忽然站起。',
 85: '叶东站着梗颈开口，苏墨脱口回应，其他孩子抬起头。盆里的清汤冒着热气。',
 86: '苏墨握筷的手停住，六个孩子抬头，叶东咬牙攥拳。',
 87: '叶东急切看向苏墨，叶南、叶北、叶寻接连站起来。',
 88: '叶嫣儿坐着搂住叶西决，苏墨望着他们。',
 89: '苏墨看过桌上稚嫩的脸，收起笑容。',
 90: '苏墨让孩子们回房，叶北、叶寻拉住叶东，孩子们边走边回头。',
 91: '从孩子房门缝看见苏墨洗碗，叶嫣儿轻声开口，叶北摸弟弟的头。',
 92: '叶西决含泪发问，叶南捏住下巴沉思。',
 93: '叶南低声给弟弟交代第二天的打算。',
 94: '叶寻点头，叶东站在后面咬紧牙关。',
 96: '孩子们喝完牛奶，叶东把碗一推，其他人迟迟不肯先走。',
 97: '苏墨催孩子们上学，叶西决落在最后，躲到苏墨身后。',
 98: '苏墨清扫客厅，叶西决贴墙从屋门溜走。',
 99: '苏墨独自站在刚清扫过的屋里，神情放松。',
 100: '苏墨摸出旧手机，翻开短信，嘴角扬起。',
 101: '他看过短信，转向孩子们紧闭的房门扬声叫人。',
 102: '苏墨朝紧闭的房门喊了一声，把手机揣好，拎外套出门。',
 103: '叶西决沿街往学校跑，气喘吁吁地慢下来，望向巷口。',
 104: '矮个男人收紧麻袋口，袋子晃动。',
 105: '矮个男人向袋子开口，高个男人朝地上吐唾沫。',
 106: '高个男人对着袋子开口，巷内光线昏暗。',
 107: '焦点落在高个男人说话时的侧脸。',
 108: '窄巷中，两人守着麻袋，远处保持空巷。',
 109: '矮个男人摸着下巴，转动眼珠。',
 110: '矮个男人朝同伴开口，高个男人会意。',
 111: '两人相视而笑，麻袋中的动静渐弱。',
 112: '近景停在墙边麻袋的表面，画外叙述继续。',
 113: '苏墨从巷口阴影走入，神情严厉。',
 114: '麻袋口被打开，光线照进来，叶西决抬起手。',
 115: '叶西决抬眼，认出苏墨；苏墨看清他后回身护住孩子。',
 116: '近景停在蹲下的苏墨脸上，他看着袋口的孩子。',
 117: '苏墨把叶西决拉出来，替他拍去尘土，蹲下察看手脚。',
 118: '苏墨挡在叶西决身前，朝地上的男人开口。',
 119: '叶西决靠在苏墨怀里，抬眼看他的侧脸。',
}
SPLITS={62:[(0,1,'kitchen_door',[D,N],'叶东朝孩子房方向示意。'),(1,2,'child_room',KIDS,'孩子们聚在房间中间，压低声音交换眼神。')],
 95:[(0,1,'adult_room',[SU],'苏墨从枕下数出零钱，攥着出门。'),(1,2,'stall',[SU],'苏墨在清晨的街摊买面包和牛奶。'),
     (2,5,'breakfast_table',FAMILY,'苏墨摆好早餐，孩子们陆续入座，分别拿起面包和牛奶。')]}



def draft():
    data=json.loads(COVERAGE.read_text(encoding='utf8'))
    places={s['id']:p for s,p in zip(data['scenes'],SCENES,strict=True)}
    people={n:dict(id=n,kind='person',age_source={'value':a,'source':src},appearance_design=look,
            origin='individual_turnaround',views=dict.fromkeys(PERSON_VIEWS),canonical_sha256=None,status='missing',review=None)
            for n,a,src,look in PEOPLE}
    environments={k:dict(id=k,kind='place',layout_design=v,origin='empty_scene_plate',views=dict.fromkeys(PLACE_VIEWS),
                  canonical_sha256=None,status='missing',review=None) for k,v in PLACES.items()}
    shots=[]
    for i,seg in enumerate(data['segments'],1):
        cast=next(c for a,z,c in RANGES if a<=i<=z)
        chunks=SPLITS.get(i,[(0,len(seg['units']),places[seg['scene']],cast,DIRECTIONS.get(i,''))])
        for j,(lo,hi,place,visible,action) in enumerate(chunks,1):
            units=seg['units'][lo:hi]
            audio=voice_items(units)
            placements=['on_screen' if a['delivery']=='on_screen' and all(ALIASES.get(s,s) in visible for s in a['speaker'].split('／')) else 'off_screen' for a in audio]
            shots.append(dict(id=seg['id'] if len(chunks)==1 else f"{seg['id']}.{j}",segment=seg['id'],scene=seg['scene'],place=place,
              visible=visible,visual=action,units=[u['id'] for u in units],source_hash=fingerprint(units),voice_placement=placements,review=None))
    return dict(schema='h3_asset_proposal/v2',people=people,aliases=ALIASES,places=environments,shots=shots,coverage_path=str(COVERAGE),
                pilot_review=None,status='blocked_pending_assets_and_shot_reviews')


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'PROPOSAL.json').write_text(json.dumps(draft(),ensure_ascii=False,indent=2),encoding='utf8')



