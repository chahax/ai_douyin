# 新标准S03：六秒原生尾帧续段实际记录

用户收到S02后回复“继续”，按[单段计划](S03_TIMING_V2_VIDEO_CONTINUATION_PLAN_20261018.md)仅续S03一次。父S02原receipt、视频和原尾不改，用户原话与仅续S03范围另存父目录`receipt.continuation_user_decision.json`；视觉、声音、口型、节奏评价仍null。来源继续使用已核对的v4编辑候选，不冒称新的MiniMax/DeepSeek验收。

唯一原ID为`cgt-20261018225609-tf9hb`，Ark Seedance 2.0 Mini、6秒、720p、9:16、原生音轨。两句为“你不拦我？”和“我舍不得，是我的事。不是你留下的理由。”，共20汉字；声音计划5.9秒、接话0.1秒，女儿反应与父亲末句同时发生，话后额外反应窗为0。这是生成输入安排，实际表演由用户审片判断。

已保存[实际S03视频](../data/video_generation/novel_ferry_timing_v2_trial_20261018/S03/S03.mp4)，状态`awaiting_human_review`。原生服务created/updated间隔91秒，保存时间为北京时间2026-10-18 22:58:15。容器6.080秒，H.264视频720×1280/145包，AAC音轨191包；文件4282803字节，SHA256=`99a0c17a118934076d95a78c2a4978d8aaceb98e0df95a9dde5ab46e83eb6ddf`。服务原尾295666字节，SHA256=`8dc46eef236eac5525fa191a0c7d330e1a4537ecd31b7e689bd0329c99ba3cb6`。

唯一图输入为S02服务返回的原始尾JPG：305990字节，SHA256=`6de202a1bd641984b2f7635a4df82b407e41e894d39c3ab8677880ae705642d0`。实际REQUEST中的base64反解与原文件逐字节一致，SDK role=`first_frame`；实际图生请求等于S03纯文本预览加这一个原生首帧。未抽帧、编辑图片或换用旧版本尾图。

独立v4模块及CLI保持冻结v3/v2不变。子agent8项必要差异回归、主agent4项复验通过，有重叠不相加；分别见`data/qa/compact_ferry_continuation_v4/TESTS.xml`和`data/qa/compact_ferry_continuation_v4_root_v1/TESTS.xml`。主agent已审v3→v4完整差异，并核实际86份来源、10份代码、35份旧终态绑定、107份保存基线、父原ID、用户侧记、一次claim及输出SHA/容器包。新回执来源键保持绝对路径，避免父子同名文件覆盖。

本次实际一次POST、两次GET原ID，新增失败0、历史2/10保持。原生usage为130500视频completion/total tokens，费用未知；新标准S01—S03累计434700已报告视频tokens，与旧媒体及文本20次/383259账本分别保留。本次新文本调用0，不重领文本停止额度。

完成证据在运行根`data/video_generation/novel_ferry_timing_v2_trial_20261018/S03`，包括`PRE_SUBMIT_REVIEW.json`、`PRIMARY_DELIVERY_REVIEW.json`及独立审计。助手仅核字节、SHA、容器包和原尾结构，未看听、抽帧、ASR或判断对白/口型/连续性/节奏通过。当前仅交用户审片，无S04、视频重试、合成或发布授权。
