# S01 首图服务退出：只读结论与最小恢复设计

本次只读检查，没有改生产代码、原任务、服务参数或依赖，也没有发新 POST。

## 已确认的事实与推断

原图片 ID 为 `10fad168-10d1-4f31-81ad-225d69a086ab`。REQUEST/CLAIM/RESPONSE 和四图输入均存在；原 STATE 仍为 submitted，没有 RESULT 或原生 HISTORY。

服务守护器的原代 `457e3db6fc4a4452a6c262a04b05e818`：PROCESS 与 EXIT 的 PID 17880、创建时间完全对应，EXIT 在北京时间 2026-11-09 01:10:53 记录 returncode 3。其子进程 17904 也已不存在。stderr 最后一段从收到新 prompt、加载 flux2 VAE / AutoencoderKL，到 aimdo WDDM 查询失败与 Python Aborted；栈位于 ModelPatcherDynamic 的 restore_loaded_backups / partially_unload，经 VAEEncode 进入，未观察到本段 Klein sampler/save。

当前服务 GET `/history/<原ID>` 返回空，queue 为空。按原冻结图限定的 output scope 不存在，本地 artifacts、RESULT 与 HISTORY 也不存在。这证明**未找到保存输出**；不能据此伪造服务端 execution_interrupted 事件，更不能声称原模型结果已知成功。

本次 image CLAIM 未直接存 accepted-service 代次。归属可由“覆盖 POST 时间的守护代次 + PID/argv/listener 事件”回溯推断；更早缺 EXIT 的 5555ba... 记录，要用 457e... 启动前 families 空、port closed 的权威启动证据排除。此推断与直接原生 queue/HISTORY 证据分开记录。

建议精确分类：

- 本地服务进程退出：已知。
- 原 native provider outcome：`unknown_after_service_exit`，保留。
- 原输出：`no_saved_outputs_observed`。
- 后继资格：只有新、窄、显式的进程退出处置审批可授予；本只读审计本身不授权。

新审计见 `data/qa/h3_service_exit_image_recovery_v35_20261109/READONLY_AUDIT_R2.json`。R1 中按无 EXIT 记开区间会得到两代，已保留并在 R2 明确排除依据。

## 现有机制为何不会自动继续

`h3_service_guard_20261104.py` 只确保原服务进程恢复并保存 PROCESS/EXIT，不重派媒体。`h3_persistent_supervisor_20261103.py` 遇到已知 ID 在新服务 history/queue 丢失会停，不把网页恢复当任务恢复。

旧 `h3_restart_continuation_20261104.py` 有“保存原丢失证据，再独立后继”的设计，但严格绑定旧 run、原接受代次和四个视频角色，不能套本次图片记录或冒充其资格。

图片 jobs 只有原生 HISTORY error / execution_interrupted 才登记相应终态；缺历史仍是 unknown。v34 的 `select_anchor` 则有意只允许“原图片已按原 ID 保存后，root 明确拒绝，再选实际后继”。本次没有原图，不能通过写假的 saved/HISTORY 绕过它。

## 最小合规恢复：独立 v35 sidecar + 显式 opt-in 交接

新增一个只核本次服务中断的 sidecar verifier，不放宽 image jobs、v33 或普通 unknown 规则。它至少绑定：

1. 原 PLAN/graph/REQUEST/CLAIM/RESPONSE、ID、同一 CONTEXT_SPEC 与工作单；输入像素、模型、分辨率和 prompt 不变。
2. 原服务 PROCESS/EXIT 的 PID、create_time、非零退出码，父子身份确实已消失；旧代归属证据单独列明是否直接或回溯推断。
3. 新代身份、原 ID 的新 GET history/queue 和原 scope/local artifacts 全量输出清单。发现原输出、活跃队列、同代仍存或部分文件时停，不猜 null=0。
4. root 对此**具体 ID/工作单**的显式处置审批：原记录不再等待，但 unknown 与可能消耗保留；允许一个新原生图片后继，仍计原 8 图范围。

原 STATE、REQUEST、CLAIM、ID、未知结果全部不改，不删锁，不造 native HISTORY。sidecar 的含义是“已知服务进程终止后允许创建独立后继”，不是“原 native 已成功”或“原调用未发生”。

后继使用本轮另一个新的 still run / job ID，继续相同四图和源状态，产生实际新原生 ID。只有它真实保存且审核通过后，才交 v33 正常 native receipt 深核并生成 I2V 首图。原失败 claim 仍占 1 图，后继占第 2 图；没有新增视频或 probe 额度。

v34 需要的桥接也必须是窄的显式分支：

- 仅对绑定了该 sidecar 的原图片忽略“阻止后继派发”的 unknown 视图；raw unknown 仍显示、仍计预算，仍能查询原 ID。
- 在原 RESULT 不存在时，允许已验 service-exit selection 指向实际 saved 后继；普通 `select_anchor` 路径保持原样，metadata/任意 unknown 不适用。
- 原 CLAIM/PLAN 不变；新模块、窄桥接和 CPU 验收重新绑定到新的 launch revision。旧 launch 与旧 187 测试验收保留，不能边改源码边沿旧审批发任务。

建议 CPU 反例必须覆盖：PID 被复用、EXIT/create_time 不匹配、活进程、同一服务代、原 ID 仍在 queue/history、部分输出、不同原图/源/工作单、不同授权 projection、重复后继、原未知被误写 saved、预算未计旧 claim，以及默认 unknown 仍拒绝。另验真实 stub 保存新后继后按正常 receipt 进入视频；所有旧记录 SHA 不变。

## 本机已有的显存参数

本地 ComfyUI 已有 `--disable-dynamic-vram`。`comfy/cli_args.py` 的 `enables_dynamic_vram()` 先判断 `--enable-dynamic-vram`；`main.py` 也优先判断 enable。因此当前服务命令里的 `--enable-dynamic-vram` 必须移除，不能只追加 disable。

`--lowvram` 在动态显存开启时，help 明确说无效；关闭动态显存后会切 LOW_VRAM，text encoder 走 CPU。它可能更慢并增加主机内存压力，不能声称一定适合全部 H3 任务。

最小单因素规避候选是**移除 enable，添加 disable，先保持其余参数不变**，让 main.py 不替换 CoreModelPatcher 为 ModelPatcherDynamic，绕开这次 aimdo 动态卸载路径。需要低显存模式时再根据真实内存证据加 lowvram。`disable-nvml-pressure` 只改变动态显存压力来源，不能据此保证修好 restore_loaded_backups 中的 abort。

以上只由本地源码证实参数作用，尚未实际重启或实测其稳定性。服务 guard 严格核对完整 argv；任何参数修正都应作为单独、受控的服务配置修订，保持 8190、原 input/output/cache 路径及离线模式，不能旁启另一个服务或偷偷改变其守护计划。
