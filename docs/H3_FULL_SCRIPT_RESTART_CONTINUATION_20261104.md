# 完整稿 H3 跨服务接续

独立运行根 h3_six_children_full_script_recovery_20261104。119 段内容、种子、参考图和帧数继承原冻结清单。前 37 段用原本地成功 history、图、receipt 以及交付和四种原生输出的 SHA256 核实；跨服务启动后无需对旧进程发起 live history 查询。后续分段单独保存尝试，唯一输出目录，原 38 段记录保留。每个分段最多有一个替代尝试。

提交前保存原请求、输入和服务进程代，取得 ID 后用 queue 或 history 将 ID 和图绑定到该代。跨重启仅在原 ID 已知、旧代死亡、新代 Comfy 身份和新启动回执可核、原 ID 已从新 history 和队列消失、全局队列空闲后准许替代。先核对原目录；已有完整输出时优先就地验图元数据、帧数和音轨后收存，证据歧义则停。服务仍为同代、无 ID 的 claim、已知失败、缺失身份、重复替代、输入改变均不盲派。新任务持原完整运行锁，同时持新根运行锁。替代只发生于本地已有授权的剧本和模型，原 ID 的未知结果留审计。

新计划任务使用项目 pythonw 常驻，匹配绝对 execute --run 参数的进程家族。旧调度监护停用且旧执行器消失后才可切换。新运行断开后保留原 ID 继续检查，服务无响应仅等待。完成后仍以 119 段回执和完整片校验确认。完成只指技术收存；分段声画内容仍待人工审片。

## 2026-11-04 14:39 实际启动

用户明确要求启动停住的批次。prepare 实跑通过（PLAN SHA 70654cfbf9ed9e24b66e7e4ba40781306f6215f2d17e3dc9c46109cb5f81f76f），核验前 37 段 receipt/交付/四种原生输出与 F0038 原代绑定。旧 ID 5119a505-c86a-4847-b1eb-33259a100e95 已在新 history/queue 消失，loss/F0038/ORIGINAL_LOSS.json 记录 provider_outcome=unknown_after_service_exit，未声称原结果成功。

旧 AI_Douyin_H3_FullScript_Ensure 已停用；新任务 AI_Douyin_H3_FullScript_Continuation（pythonw supervise，每分钟+登录、IgnoreNew、PT0S）已注册启动，TASK_DEPLOYMENT_VERIFIED.json 记录命令、用户、XML SHA。新代 457e3db6fc4a4452a6c262a04b05e818。

F0038 唯一替代已提交 cb8dbb6f-cb93-4d60-a700-497a912b09bb（输出前缀 six_children_recovery_20261104/A1/F0038），原代失败记录与半成品证据保留；后续 F0039—F0119 沿用冻结清单串行。当前根 STATE=running/37 of 119，监护心跳与 WAIT 正常。新模块尚无独立自动化测试目录，本次依据代码审阅与 prepare 实跑放行，未冒称完整测试。
