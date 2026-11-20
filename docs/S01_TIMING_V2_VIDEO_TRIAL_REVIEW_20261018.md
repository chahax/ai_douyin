# 新标准七秒首段视频：实际提交与核验

用户经澄清明确“是新标准的第一段就生成”，按[本次计划](S01_TIMING_V2_VIDEO_TRIAL_PLAN_20261018.md)仅提交一次Seedance Mini首段。实际原ID为`cgt-20261018220732-5czvf`，七秒、720p、9:16、原生音轨，纯文本无参考图，不使用旧尾帧。

已成功保存[实际首段视频](../data/video_generation/novel_ferry_timing_v2_trial_20261018/S01/S01.mp4)，状态`awaiting_human_review`。服务原生created/updated相差112秒；文件保存于北京时间2026-10-18 22:09:55。容器总长7.104秒，H.264视频720×1280/169包、AAC音轨223包，文件3583973字节，SHA256为`5f75aee737c0afda6ac063a2261e7bac2685ac0ef9f399df7245d952fd2bea0f`。这些仅证明文件及容器完整，不证明实际对白、口型、动作或节奏通过。

原生usage为152100 completion/total video tokens，单列媒体用量，不与已冻结20次/383259文本tokens混算。59份保存基线全部SHA不变，旧失败2/10保持、新失败0。实际原尾图另存，只作为生成服务原始产物保存，没有用户批准，不可据此续段。主审交付证据为`PRIMARY_DELIVERY_REVIEW.json`，实际原生请求/回执/QUERY完整保留；未重试、续段、合成或发布。

选中v4已经主助手与独立子agent核对的新标准编辑候选S01，实际prompt逐字沿用。它没有新MiniMax/DeepSeek通过身份；上一份MiniMax歧义稿及final revise、原20次文本消耗与停点保持，不直接制作该失败稿、不手工删字冒充重新审查。本轮0新文本调用。

新模块`compact_ferry_video_trial_v2.py`及CLI独立于旧固定十秒入口。主agent审查完整diff，独立11项必要回归通过；子agent41项通过，两者重叠不相加。一次初始测试因临时目录父级不存在产生setup错误，原XML保留，正常重跑证据为`data/qa/compact_ferry_video_trial_v2/TESTS_V2.xml`；没有实现失败被覆盖。

输入绑定v4全稿、分段、profile、源prompt、原SDK预览及本次授权。提交前在共享registry锁内复核21份旧任务终态证据，三个历史媒体任务均为已知结果；旧失败2/10保持。永久claim在POST前保存，实际请求与预览一致且恰好一次提交；未知不可重派，后续只GET原ID。

资产统一索引未检出周禾/周明/渡口/青岚河匹配，本次维持原试法纯文本，不将未批准旧尾图当角色参考。59份旧产物、历史原稿、模型回执、媒体与失败记录已做保存基线，结束再按SHA复核。

运行根：`data/video_generation/novel_ferry_timing_v2_trial_20261018/S01`。状态、原ID及SHA以其中`state.json`、原生QUERY和`receipt.json`为准。主agent独立重新计算文件SHA并执行ffprobe容器/音频包检查，与保存metadata一致；仅检查原生尾图结构，不看听、抽帧、ASR或调用内容审核。内容由用户人工审核，不因接口成功自行续段。
