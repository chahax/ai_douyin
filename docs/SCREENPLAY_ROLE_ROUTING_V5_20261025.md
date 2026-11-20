# 按任务分配模型的剧本流程（2026-10-25）

用户要求按“拆分职责、不同模型分别使用、再整合”的方向开发测试。本版是独立实验入口，不修改原账号服务或原剧本任务，不把旧失败改成通过，不进入媒体生成。

## 已实现的职责链

`来源整理 → 独立来源复核 → 本集简报 → 情节/对白节点 → 程序分配时长 → 表演摄影 → 自然全稿整合 → 独立全文审查`

程序分配时间不需要模型，其余七个角色各有独立模型配置。原先固定的writer/director并未被覆盖；新入口明确使用 `screenplay_roles/v5.3-experimental`。旧v5/v5.1/v5.2实验保留，不用新执行器接着运行旧准备记录。

| 角色 | 输入与职责 | 校验 |
| --- | --- | --- |
| facts | 本集意图、冻结原文；人物与事实整理 | 角色/事实ID唯一，来源段落ID存在，原文章节SHA一致 |
| source_review | 原文及原生事实表，独立复核每条断言 | 人物与事实逐项覆盖；不支持则交回facts修改一次，再完整复核 |
| brief | 原文、已复核资料、本集目标 | 保留本集起点/终点/范围、角色、必须交代的事实、来源编号 |
| outline | 本集简报、原文、事实 | 台词说听者均须在场，必需事实覆盖，角色不能越出简报；按对白和串行动作预算 |
| staging | 已分配时间的节点与原文 | 所有节点一次且顺序覆盖，补表演、视线、环境光线和镜头 |
| integrate | 同源资料、节点、表演设计 | 写自然完整稿；保留每段时间、对白和说话人；无引号台词或新增未统计角色行直接拦截 |
| review | 原文、本集简报、最终稿，不接收前一审核意见 | 忠实性、因果、人物道具、表演、节奏五项覆盖；问题必须对应稿内原句、节点与来源编号 |

“结构通过”只表示上述程序检查通过，不等于引用真的支持结论，也不等于内容质量合格。世界观、人物关系等仍需语义复核。模型自评通过后的状态是 `machine_review_passed / awaiting_independent_acceptance`，不是自动生产验收。

## 按责任返修和证据

- 格式/引用/节点失约：仅返修当前角色一次，完整原输出与拒绝原因保持。
- 来源语义错误：退回facts，复核后才能进入brief；最多一次来源修订，不循环刷调用。
- 全文语义错误：根据审核issue.owner回到最早负责的环节，作废其后结果并重新生成。先前原稿、原审核、哈希和无效化列表单独保留。
- 原生截断、未知用量、网络超时不当作普通内容返修。未知保持原调用ID；已确认截断保存原生回执并停止。
- 输入、模型路由、模型权重digest、输出模式、来源及每次原生响应单独保存。冻结配置或来源变化、同模型标签换权重均拒绝继续。
- 本版自然整合严格保留outline阶段对白，因此当前混合配置只测试MiniMax的全稿整合，不足以单独证明它的对白创作优势。

本机采用Ollama原生JSON Schema；动态约束允许的检查ID、角色ID和节点ID，避免生成不存在的WORLD等检查项。云端沿项目已有验证适配器：MiniMax仅自然整合，DeepSeek处理JSON角色；程序仍独立校验，不假装两种接口具有完全相同的解码约束。

## 模型路由与评测

本机配置默认Qwen3.5 9B；来源复核/全文审查使用思考模式，其余非思考模式。可逐角色配置provider、model、endpoint、thinking、输出上限、温度及本机上下文/seed。参数和模型digest在prepare时冻结。

混合候选配置：Qwen整理事实、规划节点、设计表演；DeepSeek复核来源、编制简报、审查全文；MiniMax自然整合。它是待验证配置，不是“最佳模型组合”的结论。

`benchmark`从真实原调用复制完全相同的角色输入，换一个模型只运行该步骤。`report`按任务、模型和思考模式统计次数、耗时、输入输出tokens及结构通过率，列出相同输入的对照。默认没有质量排名，不把格式得分当内容得分。

`evaluate`另外保存助手对来源的独立核对或人工审核，必须引用实际输出原句和存在的来源ID；原响应不改。所有评价绑定响应及来源SHA，不覆盖原模型pass/revise。评测结果没有被自动提升为生产默认路由。

## 使用入口

工作目录 `D:\IT\ai_douyin`，Python为项目`.venv/Scripts/python.exe`。

```powershell
# 查看可编辑的完整角色配置，不派发模型。
.venv/Scripts/python.exe scripts/run_screenplay_roles.py routes --profile local
.venv/Scripts/python.exe scripts/run_screenplay_roles.py routes --profile hybrid

# 新实验：从既有原生编剧请求复用已取得的原文。新目录必须不存在。
.venv/Scripts/python.exe scripts/run_screenplay_roles.py prepare --run data/screenplay_role_trials/NEW_RUN --source-request ORIGINAL_CALL.json --episode "本集事件及关系变化" --user-statement "本次授权说明"
.venv/Scripts/python.exe scripts/run_screenplay_roles.py execute --run data/screenplay_role_trials/NEW_RUN

# 同一道题换模型，只运行原call对应的一个环节。
.venv/Scripts/python.exe scripts/run_screenplay_roles.py benchmark --reference-run ORIGINAL_RUN --call-number 1 --run NEW_COMPARISON --model qwen2.5:7b --endpoint http://127.0.0.1:11434 --user-statement "同题模型比较"

.venv/Scripts/python.exe scripts/run_screenplay_roles.py report --runs ORIGINAL_RUN NEW_COMPARISON
```

`--routes`可读取自定义JSON，默认仅本机；混合准备需要显式`--profile hybrid --allow-cloud`及新授权说明。新实验默认最多18次总调用，协议返修和语义返修都计入，不借用旧已结束云任务预算。已有未知请求、审批阻塞、已结束实验不能通过换参数重跑原ID。

## 本次实测及限制

1. `20261025_school_v5`：4次本机调用；发现来源表错误，后续节点越出简报在场角色，首次及返修均被拦。未产出完整稿。
2. `20261025_school_v51`：3次本机调用；来源复核额外生成WORLD检查项，修订后仍覆盖不符，保存失败。随后增加动态编号约束，未回写该记录。
3. `20261025_facts_qwen25`：与v5.1第一步相同输入，Qwen2.5 7B约31.4秒，结构通过，但把叶西决写成“三哥”，并大量堆列引用；Qwen3.5同题约23.03秒，写成“老四”。两者均不能独立作为可靠事实来源。样本数为1，不做普遍排名。
4. `20261025_school_local_v52`：4次本机调用。动态约束使第一次来源复核按合同完成，识别无关支线与未确认排行，自动交facts修订；第二次来源复核达到8192输出上限，已知截断停止，pending=null。未进入编剧，没有通过稿。复核仍漏看部分复合断言，不能说来源质量问题已解决。
5. 钥匙交接留出样本使用独立合成原文，明确不是平台小说，也不是助手代写的交付剧本。v5.2实测5次在节点阶段失败，发现动态schema共享IDS引用，使cast允许值被fact_ids的F编号覆盖。这是新增代码缺陷，不应归因模型。v5.3按属性分别深拷贝，新增人物/事实/说话人枚举隔离用例后重新实测，旧5次原生失败与消耗保留。v5.3实测7次已通过节点及分镜，但整合稿/返修均将台词嵌入段落、引入带引号音效，校验拒绝；未进入全文审查。最后整合返修去掉失败全文，改用上游原生对白排版对照，在独立 `20261025_holdout_integrate_repair` 做定向实测，结果单列，不回写原失败。
6. 混合实验 `20261025_school_hybrid_v52` 已完成准备，执行前被自动审批拒绝，尚未产生任何云端调用。审批认为本次具体第5—7章外发至DeepSeek/MiniMax及最多18次调用范围需明确授权。修复代码后另存 `20261025_school_hybrid_v53` 准备方案，继承 `APPROVAL_REQUIRED.json` 阻塞，两份均0调用；没有再次尝试执行。需批准的是v5.3这份具体方案，不重新执行旧版。

当前输入裁剪为第5—7章，其中没有确认幼弟具体排行的原句；这一缺口本应使模型省略排行，而非补造。此前更完整资料有幼弟排行证据。后续来源检索必须保留角色关系的必要支持段，不能只按事件发生章节截取就声称上下文完整。

云端真实分工与最终路由优劣尚未验证。账号/视频后台未部署此实验入口，原v4仍保持。代码回归、模型实际执行、结构合格和独立内容验收分别记录。

最后定向整合返修实际2次，仍不符合独立对白行要求，按已知失败停止，未派发全文审查；去掉失败全文没有单独解决本机模型遵循格式的问题。所有本轮实验均无未决模型调用。共26次本机请求，输入156734 tokens、输出60941 tokens（含思考）；0次云端、0媒体、0发布。不同版本、重复同题和代码缺陷造成的失败均保留，不能把26次当成26个独立故事样本。

实现：`src/content_factory/screenplay_roles_v5.py`、`screenplay_role_runner_v5.py`、`scripts/run_screenplay_roles.py`；测试：`tests/test_screenplay_roles_v5.py`。最终58项新旧相关用例通过，JUnit为 `data/qa/role_v53_acceptance_20261025.xml`。覆盖动态schema原生请求、按模型分工、责任返修、未知/截断、源SHA、不可测对白、旧v4/corpus及原实验工具回归。证据根：`data/screenplay_role_trials`。本轮最终测试与用量见 `DEVELOPMENT_ACCEPTANCE_20261025.json`；按任务对照为 `MODEL_TASK_REPORT_20261025.json`。
