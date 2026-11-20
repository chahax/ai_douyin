# 冻结历史链守卫的重复校验诊断

本记录只读分析当前独立producer_v6及其历史代码。没有构造实际runtime、运行整链guard、计算完整文件SHA、调用模型，也没有触碰在途代码、ledger、claim或DISPATCH.lock。请求文件和TaskStore claim先于runtime的派发入账建立，因此请求文件存在、ledger仍为0且进程在dispatch锁内guard，不能解释为模型已经调用但没有返回。

## 已验证调用关系

`run_goal_context_text_production_v4/v5/v6.py`的`prior_guard`均依次执行：

1. `previous.prior_guard()`。
2. `previous.get_runtime().inherited_guard()`。
3. `prior_runtime.check(ledger)`；`ContinuationRuntime.check`首行再次调用`inherited_guard`。
4. `prior_runtime.summary()`；其父`summary`又调用`self.check(ledger)`。

父runtime的`guard`又从父版本的`prior_guard`开始。于是每加一层生产版本，祖先`prior_guard`调用数乘4。一次v6 guard会进入v5 prior4次、v4 prior16次、v3 prior64次；相应父runtime guard为v5 3次、v4 12次、v3 48次。底层M31 `old_guard`至少执行64次，源批次时效门也在这些runtime guard中重复64次。

依据位置：v6 `prior_guard`第41–64行；v4/v5同名方法；`creative_resume_dispatch_v3.py`的`check`第118–130行、`summary`第144–150行；`creative_goal_context_dispatch_v3.py`的`summary`第122–138行。

## 重复规模

以下仅读取冻结清单JSON和文件大小，未运行SHA验证。计入每个直接freeze文件循环，尚未计入old_guard的源快照、外部资源和父runtime.check的源快照双重校验。

| 直接文件循环 | 一次v6 guard执行次数 | 文件条目 | SHA操作数 | 累计读取字节 |
| --- | ---: | ---: | ---: | ---: |
| M31 TEST_FREEZE | 64 | 1151 | 73664 | 1742349760 |
| v3 round_02 | 48 | 1164 | 55872 | 1324049568 |
| v4 round_03 | 12 | 1177 | 14124 | 340582872 |
| v5 round_04 | 3 | 1188 | 3564 | 87448287 |
| v6 round_05 | 1 | 1201 | 1201 | 29908130 |

这些清单的并集只有1201个路径、29908130字节，且重复路径的期望SHA一致；递归直接循环却产生148425次SHA操作、3524338617字节读取。运行开始的显式guard与第一次dispatch锁内check，在首次runtime派发入账前各走一次这条链，至少把上述直接循环再乘2。来源时效/SQL历史/JSON反序列化也重复。

因此已确认的原因是本地校验调用结构重复。不能由这些静态计数推断远端服务耗时，也不能把文件缓存命中当作校验已经完成。

## 最小修复方向

下一独立版本增加只读flat lineage verifier，不替换在途v6：

- 按真实父节点关系遍历冻结、scope、authorization、claim、ledger、receipt、SDK证据和源快照；保留所有原有身份、范围、已知用量、连续序号、terminal状态及累计检查。
- 每个校验周期建立路径→字节→SHA的局部读取表。同一绝对路径在这一周期只读取/计算一次SHA；所有逻辑引用仍逐一核对其期望值，期望值冲突直接拒收。
- 每次派发开启新周期，不跨请求永久缓存，不用mtime/文件大小替代SHA。源原件和source_at_dispatch是不同路径，必须各验证一次。
- 祖先账本各解析一次，在已验证receipt上计算累计、unknown与reservation；不调用旧runtime的check/summary递归链。公开summary若需要新验证，单独新建周期；派发事务内可从刚验证的ledger计算汇总，不再借summary触发祖先guard。
- 旧冻结、旧账本、未知历史70/160和93117、原始工具响应、模型身份与重试边界完整承接。实现不只信汇总数字或统计mtime。

验收应覆盖源/快照、冻结集合、授权、模型、receipt、实际SDK请求及原始响应、历史起始数、累计、未决新claim被改时的拒收；证明同周期同路径只读一次、下一周期重新SHA，并与原职责逐项对照。模拟通过不算生产接口或创作质量通过。本轮只开发独立模块供后续入口选择，不修改当前RUN_CLAIM、不重启或再派发当前请求。
