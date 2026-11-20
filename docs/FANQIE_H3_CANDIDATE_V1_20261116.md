# H3成片进入正式番茄P0台账

本组件 `src/services/fanqie_h3_candidate_v1.py` 只扩展现有 P0 数据库。构造只读；`migrate(path, backup_path)` 是显式迁移入口，先 SQLite 一致备份，再增 `fanqie_h3_candidates`。原 books、tasks、script_versions、video_jobs、publish_records、operation_events 继续承载业务记录。不创建第二套 job 数据库。

## 注册与来源

`register_pending(handoff_ref, provenance_ref=..., technical_review_ref=..., account_binding=...)` 返回 candidate_id。所有 ref 是 `{path, sha256}`，按文件实际字节验证。无当前真实推广任务时仍可登记候选，但 task_id、video_job_id 保持空，不伪造任务。

handoff 保留已有 `novel_promotion_local_candidate/v1`；不改旧 quality=false、publish_allowed=false。额外 provenance 是：

```json
{
  "schema": "fanqie_candidate_provenance/v1",
  "book_id": "原书ID",
  "media": {"path": "已有成片", "sha256": "实际SHA"},
  "script": {"path": "已有剧本", "sha256": "实际SHA"},
  "script_selections": [{"path": "已有选段或修词记录", "sha256": "实际SHA"}],
  "book_manifest": {"path": "原章节清单", "sha256": "实际SHA"},
  "assembly_result": {"path": "原合片RESULT", "sha256": "实际SHA"},
  "source_cases": [{"path": "原SOURCE_CASE", "sha256": "实际SHA"}],
  "source_code": [{"path": "原合片PLAN绑定源码", "sha256": "实际SHA"}]
}
```

source_cases 必须精确对应原生成 manifest 的 segments；各场 authoritative_script 与 script 一致，script_selection 集合对应全部 selections。source_code 对应 assembly RESULT→PLAN.code。没有固定段数、书ID、任务ID或旧V6依赖。technical_review 必须绑定同成片、RESULT、PROOF，并有完整像素/PTS、PCM/AAC及来源SHA技术复核记录；技术通过不等于观众已验收。

## 账号与推广任务

`ensure_runtime_account(account_binding, runtime_db=...)` 只把已存在、active 的原抖音 UUID/key 注册到 P0 映射；只读原runtime及active策略版本计算原binding_version。UUID或key冲突不换绑。

`bind_promotion(candidate_id, snapshot, row, resource_binding)` 使用 A 的 `fanqie_promotion_snapshot/v1`，要求固定DOM证据能重建整份快照、身份匹配、无验证码、分页完整、观察不超过60秒、任务/别名/推广路径/AIGC/有效期均明确。只在此时写真实任务、剧本与video_job。同一已验证task可关联另一媒体；跨书或身份不符拒绝。

resource_binding：resource_id、binding_version、platform_identity_key、environment_key、douyin_account_uuid、account_link_version。account_link_version 为原番茄环境到抖音绑定的摘要。日期无时区时明确按上海时区，不按机器默认时间推断。

## 用户验收与发布意图

`record_user_review(candidate_id, review_ref)` 需要 `fanqie_candidate_user_review/v1`：media、decision_source=`explicit_user_statement`、user_statement、accepted_for_publication=true、known_findings 精确对应旧handoff引用。保存新事件；不把用户接受写成代理已听审或旧质量评估通过。

`prepare_publish(... metadata, authorization_ref)` 要求明确AI声明、虚构声明和标签；metadata 含 title、description、hashtags、ai_generated=true、fictional_story=true。授权 JSON 包含 candidate_id、media、account_uuid、publish_authorized=true、decision_source、user_statement，以及 metadata_sha256（规范化 PublishRequest 字典摘要）、promotion_subject_sha256（稳定 row identity＋resource binding 摘要）。这使用户授权对应具体标题、标签与推广任务。

`dispatch(candidate_id, snapshot=..., row=..., resource_binding=...)` 接受重新观察的当前快照；稳定业务意图不含观察时间，避免60秒后无法刷新的死锁。调用现有 queue_publish_request 前持久化 dispatch_started；未知不盲重试。

`recover_dispatch_receipt(candidate_id, browser_db=...)` 仅按原账号＋publish:mediaSHA找到精确 request、authorization 和绑定版本匹配的原命令，恢复本地回执；0条仍未知，多条拒绝，不创建命令。

## 成功凭据回写

`attach_publication(candidate_id, command_id=..., browser_db=..., evidence_directory=..., metadata_command_id=None)` 用现有 PublicationEvidenceReader，再核原publish payload 的媒体SHA、完整request及authorization。必须有可验证发布时刻，不用今天日期补造。原publish已有明确时区日期时直接验证；现有发布结果无日期时，`request_publication_metadata` 以稳定幂等键复用受管 `read/sync_videos`，沿原账号核验真实作品发布日期。仅接受成功的同账号/版本命令、精确post及VideoItem账号信息；`YYYY年MM月DD日 HH:MM` 按北京时间转换。公共 `publication_time_evidence_v1` 保存源命令payload/result摘要，C使用同一个只读validator复核，不重造日期口径。一次写原P0 publish_records，post唯一；重入同命令返回同记录，异命令/异post拒绝。

返回 `fanqie_h3_publication_handoff/v1`，包含 candidate_id、book_id、task_id、video_job_id、publish_id、media、command_id、account_uuid、account_key、binding_version、post_id、publish_url、published_at、publication_evidence。C回填组件据此构造正式v2合同。此入口只登记成功证据，不代替番茄回填或发布授权。

开发测试使用真实P0 DDL副本及D盘隔离SQLite，不迁移生产，不发模型、媒体、账号或平台请求。
# Native alias identity extension (2026-11-16)

`fanqie_promotion_snapshot/v2` uses the shared
`src.services.fanqie_promotion_identity_v2` validator and authorization subject.
It never copies `alias_id` into `platform_task_id`. Native tasks keep that old
column NULL. The verified platform identity, native kind and original native
record ID identify a separate local task; multiple media may reuse that exact
task, while another platform identity with the same bare alias ID cannot.

The explicit `migrate(path, backup_path)` operation now also adds nullable
`native_identity_scope` to existing tasks and the native mapping table. It
changes the legacy active-alias unique index to apply only when scope is NULL,
retaining its complete old status condition, and adds uniqueness for native
scope. Original rows, IDs, statuses and values remain unchanged. Before backup
and again under BEGIN IMMEDIATE it validates the exact expected schema/index;
unexpected schemas are refused, never silently repaired. Constructors remain
read-only. No production migration is performed by development tests.

`CandidateLedger.verify_native_task(task_id, *, snapshot, row)` is read-only and
returns `task_id`, `native_identity`, `native_identity_scope`, and
`promotion_subject`. It validates static evidence and exact P0 mapping, without
requiring the historical observation to remain fresh or publishable. Freshness
and current publishability are separately required before a new write intent.

Native publication authorization uses schema
`fanqie_publication_authorization/v2`. Its promotion digest binds the shared
subject (including unclassified raw task mode and raw publication-type code)
and resource binding. The prepared intent also stores the shared UI selection
key; this key is not a platform ID. Successful native publication produces
`fanqie_h3_publication_handoff/v2` and `fanqie_h3_publication_evidence/v2`, carrying
the native identity, scope and subject. Original command, media, metadata,
actual publication date and once-only safeguards are unchanged. Legacy v1
snapshots, authorization digests and evidence are not reinterpreted as v2.

