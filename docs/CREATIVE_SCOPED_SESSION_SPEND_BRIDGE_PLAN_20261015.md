# Session3终态消费交接计划

2026-10-15。当前Session3只消费626的一次后继，不能用更换目录重新领取626。为在本次真实运行结束后继续导演或修复，新增独立、只读的Session3消费锚；不修改已冻结Session3、旧bridge、回执或账本。

子agent实现新`creative_scoped_session_spend_anchor_v1.py`和必要离线验证，根agent审查。复用现有原始SDK、SQL TaskStore、文件哈希与typed父锚校验函数，不整份复制调度器，不伪造Session1/2版本，也不构造新的生产claim。

锚必须核实：唯一原RUN、当前终态、连续ordinal、16次与{goal_plan:3,goal_audit:4,complete_script:3,full_review:6}同一政策、原始wire/response/tool/用量/源身份、TaskStore原claim/result、实际冻结文件及snapshot、父626完整消费。已知完整合同或内容失败仍计消耗；未知用量、未返回、截断、未决claim不能伪装成已结算后继。

保留3份旧规划以及本次实际计划4的消耗，旧导演7/7、原诊断2/2和历史70/160及93117预留。实际起态/正文/审查用量分别累计，不能因新目录重新授予。最新原生规划指针只指真实原生tool对象，不把缺工具正文转换为已验收对象；机器text_ready也不写成人工或创作质量通过。

消费锚只证明已结算与来源绑定，不授予新候选、媒体或发布。下一入口必须采用唯一父锚+真实父运行双successor、新冻结及当前修复轮门。未知的原请求只查原证据，不能被本bridge重派。

当前真实运行未结束时只开发和离线测试，不能调用生产run/prepare或修改当前STATE。实际终态到达后由root调用只读builder并复核；若现有通用函数不支持新版本，应新增明确适配，不能修改旧globals或降级校验。
