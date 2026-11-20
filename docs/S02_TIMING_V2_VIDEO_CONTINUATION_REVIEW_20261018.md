# 新标准S02：原生尾帧续段实际记录

用户收到新标准S01后回复“继续”，按[本次计划](S02_TIMING_V2_VIDEO_CONTINUATION_PLAN_20261018.md)仅续S02一次。原S01回执与媒体不改，另存`receipt.continuation_user_decision.json`，仅记录当前原尾续一段的用户接受；具体视觉、声音、口型、节奏评分仍null，不伪写助手或用户逐项内容通过。

本次原ID`cgt-20261018222555-js2z2`，Ark Seedance 2.0 Mini、7秒、720p、9:16、原生音轨。来源仍是v4已核对编辑候选S02，不是有歧义的MiniMax失败原稿，不冒称新MiniMax/DeepSeek验收。四句25汉字，声音计划6.5秒、接话间隙0.5秒，女儿的防备松开与末句重叠，无额外反应尾窗。

已成功保存[实际S02视频](../data/video_generation/novel_ferry_timing_v2_trial_20261018/S02/S02.mp4)，仍为`awaiting_human_review`。原生服务created/updated相差143秒，文件保存于北京时间2026-10-18 22:29:40。容器7.104秒，H.264视频720×1280/169包、AAC音轨223包，文件4640760字节，SHA256为`ccc3486b4a22e065c1444803b3b7895fffb5f268ca9093bad67f519279cc7b47`。主agent重新ffprobe和SHA核验，与原metadata/receipt一致；原帧输入反解仍等于父原尾。它们证明技术完整，不证明对白、口型、连续性或节奏实际通过。

原生usage为152100视频completion/total tokens，费用未知；本次新标准S01＋S02两段共304200已报告视频tokens，和旧故事媒体历史、文本20次/383259账本分别保留。82份保存基线SHA不变，原S01receipt仍原状态，当前新增失败0、历史2/10保持。实际请求、原ID、父原尾、用户侧记与完成证据见运行根`PRIMARY_DELIVERY_REVIEW.json`，不续S03、不重试、不合成或发布。

唯一视觉输入为S01服务原生尾JPG：282191字节，SHA256 `b5971a969cbdf323200e4d16dc75f8c618990dfbda009fa630fa8465f809380e`。实际请求使用base64 data URI，SDK role=`first_frame`；主agent反解实际请求确认与原文件逐字节相等，未抽帧、编辑、重生成或使用旧十秒版尾帧。实际图生请求明确派生自原S02纯文本SDK预览，仅增加这一个原生首帧。

独立模块`compact_ferry_video_continuation_v3.py`和CLI不改冻结v2，主agent审完整差异并修正父子同名源覆盖风险，新回执按绝对路径保存source_bindings。父S01完整源/代码/计划/请求/回执/原ID/视频/原尾、侧记与首末态均核验，并冻结到本次source_files。

子agent13项必要差异测试通过，主agent独立9项复验通过，测试有重叠不相加；证据分别在`data/qa/s02_timing_v2_adapter_v1/VERIFIED_TESTS.xml`和`data/qa/compact_ferry_continuation_v3_root_v1/TESTS.xml`。覆盖原尾同字节、坏侧记、父证据变化、同源未决、永久onceclaim、unknown停止、S02待人工且无S03授权和同名源全保留。首轮因临时目录父级缺失产生setup错误，原XML保留，修好测试环境再跑，无真实服务重试。

实际提交前在共享registry锁内复核28份旧任务终态绑定，失败2/10保持。唯一claim先于POST，后续只GET原ID；新文本调用0，旧20次/383259停止不改。82份原S01和旧历史文件作为保存基线。

运行根：`data/video_generation/novel_ferry_timing_v2_trial_20261018/S02`。完成情况以其中原生QUERY、state和receipt为准；接口成功仍是`awaiting_human_review`，助手仅核文件/容器包和原尾结构，不看听、抽帧或ASR，不继续S03、重试、合成或发布。
