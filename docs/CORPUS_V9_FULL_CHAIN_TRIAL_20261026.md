# v9 整链真实试跑：材料复审停止

用户要求“整链试试”。本轮接续既有合成《两把钥匙》三章399字符的 v9 材料，目标60秒完整剧本。没有重跑已完成分类，没有发送真实小说69章，没有改旧外发审批。

## 实际执行

- 新增5次真实调用：Qwen 4次（20,195 reported tokens），MiniMax-M3.1-Flash 1次（6,120），合计26,315。全部原生stop，pending=null。
- 前两章Qwen材料审通过；第三章首审revise，MiniMax自动返修一次，Qwen复审仍revise，按原限制停止。
- 状态needs_attention，原因material_semantic_revision_limit_reached:materials。
- 框架、本集状态快照、视觉设计、编剧、DeepSeek终审均未执行。无完整新稿、媒体、发布。不是整链验收通过。
- 运行约767.385秒，包含本地运行时加载与模型请求等待，不能当成纯模型生成耗时。
- 原任务累计8次/41,570 tokens（包括既有3次分类）；含该任务既有历史117次/1,687,441。兄弟留出实验未并入此账本。

## 主助手独立核对

原CH3-F004“林岚在昨天把黄铜钥匙交给了阿禾”标actual/earlier；F005“周远在本章当下才得知……”标actual/chapter_present。两条已分开。第三章叙述者确认过去交接，第二章也直接描写交接。

Qwen首审却把F004主体误当成“周远得知”，建议过去交接标plan/earlier或memory/earlier。这个建议缺乏原文支持，不能作为正确纠错结论。MiniMax返修后保留当前告知与获知，但增加“阿禾对前一天钥匙交接的追述是……”并标memory/earlier；该表述主体又可读作当前追述，造成新的歧义。Qwen复审指出这一点，但其解释仍夹带将过去内容称作plan的不当说法。

因此，故障不只是分类模型：独立审核会误读主体，错误建议经引文/格式检查后直接进入返修。引用存在不代表审核结论正确。需要增加审核意见针对原命题及相邻证据的有效性检查/有界裁决，并避免把审核建议中的模态标签作为必须服从的事实。不能手改候选或把机器revise改成pass绕过本轮。

## 环境及证据

初始11435未启动，预检在推理前拒绝。恢复既有D盘模型的独立隐藏Ollama服务，模型digest与冻结路由一致；没有下载、切换模型、修改自启或重启账号后台。加载等待期间最终正常进入GPU推理，没有证据证明CUDA故障。

早期一次execute因prepare尚未完成而缺续行授权文件，在START/模型派发前退出，已单独记录。成功prepare/execute均不可重跑。

证据目录：`data/corpus_production_trials/20261026_v9_full_chain/`：CONTINUATION_AUTHORIZATION、PRECHECK_NOTES、RESULT、PRIMARY_MATERIAL_REVIEW及本地运行时日志。原生请求/返回在原v9任务`original/run/cloud/`。RESULT确认全部冻结旧非状态文件SHA未变，执行锁已正常释放。此次仅新增测试与审查记录，未修改生产源码，也未宣称新增回归测试通过。
