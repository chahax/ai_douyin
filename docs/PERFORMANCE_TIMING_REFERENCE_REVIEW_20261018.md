# 表演参考时长与完整候选：实施和主审

当前渡口压缩候选的剩余段已逐段重排，完整稿为6段、7／9／8／13／13／10秒，累计60秒。S02缩短普通交接，S04/S05各保13秒容纳愧疚与释然，原4秒独立挥手尾段合入最后10秒。对白和说话人与前72秒编辑候选一致；总长是逐段结果，不是必须达到的目标。

## 规范与接线

人读规范：[动作、对白和情绪反应的排时参考](PERFORMANCE_TIMING_REFERENCE_20261018.md)。独立`performance_timing_reference/v1`把动作、情绪反应和对白参考区间、并行/依赖计算、最后有效内容收段等完整说明及SHA写入新任务brief。它是项目初始参考，不是行业硬标准、语言分类器或内容合格门。

实现为`src/content_factory/performance_timing_reference_v1.py`。网页新来源准备已接入；独立CLI为`scripts/run_performance_timing_natural_director_v1.py source-prepare`。原`content_end_pacing/v1`、v9/v10运行器及其合同保持原文件，两个规范一起冻结。编剧、全文审查、自然导演、忠实整理和最终全部SDK请求复审收到同一完整brief。参考时长不覆盖原显式硬范围，旧任务不补写；原命令仍按原任务执行，不增加调用预算或媒体权限。

## 完整文字候选

`data/narrative_pacing_revision/20261018_performance_v3`保存：

- `FULL_SCREENPLAY.md`：世界、人物、空间及各段对白、动作、视线、内部估时、关键反应和切出条件。
- `SEGMENTS.json`：同一候选的分段、起末态、内部并行拍和来源绑定。
- `TIMING_REFERENCE_PROFILE.json`：本轮参考规范完整副本。
- `S01.PROMPT.txt`至`S06.PROMPT.txt`及`SDK_REQUEST_PREVIEWS.json`：实际SDK本地构造的纯文本预览，均使用所选段长；不把内部小数时间表或参考素材资格说明发给视频模型。
- `PREVIEW_VALIDATION.json`：对白/说话人、累计时长、拍连续、段间状态及预览文件绑定核对。

主agent审读全部段后修正三处：S04不重复演S03已经消失的防备，改为被理解后的动容；S03准确记录沿用已有不拿杯安排；S06到门后不再重复走向门口。另补全文的时代与地点说明，核对最后回应完成即收束。

这是一份助手编辑候选，并非MiniMax新原生完整稿或DeepSeek新验收。相对原v10冻结105—135秒范围的缩短属于本轮另存建议，不能挂旧审核或旧十轮预算直接提交。未来正式采用新总长仍要显式新范围与来源绑定，承接原用量，不能放宽旧硬范围或重领消耗。

当前SDK为无参考图本地预览，尚未选择正式素材或获准尾帧，不是可直接派发的制作交接；预览包含`submission_authorized=false`。本轮0外部文本/图像/视频调用，原10.08秒首段、用户反馈与回执不改。

## 验证与实际限制

主agent97项组合离线验证通过，子agent11项独立验证通过。覆盖完整profile/SHA、五阶段实际请求材料、网页新来源接线、硬范围不放宽、旧运行拒绝补写、原CLI操作不注入。证据在`data/qa/performance_timing_root_v1/TESTS.xml`及`data/qa/performance_timing_reference_v1/TESTS.xml`。

另用可重现本地脚本`data/qa/performance_timing_root_v1/build_editorial_previews.py`核对全部6段和SDK构造：18条表演对白相对原17处引用没有删词或换说话人，差别仅原连续父亲两句在内部拆为两个拍；段间状态连续，完整累计60秒，原版本来源哈希保持。

独立规则审查确认：普通0秒仅指额外展开或空尾；重要反应不能归零。并行取最长分支前先处理刺激到达和真实先后依赖。以上证明代码接线与文本候选可对照，不证明新稿生产语义验收或成片质量；视频仍由用户人工审查，无播放、抽帧、ASR或音画模型审核。
