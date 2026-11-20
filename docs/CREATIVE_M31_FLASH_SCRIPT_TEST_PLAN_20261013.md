# M3.1 Flash Preview 完整剧本生产测试

## 用户指令与范围

用户最新要求：“剧本生产换M3.1 Flash Preview然后生产个剧本看看”。这明确授权使用新模型新增一份完整原生正文测试及少量必要同源全文复审。原528第三稿3/3的失败、旧M3冻结入口和累积账本不改；新增测试不是重派旧请求或清零旧候选。先记录官方能力/实际接线，子agent开发独立适配，主agent审查后执行。未知结果/用量、截断或未决claim仍停止。当前不增加媒体或发布。

本测试使用已经保存的158去重法律视频元数据、标签关系、R01表达机制参考全文、模型525完整规划、冻结brief和初态，沿用骑手阿磊向站长老韩追问配送费并争取书面说明的故事方向。素材为2026-10-12历史采集快照，不冒充今天新采；不更改旧SOURCE_PACKET或采用旧失败正文为正式稿。需要由新模型提交完整新稿，不能手工删补或拼接。

## 已核官方能力

https://platform.minimax.cn/docs/guides/text-generation 的精确model id为 MiniMax-M3.1-Flash-Preview；暂通过M Plan/MiniMax Code订阅Key提供，支持OpenAI兼容Chat接口。思考默认开启且不能disabled，OpenAI字段 reasoning_effort，支持low/medium/high/xhigh/max，省略为max。输出上限可用 max_completion_tokens。本次显式medium，temperature=.4，max_completion_tokens=16000，非流式，SDK max_retries=0、HTTP follow_redirects=False；不加另一次付费探测。官方提供function tools；本次writer不发送未验证的强制tool_choice/strict或旧thinking字段，客户端验证出站model、完整Schema和reasoning_effort；实际凭据是否具备M Plan访问权限由这一份正式请求核验，不加付费探测。不把工具支持写成服务端强制Schema保障。

## 最小独立接线

新增单独M3.1客户端及运行入口，不改冻结旧客户端/运行器或既有.env。配置文件将本次剧本writer设为新模型；必要文本复审仍用现有DeepSeek。新请求身份、原生请求/响应字节、模型、明确结束、真实用量及完整工具提交必须核验；输出Schema仍复用原完整剧本结构，实际请求含参考全文一次及原失败稿的单句与整片双诊断。

用 creative_fresh_script_feasibility_v3 在完整正文进入复审前同时检查全部单句与全文对白下界；正常3.3字/秒、每段15秒和本批整片180秒偏好不放宽。必要条件通过不等于排时或创作质量通过。DeepSeek消费同一完整原稿、brief、原计划和标准，完整回执审查前不写text_ready。无自动内容返修或额外格式恢复请求；本次先输出新模型的一份完整原生稿及真实验收结论。

调用从528次/9951442 reported tokens承接，历史70/160未知及93117预留维持；创建新授权和新账本记录这次明确模型变更，不回写旧上限或旧freeze。复用共享派发锁防重复；任何既有未决请求阻断新派发。新测试仅writer一次、必要全文审查一次；旧格式恢复claim不重领。

## 验证与交付

先离线验证真实SDK序列化的model/reasoning_effort、没有disabled、输出上限、Schema/参考和URL身份，检查拒绝缺工具/截断/类型错误/结果未知且没有自动重发；验证旧消费承接、新一份上限及重入不派发。主agent审查新代码和实际预览，再单次生产。提交后保存完整原生全文（即使验收失败也保留并准确标记）、可复制绝对位置、响应/用量与未解决问题。代码和文档能恢复独立副本，不恢复消费或重启claim。

生产前主agent与独立子agent核查：来源完整packet按当前时间重验而非只读compact投影，DeepSeek实际请求必须绑定唯一writer原生全文；canonical已知用量526次、历史未知70/160与93117预留完整继承。新账本按阶段各1次承接，重入和源稿不一致在派发前停止。
