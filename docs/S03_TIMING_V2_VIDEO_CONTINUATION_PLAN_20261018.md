# 新标准S03：沿第二段服务原尾续一次

用户收到S02视频后再次回复“继续”，本次仅允许使用刚交付S02的服务原始尾图生成S03一次，不扩展S04或整批。父S02原receipt/视频不改，另存`receipt.continuation_user_decision.json`记录原话、当前父身份和单段继续范围；视觉、声音、口型、节奏评价仍null，不代用户作内容评分。

父ID为`cgt-20261018222555-js2z2`。父服务原尾JPG位于S02目录，305990字节、SHA256=`6de202a1bd641984b2f7635a4df82b407e41e894d39c3ab8677880ae705642d0`。仅以该原始字节base64作为SDK `first_frame`，不抽帧、编辑或生成替代首帧，不换用S01或旧十秒版本尾图。

来源仍为`data/narrative_pacing_revision/20261018_dialogue_v4`的第三段与`S03.PROMPT.txt`。S03六秒，两句为“你不拦我？”和“我舍不得，是我的事。不是你留下的理由。”，女儿问话0.9秒、接话0.1秒、父亲16字约5秒含明确停连，听见放手的变化与末句重叠，话后无另补尾窗。段首必须与S02文字末态一致，源提示词逐字保留，实际SDK由六秒纯文本预览明确增加一个父服务原帧派生。

独立scope=`timing_ferry_v2_20261018_S03`，运行根`data/video_generation/novel_ferry_timing_v2_trial_20261018/S03`。Seedance Mini、6秒、720p、9:16、原生音轨。新v4模块/CLI不改冻结S02/v3或S01/v2；父全部源、代码、回执、原ID、原尾和继续侧记核对后冻结，主agent核实际base64反解与父原字节一致。

共享registry锁内核同源未决及永久onceclaim，承接失败2/10，不清零历史；一次POST，未知结果不重派，只GET原ID。0新文本模型调用，文本20次/383259停点保持。完成后仅核SHA、容器/音频包及原尾结构，状态`awaiting_human_review`，不看听、抽帧、ASR或自动内容审核，不自动S04、重试、合成或发布。
