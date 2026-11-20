# 同源全文审查 v4 实施边界

独立模块：`src/content_factory/creative_full_review_contract_v4.py`。旧 v3、round_06 的 541–546 原生回执、冻结记录与账本不改。此模块无客户端、模型调用、媒体、自动重试或人工补稿能力。

## 实际问题与新增内容

546 的 `turn_function=statement` 是解释性标签，原 v3 的封闭词汇阻止后续验收。新 v4 允许含非空白字符的文字标签；该文字不参与接受路由。版本、源 SHA、对白覆盖、原 E 编号、角色身份、法律引用及 pass/fail/unknown 仍封闭。

v3 本来已要求动作前提来自初态或严格更早事件、原句逐字匹配，以及实际值/所需值和连续状态一致。546 先被标签枚举拒收，尚未执行这些后续门。v4 复用这些门；不能把它们全部称为本轮新增保证。

本轮新增的是显式 `opening_setup` 来源绑定：

- 响应中 `opening_setup_sha256` 与实际完整原生 setup 精确绑定。
- `initial_evidence_catalog` 按同一实体 ID 直接展示 setup 原对象及路径，不能由当前动作生成初态。
- brief 的 JSON 值 `expected_state` 必须逐值保留同一个 setup 对象，不改写中文表述或归一化状态。
- 初态引文来自对应原生实体；真引文不能给不相符的明示实际状态背书。
- setup 明确给出的 location、posture、holder、presence 或 open 原子逐值核对；v2 的 actor/scene/prop/absent 类型只按明确 ID 映射 holder、support、presence。absent 没有位置。
- 同一实体的真位置引文也不能证明它未声明的 open 等原子。未声明原子不能支持 pass，也不能填确定的 actual 值；open=null、presence=unknown 等未知值不能支持通过。诚实的 actual=null 可保留 fail/unknown，分别进入完整返修或停止接受。
- holder=null 表示明示无人持有，absent 类型的位置和支撑 null 表示明示缺席，不把这些确定语义误作未知开合。

没有从中文推断未提供的开合状态，没有把任何纸页或副本补进正文，没有证明模型已理解全部动作。未被审查模型报告的物理和因果矛盾仍可能漏判；新 workflow 必须先找反例，不拿摘要、既有 pass 或计划承诺替正文演出。

## 接口

```python
build_review_schema(script, brief, plan, legal_context,
                    *, goal_contract=None, opening_setup=None)
validate_full_review(document, script, brief, plan, legal_context,
                     *, goal_contract=None, opening_setup=None)
initial_evidence_catalog(brief, opening_setup=None)
```

真实新入口显式传 `opening_setup=views["opening_setup"]`，并把生成的初态来源目录放入实际审查请求。未提供 setup 的兼容模式只针对原有离线调用；目录标记为 `compiled_native_brief_projection`，结果不声明原生初态投影已核实。

新响应 schema 为 `creative_full_review_contract/v4`。本地只验收新 schema，不调用 v3 的响应枚举。随后把说明性字段从只读 legacy 投影移除，保留原有法律、完整覆盖和内容判定，再执行原状态/证据门。任何 fail 仍进入完整新稿返修；unknown 停止接受。机器文本资格不等于用户采用或创作质量。

## 离线和真实故障回演

`tests/test_creative_full_review_contract_v4.py` 的 61 项必要用例通过，报告：

```text
D:\IT\ai_douyin\data\qa\full_review_contract_v4_20261013\own_r4.xml
```

覆盖开放说明标签及空值拒收、原生 SHA/全覆盖、初态投影篡改、真引文搭假位置或未声明开合、明确未知原子不能通过、诚实未知保持非通过路由、当前/未来动作作前提、更早事件原句、不同表述不人工归一化、fail/unknown 阻断及输入不变。

独立工作流实际反例 `test_undeclared_container_open_atom_cannot_be_established_by_its_location_quote` 已单独复验通过：book 原生状态只写 `kind=scene, location=柜内搁板上`，使用该真位置引文填写 `open=true` 不能被接收。修复前失败证据 `causal_v8_added_r1.xml` 保留；修复后证据：

```text
D:\IT\ai_douyin\data\qa\goal_context_production_repair_20261013\review_open_atom_independent_fixed_r1.xml
```

独立审查另用固定 41 项复验，全部通过，报告 `data/qa/goal_context_production_repair_20261013/full_review_v4_independent_r2.xml`。执行前后新 v4 源码 SHA 均为 `5f4ac922688302d882342cf43ec4c76e3de7bc6c1326f714704b023788441390`；旧 v3 SHA 保持 `16caeac2a3ddcaa4f7452c0468a96a8789b6825b57611de1b04d8094c29037d3`。这些独立用例只验证合同与拒收边界，不证明模型没有漏报前提或正确理解隐含知识、承诺及情绪。

真实 546 只作只读离线回演。在内存拷贝中标记假设新合同头，保留原始全部内容。它不再因 statement 词汇被拒，却首先被已有的冻结初态声明核对门拒收；单独检查原生初态引文也拒收。回执字节未变，原 546 没有被转成已通过的新审查。

首轮 45/46 通过，失败是用例误预计最先触发新引用门；实际上原有初态声明门更早拒收。修正测试预期并同时检查两道门，46 项通过。独立审查随后发现真引文搭假位置的缺口，新增明确原子核对及 5 项反例后 51 项通过。生产前工作流反例再证实未声明 open 的确定值仍能漏过，补齐未明示/未知原子门及 10 项正反例后 61 项通过。早期报告保留，不覆盖原证据。

此记录只证明离线合同及真实失败响应仍被拒，未获得新模型审查、新完整正文、导演、表演或媒体质量通过。
