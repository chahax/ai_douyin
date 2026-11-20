# 本地视觉 worker 启动链修复（2026-11-06）

原 v6 target appearance worker 没有进入 Python 脚本：venv launcher 长时间消耗用户态 CPU，其 base Python 子进程保持 stopped、CPU 为 0，仅映射程序和 ntdll。原 caller 900 秒超时后，原 wrapper、子进程、主 caller 及外层 launcher 均已确认退出。原 unknown、CLAIM、REQUEST 和空日志保留，未重派或改成已知成功。

## 原生无模型对照

四例使用同样的私有环境、`CREATE_NO_WINDOW` 和独立新 ID；TEMP/TMP 长 271 字符，HF 路径长 272—280 字符。

| 启动方式 | REQUEST 路径 | 结果 |
|---|---:|---|
| `.venv/Scripts/python.exe` redirector | 121 字符 | 15 秒超时，launcher 忙、base 子进程暂停 |
| 同上 | 279 字符 | 同样超时 |
| 直接 base exe，配 `__PYVENV_LAUNCHER__` | 121 字符 | 约 0.11 秒成功 |
| 同上 | 279 字符 | 约 0.11 秒成功 |

每个超时只收尾本例已记录创建时间的进程家族，并确认退出，没有处理个人浏览器、服务或原未知任务。实际 direct 子进程为 `C:/Python314/python.exe`，但 `sys.executable`、prefix、site-packages 以及 torch/transformers/bitsandbytes 的 `find_spec` 均正确指向项目 venv；这些模型库没有被导入。

证据为 `data/qa/residence_runtime_start_20261106/native_cases/SUMMARY.json`。系统长路径开关为 1，同环境能够只读打开原 279 字符请求，没有观察到 WinError 206/5。因此不能简单把 REQUEST 超过 260 字符认定为根因。已稳定复现的是带该私有环境的 venv 转发启动链异常；精确的底层 native 忙等位置未取得栈证据，不归因于 CUDA。

## 最小代码变更

`visual_worker_runtime_v6.prepare` 仅对 Windows venv worker 返回 subprocess 的实际 `executable=sys._base_executable`，并在该子进程环境设置 `__PYVENV_LAUNCHER__=sys.executable`。保持原 argv[0]、私有缓存、超时、静音隐藏选项与审核输入不变。它独立核对 `pyvenv.cfg` 的 home、实际 base 文件和当前 venv，不能默默切换到其它解释器。非 Windows、非 venv 的解释器选择保持原行为。

普通布局 client 与共享 material/appearance dispatcher 均接此 helper。原 CLAIM/已完成/未知结果保护仍先执行，不会因为修启动器自动重派原 unknown。

新调用保存不可覆盖的 `WORKER_LAUNCH.json`，绑定运行方式、预期 prefix、base/redirector/config SHA。worker 在模型加载前保存 `WORKER_RUNTIME.json`，记录实际 PID、物理 executable、venv prefix、site-packages 与包定位；若原回执已存在，新的实际启动回执另存独立文件，不覆盖历史。

这是每次 worker 的显式进程参数，不修改系统环境、Python 安装、依赖、权限或服务参数。CPython 自身的 venv redirector 也使用相同的环境标识传递 venv 身份，见[官方 3.14.3 源码](https://raw.githubusercontent.com/python/cpython/v3.14.3/PC/venvlauncher.c)。

## 验证与后继

新 helper、真实无模型短/长路径，以及两类实际 dispatcher 相关测试 **132 项通过，0 失败/跳过**，34.24 秒；XML 为 `data/qa/visual_worker_runtime_v6.xml`。这是启动修复的针对性回归，不与此前 637 项阶段结果相加。

修复证明了可用执行路径，不代表原 target appearance 已通过。原 unknown 必须保留；后继只能在原请求 SHA、原超时与家族退出证据全部核对后，以明确的新受控审核记录处理已保存图像，不能自动盲重派原任务。开发代理未调用模型/GPU。

## 第二层嵌套进程：短私有 TEMP 修复

之后厨房 worker 已进入脚本并保存 loading，但在 `probe_resources()` 启动 `nvidia-smi` 时再次出现父 CPU 忙、子进程 stopped。原 nvidia 仅映射 exe 与 ntdll，没有执行资源查询；并非 NVML 推理慢。`subprocess.run(timeout=5)` 的等待超时尚未覆盖卡住的进程创建阶段。

在原 worker 相同环境、相同长 HF 路径下，仅改变 TEMP/TMP 和子查询的隐藏 flag，独立无模型对照如下：

| TEMP/TMP 长度 | CREATE_NO_WINDOW | 结果 |
|---:|---|---|
| 132 字符 | 开 | nvidia 查询约 0.04 秒成功 |
| 290 字符 | 开 | 创建阶段卡住，外层 15 秒收尾本例 |
| 132 字符 | 关，仍隐藏窗口 | 查询约 0.03 秒成功 |
| 290 字符 | 关，仍隐藏窗口 | 同样创建阶段卡住 |
| 与原现场相同的 271 字符 | 开 | 同样卡住，外层 15 秒收尾本例 |

这些证据将触发条件定位到长 TEMP/TMP 的嵌套创建链，而不是 REQUEST 长度、HF 缓存长度或隐藏 flag 单独造成。操作系统内部精确的 native 忙等位置仍未取栈，不据此断言特定 Windows/CPython 内部缺陷。

当前 runtime 策略升级为 `python_worker_direct_base_short_temp/v2`。仅 Windows worker 的子进程环境 TEMP/TMP 改为项目 D 盘 `data/visual_worker_runtime/temp/<jobSHA32>`，绝对长度限 180；原命令与原 TEMP 参与完整 job 摘要，`TEMP_BINDING.json` 检查完整 SHA，防止不同任务碰撞混用。HF 缓存、REQUEST/CLAIM/SHA、模型与系统环境保持原样，不更改资源探测源码。

本次只修改 runtime helper 和对应测试，**10 项通过，0 失败/跳过**，0.51 秒，`data/qa/visual_worker_short_temp_v2.xml`。包含真实 direct worker 在短私有 TEMP 中嵌套启动 nvidia 的原生探针，查询成功且 torch/transformers/bitsandbytes 未导入。原 26288、32820、28032、23324 家族等待原 caller 超时后于 20:47 只读确认均已退出，开发代理没有杀掉原家族。

厨房已经处于 loading，与此前完全没有 WORKER_STATE 的场景不同，不能直接套用旧 local-unstarted 恢复例外。原 unknown 继续保留；是否使用最后一次明确 successor 或保持 pending，由主代理依据对应新证据和原预算决定，不通过扩大恢复条件或更换 run 无界重试。
