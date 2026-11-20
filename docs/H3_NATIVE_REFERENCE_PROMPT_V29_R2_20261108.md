# v29 r2：原闭眼状态与实际 guide 术语修正

root 实读 r1 指出：S01 原稿只有父亲闭眼躺着，末尾听懂对话；英文误写 sleeping/asleep 增加了未确认的睡眠状态。r2 仅在该原稿的三处英文输入中改成闭眼躺着、保持闭眼，不预先补写醒着状态。S02 原有睁眼动作保持。这是逐段语义修正，不是通用禁止写睡觉。

r1 稿件、INPUT_SPEC、AUDIT、READING 与 `CPU_ACCEPTANCE.json` 不变。原 r1 源码和测试已按旧 SHA 重建存档于 `data/qa/spatial_v29/r1_source_archive/`；当前编译器只添加 opt-in `task_type` 参数，默认四份输出字节与 r1 全部相同。

新候选在 `data/video_generation/spatial_minute_experiments_20261107_v1/B_native_v29_r2/`，由 `scripts/prepare_spatial_native_prompt_v29_r2.py` 从 r1 spec 构造。修正输入清单写在新 INPUT_SPEC 的 `revision_input_audit`，并绑定 `parent_spec`。

实际每段都有 frame-zero AddGuide，因此四段 summary 的任务类型为 `[reference generation + keyframe completion]`，每段首镜增加从实际提供的 frame-zero guide 的位置和构图承接动作的英文说明。S03 末句明确向 provided closing guide 的三人站立姿态承接，父亲持有面包袋。S01、S02、S04 没有增加末帧锚。五 Picture 参考槽保持原绑定，guide 不伪标为第六图。

`CPU_ACCEPTANCE_R2.json` 逐稿确认：将 r1 正文按上述声明变换后，与实际 r2 输出完全一致；原四份中文 source 字节与十句逐字引号内容均保持。37 项测试通过，其中包含四份默认 r1 输出逐字节回归、r2 实际 prepare、错误修改锚拒绝以及允许其他故事明确写睡眠状态的反例。

本次仍为 0 GPU/POST，仅更新待 root 审查的输入。v24 没有修改，后续实际媒体必须使用经 root 审核的 r2 文件，不能把 CPU 格式通过当成演员/动作/原生声音验收。
