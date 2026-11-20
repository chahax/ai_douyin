# H3源镜头机位合同v19

新计划的H3节点负责格式适配，镜头导演权在上游剧本/分镜。取消response Schema、system和compiler三层统一locked-off/tripod/保持构图。已有v15的PLAN、REQUEST、原生回执和graph不迁移。

## 新入口

`visual_h3_native_prompt_v15.prepare(...)` 和 ready-only helper的新默认均为 `camera_contract="source_designed/v19"`。可使用新目录 `data/visual_h3_native_prompts_v19/<run>`；旧v15目录仍可读取。新PLAN schema为 `h3_motion_planner/v19`，新输出为 `h3_native_prompt_plan/v19`，wire为 `official_multimodal/v19`。旧公开常量CONTRACT/SCHEMA/VERSION保留v15供旧调用方使用；新常量分别为CONTRACT_V19/SCHEMA_V19/VERSION_V19。

默认机位材料来自原shot的camera_design、camera_instructions、camera_motion和visual_prompt，整体绑定原shot SHA。模型回执的camera_motion是程序常量 `inherit_source_shot_design`，不能自行选择机位；camera_contract为 `source_designed/v19`。模型只把已给镜头与人物动作适配为H3英文描述。已在源中明确的固定单镜仍固定；上游已有的推拉、摇移或切特写不再被全局拒绝。新校验保守核对可识别的相机操作必须在源设计中出现，不能代替完整语义/实片审核。

## 显式上游机位设计

可选参数camera_design接不可变文件绑定 `{path,sha256}`。该JSON须为 `schema="source_camera_design/v19"`，包含 `shot_sha256`、非空instruction和camera_motion；若mode或camera_motion为fixed/locked_off_tripod/static等，则按明确固定镜头处理。显式设计的instruction为相机权威，旧首图构图只约束起点。文件绑定和shot SHA在status、verify及compile时重核，改文件不能复用原计划。

## 实际消费

新h3配置使用新输出对应的wire：

```python
profile = {
    "native_prompt_contract": "official_multimodal/v19",
    "native_prompt_plan": {"path": ".../NATIVE_PROMPT_PLAN.json", "sha256": "..."},
}
```

`visual_h3_handoff_v3._config`同时接受v15/v19，并在实际加载entry时拒绝wire与camera合同错配。新compiler没有统一tripod/keepframing后缀，人物身份、衣物、源道具和空间连续性仍受约束。首尾图只有显式端点策略时才使用；新CLI默认仅首帧，旧v15 compile默认仍保留其原首尾行为。graph结构、原生等价性、GPU锁与实际媒体提交函数未改。

## 兼容与验证

旧无camera字段的v15计划继续走legacy Schema、校验与编译分支；F1正式黄金字符串SHA仍为 `b54f2b0c7e5aeb62037eaa525ba338c3291ee933115a965fc9c4130921986f44`。实际旧F1、F10、F11三个冻结计划逐字编译核对通过，F10原H3 PLAN也通过只读_load(current=False)。

最终5模块142项CPU回归通过，XML为data/qa/h3_camera_contract_v19_release.xml。新用例包括：规划推近/切特写可通过；未设计相机操作拒绝；明确固定拒推拉；显式机位文件不可篡改；身份/原音频和未知不重派不变；真实prepare_from_ready→_load→graph构造链同时消费v19与legacy v15（仅临时CPU假服务/输入，不提交GPU）。

这是程序合同验收，不是新v19实片验收。0真实模型调用、0生产媒体POST。没有改旧5分钟父packet、PP、任何旧原生回执、账号、服务或PAUSE。Seedance原REQUEST直交H3的对照runner独立，不经过本planner。
