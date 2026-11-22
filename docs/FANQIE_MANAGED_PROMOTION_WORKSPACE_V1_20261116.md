# 番茄专属推广工作台

这是已有账号管控、P0候选台账、原发布器和回填协调器的显式接线。没有新业务数据库，也不会通过旧公共缓存浏览器执行这些操作。现有登录窗口与未决任务保持原记录；它们未结束时，工作台显示阻塞，不把复用旧登录任务说成新推广任务已经入队。

## 页面

管理平台的「番茄账号」页新增「小说推广工作台」。读取状态不启动浏览器、不迁移数据库；写操作沿用管理员权限。

1. 同步当前专属环境的推广任务。只从明确属性、链接参数或中文列头提取平台任务ID、别名ID、推广路径。缺少时显示待补资料，不拿书籍ID、行号或书名代替。
2. 申请推广词时明确书籍ID、准确书名、推广词、实际推广路径及AIGC，并记录本次授权。先查相同任务；已有任务保留，不自动换书、换词或换路径。
3. 导入已有视频的交接、小说来源和同一视频技术审核工件。只登记待审核候选，不自动通过内容审核。
4. 绑定作品对应的推广任务，确认素材后填写标题、标签和一句剧情引子。工作台分别预览短正文和作者评论。正文保留推广收益、AI 生成和虚构剧情说明，评论使用已绑定的番茄搜索词及原著书名。两段文案随本次授权固定，发布器核实抖音作品后发送作者评论。
5. 使用候选对应的原发布任务读取真实作品链接。若原凭据缺少发布时间，通过已有作品同步任务核实，不猜发布日期。
6. 以这些原凭据、准确推广任务和官方模板准备回填。回填资料ID与校验值由准备结果传递。授权、派发、只读核对是不同操作。

普通流程不要求手填原发布ID或回填校验值；历史记录高级核对保留显式输入。候选切换不会沿用另一候选的前端交接和准备缓存。

## CLI

公开入口：`.venv/Scripts/python.exe scripts/run_fanqie_promotion_workspace_v1.py`。

```text
status [--resource RESOURCE]
sync --resource RESOURCE
apply --resource RESOURCE --input exact_application_parameters.json
migrate --input explicit_backup_parameters.json
register-candidate --input candidate_import_parameters.json
bind-candidate --input exact_task_parameters.json
review --input same_media_user_review_parameters.json
prepare-publish --input exact_publication_parameters.json
dispatch-publish --input exact_prepared_candidate_parameters.json
recover-publish-receipt --input candidate_parameters.json
request-publication-metadata --input candidate_parameters.json
attach-publication --input original_receipt_parameters.json
prepare-backfill --input verified_handoff_parameters.json
authorize-backfill --input exact_manifest_authorization_parameters.json
dispatch-backfill --input binding_parameters.json
reconcile-backfill --input original_binding_parameters.json
backfill-status --input binding_parameters.json
```

`--input`是该命名操作的结构化参数，不接受动态模块、函数或浏览器配置。工件使用固定`path/sha256`；候选导入另支持`handoff_path/provenance_path/technical_review_path`，按实际文件计算SHA。申请参数为`book_id/book_name/alias/promotion_path/user_statement`，发文类型固定AIGC。迁移参数为新的项目data备份目录`backup_directory`，只能在已有兼容P0库上显式执行。

`prepare-publish` 的 `metadata` 传入 `title`、`hashtags` 即可使用小说号模板。可用 `story_hook` 单独指定剧情引子，省略时采用标题。调用方也可一并传入预览的 `description` 和 `comment`，系统会重新核对两者。只显式传入原有正文 `description` 的旧调用沿用单正文发布。

独立专属账号CLI另增加`promotion-list`、`promotion-apply --request FILE`和`backfill-reconcile`；后台注册相应handler，回填factory保持lazy，缺业务台账不会阻断旧登录handler。

## 结果边界

申请提交前冻结稳定意图claim。正常handler结束但平台尚未确认时，账号命令可结束，业务仍为`application_status=outcome_unknown / confirmed=false`，只允许后续同步核对。同平台身份、书籍ID、推广词、路径及发文类型的claim不因更换授权文件或新command而再次提交。失去owner或硬失败仍保留broker未知保护。

回填同样必须按业务`confirmed=true`显示完成；账号命令`succeeded`不等于平台回填成功。新前端不清锁、不重派未知提交、不修改平台验证码流程。

台账读取失败或占锁显示不可用并停写，不能伪装成未部署或空列表。只有明确缺少候选扩展时才显示备份迁移入口。

本轮验收为CPU临时数据库、mock page黑盒，以及独立真实Chrome的本地HTML测试。未申请真实推广、未发布、未回填、未调模型、未重启服务；不据此宣称真实平台完整无人生产已通过。当前页面字段缺少稳定证据时，仍明确返回pending。
