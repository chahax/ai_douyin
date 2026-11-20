# 世界、场次与人物表演：通用流程交接

2026-10-15。按用户确认，本会话完成通用流程代码与离线验证；当前样片真实重写及视频由另一会话“你可以生成视频吗”推进。本记录不把Mock稿作为可采用剧本，也不声称默认生产入口已切换。

## 已完成的行为

- 同一次完整规划产出world_frame，开头交代时代/社会环境/前史/人物关系和空间衔接。阅读版派生展示已有角色档案、开场处境及当下目标，不由显示层创作补充。
- 完整正文包含scene_contexts、每拍场次绑定、所有参与者的ensemble及action-dialogue并行许可。每拍场景必须符合原规划，沉默听者也覆盖；允许保持，不强制每句新动作、固定姓名/段数/秒数。
- 完整新世界进入原四项规划审查及writer。H/P新目录覆盖故事时间/环境和人物神情；G/C/E保原职责。精确角色/场景外键才按元数据处理，实际设定正文不豁免。
- 同源语义/物理全文双审覆盖新字段与跨拍比较，不增加单独世界审查请求。动作前提改用有原文支持的部分先后，未排明冲突写入、仅重叠或缺边不能冒用初态通过，纯保持无需强行排序。跨包兼容关系可合并，不要求理由逐字相同；相反关系拒绝。
- 显式注入新编译/渲染/审查，原生稿与编译稿分别核SHA。整稿失败携完整原稿及具体反馈，完整重生成后重建同稿双审；未知读法、未知结果及资格阻断不盲重派。
- 旧全文从writer无关上下文移除；历史同故事资格显式进入semantic审查并核原范围SHA，physical不重复旧故事。旧版本不因换目录或新世界合同而重获额度。
- 首段交接携世界、全局角色/场景/道具、当前场次/表演及合格setup；前一拍剧本背景明确不等于已验证执行。后续段仍须合格表演终态或按人工批准规则成立的服务原始尾帧资格。

## 实际验证

主agent独立CLI执行了9份预登记静态合成响应的完整链，结果offline_mock_contract_closure。输出明确synthetic_mock、0 provider/claim/media，顶层text_ready_for_director=false；内部机器判定不被冒充实际新稿。writer与semantic各保项目R01原始全文一次，逐字SHA为f007ea01a63dfb6c280b9cb3203774fe9828fe469582a03a060a82eee58f3216，原CRLF也保留。

作者最后3项完整链/整稿返修/未知停止通过105.65s；独立2项“全稿返修后双审”“缺先后/仅重叠不支持物理前提”通过51.61s；主agent另2项“未排明冲突与保持”“同故事原范围/unknown/SHA”通过16.98s。各组选项有重叠，不能合计为互不重复用例。纯world合同此前29项及主agent4项检查、渲染补充1项的源码时点在原报告分别保留。编辑期失败测试与导出路径错误未删除，不算生产失败或成功。

已核8份旧workflow/driver/full-review源码字节未改。旧627/634/635等原回执未补写成通过。A/B语义对照实际prepare因合法并行后继claim在派发前停止，0次执行，不据此比较两种表示质量；旧claim与账本不动。

证据：
- data/qa/creative_world_scene_workflow28_20261015/ROOT_FINAL_ACCEPTANCE_v1.json
- data/qa/creative_world_scene_workflow28_20261015/ROOT_CLI_HAPPY_v1.json
- data/qa/creative_world_scene_workflow28_20261015/OFFLINE_HANDOFF_v1.json（生产调用API清单）
- data/qa/creative_world_scene_context_20261015/INDEPENDENT_WORLD_WORKFLOW_REVIEW_v1.json
- data/qa/creative_full_review_v6_20261015/A_HANDOFF_v1.json（请求体量及作者分次证据）

## 入口与未接入范围

独立新接口为src/content_factory/creative_goal_context_workflow_v28.py；全文为creative_full_review_protocol_v6.py，世界为creative_world_scene_context_v1.py。纯构建器生成可核实际wire，但不发请求。当前CLI/driver只读明确合成的登记响应，不能当真实coordinator。

离线复验命令（输出必须用新文件名，不覆盖旧证据）：

```powershell
.\.venv\Scripts\python.exe scripts/run_creative_world_scene_offline_v1.py mock --scenario data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json --output data/qa/creative_world_scene_workflow28_20261015/NEW_OFFLINE_RESULT.json
```

真实生产仍须新coordinator显式接入v28、SDK/原始回执、来源鲜度、消费承接、锁内计轮和唯一claim准入；本次没有完成这些真实派发接线，没有新的模型原生合格全文/导演/实际表演/媒体。本次各模型/参数保持原分工，无服务端生成保障或创作质量通过的结论。semantic原生响应的合成体量也不证明实际模型能在输出上限内可靠返回。视频仍完全由用户人工审查。

## 保存与恢复

本次代码/测试/文档另存data/development_checkpoints/creative_world_scene_release_20261015_v1。旧入口与creative_studio_baseline_20261012等快照保留。若新内容不满意，可以停用独立v28并在独立目录恢复对应旧入口；不得覆盖生产账本、冻结回执、媒体或凭据，不因恢复重置消耗/资格。该副本是项目内增量发布，依赖现有冻结基础模块，不是独立安装包。
