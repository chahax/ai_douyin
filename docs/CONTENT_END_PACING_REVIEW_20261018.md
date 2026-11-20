# 按有效内容收尾：接线与验证

用户指出票约7秒推完、后续没有有效动作后，已把结束条件接入新任务的冻结创作要求：最后必要对白、动作和关键反应完成即收段，普通反应与对白、递物并行，不再例行留尾窗或凑参考总长。

## 实际原因

原首段专项入口、计划和SDK请求均固定10秒；提示词又单独安排9.2—10秒回看。因此内容提前完成仍可能停留。通用自然导演v10原本已逐段原值传递`duration_seconds`，并没有自动加到10秒；本轮没有改它的编译算法。

## 已接入的范围

- `src/content_factory/content_end_pacing_v1.py`：独立`content_end_pacing/v1`规则及SHA，加入新来源brief；明确参考总长、硬上下限、普通动作并行、必要反应与及时收段。MiniMax编剧、DeepSeek全文审查、MiniMax自然导演、DeepSeek忠实整理与最终全部SDK请求复审均沿用同一个冻结brief。
- `src/web/natural_director_panel_v10.py`：新来源准备调用独立适配；“参考成片时长”下限可到4秒，说明不为参考总长补动作。原任务查看及执行入口保持原行为。
- `scripts/run_content_end_natural_director_v1.py`：新来源`source-prepare`加入新规则，其余原任务操作原样委托旧CLI。原专属授权、预算、未知结果及计数门仍由冻结运行器核对。
- 既有来源没有本规则时拒绝补写；旧v9/v10运行器、合同和模型客户端未修改，旧十轮记录不重启。显式最短、最长及目标加容差仍是硬约束，发生冲突返修上游，不暗改秒数。

新CLI示例（只准备，真实来源和原有效授权须自行满足运行器要求）：

```powershell
.venv\Scripts\python.exe scripts/run_content_end_natural_director_v1.py source-prepare --source-run-dir <新writer目录> --source-path <正文或原创简报> --source-kind original --authorization-path <该源有效授权.json> --brief-json <创作要求.json>
```

## 当前首段的7秒候选

位置：`data/narrative_pacing_revision/20261018_content_end_v2/S01`。三句对白保留，女儿的普通意外和回看在父亲推票及最后一句内完成，票到位、话说完即结束。实际SDK预览为7秒、720p、9:16、原生音频、无参考图；Mini提示词按动作顺序写，小数估时只留内部表。

该候选由主助手编辑、子agent独立文本核对，未重新进入MiniMax/DeepSeek真实生成和审核，也未提交新视频。原10.08秒片、原生回执、请求与用量保持；用户反馈单独绑定原任务`cgt-20261018183930-rdnhd`及原视频SHA，不标为用户通过或允许续段。

## 验证和限制

主agent审查实现与实际请求材料后，86项组合离线验证通过；子agent14项独立验证通过。覆盖网页新任务实际传递、五阶段相同规则、7秒SDK预览、硬时长范围不放宽、旧任务不迁移及原命令不注入。证据分别为`data/qa/content_end_pacing_root_v1/TESTS.xml`和`data/qa/content_end_pacing_v1/TESTS.xml`。

独立核对当前候选时只读文本、容器元数据和文件SHA，未播放、抽帧、听看或ASR。离线验证证明规则接线和请求一致，不证明视频模型必然按7秒演好；新稿语义质量仍须同稿审查，实际视频仍由用户审片。本轮新增文本服务和媒体提交均0。
