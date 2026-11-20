# 素材库一分钟流程：独立技术尝试路由

本适配只服务 `h3_library_bound_minute_20261112_v1` 的四段新视频。原四段生产源码、旧段目录、PLAN、REQUEST、原任务 ID 和 unknown 记录均保留。没有自动重试循环，也不根据 GPU 空闲或 HTTP 超时推断生成失败。

## 两条明确分开的重新尝试依据

1. **原生已知失败**：原 ID 的实际 history 为 error，包含同 ID 的 execution_error / execution_interrupted，原图相符，STATE 已由原 collector 登记 failed / interrupted，保存的队列观察确认原 ID 不再运行或排队。
2. **受控本地终止**：没有伪造原生失败。保留原 running / unknown 状态；绑定原唯一 ID、graph、精确进程及父进程身份、定向中断请求及 200、停滞观察；保存受控终止和两个旧进程均退出的 OS 证据；同 guard 的新进程须具有新创建时间、相同 argv、真实监听和已核服务路径，新队列为空且无原 ID / 自动恢复旧队列；root 具名明确批准一次同来源的新技术尝试。本通道仅说明旧进程不能继续执行，不声称旧任务未生成过部分数据或没有资源消耗。

只存在低利用率、interrupt 200、旧 PID 仍在、缺新服务或缺明确新尝试批准，均不能通过第二条。Adapter 不杀进程、不启动服务、不合成失败 history。

新服务为空时，原 GET-only collector 可能自然把旧 STATE 从 `running` 收存为 `outcome_unknown`。仅允许这一种状态承接，其他 STATE 字段须逐项不变，并绑定原 collector 最终 JSONL、退出 0 证据、最终 STATE 及同一新服务观察。JSONL 最后一条须明确原 ID、`outcome_unknown` 和完全相同的 STATE，且发生在旧 owner 退出和新服务创建之后。不得为匹配旧快照而写回 `running`。

## 文件与选择

- 原 A01：所有原路径不变。
- 新 A02 的输入、状态审查和终止依据：`N/technical_attempts/S02/A02/`。
- 新 A02 的原生 PLAN / REQUEST / 四原件：`N/visual_h3_v3/Nname_S02_A02/`。保留原生 producer 对 `runs_root` 直系子目录的约束。
- `N/attempt_routing/ROUTES/0001.json` 起始为四个原路径；每次确认一个新尝试，追加下一份带前件 SHA 的不可变选择清单。每份只允许一个段的尝试编号增加一。
- 不复制任何旧 native 任务到新目录；新尝试只复制对应原文和实际首帧状态审查的字节，重新编译独立 scope，逐图核对并实际发送同一版本的全部参考图。新 graph 仍需 root 的新启动审批。
- S03 的前驱解析已选 S02 的真实 `RESULT.last`。没有结果就等待，不使用旧 A01 尾帧，也不预造未来图。
- 同一个一分钟成片仍为 4 段、1448 帧、60.333333 秒。合片输入、最终回执和独立 QA 都绑定实际选择清单，不能合完后再改变选择。9 图输入、库特点、剧本和原声音校验沿用原冻结实现。

## 实现方式

`visual_h3_library_attempts_v1.py` 把冻结 producer 的同一函数代码放入独立 globals 命名空间，只替换物理路径、输入路径解析、前驱选择和包含路由 SHA 的审批请求。不修改 producer 文件，也不 monkeypatch 共享导入模块。原实例可继续只读检查或收存旧 ID。

命令入口 `scripts/run_h3_library_attempts.py`：

```powershell
# 只追加初始路径清单；不调服务、不生成
.venv/Scripts/python.exe scripts/run_h3_library_attempts.py initialize

# 原生 terminal 证据齐全后登记新的 A02；不发送生成请求
.venv/Scripts/python.exe scripts/run_h3_library_attempts.py register-attempt --shot S02 --terminal-history <实际终止history.json> --queue-observation <实际队列快照.json> --confirmed-by root --evidence <具体依据>

# 或者采用独立、完整的受控本地终止审批证据；不改原 unknown
.venv/Scripts/python.exe scripts/run_h3_library_attempts.py register-attempt --shot S02 --controlled-abort-approval <root审批.json>

# 新 graph 审批后，root 才执行 video；每阶段独立调用
.venv/Scripts/python.exe scripts/run_h3_library_attempts.py prepare-video --shot S02
.venv/Scripts/python.exe scripts/run_h3_library_attempts.py video --shot S02
```

`status` / `collect` / `review-request` 同样读取显式选择。后续各段都应使用这个入口，不能再让原固定路径 CLI 继续派发 S03 / S04。独立 QA 使用 `qa_h3_library_attempts.py`；原 QA 保留用于原路径证据，不拿它假装检查了 A02。

本次生产 CLI 的登记范围固定为 S02 从 A01 到 A02；其他段或更多尝试需另行明确范围，不能通过修改选择清单扩展。

CPU 色块和本地 HTTP 黑盒验证路径、未知保护、真实尾帧链和合片时钟；不代表真实人物、字幕、说话人或空间效果已经合格。
