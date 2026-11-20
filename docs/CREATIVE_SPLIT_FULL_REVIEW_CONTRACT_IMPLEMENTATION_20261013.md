# 零项协议与同源分包审查合同实现

本轮依据 `CREATIVE_SPLIT_FULL_REVIEW_REPAIR_PLAN_20261013.md`，新增独立 `creative_full_review_contract_v5.py` 与 `creative_split_full_review_contract_v1.py`。旧 v4、round_07 的 547–552、冻结记录、账本和服务回执不修改；模块没有模型、媒体、自动重试或派发能力。

## 真实拒收与原因边界

552 收到完整原生响应。当前覆盖目录中 `plan_support`、`obligations`、`order_checks` 都为零项，原 v4 仍要求三个空对象；模型把 `plan_support` 填为通用判断行而被拒。实际请求没有独立覆盖目录，这可能使模型误把零项当整片总评，属于推断，不宣称服务端根因已确定。

只去掉零项仍无法采用 552：它的对白和动作存在未含当前 E 编号的通过判断，`CC_CTA` 还为 unknown。真实故障测试仅在内存副本中预览新版头和零项省略，正文判断全部保持；语义包被对白自身引用门拒收，物理包被动作自身引用门拒收。原 552 字节未变，没有转成已通过的新服务响应。

## v5 的零项合同

`coverage_specification` 是唯一覆盖来源。`review_table_contract` 明确当前必需表、实际零项省略表和全部非零 ID。法律判断、限制说明及有来源时的旧故事关系保持固定必需字段，不能按空数组或字段名任意裁掉。

响应 Schema 不含零项表，顶层保持 `additionalProperties=false`：零项表连 `{}` 也不可返回。非零表仍要求每个真实 ID 一次，缺表、空表和额外 ID 均拒收。先验收完整新原生响应，随后只在内部编译视图为已证实零项补空对象，供旧 legacy 编译为空数组；这不是补审查行或改变原生响应。旧 v4 响应不能作为新 v5 原生结果。

v4 的开放说明标签、原生初态 SHA 与精确投影、明示状态原子、未知初态不能支持通过、严格更早 E 引文和完整来源检查继续执行。所有审查行 fail/unknown 阻断规则保留；零项协议不决定 CTA 的作用域，也不推断未明示开合状态。

## 分包职责与身份

语义包负责 `plan_support`、`fact_checks`、`literal_events`、`obligations`、`order_checks`、`dialogue_checks`、`criteria`、`ending_checks`、`goal_checks`、`legal_claims`、`review_limitations`；有旧故事范围时还必须提交 `prior_story_relation`。物理包只负责 `initial_checks`、`observed_prop_initial`、`action_checks`。每包仅返回其非零表，没有跨包重复表或合并总评。

每份原生响应都绑定 `schema`、`part`、独立 `context_sha256`，以及同一 `script_sha256`、`brief_sha256`、`plan_sha256`、`legal_context_sha256`、`goal_contract_sha256`、`opening_setup_sha256`。实际上下文由工作流按实际 payload 计算，合同核对传入的精确身份；服务原始响应与实际请求、模型及回执的绑定仍由生产入口负责。

两包均读取完整当前正文与原生规划和起态。语义负责信息先后、物件上实际写了什么及其功能、情绪与策略促因、结尾承诺和法律；物理负责穿着、移动、取放、容器和状态连续。结构合同只能约束模型报告的证据，不能证明它已发现所有隐含知识、承诺或表演问题。

每包先独立校验 Schema、源身份与其负责的真实证据。单包检查不会构造另一包的通过行；物理只给原有状态证据函数空的对白/goal 迭代集合，语义使用专用对白、goal、法律和事件次序门。单包通过为 `review_part_passed`，不是完整文本资格。

两份原生结果俱全后，bundle 才形成内部确定性 v5 编译投影并执行完整 legacy 门。结果明确标记 `review_origin=two_native_same_source_parts`、`native_single_full_review=false`，不冒充模型提交了一份完整 v5 审查。缺包、混源、混上下文、缺覆盖、额外表、fail 或 unknown 都不能接受。先包 unknown 时是否不派第二包，由新的生产入口执行；合同本身不派发请求。

每包必须原生提交 `revision_target=none|script|plan`：无明确 fail 必须 none；有 fail 必须 script 或 plan。即使 `plan_support` 为零，goal、criteria 或动作前提失败仍可明确指定 plan。确定的 plan 目标在全文投影之前返回 `halt_full_review_requires_new_complete_goal`，不让正文迁就错误规划；unknown 仍先停止。旧故事的特殊 halt 在单包和 bundle 都保持，`revision_dispatch_blocked=true`，不能借 plan 目标重领额度。

Schema 保留标准共享定义，只按当前包 `$ref` 可达性剪去未使用的 `$defs`。不无条件展开成大量重复行，也不声称有服务端强制生成保障。

## API

```python
# v5；关键字与 v4 兼容
build_review_schema(script, brief, plan, legal_context,
                    *, goal_contract=None, opening_setup=None)
validate_full_review(document, script, brief, plan, legal_context,
                     *, goal_contract=None, opening_setup=None)
review_table_contract(script, brief, plan)

# split/v1
part_table_contract(part, script, brief, plan)
build_part_schema(part, script, brief, plan, legal_context,
                  *, context_sha256, goal_contract=None, opening_setup=None)
validate_part(document, part, script, brief, plan, legal_context,
              *, context_sha256, goal_contract=None, opening_setup=None)
build_review_bundle(native_semantic_review, native_physical_review)
validate_bundle(bundle, script, brief, plan, legal_context,
                *, semantic_context_sha256, physical_context_sha256,
                goal_contract=None, opening_setup=None)
```

## 离线证据与限制

自有 135 项必要用例通过：`data/qa/goal_context_production_repair_20261013/split_contract_own_r4.xml`。最后只补单包旧故事 halt 的返回标记，定向 3 项通过：`split_prior_guard_own_r1.xml`。覆盖零项省略、非零伪空、额外表、六个来源 SHA 和上下文、真实两包分工、旧故事范围、原生 plan 返修目标、fail/unknown 阻断、v4 初态门、原生输入不变和 552 仍拒。

早期 r1 的 122/123 通过，唯一失败是测试误预计 552 语义预览到 unknown；实际更早被对白缺自身 E 拒收。修正测试预期后 r2 为 125/125，补旧故事控制后 r3 为 128/128；各报告保留，没有通过删故障证据让旧稿采用。

独立合同 r1 有 62 项，60 项通过、2 项因 fixture 误选 table 道具而失败，来源为前一版 `1ea558...`。精确修正为 slip 后，final 版的 8 项必要复验全部通过，包含该两项，以及原生 plan 返修、无失败不能指定返修和旧故事 halt 优先；没有通过改动验收门使测试通过。证据 `split_full_review_independent_r1.xml` 与 `split_contract_independent_r2.xml` 保留。r1 同场还有生产接线测试，不能把其失败全部计为本合同缺陷，也不能把其修复算为本模块独立证据。

以真实 551 的相同来源离线构建，UTF-8 紧凑 JSON Schema 为：v5 全文 15122 bytes/20 个共享定义，语义包 10480 bytes/11 个，物理包 6666 bytes/12 个。每包体积小于原整审，不证明总 token 降低、服务响应遵守率提升或审稿语义已经可靠。

稳定源码：v5 `900a6cf72ad0136834f18d1baaf2456d3d29dba19d49ada77f881f4e8eee248a`；split/v1 `83bc149a0911b0b8206ddea6edf1d61ca922f207752e13f0b7aea65b1c310222`。final 独立 8 项 XML SHA `b2597fac39d1abaa1711dd80b76840618b20e9424b77ac5a50b11722b23dcbfc`。本次只证明合同与编译门离线通过，没有新完整正文、真实双审、导演、表演或视频质量通过。
