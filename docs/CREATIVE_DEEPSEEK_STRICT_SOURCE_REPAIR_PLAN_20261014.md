# 605完整但非法工具JSON：独立协议修复计划

2026-10-14，round_18已停止在605，604完整规划结构通过，605 HTTP200、finish_reason=tool_calls、响应体完整、原始用量38266已知，但arguments有末尾额外一个右花括号，严格JSON解析报Extra data。原605保持interface_rejected，不删字符、不转换为来源报告、不重跑原RUN_CLAIM。

本轮核查DeepSeek官方Tool Calls与Chat Completions文档（https://api-docs.deepseek.com/guides/tool_calls/、https://api-docs.deepseek.com/api/create-chat-completion/）。普通工具模式不保证合法arguments；严格工具模式需要官方/beta端点及function.strict=true。支持anyOf；所有object属性必须required且additionalProperties=false；minLength/maxLength、minItems/maxItems不支持。这是当前普通/v1、strict=false接口的已验证设计差别，不证明新接口已实测。

最小新方案：模型仍deepseek-flash、非思考、指定原工具名；独立新严格适配器及兼容Schema编译器。服务Schema仅做等价ref展开、互斥kind分支oneOf转anyOf、字符串const转单值enum，并剥离官方不支持的长度/数组数量限制；本地仍使用完整原合同验收，不放宽kind、法律关系、来源身份或所有目录。新请求须分别记录原合同SHA和服务Schema SHA，真实wire比对绑定端点与strict，SDK重试0。MiniMax创作及旧客户端不变。

先离线检查未知schema关键字、循环ref、非互斥oneOf、缺required、endpoint漂移、单次HTTP、非法JSON、未知/截断、身份与账本故障。真实生产前冻结新的客户端/profile/请求，首轮仅一次独立DeepSeek来源审查；不是运输重试，也不是将605修补后录入。该完整新报告通过后才进入原生情绪审查、开场与完整正文及同源全文复审。

新入口只能承接明确闭合605及完整604原生身份，精确验证原非法arguments、响应体、结束、用量、原请求/源身份。不得把605计入内容通过；原601 PENDING与70/160历史未知保留。继承605次/12148396 reported tokens/603 known和93117预留；round18规划used26/max27剩余1保持关闭。使用604作本轮待审完整规划不增加规划次数；内容返修仍模型提交完整新规划，有界至多2份新规划与正文初稿加2整稿返修。阶段边界不是重置累计消耗。

开发由子agent按模块独立实施，主agent审真实接线、失败用例、旧冻结和官方支持；原来源v2不改。单次严格来源结果失败或未知须保存并停止该独立诊断，不盲派或默认迁移。新接口成功与机器文本合格、用户审美采用、视频通过分开。没有媒体或发布。

实施核实补充：原source2的judgment复用含两条allOf/if/then的已冻结结构规则。只允许精确匹配该完整已知结构，将pass/fail/unknown转换为互斥status的anyOf分支；pass空revision保留，fail非空按官方pattern表达或在manifest明确服务更弱并留本地原规则。其他allOf/if不静默删除。该适配首先只用于source v2，focused/drama/全文审查沿用普通原客户端，不能冒称所有审查已接strict。实际expanded服务Schema及整份wire字节单独计算，不能用旧logical Schema尺寸代替。新增审查调用每运行仍最多6，达到上限先停止，不因分模块而扩大次数。

实际只读预览：604来源合同展开后的服务Schema402758 UTF-8 bytes，compact整份wire484136 bytes，明显大于原逻辑300000字节上界。本轮为独立严格source请求单设600000实际wire字节上界，同时保留原logical阶段上界；SDK真正发送的序列化raw也要在发送前查上界。官方最新model列表（https://api-docs.deepseek.com/api/list-models/）与价格页列deepseek-flash上下文1048576 tokens、最大输出393216；本次仍16000输出，不把字节量当真实token消费估计。是否接受这份大Schema仍须真实端点验收，失败不自动重派。
