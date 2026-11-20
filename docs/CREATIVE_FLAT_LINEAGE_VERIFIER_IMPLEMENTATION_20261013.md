# 新独立历史链只读证书校验

本轮仅新增 `src/content_factory/creative_flat_lineage_verifier_v1.py`、公开薄入口 `scripts/creative_flat_lineage_guard_v1.py` 和离线测试。没有替换已冻结v6，也没有修改旧账本、claim、锁、回执或数据库。性能原因见[重复守卫诊断](CREATIVE_LINEAGE_GUARD_PERFORMANCE_DIAGNOSIS_20261013.md)。本模块不创建runtime或模型客户端，不派发模型/媒体，不决定剧本采用或创作质量。

## 首次证书与后续周期

新入口在独立prepare进程执行 `build_lineage_certificate(PROJECT, parent_root, certified_check=prior_guard, expected_summary=parent_STATE_spend, dependency_paths=[...], guard_code_paths=[...])`。`prior_guard`必须是既有完整历史guard及原runtime.summary，完整执行一次并返回已验证汇总；汇总必须与原terminal记录完全相等。测试中的模拟callback不能当作生产证据。

临时只读观察器记录真实Python文件读取、目录枚举、存在性/类型探针，以及原SQLite只读连接的数据库与WAL输入。它覆盖 `open/io.open`、`scandir/listdir`、`stat/lstat`、`Path` 与 `os.path` 的存在性判断，避免Windows的快速exists绕过stat。证书补齐来源快照、原生SDK实际请求/响应、模型映射、用量、工具参数及任务结果身份。全部依赖在旧检查结束后用第二个独立SHA周期核对稳定性；发生写入、未知原生证据、不一致或目录变化即拒绝建立证书。

新入口将证书和校验模块本身纳入自己的冻结。`verify_lineage_certificate(certificate_dict, expected_certificate_sha256=digest(certificate_dict), expected_inherited=freeze_inherited, fresh_source_gate=parent.source_gate)`每次创建新的缓存周期。证书对象使用canonical JSON SHA；传证书文件路径时使用原始文件字节SHA。原输入、授权、冻结、原生请求、回执、父账本及目录成员都重新核对，不能只看汇总；未知历史70/160和93117预留、累计调用与消耗原样承接。证书缓存只活在该次校验中，不保存到下次派发，不用mtime代替SHA。周期内每个证书文件只读取及计算SHA一次。

时间敏感的来源门每周期执行，必须返回实际已验证的packet对象且 `blockers=[]`。旧证书中的来源门通过不代替现在的有效期判断；False、None、unknown或阻断返回均拒绝。当前运行自己的新授权、阶段限额、claim和源快照仍由新runtime独立检查；本模块负责历史依赖，不宣称已经消除新runtime自己的全部重复读取。

## 原生证据和数据库边界

M3.1实际外发证明为 `M31_WIRE_PREFLIGHT.json`，schema为 `creative_m31_flash_role_clients/v1/outbound_proof`，状态 `wire_verified_before_send`。旧能力客户端使用其实际 `CAPABILITY_PREFLIGHT.json`。校验按各自已实现的字段要求，重新用对应纯映射函数构造请求，再全文比对实际SDK请求正文；不补造不存在的字段，不把证明写成服务端强制Schema保证。

原始工具参数必须与回执原文和原生output相等；HTTP、模型、response_id、finish_reason、usage均与服务原响应核对。正文兜底不能改造成工具结果。SQLite任务身份按实际合同核对：新入口的 `{ordinal,native_output}`、M31专项的 `{receipt_ordinal,native_output}` 和原完整流程的receipt SHA各按原记录保留，不统一伪造新字段。

直接父数据库在无非空WAL的情况下，只解码已验证字节的内存副本；WAL格式主数据库留有版本2标记时仅调整内存副本的读取模式，不触碰原文件。旧fresh父数据库有非空WAL，其提交视图由已有完整guard的原SQLite只读查询认证；只有观察器确实捕获该原SQL只读连接，才允许继承它。数据库和WAL字节仍冻结，不能忽略WAL或替旧库checkpoint。SQLite SHM为派生索引及读锁材料，新增观察器不额外将其易变字节当成生产来源；若旧freeze/guard显式读取其字节，原SHA职责仍照常保留。相关格式依据[SQLite官方文件格式](https://www.sqlite.org/fileformat2.html#the_write_ahead_log)。

## 验证与实际证据

- 自有27项离线测试通过，最终回执 `data/qa/flat_lineage_guard_20261013/own_r5.xml`；初轮因测试临时目录父路径缺失没有进入代码，第二轮Windows否定exists用例发现并修复了真实分支漏洞，旧失败XML保留。
- 独立42项必要复验通过，回执 `data/qa/goal_context_production_repair_20261013/flat_lineage_independent_v1_r5.xml`，测试前后校验模块SHA相同。包括实际M31 proof格式、DeepSeek角色、原生工具/请求/响应/数据库三角、否定依赖、same-size/mtime变化、未知结果和未决claim隔离、旧未知消耗承接、观察器失败后恢复。
- 只读实际518–540共23份原生SDK证据全部通过；M31 529/530和round02–05数据库任务三角通过；539/540直接父完整原生和SQLite核对通过。这次小范围复验没有调用旧递归guard、运行整链源快照SHA、创建实际runtime，亦没有付费调用。
- 校验模块最终SHA：`1bf4bfdcdca7876d068c0021dd12b34c0404e2e0056a50aeb1808e23d4c7a338`。公开薄入口SHA：`941d09734443551a5277c4e344f221dd9ad8e383cc997ee3a74fd278f8d29a74`。

实际新入口的零付费prepare、证书规模与每周期用时仍须由主agent执行记录。这些离线与原生证据核对不构成新剧本或视频质量通过。
