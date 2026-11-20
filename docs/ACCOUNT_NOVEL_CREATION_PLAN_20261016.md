# 账号选题到目标小说完整创作开发方案

日期：2026-10-16。范围来自本轮用户“开始开发这段流程先完成：账号选题 → 目标小说完整创作”。

## 目标与边界

将已有小说推广账号的 ContentOpportunity 接入目标小说选择、原文绑定和现有完整创作工作流，提供实际可执行的独立入口及账号机会页面入口。交付完整剧本、导演分镜、原文与审查证据或明确停点，不把占位 A/B 简报当成完整稿。

本轮开发和离线验证不派发真实模型、媒体、推广申请、回填或发布，不修改旧任务、冻结、失败计数和账本。实际生成入口可调用既有 MiniMax 创作/DeepSeek 审查配置并沿用原始回执、逻辑任务登记、预算、未知结果停止和视频禁派发边界。真实服务及创作质量须另有实际结果，不能用夹具通过代替。

## 已核实断点

- `NovelOpportunityScriptStrategy` 产出含原文占位符的推广简报，不是完整小说改编稿。
- `PreVideoScriptService.generate` 明确仅允许法律领域；小说不能借该入口绕过限制。
- 小说完整创作已有 `CreativeWorkflow`、`load_materials(source_driver='novel')`，当前 CLI 要用户自行填写正文路径，未接账号机会和书籍选择。
- 本地番茄素材目录已有 meta.json、material.txt 和章节。下载/入库不等于授权；只有已绑定明确文本使用依据的候选才能自动进入创作。正文范围不代表整书。
- 机会页面只有 A/B 简报按钮；新小说完整创作入口必须与旧功能区分。

## 实现分工

1. 子 agent A：新增 `src/content_factory/account_novel_selection_v1.py` 和独立测试。只负责本地候选发现、小说账号/机会核对、授权正文身份、匹配排行与目标选择。不得改旧模块和数据。
2. 子 agent B：新增 `src/content_factory/account_novel_creation_v1.py` 和独立测试。只负责选择结果冻结、创作简报/材料、真实工作流适配、预览/执行/恢复与产物验收。复用现有完整创作器，不能另写假成功执行器。
3. 子 agent C：新增 CLI、网页创作面板及接口测试，所有读写与执行复用同一模块。
4. 主 agent：审查实际调用链，接通当前选题页的小说分支，执行跨模块故障验证，保存验收交接及导航。选择模块完成后，其子 agent另作只读独立审查，问题交实现者修复。

## 模块接口约定

选择模块暴露：

```python
discover_books(books_root: Path) -> list[dict]
select_target_novel(profile, opportunity, candidates, *, now=None, target_book_id=None) -> dict
```

候选使用 `book_id`, `book_name`, `metadata_path`, `material_path`, `authorization`。自动发现读取既有 meta/material 和可选 `text_authorization.json`。路径相对各自素材目录解析；不静默生成真实授权。授权绑定 `book_id`, `source_sha256`（原文件字节 SHA256）, `allow_text_adaptation: true`, `allow_model_input: true`, `reference`（真实依据文本/位置）。这仅记录既有依据，不代表平台推广申请生效。

`select_target_novel` 返回 `schema: account_novel_selection/v1`，`account` 与 `opportunity` 完整快照、`rankings`（每本依据/排除原因）、`selected_book`（上述字段、正文和元数据文件 SHA256、章节与获取范围），以及 `status: selected | needs_materials | no_matching_book`。错误账号、非小说领域、策略/版本不一致、拒绝/过期/未来机会一律抛 ValueError，不让显式选书绕过。未选书时不能调用模型；无匹配不能默认取第一本。相同书ID冲突、授权或文件身份不符须拒绝该候选。

创作模块暴露：

```python
prepare_account_novel_run(profile, opportunity, candidates, run_dir, *, now=None,
                          target_book_id=None, **options) -> dict
preview_account_novel_run(run_dir, *, now=None) -> dict
execute_account_novel_run(run_dir, *, now=None, runner=None) -> dict
inspect_account_novel_run(run_dir) -> dict
```

根目录保存 `BINDING.json`、`SELECTION.json`、冻结的账号/机会/原文/元数据/授权和 `creative_brief.json`；完整创作器只使用子目录 `creative/`。新接口用现有默认预算、默认最多两轮内容返修并冻结；恢复不能变预算/来源。`runner` 仅为测试注入，真实默认必须确实调用现有完整创作入口。模块实现可协商小幅调整，但在完成交接中写明。

账号与机会是推广目标/表达依据，小说原文仍是人物、剧情和对白唯一来源。完整世界框架、人物关系与目标、空间前情、动作对白/表情视线与反应、因果及段首尾状态写进创作要求；不复制热门视频剧情。书名与推广CTA明确来自目标书和账号，不能为了引导阅读伪造原文情节。

## 执行与恢复

- prepare/preview/inspect 只本地；页面渲染、选书和预览不会隐式调用模型。
- 入口冻结 account_uuid/key/profile_version、策略版本、opportunity_id/有效期、book_id、授权、正文/元数据 SHA256 和实际预算/模型协议。执行前重新核对，输入变化不得静默覆盖。
- 同一创作意图沿用既有 logical task registry，重复点击不能换目录领预算。执行锁覆盖实际派发。未知响应、用量未知或遗留在途锁保存停点，不自动重派。
- 不手写人工批准、媒体通过或消耗；根状态映射必须保留实际底层状态。完整产物成功也只是文本完成/待相应复核，视频/推广/发布始终未执行。
- 独立新入口不迁移默认 v23 或旧法律任务的冻结。2026-10-15 法律计数运行仍保留原范围，本开发不以新目录重领旧故事预算。

## 验收

覆盖正常自动选书、明确指定书、无候选/不匹配、缺少授权/原文、同名不同书ID、冲突ID、错账号/策略/版本、过期/未来/拒绝机会、正文/授权/元数据篡改、完整实际载荷、重复prepare/执行、预算继承、真实底层失败/未知/待复核状态以及产物缺失。CLI 到工作流适配须有跨模块离线运行证据；不能仅测试 argv 或 mock 返回 completed。

开发完成后保存 `ACCOUNT_NOVEL_CREATION_REVIEW_20261016.md`，列实际能力、入口、测试、真实验证未完成范围和交付路径。
