# M3.1 Flash Preview 实际完整剧本测试与交接

用户指令：“剧本生产换M3.1 Flash Preview然后生产个剧本看看”。独立完整剧本入口已实际换为 `MiniMax-M3.1-Flash-Preview`；旧M3/v23及其冻结入口没有静默迁移。本次只有一份完整新稿及一次必要DeepSeek同稿全文审查，无导演、表演、媒体或发布请求。旧528稿3/3与旧账本不改。

## 实际产物

- 完整六拍原稿：《空白处那一行》，`data/production_trials/m31_flash_script_test_20261013/round_01/COMPLETE_SCRIPT_FOR_REVIEW.md`。
- 原生全文：同目录 `NATIVE_SCRIPT.json`；直接来自529工具结果，仅确定性编译为阅读版，没有人工删补、拼接。
- 新模型配置：`config/creative_script_model_profile_m31_flash_v1.json`。
- 可执行独立入口：`scripts/run_m31_flash_script_test_v1.py`。本批已经有RUN_CLAIM，只能查原回执，不能再次执行派发或重启。

故事是骑手阿磊找站长老韩追问两个月配送工资的差额。老韩先用算法过渡、平台统一调价回应，随后只提供当月汇总工资条。阿磊不接受只给汇总，要求把跨日单与夜间单价的说明写在纸上并盖章。结尾老韩放下听筒、翻开文件夹后沉默，书面说明仍未得到；不是已经追回差额，也不是法律争议已经解决。

## 真实接口及来源验证

529：HTTP200，请求和返回均为精确模型 `MiniMax-M3.1-Flash-Preview`，`finish_reason=tool_calls`，唯一指定工具，原始完整body、实际SDK请求和用量已保存。实际端点为 `https://api.minimax.cn/v1/chat/completions`；reasoning_effort=medium，max_completion_tokens=16000，没有发送旧thinking=disabled、tool_choice或strict保障字段。完整R01参考2313字实际进入请求恰一次；brief、525原生规划的编译结果、原法律来源/标准/偏好保持绑定。

529用量：prompt28772/completion3473/total32245 reported tokens。结构及单句、整片对白下界合同通过：21句、361个计数字符，最长22字；按3.3字/秒仅对白估算109.39秒，距180秒偏好还剩70.61秒。动作、反应、切镜和实际语速尚未排时；这一结果只证明必要条件通过，不能证明整片实际可制作或创作质量通过。原528稿为644字、195.15秒对白下界；本次模型及双诊断同时改变，不能用这一单例断言差异全部由模型造成。

530：DeepSeek-flash，HTTP200，明确tool_calls结束，完整工具原稿、同稿全文及原始body已保存；prompt33022/completion8903/total41925 reported tokens。实际请求的full_current_script及其SHA与529原生完整稿确定性编译结果一致。

## 审查拒绝的已验证原因

530返回 `dialogue_checks=[]`，缺少全部21个必须检查的dialogue_ref。本地validate_review要求完整覆盖21句，以 `duplicate or incomplete dialogue_ref` 拒绝；本次具体是遗漏，不是重复、截断、缺工具、结果未知或用量未知。

实际请求Schema的dialogue_checks设minItems=0且没有maxItems，允许空数组；530原稿通过JSON Schema，但不符合更严格的本地完整合同。原因同时包含审查模型漏覆盖与出站Schema/本地合同不一致，不能只归因“服务违反Schema”。其它已填项的pass也不能代替未完成的21句审查。没有人工补检查表、修改服务原稿、把审查拒绝改成通过，亦没有额外重派。

## 主agent文本阅读发现

1. B2已把记录本“合上放回桌沿”，B3又写伸手合本，之间没有重新打开；B4的阻止合本反应因此缺少明确前提。这是原文可直接验证的状态链冲突。
2. B5写“把工资条原样放回桌沿，没有拿起来”，取放动作前提矛盾。
3. B5“眼睛没真的拨出去”把眼睛和拨号动作错误搭配，表演指令不清。冻结brief写明阿磊初态站立，正文没有落座动作，B6却从折叠椅起身，已验证缺少动作前提，不能假定对白“坐下说”等于实际落座。
4. 结尾继续沿用525已经冻结的沉默悬置，而不是给出实际书面回应。对白比528更短，但专业表演、情绪释放和结尾质量没有因此自动通过；DeepSeek已填的factual_physical=pass漏掉了上述问题。

当前真实状态：`full_review_not_accepted_no_retry`。已有完整文本，可供用户阅读；未成为text_ready_for_director、用户采用或最终可制作稿。本次没有制作交接或新视频。

独立子agent进一步核对：530使用末拍翻开文件夹的E0032支持起态检查，而规则要求正文最早出现前核起态；其制作项又避开上述取放与落座缺陷。审查漏检有实际证据，不是仅凭文风不喜欢作出的判断。新SQL两个attempt状态分别completed/content_rejected，请求、原native output、raw body SHA及用量均与回执匹配；TEST_FREEZE全部成员复核未变，worker已结束。

## 离线验证、消费与后续范围

53项SDK MockTransport及14项运行器故障测试通过；主agent分别复验一致，67为去重用例数量，不把复验重复相加。覆盖精确出站、缺工具/截断/模型错/未知用量停止、同稿审查、次数门、重入、旧消费承接及过期来源。第一次主agent测试因为Windows默认TEMP的ACL导致fixture错误，保留XML；指定工作区独立临时目录后53项通过，不是接口或模型失败。离线通过不代表本次创作质量通过。

本次新增529、530两次，74170 reported tokens；承接至累计530次/10025612 reported tokens，已知用量528次，历史未知70/160及93117预留保留，本次新增未知为0。旧CALL_LEDGER SHA仍为 `116b197d94b57040c62af4d516669d8729caec6f3f4f4e41bedf124c4ff1b405`；没有清零、重领格式恢复、SDK自动重试或媒体调用。

下一轮应先在独立新合同中让审查Schema与本地覆盖要求一致（每句dialogue_ref必须且仅出现一次），再加强跨动作状态校验和原生整稿返修诊断。当前冻结入口与已耗尽的一稿/一审范围不能直接改写重跑。M3.1实际可调用已确认；统一主题/源规划/导演等其它入口仍须独立适配和验收，不把这一稿接线写成全平台迁移完成。

开发前v7副本与旧完整快照仍可恢复；恢复采用独立目录或旧入口，不覆盖账本、冻结回执、原生媒体或凭据，不恢复消费/重启已提交请求。如果后续不满意，可退回这些代码和文档基线。
