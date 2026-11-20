# 真实导演失败后的结构化诊断修复

本计划承接用户“这些审核你可以直接进行，人物你可以主动接取，这些都是正常的重构修复流程的你可以自动运行的”的自主正常修复授权，先文档、子agent实施、主agent审查。当前已冻结`capability_v5`、原账本与512/513均不修改。

## 实际证据

真实518/519/520均HTTP200、完整tool_calls、用量已知，合计77407 reported tokens。三份整片导演均被排时合同拒绝，候选累计7/7、remaining0，没有逐段表演、DeepSeek制作复审或媒体。本次结果不是服务端未知，也不构成创作质量通过。

518/519的端点与档位完全相同：M004反应档需15.530303秒、仅minimum可用；M011最低也需16.663636秒，范围根本不可用。520已经修正前两处，但M006反应档需15.227273秒，当前范围只支持minimum/natural。

已验证两处诊断丢失：`EndpointContractError`保存`diagnostic`，冻结Runtime只读取`detail`；coordinator再次编译后的返修路由只传`str(exc)`。下一请求因而没有具体镜段、推导起点、时长下界或合法档位。这是确定的接口/反馈缺陷；不能据此断言补诊断后模型必然生成合格作品。

## 最小修复与分工

1. 子agent A新增纯诊断适配器与v4 coordinator子类，保留原生计划，按原输入重新计算错误；异常提供Runtime消费的`detail`，下一完整返修输入携带具体segment、来源、时长下界与可用选项。只枚举合法选项，不替模型选档、改端点、删对白或补动作。
2. 主agent审查本轮真实诊断、生成只读新请求预览、验证原冻结及账本。真实测试入口v5保持原字节；新修复不借改目录重领候选。
3. 独立审查核对原生身份、最新反馈替换、Runtime实际detail消费和超范围停止。通过后保存代码/测试/预览证据。

代码仅新增`src/content_factory/creative_endpoint_revision_feedback_v5.py`、`src/content_factory/creative_endpoint_feedback_coordinator_v5.py`及专属测试。不得修改当前冻结src/scripts文件、模拟出新服务回执、改写三份失败为通过或新增付费调用。当前候选上限仍为7，修复后的新生产验证须单独按有效范围登记，当前阶段只离线复放与预览。

## 验证范围

- 对完整已知失败提供精确源与错误字段；结果未知/截断/缺工具/未知用量不进入内容返修。
- 原生计划/原响应/原消耗不变；合法输入仍使用原确定性编译；局部表演失败不被误当端点失败。
- 整稿返修仍完整提交、全文复审；不累积重复旧全文；列出的端点与档位确实来自当前图。
- 新子类实际经原Runtime `_validate_output`留下结构化detail，并将其传入下一完整请求。
- 真实518–520仅只读复算；无新的生成、媒体、人工批准或预算重置。

当前状态：`offline_repair_reviewed_production_unverified`。主agent相关回归108项、独立复验82项通过；三份真实原生稿只读复算，新请求预览明确7/7剩余0、无新增派发。最终证据见[执行交接](CREATIVE_CAPABILITY_PRODUCTION_ADAPTER_REVIEW_20261012.md)与[独立审查报告](../data/qa/creative_capability_production_adapter_20261012/endpoint_diagnostic_repair/INDEPENDENT_ENDPOINT_DIAGNOSTIC_REVIEW.md)。

## 完成后的适用范围

真实试验已证实原Runtime的detail缺失及正常返修只传字符串。新增适配修复这两处，并补有terminal恢复首请求；普通schema/内容失败不误作端点失败。主agent只读预览使用原verify_loop_history核对实际事件与账本，而不只检查计数。无terminal历史初始化仍沿冻结helper，其重复全文未在本轮替换。新源码尚未接入新的生产freeze，不能宣称已生成合格导演、表演或制作交接。
