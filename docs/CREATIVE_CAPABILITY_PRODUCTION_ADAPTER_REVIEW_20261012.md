# 自主接入、真实文本测试与诊断修复交接

本轮已按用户“这些审核你可以直接进行，人物你可以主动接取，这些都是正常的重构修复流程的你可以自动运行的”执行正常代码审查、素材发现、独立复核和有限真实文本测试。先保存[实施计划](CREATIVE_CAPABILITY_PRODUCTION_ADAPTER_PLAN_20261012.md)，由子agent实施、主agent审查。默认v23及原run_01/probe_v4不迁移。

## 当前实际结果

完整正文仍为512《桌面那张纸》，513同源全文审查通过。公司决定让小林离开，却要求签写着“个人原因”的自愿离职申请；小林顶住公司口径和周姐个人劝说，仍不签。周姐收走未签纸笔、夹进文件夹独自离开，小林留坐，争议未结束。没有手工改正文、删对白或加快语速。

新的`capability_v5`入口实际派发三份MiniMax-M3整片导演，均HTTP200、完整tool_calls、结束和用量已知，但均被排时合同拒绝。当前7/7候选耗尽；没有可采用整片导演、逐段实际表演、DeepSeek制作全文复审、制作交接或新视频。接口成功不代表完整制作文本或创作质量通过。

| 调用 | prompt / completion / total reported tokens | 实际验收 |
| --- | --- | --- |
| 518 | 19757 / 2641 / 22398 | M004选reaction需15.530303秒；M011最低需16.663636秒，超过单段15秒 |
| 519 | 21798 / 2419 / 24217 | 同上；14个端点及档位与518完全相同 |
| 520 | 22006 / 8786 / 30792 | 修了上述两处，但M006选reaction需15.227273秒；该范围仅minimum/natural可用 |

本轮新增3次、77407 reported tokens；累计520次、7964215 reported tokens。历史70/160仍未知，93117未知用量预留保留，不能以本轮未知为0结清。当前文本没有总token硬上限，有限导演候选门仍有效。重入已保存执行新增派发0，账本哈希未变；没有新增媒体或发布。

## 已接入的可复用实现

| 模块 | 实际职责 | 验证 |
| --- | --- | --- |
| `creative_capability_role_clients_v2.py` | SDK真实序列化前后核对模型、角色、参数、工具、完整消息、HTTP方法及目标；最后出站hook再次绑定，保留原body/能力证明，零运输重试 | 33项真实SDK MockTransport负例 |
| `creative_reference_intake_v5.py` | 发现原文件、原服务回执及历史采用记录；当前人物/场景映射、原字节MIME与供应商资格分开，不伪造历史批准 | 28项新测试，相关旧素材编译回归保留 |
| `run_creative_capability_production_v5.py` | 新独立freeze，继承原512/513、完整R01、原四份导演与消耗；持久claim、实际出站证明、重入复用、交接门 | 24项新入口测试，已真实运行三次 |
| `creative_complete_production_coordinator_v4.py` | 返修只传最新完整失败，不累积所有旧全文；旧完整历史仍保存 | 4项新增与45项原协调器回归通过；本文件现已冻结 |
| `test_creative_capability_runtime_sdk_v5.py` | 原Runtime、SDK、出站hook、原响应、协调器与交接证据门贯通；超时保留原请求，不重派 | 2项贯通验证 |

生产前主agent相关回归354项通过，独立审查179项通过，另有同grant换目录不得重领的1项隔离检查。独立审查发现的出站后URL变更、外部纯背景供应商范围与多模态text证据消费问题均已修复并复验。根目录中其他历史变更未擅自清理。

实际三次出站原body/能力证明均通过核对：MiniMax-M3、temperature0.4、thinking disabled、max_completion_tokens10000；完整正文、人物场景manifest、初态、R01参考全文及真实可选端点图确实进入服务请求。不是仅写入本地提示文档。DeepSeek分工保持，但本轮没有进入制作复审阶段。

## 故障分类和可确认的原因

| 类别 | 本轮事实 | 限制 |
| --- | --- | --- |
| 生成 | 原生计划选择了当前不可用的范围或档位；519重复518的全部端点及档位，520部分修正 | 不能推断模型永久不能理解规则，也不能用手选档位替代原生新稿 |
| 接口 | 三次响应均完整工具调用，HTTP、结束、用量及原响应已知 | 旧MiniMax长分析的服务端原因仍未知；本轮成功返回不解释旧未知 |
| 状态契约 | 7/7候选、原失败、原消耗及历史未知完整继承；重入派发0 | 没有新表演终态，不能宣称跨段身份或道具状态已生产通过 |
| 编译/反馈 | 编译器能准确算出错误，但异常只暴露`.diagnostic`，原Runtime取`.detail`；协调器正常返修又只传`str(exc)`，具体镜段/下界/可选项丢失 | 这是已验证的反馈接口缺陷，不证明它是模型错误的唯一原因 |
| 审查 | 513只证明同源正文机器审查；三份导演均未过编译 | 不能替代制作全文审查、用户采用或实际视频通过 |

## 结构化诊断的新独立修复

真实失败后先保存[诊断修复计划](CREATIVE_ENDPOINT_DIAGNOSTIC_REPAIR_PLAN_20261012.md)。新增加纯适配器`creative_endpoint_revision_feedback_v5.py`、协调器子类`creative_endpoint_feedback_coordinator_v5.py`及只读`preview_creative_endpoint_feedback_v6.py`，原v5冻结代码、回执、范围与候选门不编辑。

只对已知完整、同源同身份的端点失败复算并传入：出错segment、推导起点、原所选终点、原档位、对白和动作时长下界、15秒上限、该范围合法档位及当前起点合法后继范围。程序只列选项，不选择、改动或采用原生计划。Runtime消费的异常提供`.detail`；下一完整返修及恢复后的首请求都须保留精确诊断。同一导演失败稿只保留一次全文，原生字值不变。非端点schema/内容错误与局部表演/全文审查失败保留原路由，结果未知等不得借此返修。

最新只读请求见[可读预览](../data/qa/creative_capability_production_adapter_20261012/endpoint_diagnostic_repair/preview_r2/READABLE_REQUEST_PREVIEW.md)及同目录`FULL_MODEL_REQUEST.json`。预览明确7/7剩余0、dispatch_allowed=false，没有新授权、候选、消费或采用。SDK body文件是预览，不是已发送证明。

主agent修复相关回归108项通过（含28项新诊断、5项只读预览及原协调器/生产/SDK相关回归）；独立修复复验82项通过，当前修复范围无未解决代码阻断，见[独立审查报告](../data/qa/creative_capability_production_adapter_20261012/endpoint_diagnostic_repair/INDEPENDENT_ENDPOINT_DIAGNOSTIC_REVIEW.md)。额外实际截获有terminal恢复首请求验证通过，provider调用0、响应新建0、原state字节不变。首轮预览测试的JSON转义比较断言错误已改为解析后比较，原失败XML保留。只读预览还补齐原事件与账本请求/响应身份核对，防止相同7/7计数掩盖被改的历史。尚未接入新的生产冻结，也没有新的真实生成。

适用边界：当前任务有持久terminal，恢复首请求与同运行返修路径已覆盖；无terminal的历史初始化分支仍沿冻结helper保留全文与full audit，可能重复native，未在本轮替换。不能将新子类说明为所有历史初始化或默认v23均已接入。

## 人物素材与下游未解决项

主动发现44张旧服务原始尾帧；虽然扩展名`.png`，原字节均为JPEG，现按原字节认MIME，原文件不改。r2索引包含5份历史原段批准、2份拒绝、13份缺批准、24份旧回执形态未适配。这些不是44张当前人物候选，也不能把含旧人物的尾帧冒充纯办公室背景。

当前“小林＝年轻男性、周姐＝中年女性”的两名角色尚无可证明匹配的独立人物素材，selected_asset_ids为空；声线unbound，没有资格/身份就位的生产证明。索引及原因见[素材接入报告](../data/qa/creative_capability_production_adapter_20261012/asset_intake/r2/INTAKE_REPORT.md)。无新增图像生成，也不观看/抽帧旧视频来替代原服务素材。

整片规划负责情绪因果和源范围/预算选择；局部表演负责刺激、回应和正常语速的真实窗口；确定性编译负责完整来源、时间、共享身份与道具状态约束。局部超窗应带完整原生计划返回导演重新安排，不提速压扁、补操作或手拼旧稿。当前数值图只是可行下界，动作重叠、面部表演与情绪仍需后续表演及全文审查证据。此次没有这些有效后续产物。

## 实际保存位置

真实请求、原始回执、能力与出站证明、账本和停止记录：

```text
D:\IT\ai_douyin\data\production_revisions\shared_full_production_20261012\capability_v5
```

修复代码审查、离线回放与完整只读请求：

```text
D:\IT\ai_douyin\data\qa\creative_capability_production_adapter_20261012\endpoint_diagnostic_repair
```

总状态：`implementation_tested_real_director_trial_rejected`；完整制作目标仍未完成。
