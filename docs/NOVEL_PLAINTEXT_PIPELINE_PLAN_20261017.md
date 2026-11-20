# 小说正文直写与DeepSeek全文审核（2026-10-17）

## 本次指令与方向

用户在看过实际例子后明确提出：取消字面引用匹配和规定工具交稿的创作硬门，采用“minimax出内容deepseek审核通过生成”，继而要求“修改测试生产测试”。本轮据此开发新独立v3并实际用同一已获取小说验证。旧v1、production/v2、旧响应、失败、账本和停止门不改写。

新的内容主链为：真实小说正文 → MiniMax一份完整创作稿（背景、角色选择、主线及高潮分析、改编规划、完整可拍剧本） → DeepSeek对照同一正文审核整份稿 → 通过交付 / 有实质问题有界完整新稿及全文复审。业务分析步骤保留在完整稿中，不再在每个小步骤用排版合同消耗整稿返修。阅读稿以MiniMax原生Markdown/纯文本为权威，不要求双写JSON、不强制writer工具，不要求逐句原文证据或字符位置。允许对白改写、场景合并、支线压缩，主线动机与关键因果交语义审核。

## 分工与API

1. `src/content_factory/novel_plaintext_contracts_v3.py`：导出 `VERSION, WRITER_PROMPT, REVIEW_PROMPT, REVIEW_SCHEMA, REVIEW_DIMENSIONS, response_evidence(record, protocol_role) -> (errors:list[str], known_total:int|None, native_text:str|None), validate_review(value) -> list[dict]`。请求role/model/原生正文/结束/usage核对保留。writer普通正文及唯一可用工具正文均可被保留，不强制工具；不把reasoning当正文。DeepSeek正常正文JSON/fenced JSON可解析，不使用工具，审核不回传hash；程序绑定同稿身份。writer内容不因引文/段落/引号而拒绝，完整性与质量由DeepSeek核对。
2. `src/content_factory/novel_plaintext_pipeline_v3.py`：导出 `prepare(run_dir, *, source_path=None, acquisition_receipt=None, title=None, book_id=None, scope=None, registry_dir=None, max_calls=20, max_total_tokens=500000, max_revisions=2, authorization=None)`, `preview(run_dir)`, `inspect(run_dir)`, `execute(run_dir, *, clients=None)`。新任务可用旧_source等纯函数和相同真实CreativeRoleClients（writer structured_schema=None）；不得修改旧模块或用全局monkeypatch。prepare/preview/inspect零模型；锁、同源登记、不可变请求/原生响应、state checkpoint、已收响应恢复、缺用量/截断停止、全稿与复审双绑定、完成文件复验与原预算门必需。
3. `scripts/run_novel_plaintext_v3.py`及网页入口接线：fresh prepare/preview/execute/inspect。网页默认新任务走v3，已有v1/v2任务按原版本只读或原恢复，不静默迁移；实际MiniMax输入不含forced tool，展示完整原生文本和DeepSeek复审结果，不把text_ready_for_director写成人工采用或视频通过。source采集桥接保持已有实现。

## 真实旧来源续行授权合同

本次真实源为BookID7353289642218638361、已保存第1章。旧小说共14次/228513 known reported tokens（原11/180079，加production/v2的3/48434）。原总上限20次/500000保留，所以新增最多6次/271487；本次新“完整稿→语义复审”初稿加最多2轮完整内容返修，共最多6次请求。旧两轮分析格式返修及旧故事候选历史保留，不能写成从未发生；本次修订质量策略来自当前明确新指令，媒体/发布均无授权。

授权JSON schema=`novel_plaintext_authorization/v3`，必含 `user_instruction="修改测试生产测试"`, `run_dir`, `acquisition_receipt`, `book_id`, `source_identity={full_source_sha256,excerpt_sha256,binding_id}`, `parent_checkpoint={path,sha256,bytes}`（production/v2 FINAL_ACCEPTANCE_CHECKPOINT.json），`parent_run`，`history_bindings`（旧原11响应、production/v2新3份REQUEST/RESPONSE、父state/BINDING/ANCHOR/AUTH/checkpoint及其他必要来源/registry绑定），`legacy_totals={calls_started:14,reported_tokens:228513}`, `original_budget={max_calls:20,max_total_tokens:500000}`, `new_budget={max_calls:6,max_total_tokens:271487,max_revisions:2}`, `automatic_media_submit:false`。scope=null按既有实际1章范围。主agent创建本轮实际AUTH，运行器须审计旧14份原生usage/结束/响应身份，并确认父pending_call=3是已收到stop且REQUIRED_TOOL_MISSING，不是未知在途；只允许精确授权的历史来源链。

生产续行的唯一claim必须进入实际派发门。在现有全局小说登记旁新增独占continuation claim，指明原canonical claim/parent/run/source/auth，原登记保持字节不变；同一parent/来源不能换目录或auth重领。每次派发复验AUTH、父快照和所有旧原生响应，累计消耗不得归零。其他历史/未知停点不得被授权过滤。旧任务不重发，新版不把旧失败稿追认为通过。

## 内容及审核标准

MiniMax完整稿先交代时代/日常环境、空间前情、人物关系处境目标；说明所选主线、高潮、起止范围、修改理由；再输出逐场时间地点、在场人物动作神情视线、自然对白、刺激与反应、段首段尾和明确结尾。只改编已取得章节，不依据书名补写未读后续。用少量必要人物，可合理改写对白/合并场景；不凭空把缺席人物放入现在现场，不编出原文未证明的年龄生日/人物关系等事实。预计时长作为创作安排，算术/排版不交给模型回传身份的强合同，不为凑时长增加静候。

DeepSeek审核完整正文+完整稿，显式给出 verdict=pass|revise、whole_text_reviewed=true、九维具体checks及severity/具体位置/证据/建议。维度为 mainline_and_motivation, causality, character_identity, space_gaze_action, emotion_windows, dialogue_naturality, shootability, completeness, timing。pass仅当九维全部完成且无major/blocking，不允许未填检查项默认通过。review格式不可读、响应不完整/未知则技术停止，不重写内容来迎合格式；minor可记录后交付。对白不逐字等于原文、引用省略空行/引号、没有工具不构成内容失败。程序审核绑定覆盖真实请求/源/稿件SHA，模型不猜hash。

## 验证与交付

先用已保存真实失败响应离线回放证明：省空行/改引号不再触发内容重写；普通正文无tool仍能交DeepSeek；未完整正文/虚构后续由语义审核拒绝；截断/usage未知仍停止；旧ledger/claim/产物篡改无派发，已收请求重入不重复。主agent审查子agent代码和真实UI/CLI接线后派发本轮最多6次真实调用。

交付原生`SCREENPLAY.md`（完整创作包）、`FULL_TEXT_REVIEW.json`、`DIRECTOR_HANDOFF.json`、`OUTPUT_MANIFEST.json`及完整原生回执和累计账本，完成状态`text_ready_for_director, human_approved=false`。不自动生成人物图、视频或发布。真实失败仍如实保留，不以离线测试替代生产验收。
