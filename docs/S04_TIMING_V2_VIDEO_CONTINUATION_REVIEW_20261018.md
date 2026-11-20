# 新标准S04：十一秒原尾续段实际记录

用户收到S03后回复“继续”，按[本次计划](S04_TIMING_V2_VIDEO_CONTINUATION_PLAN_20261018.md)仅生成S04一次。唯一原ID`cgt-20261018231100-d6kjb`，Seedance Mini、11秒、720p、9:16、原生音轨。来源仍为已核对的完整v4编辑候选：三句35汉字，声音10.2秒、两次交接共0.3秒；末次动容共0.8秒，话中0.3秒与句后0.5秒是同一次变化，不重复追加。

已保存[实际S04视频](../data/video_generation/novel_ferry_timing_v2_trial_20261018/S04/S04.mp4)，状态`awaiting_human_review`。服务用时112秒，保存于北京时间2026-10-18 23:13:39。容器11.104秒，H.264 720×1280/265个视频包、AAC 348个音频包。文件7064458字节，SHA256=`19f9778e614594d344dec47f2d9db9fef62b7fc30f41527d346c2542204aba72`；服务原尾299621字节，SHA256=`036f4da6e3fbcf739048aee13ad1b38803afe9ea8132db70f9da9c592db30409`。

唯一图输入为S03服务原尾：295666字节，SHA256=`8dc46eef236eac5525fa191a0c7d330e1a4537ecd31b7e689bd0329c99ba3cb6`。实际REQUEST的first_frame反解与该原文件逐字节相同，实际请求等于原S04纯文本SDK预览加该图，提示词未改。父receipt原样保留，用户继续范围另存侧记，具体质量评分仍null。

独立v5保持冻结v4/v3/v2不变。子agent5项必要差异测试、主agent3项复验通过，有重叠不相加；证据在`data/qa/s04_timing_v2_adapter_v1/TESTS.xml`及`data/qa/compact_ferry_continuation_v5_root_v1/TESTS.xml`。主agent已审完整差异、真实107份来源绑定、10份代码绑定、42份旧终态绑定及166份保存基线；独立完成审计再次核SHA、原ID、实际首帧字节和ffprobe容器包，未发现阻断点。证据保存于运行根的`PRIMARY_DELIVERY_REVIEW.json`及`INDEPENDENT_DELIVERY_AUDIT.json`。

本次一次POST、三次GET原ID，新增失败0、历史2/10保持。原生usage为238500视频completion/total tokens，费用未知；新标准S01—S04累计673200已报告视频tokens，与旧媒体和文本20次/383259账本分开。本次新文本调用0，不冒称新MiniMax/DeepSeek验收。

运行根为`data/video_generation/novel_ferry_timing_v2_trial_20261018/S04`。助手仅核字节、SHA、容器包和原尾结构，未看听、抽帧或ASR；技术完整不等于实际对白、口型、连续性和节奏通过。当前待用户审片，无S05、重试、合成或发布授权。
