from pathlib import Path
import json
r=Path('data/creative_workflows/reusable_trial_20260927');s=json.loads((r/'state.json').read_text(encoding='utf-8'))
rows=[
('director','SH03A SH03B','SH03B只有画外林屿台词但dialogue_mode=画内。SH03A只有陈默对白却prompt称林屿在画外说话。','声音归属仍然错误，可能重复对白或让听者对口型。','SH03A仅保留陈默当前一句，删除关于林屿在本镜发声的描述；SH03B明确dialogue_mode=画外，林屿声音属于林屿，陈默只听不对口型。'),
('writer','B03','左手一直托调色板，把笔放在调色板凹槽后直接双手垂下，未放置调色板。','调色板会消失或悬空。','放笔后只让右手垂下，左手继续稳定托板；后续拉凳仅用空闲右手。同步所有当前拍状态，不增加多余放拿动作。'),
('writer','B01 B02 B03 B04 B05','B04+B05仍32/77秒，SH05B9秒只是看凳子与嘴角放松。','短促情绪被拖成长停顿，主要信息在前半而操作占后半。','在总70–100秒范围重新分配，可优先采用B01=15、B02=23、B03=18、B04=6、B05=8，共70秒；保留原事件、对白及人物关系，把新增时间留关键句前后而不是无声收尾。无需固定使用该分配但B04/B05应短而清楚。'),
('director','SH01A SH02A SH02B SH03A SH03B SH04A SH04B SH05A SH05B','实际背景左上窗、右后门、大桌前景、后方画架凳子。SH02还声明右后窗与旧图一致；设计虚增右后窗。','空间和视线在已声明复用的图中不成立。','只使用已实见的左上窗与右后门，修正角色看窗方向及所有构图/prompt/production_choices；若新角度必要则作为新背景reuse_key空串，不冒充旧图。'),
('director','SH01A SH02A SH02B SH03A SH03B SH04A SH04B SH05A SH05B','设计required_tags包含未登记标签，三项都将generate。库中陈默tags仅adult_male/black_short_hair/charcoal_jacket/photoreal；林屿仅adult_female/shoulder_black_hair/offwhite_cardigan/photoreal；日间画室仅studio/day/warm_window_light/photoreal。','历史图明明兼容却重复生成。','用于复用匹配的required_tags必须选自对应已登记tags，不新造检索标签。外貌细节可写prompt但不当必需标签；选择reuse_key时不能擅改旧图衣服或空间。将这条传给本轮production_design资产编排。'),
('director','SH01A SH02A SH05A','opening_prompt分别提前开门让人出现、提前跨门槛、提前走到凳旁伸手，与各镜start_state不一致。','首图提前完成动作，后段会重复或跳步。','所有首帧描述严格静态投影本镜start_state，不把镜内尚未发生的动作写成已完成；逐镜核对。重新编排asset设计须保留这一要求。')]
issues=[{'owner':o,'location':loc,'evidence':ev,'impact':imp,'proposal':pr,'severity':'major'} for o,loc,ev,imp,pr in rows]
f={'schema':'creative_assistant_feedback/v2','handoff_sha256':s['handoff_sha256'],'assistant_review_sha256':s['assistant_review_sha256'],'parent_revision_review_sha256':s['assistant_revision_review_sha256'],'issues':issues}
Path('data/production_trials/reusable_20260927/feedback2.json').write_text(json.dumps(f,ensure_ascii=False,indent=2),encoding='utf-8')
