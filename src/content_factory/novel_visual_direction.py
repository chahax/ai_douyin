"""Genre-aware visual direction for source-bound novel storyboards.

The novel splitter owns story facts, dialogue and timing.  This module runs
after that stage and adds a production design bible plus executable camera,
composition, lighting, performance and continuity instructions.  Source facts
and production choices are deliberately stored in separate fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


SCHEMA = "novel_visual_direction/v1"
STYLE_ID = "modern_campus_romcom_2d_v1"


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result


def _abstract_labels(abstract: str) -> list[str]:
    labels: list[str] = []
    for group in re.findall(r"【([^】]+)】", abstract or ""):
        labels.extend(re.split(r"[+＋/、，,\s]+", group))
    return _unique(labels)


def classify_visual_style(metadata: dict[str, Any]) -> dict[str, Any]:
    """Classify genre and choose a concrete visual treatment from book metadata."""

    categories = _unique([str(item) for item in metadata.get("categories", [])])
    abstract = str(metadata.get("abstract") or "")
    labels = _abstract_labels(abstract)
    searchable = " ".join(categories + labels + [abstract])

    if any(token in searchable for token in ("校园", "校花", "大学")) and any(
        token in searchable for token in ("恋爱", "甜文", "先婚后爱", "单女主")
    ):
        primary = "现代都市校园甜宠轻喜剧"
        profile = {
            "style_id": STYLE_ID,
            "medium": "精致二维动画，现代国漫人物质感融合日系青春恋爱番的表情节奏",
            "rendering": "清晰线稿、柔和赛璐璐明暗、克制的皮肤高光、真实空间透视",
            "palette": "停车场以蓝灰和低饱和青色为底，人物肤色与夕阳边光使用暖橙，形成冷暖分离",
            "texture": "混凝土、车漆和衣料保留细微纹理，避免塑料皮肤和空白背景",
            "emotion_language": "眼神、眉形、呼吸、手指力度和人物距离承担情绪；轻喜剧允许适度反应放大",
            "avoid": [
                "真人写真感",
                "儿童脸或未成年体态",
                "糖果色扁平背景",
                "过度磨皮",
                "每镜随机换画风",
                "无意义镜头光晕",
            ],
        }
    elif any(token in searchable for token in ("古言", "宫斗", "权谋", "仙侠", "玄幻")):
        primary = "古装幻想剧情"
        profile = {
            "style_id": "chinese_fantasy_donghua_v1",
            "medium": "精致国风二维动画",
            "rendering": "工整线稿、国画色阶与电影化空间光影",
            "palette": "低饱和矿物色配局部高纯度身份色",
            "texture": "织物、木石与器物纹理清楚",
            "emotion_language": "姿态、袖摆、视线和礼仪距离承担情绪",
            "avoid": ["现代服饰", "现代建筑", "廉价游戏立绘", "空白背景"],
        }
    elif any(token in searchable for token in ("悬疑", "推理", "犯罪", "惊悚")):
        primary = "现代悬疑剧情"
        profile = {
            "style_id": "urban_suspense_illustrated_v1",
            "medium": "半写实二维剧情动画",
            "rendering": "克制线稿、硬柔结合的明暗与可信空间透视",
            "palette": "中性低饱和色，关键线索使用单一强调色",
            "texture": "环境材质和线索细节清晰",
            "emotion_language": "遮挡、视线和负空间制造不安",
            "avoid": ["甜美滤镜", "无依据血腥", "空白背景", "随机霓虹灯"],
        }
    else:
        primary = "现代都市剧情"
        profile = {
            "style_id": "urban_story_2d_v1",
            "medium": "半写实精致二维动画",
            "rendering": "清晰线稿、自然明暗和可信空间透视",
            "palette": "环境中性色配人物身份强调色",
            "texture": "建筑、衣料和道具保留可读材质",
            "emotion_language": "面部、手势和空间距离共同表达情绪",
            "avoid": ["真人写真感", "空白背景", "塑料皮肤", "随机换画风"],
        }

    return {
        "primary_genre": primary,
        "platform_categories": categories,
        "abstract_labels": labels,
        "evidence": {
            "categories": categories,
            "abstract_tag_line": next(
                (line for line in abstract.splitlines() if "+" in line and "【" in line),
                "",
            ),
        },
        "style_profile": profile,
        "selection_reason": (
            "题材以成年大学生的校园恋爱、占有欲冲突和甜宠反转为主；"
            "二维动画比普通写实都市画面更能承载夸张而细腻的表情切换，"
            "冷色停车场与暖色人物边光可把强势到撒娇的反差直接视觉化。"
        ),
    }


def _source_evidence(source: str) -> dict[str, list[str]]:
    evidence = {"林夏": [], "洛雪微": [], "continuity_props": []}
    candidates = {
        "林夏": [
            "十九啊……",
            "林夏皮肤白皙，五官清秀，又留着柔顺的刘海，略微偏瘦的体格充满了少年气息",
        ],
        "洛雪微": [
            "穿着衬衫短裙，竖着高马尾",
            "一对犹如狐狸一般魅惑的杏眼",
            "女生身材高挑",
            "精致的五官无可挑剔，粉薄的嘴唇吹弹可破",
        ],
        "continuity_props": [
            "林夏说完，拿着军训服就朝着外面走去",
        ],
    }
    for key, rows in candidates.items():
        evidence[key] = [row for row in rows if row in source]
    return evidence


def _visual_bible(metadata: dict[str, Any], source: str) -> dict[str, Any]:
    genre = classify_visual_style(metadata)
    evidence = _source_evidence(source)
    return {
        "schema": "novel_visual_bible/v1",
        "genre_analysis": genre,
        "format": {
            "aspect_ratio": "9:16",
            "visual_medium": genre["style_profile"]["medium"],
            "style_id": genre["style_profile"]["style_id"],
            "line_and_shading": genre["style_profile"]["rendering"],
            "palette": genre["style_profile"]["palette"],
            "texture": genre["style_profile"]["texture"],
        },
        "source_facts": {
            "characters": {
                "林夏": evidence["林夏"],
                "洛雪微": evidence["洛雪微"],
            },
            "location": ["停车场"],
            "continuity_props": evidence["continuity_props"],
        },
        "production_design_choices": {
            "林夏": (
                "19岁成年男大学生；柔顺近黑棕刘海、白皙清秀、偏瘦。"
                "本场锁定浅蓝牛仔外衫、白T、深灰长裤；左手始终带着折叠军训服袋。"
            ),
            "洛雪微": (
                "成年女大学生学姐；高挑、近黑冷棕高马尾、魅惑杏眼、粉薄唇。"
                "本场锁定米白宽松衬衫、深灰短裙、黑色低跟皮鞋，成熟而不幼态。"
            ),
            "fact_boundary": (
                "年龄、体态、高马尾、五官特征和军训服来自正文；发色、当场服装颜色、"
                "军训服袋样式与左右手分配是为保持视频一致而作的制作选择，不冒充原文事实。"
            ),
        },
        "set_design": {
            "location": "大学建筑旁的现代地下停车场出口区（由校园上下文和原文‘停车场’推导）",
            "layout": (
                "画面左前方一根方形混凝土柱；中景为两人所站的行车通道边缘；"
                "右后方是通向室外的缓坡；远处两排停放车辆和重复顶灯形成纵深。"
            ),
            "axis": "人物对视轴固定；洛雪微在画面左侧、林夏在右侧，所有正反打留在轴线同一侧",
            "landmarks": ["左前景混凝土柱", "右后方出口暖光", "地面白色车位线", "远处重复顶灯"],
            "lighting_sources": ["停车场冷白顶灯", "右后方坡道口的傍晚自然暖光"],
            "depth_rule": "每个镜头至少保留前景遮挡、中景人物、后景灯列或车辆中的三层关系",
        },
        "continuity_lock": {
            "screen_positions": "洛雪微左、林夏右",
            "height_relation": "林夏略高，洛雪微以更近距离和主动动作形成气势优势",
            "hands_and_prop": "洛雪微操作林夏右手/右臂；林夏左手的军训服袋持续存在，不凭空换手或消失",
            "light_world_coordinates": "冷白顶灯固定在上方，暖光固定来自画面右后坡道；反打时光源不随相机移动",
            "style_lock": genre["style_profile"]["style_id"],
        },
        "negative_style": genre["style_profile"]["avoid"]
        + ["字幕", "水印", "多余路人", "手指畸形", "人物忽然换发型或年龄"],
    }


def _shot_specs() -> list[dict[str, str]]:
    """Curated visual grammar for the selected parking-garage confrontation."""

    specs = [
        # size, lens, angle/move, foreground, midground, background, focus,
        # performance, end state, cut reason
        dict(size="面部近景", lens="70mm", camera="眼平微侧，极慢推近", foreground="虚焦的林夏右肩压住右下角", midground="洛雪微从冷眼转为唇角轻翘，脸占画面左侧三分之二", background="顶灯散景与蓝灰车库墙", focus="眉眼与唇角在同一焦平面", performance="先保持下颌绷紧和直视，吸气后眉心放松半拍，唇角才抬起；变化分两步完成", end="洛雪微已换成柔软表情，林夏仍在她近前", cut="先用可见表情反转建立悬念"),
        dict(size="过肩近景", lens="65mm", camera="洛雪微肩后看林夏，固定", foreground="洛雪微高马尾和肩线形成左侧框景", midground="林夏在右侧，眼睛先睁大、喉结轻动", background="坡道暖光切出窄亮边，远车保持虚化", focus="林夏被一句话击中的反应", performance="洛雪微泪光只停在下眼睑不落泪；林夏嘴唇微张但不回答，视线从她眼睛落到两人相触的手", end="林夏答案被截断，右手仍在洛雪微控制范围", cut="在答案前硬切回因果起点"),
        dict(size="环境中全景", lens="28mm", camera="腰高同侧斜拍，短距离跟停", foreground="左侧混凝土柱边缘与地面车位线", midground="洛雪微在左前拉着林夏向车道内走，林夏右手被牵、左手提军训服袋", background="车辆、坡道和连续顶灯交代停车场纵深", focus="拉拽关系和道具状态一次建立", performance="林夏身体重心向后抵抗，军训服袋因惯性轻摆；挣脱只在镜尾发生一次", end="林夏右手刚挣脱，两人拉开半步；军训服袋仍在左手", cut="时间重置后先建立空间、轴线和持物"),
        dict(size="双人中景", lens="40mm", camera="胸口高度固定，轻微手持冲击后立刻稳定", foreground="林夏甩开的右手掠过镜头下沿", midground="林夏右侧前倾喊出，洛雪微左侧停步回看", background="白色车位线斜向延伸，冷顶灯压住空间", focus="挣脱的爆发和双方距离", performance="喊声和甩手同步；林夏肩膀上提后落下，洛雪微不后退，只转头", end="两人相距约一臂，林夏右手垂在身侧", cut="爆发落点后切掌控者反应"),
        dict(size="洛雪微胸像近景", lens="60mm", camera="略低于眼平，固定", foreground="林夏虚焦手臂在右下保留关系", midground="洛雪微回头，肩线稳定，杏眼从侧视转为正视", background="混凝土柱竖线强化压迫", focus="不满眉形与控制感", performance="先斜睨被挣开的手，再抬眼看林夏；‘亲我’略挑眉，‘牵手不行’压低唇角", end="洛雪微目光锁住林夏，尚未再次抓他", cut="话尾留半拍给男方疼痛反应"),
        dict(size="手部细节转半身", lens="55mm", camera="先俯拍右腕，再小幅上摇到脸", foreground="林夏发红的右手腕清晰占下半画面", midground="林夏甩手并用左臂压住军训服袋", background="洛雪微在左后方保持清晰轮廓", focus="疼痛证据与嘴硬之间的反差", performance="手腕甩两次后停，指尖屈伸确认疼痛；眉头皱起但不演成夸张受伤", end="林夏右臂抬在胸前，洛雪微准备上前", cut="用手部证据引出下一次抓握"),
        dict(size="双人近中景", lens="45mm", camera="同侧横移半步后停", foreground="军训服袋在林夏左侧下沿形成持续锚点", midground="洛雪微左手抓住林夏右前臂并把他拉近，二人形成对角线", background="车位线和顶灯透视线汇向两人之间", focus="抓握动作和质问眼神", performance="抓住、拉近、皱眉、发问按顺序完成；林夏脚下被带动半步，不瞬移", end="洛雪微抓着林夏右前臂，两人距离缩至半臂", cut="动作完成后切听者的真实困惑"),
        dict(size="林夏过肩近景", lens="65mm", camera="洛雪微肩后固定", foreground="洛雪微发尾在左侧虚焦", midground="林夏右侧眉心抬起，眼神没有躲闪", background="出口暖光只勾出耳廓边缘", focus="莫名其妙而非心虚", performance="先眨眼一次，再略偏头回答；被抓的右臂保持原位，左手军训服不抬起", end="林夏维持困惑，右臂仍被抓", cut="保留视线轴后回到追问者"),
        dict(size="林夏胸像近景", lens="60mm", camera="洛雪微肩后固定", foreground="洛雪微抓住他右臂的手落在画面左下黄金点", midground="林夏位于右侧，只用眉眼和下巴表达不解", background="重复顶灯构成稳定节奏", focus="解释时的无辜神情与被控制的手同时可见", performance="回答时视线先看她的手、再回到眼睛；句尾轻呼气，不擅自增加摊手或耸肩", end="林夏解释完，洛雪微的手仍未松", cut="从解释切到她拒绝接受"),
        dict(size="洛雪微面部近景", lens="72mm", camera="微低机位，极慢推近", foreground="林夏虚焦侧脸压住右缘", midground="洛雪微杏眼锐利，眉峰下压", background="柱面暗部让脸与背景分离", focus="她把主观判断说成绝对规则", performance="嘴角不笑，眼神钉住对方；关键字‘图谋不轨’时下巴微抬，抓握力度只通过指节表现", end="洛雪微气势完全压过林夏，仍抓着他的右臂", cut="压迫顶点后给对方一次轻微反驳"),
        dict(size="林夏反应近景", lens="65mm", camera="洛雪微肩后看林夏，固定", foreground="洛雪微的肩与高马尾形成左侧框景", midground="林夏右侧略后仰，眉头轻蹙但没有退开", background="冷白灯列保持水平，右后暖光只勾耳廓", focus="他认为要求过度，却还没有真正强硬起来", performance="林夏先短促吸气，再说出反驳；句尾看回洛雪微眼睛，不提前被拉近", end="林夏刚说完‘这不至于吧’，洛雪微抓握指节骤然收紧", cut="反驳成为下一镜猛拉动作的直接刺激"),
        dict(size="双人极近景", lens="55mm", camera="同侧斜拍，随拉近动作短促推进后锁死", foreground="林夏左手军训服袋压在右下边缘，不参与动作", midground="洛雪微左侧猛收手把林夏拉近，林夏右侧被迫前倾，两张脸停在极短距离", background="顶灯与车位线向两人之间汇聚", focus="‘至于’的爆发、猛拉动作和骤然缩短的距离", performance="洛雪微先猛地一使劲，林夏重心被带前；两人停稳后她才咬字说‘至于’，动作与对白不倒序", end="两人脸几乎贴近，洛雪微仍扣住林夏右臂，林夏左手军训服袋未掉落", cut="动作落点切入连续四镜的近距离警告"),
        dict(size="极近双人特写", lens="85mm", camera="眼平同侧，完全固定", foreground="两人交叠的肩线形成封闭画框", midground="洛雪微左眼和林夏右眼位于左右三分点", background="仅留一条冷灯虚化光带", focus="严肃目光与被迫停住的呼吸", performance="洛雪微说前先盯住半拍；林夏不抢话，只明显屏息，军训服袋不进入此特写但延续状态不变", end="两人保持极近距离，洛雪微控制节奏", cut="警告拆句但不改变位置"),
        dict(size="极近双人特写", lens="85mm", camera="与上一镜同机位同焦距", foreground="林夏虚焦鼻梁与洛雪微清晰眼睛形成深度", midground="洛雪微的唇形和眼神同时可读", background="同一条冷灯散景", focus="‘保持距离’与当前零距离构成视觉反讽", performance="她不再向前，只在句尾略挑眉；林夏眼神短暂向后撤却无处可退", end="距离、抓握和轴线全部不变", cut="用反讽延续压迫，不重新建立空间"),
        dict(size="手臂与侧脸近景", lens="70mm", camera="轻俯角，固定", foreground="洛雪微扣住林夏右前臂的手清晰可见", midground="两人侧脸仍保持近距离", background="车漆冷反光形成细窄层次", focus="要求继续升级且控制没有放松", performance="她说话时拇指轻压他的袖口；林夏下颌开始绷紧，不点头", end="林夏出现抵触但尚未说话", cut="切向拒绝承诺的沉默"),
        dict(size="林夏反应近景", lens="75mm", camera="洛雪微肩后固定", foreground="洛雪微高马尾和耳侧轮廓虚化", midground="林夏目光稳定，嘴唇闭紧", background="坡道暖光在他侧脸只留窄边", focus="沉默本身就是拒绝", performance="听完后停一拍，眼神从她的手回到眼睛；轻吸气准备反抗，绝不点头", end="林夏下定抵抗决心，右臂仍被抓", cut="从外部压迫进入反抗准备"),
        dict(size="双人近中景", lens="50mm", camera="眼平，极慢拉远半步", foreground="左柱边缘重新出现，恢复空间感", midground="林夏身体站直、下颌绷紧；洛雪微仍近距离观察他", background="冷灯列和坡道暖光同时可见", focus="男方刚建立的骨气与女方观察到变化", performance="林夏肩线从缩紧到撑开；洛雪微先保持冷脸，看到他的反抗后眼神轻扫并决定换策略", end="洛雪微尚未松手，但表情即将改变", cut="给情绪转向一个清楚的前态"),
        dict(size="洛雪微面部近景", lens="70mm", camera="眼平缓慢推近", foreground="林夏右肩虚焦形成安全遮挡", midground="洛雪微眉心放松、眼尾下垂、唇角轻翘", background="暖坡道光形成细边，冷背景仍在", focus="强势表情逐层融化", performance="先松眉，再放软目光，最后才用轻柔声音开口；不可一帧突然换脸", end="她已完全切入撒娇状态，手部力度开始放松", cut="表情完成后切到手部行为变化"),
        dict(size="双手细节近景", lens="60mm macro", camera="胸口高度俯拍，轻跟手", foreground="林夏左手军训服袋位于画面下左边缘", midground="洛雪微松开右前臂，改为托起林夏右手掌，拇指轻抚", background="两人衣料色块和地面线条柔化", focus="从控制性抓握变成安抚性托手", performance="松开、转为掌心相托、轻抚一次按顺序完成；林夏手指先僵硬再略放松", end="洛雪微双手托住林夏右掌，军训服袋仍在林夏左手", cut="让动作证据承接道歉，不先切脸"),
        dict(size="侧面亲密近景", lens="75mm", camera="两人同侧侧拍，极慢推近", foreground="洛雪微高马尾发梢虚化在左上", midground="她俯近林夏右掌轻吹，嘴唇与指尖均清晰；林夏侧脸在右后", background="暖光散景落在两人之间", focus="吹气动作和林夏第一层身体反应", performance="洛雪微靠近前先看一眼他的手，再轻吹一次；林夏指尖微缩、肩膀瞬间僵住，不能提前抽手", end="林夏右手仍被托住，脸开始泛红", cut="动作完成后转到她抬眼追问"),
        dict(size="洛雪微仰视近景", lens="68mm", camera="略高于她眼线，从林夏手侧看下去", foreground="林夏泛红的指尖在右下清晰入画", midground="洛雪微从手掌旁抬眼，眼底有克制泪光", background="冷顶灯化为柔圆散景，暖边光描出脸颊", focus="像刚挠完人又卖乖的反差", performance="泪光不掉落；头只倾一点，眉尾放软，问完保持视线等待，不连续眨眼卖萌", end="她仍靠近他的手，等待明确答案", cut="问题后必须给受击反应空间"),
        dict(size="极近关系特写", lens="85mm", camera="同侧固定，不越轴", foreground="林夏右手指尖位于画面中央下方", midground="洛雪微粉薄唇靠近但不触碰，眼睛从指尖抬向林夏", background="车库灯光压成蓝灰与暖橙双色散景", focus="亲密距离和最后一句追问", performance="句前轻呼气可见指尖细微反应；她说到‘还不够吗’时目光才抬到他眼睛，保持成年感而非幼态撒娇", end="洛雪微停住等待，林夏的抵抗明显瓦解", cut="在触碰前切听者，避免暧昧动作失控"),
        dict(size="林夏面部近景", lens="70mm", camera="洛雪微肩后，轻微后拉", foreground="洛雪微托手的指尖仍在画面左下", midground="林夏耳根和脸颊变红，连续点头一次组", background="坡道暖边光加强但光源位置不变", focus="回答、点头和撤手的先后顺序", performance="先卡顿回答，再连点两下；说完才趁她停顿抽回右手，左手军训服袋始终不掉落", end="林夏收回右手贴近胸前，两人距离恢复半臂", cut="动作落定后切胜者余波"),
        dict(size="收束双人中景", lens="50mm", camera="眼平固定，极慢拉远", foreground="左柱与右侧车尾共同形成框景", midground="洛雪微左侧杏眼弯起、唇角得意；林夏右侧红着脸避开视线，右手护在胸前、左手提军训服袋", background="顶灯纵深通向坡道暖光，空间重新打开", focus="她赢得承诺，他意识到完全不是对手", performance="洛雪微只把笑意从眼睛扩到唇角，不追上去；林夏呼气、错开目光，保留窘迫余波", end="两人站位、服装、发型、军训服袋和光源保持稳定，以她的胜利微笑结束", cut="关系结果清楚后结束，不再追加动作"),
    ]
    designed_speakers = [
        "", "洛雪微", "", "林夏", "洛雪微", "", "洛雪微", "林夏",
        "林夏", "洛雪微", "林夏", "洛雪微", "洛雪微", "洛雪微",
        "洛雪微", "洛雪微", "", "洛雪微", "洛雪微", "洛雪微",
        "洛雪微", "洛雪微", "林夏", "洛雪微",
    ]
    for spec, speaker in zip(specs, designed_speakers):
        spec["designed_dialogue_speaker"] = speaker
    return specs


def _light_for(index: int) -> str:
    if index <= 1 or index >= 17:
        return (
            "世界光源不变：上方冷白顶灯作环境主光，右后坡道暖光作轮廓光；"
            "本镜让暖边光更容易被看见以服务柔软情绪，不新增灯源。"
        )
    return (
        "上方冷白顶灯作环境主光，右后坡道自然暖光作固定轮廓光；"
        "人物面部用地面与车身已有反射补足，背景比肤色低约一档。"
    )


def _build_shots(scenes: list[dict[str, Any]], bible: dict[str, Any]) -> list[dict[str, Any]]:
    specs = _shot_specs()
    if len(scenes) != len(specs):
        raise ValueError(
            f"Current reviewed parking story requires {len(specs)} scenes, got {len(scenes)}"
        )
    results: list[dict[str, Any]] = []
    previous_end = ""
    for index, (scene, spec) in enumerate(zip(scenes, specs)):
        timeline = "peak_preview" if index < 2 else "chronological"
        mode = "opening" if index == 0 else ("timeline_reset" if index == 2 else "continuous")
        if index == 0:
            start_state = "高光预示起点：两人已在近距离对峙，洛雪微仍是冷硬怒意"
        elif index == 2:
            start_state = "时间回到冲突开端：洛雪微牵林夏右手向停车场内走，林夏左手提军训服袋"
        else:
            start_state = previous_end
        previous_end = spec["end"]
        dialogue = "；".join(
            f"{line['speaker']}：{line['text']}" for line in scene.get("dialogue", [])
        ) or "本镜无对白"
        prompt = (
            f"竖屏9:16，{bible['format']['visual_medium']}，{bible['format']['line_and_shading']}。"
            f"同一现代校园停车场，洛雪微始终画面左、林夏始终画面右。"
            f"{spec['size']}，{spec['lens']}，{spec['camera']}。"
            f"前景：{spec['foreground']}；中景：{spec['midground']}；背景：{spec['background']}。"
            f"表演：{spec['performance']}。光线：{_light_for(index)}"
        )
        results.append(
            {
                "scene_id": scene["scene_id"],
                "timeline": timeline,
                "continuity_mode": mode,
                "duration_seconds": scene["duration_seconds"],
                "dialogue_lock": dialogue,
                "designed_dialogue_speaker": spec["designed_dialogue_speaker"],
                "shot_size": spec["size"],
                "camera": {
                    "lens_equivalent": spec["lens"],
                    "height_angle_movement": spec["camera"],
                    "axis_side": "人物轴线同一侧；洛雪微画左、林夏画右",
                },
                "composition": {
                    "foreground": spec["foreground"],
                    "midground": spec["midground"],
                    "background": spec["background"],
                    "focal_point": spec["focus"],
                },
                "lighting": _light_for(index),
                "performance": {
                    "visible_action_and_micro_expression": spec["performance"],
                    "visible_evidence": spec["focus"],
                },
                "continuity": {
                    "start_state": start_state,
                    "end_state": spec["end"],
                    "screen_direction": "洛雪微画左、林夏画右；不越轴",
                    "prop_state": "林夏左手军训服袋持续存在；涉及触碰的是林夏右手/右臂",
                },
                "cut_reason": spec["cut"],
                "generation_prompt_zh": prompt,
                "negative_prompt_zh": "、".join(bible["negative_style"]),
            }
        )
    return results


def enrich_storyboard_visuals(
    storyboard_wrapper: dict[str, Any],
    metadata: dict[str, Any],
    full_source_text: str,
) -> dict[str, Any]:
    """Return a source-bound storyboard with a reviewed visual direction layer."""

    if not isinstance(storyboard_wrapper.get("storyboard"), dict):
        raise ValueError("storyboard wrapper is missing storyboard")
    scenes = storyboard_wrapper["storyboard"].get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("storyboard has no scenes")
    bible = _visual_bible(metadata, full_source_text)
    result = copy.deepcopy(storyboard_wrapper)
    result["schema"] = "novel_highlight_storyboard/v4"
    result["visual_direction"] = {
        "schema": SCHEMA,
        "storyboard_sha256_before_visual_stage": hashlib.sha256(
            json.dumps(
                storyboard_wrapper["storyboard"],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest().upper(),
        "visual_bible": bible,
        "shots": _build_shots(scenes, bible),
        "story_text_changed": False,
        "dialogue_changed": False,
    }
    return result


def audit_visual_direction(package: dict[str, Any]) -> dict[str, Any]:
    """Deterministically audit completeness and visual continuity."""

    errors: list[str] = []
    storyboard = package.get("storyboard") or {}
    scenes = storyboard.get("scenes") or []
    direction = package.get("visual_direction") or {}
    bible = direction.get("visual_bible") or {}
    shots = direction.get("shots") or []
    genre = bible.get("genre_analysis") or {}
    profile = genre.get("style_profile") or {}
    if package.get("schema") != "novel_highlight_storyboard/v4":
        errors.append("wrong package schema")
    if not genre.get("primary_genre") or not genre.get("evidence"):
        errors.append("genre evidence missing")
    if profile.get("style_id") in (None, "", "dream_shaper_xl"):
        errors.append("specific visual style missing")
    if len(shots) != len(scenes):
        errors.append("visual shot count differs from storyboard")
    actual_storyboard_sha = hashlib.sha256(
        json.dumps(storyboard, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest().upper()
    if direction.get("storyboard_sha256_before_visual_stage") != actual_storyboard_sha:
        errors.append("storyboard bytes changed after visual stage binding")
    expected_lights = set((bible.get("set_design") or {}).get("lighting_sources") or [])
    if len(expected_lights) < 2:
        errors.append("world lighting sources are incomplete")
    for index, shot in enumerate(shots):
        if shot.get("scene_id") != scenes[index].get("scene_id"):
            errors.append(f"scene {index}: id mismatch")
        composition = shot.get("composition") or {}
        for key in ("foreground", "midground", "background", "focal_point"):
            if not str(composition.get(key) or "").strip():
                errors.append(f"scene {index}: composition.{key} missing")
        for key in ("shot_size", "lighting", "generation_prompt_zh", "cut_reason"):
            if not str(shot.get(key) or "").strip():
                errors.append(f"scene {index}: {key} missing")
        actual_speakers = _unique(
            [str(line.get("speaker") or "") for line in scenes[index].get("dialogue", [])]
        )
        designed_speaker = str(shot.get("designed_dialogue_speaker") or "")
        if actual_speakers != ([designed_speaker] if designed_speaker else []):
            errors.append(
                f"scene {index}: photography/dialogue subject mismatch "
                f"actual={actual_speakers}, designed={designed_speaker or 'none'}"
            )
        continuity = shot.get("continuity") or {}
        if index and shot.get("continuity_mode") != "timeline_reset":
            prior_end = shots[index - 1].get("continuity", {}).get("end_state")
            if continuity.get("start_state") != prior_end:
                errors.append(f"scene {index}: start state does not inherit prior end")
        if "军训服" not in str(continuity.get("prop_state") or ""):
            errors.append(f"scene {index}: continuity prop missing")
    if direction.get("story_text_changed") is not False or direction.get("dialogue_changed") is not False:
        errors.append("visual stage must not change story or dialogue")
    return {
        "schema": "novel_visual_direction_review/v1",
        "decision": "passed" if not errors else "rejected",
        "scene_count": len(scenes),
        "directed_shot_count": len(shots),
        "genre": genre.get("primary_genre"),
        "style_id": profile.get("style_id"),
        "checks": {
            "genre_evidence_present": bool(genre.get("evidence")),
            "specific_style_selected": profile.get("style_id") not in (None, "", "dream_shaper_xl"),
            "three_layer_composition_each_shot": not any("composition." in item for item in errors),
            "continuity_chain": not any("start state" in item for item in errors),
            "continuity_prop_each_shot": not any("continuity prop" in item for item in errors),
            "photography_matches_dialogue_subject": not any(
                "photography/dialogue subject mismatch" in item for item in errors
            ),
            "story_and_dialogue_locked": direction.get("story_text_changed") is False
            and direction.get("dialogue_changed") is False
            and "storyboard bytes changed after visual stage binding" not in errors,
        },
        "errors": errors,
    }
