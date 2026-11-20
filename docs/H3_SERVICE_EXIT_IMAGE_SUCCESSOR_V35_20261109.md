# v35：一条已证服务退出图片的独立后继

只为本轮 root 精确审批的原图片 ID 创建一个独立后继。原 native provider outcome 保留 `unknown_after_service_exit`，原 REQUEST、CLAIM、STATE、ID、原未知和可能消耗都不改。没有伪造原生 HISTORY、saved 或 execution_interrupted。未知视频和其他未知图片仍硬停。

## 证据与修正

原图 `10fad168-10d1-4f31-81ad-225d69a086ab` 已被服务接受，所属服务 recorder 的 PID/create_time 与 EXIT3 对应，父子身份已消失，冻结 namespace 无任何输出。进程退出是已知事实，native 结果未知。

只读审计 R1/R2 的 Fatal/restore/WDDM 摘要错误来自 ANSI 控制码插在 `[INFO]` 与 `got prompt` 之间，旧组合标记搜索返回 -1。原文没有消失：R3 独立保留了正确原文摘录和原 log SHA，未覆写 R1/R2。生产 verifier 直接读被绑定的原 stderr，按裸 `got prompt` 的最后一节检查 Fatal、restore、unload、encode 和无 sampler 进度；不把审计摘要布尔当 fatal 依据。

服务代次归属仍是回溯证据，不冒充 provider PID 回执。验证会重算 guard 各 PROCESS 寿命，使用后续 families 空、port closed 的权威 launch 排除早期缺 EXIT 记录，要求唯一对应原代。当前原 ID 在 history/queue 重现、任何部分输出、活的旧 PID/create_time 或权威证据变化都会阻止新派发。

## Root 的具体处置记录

新 CLI 只准备或读取，不提供重启、kill 或直接 POST 动作：

```text
python scripts/run_h3_service_exit_image_successor_v35.py request-disposition --service-attempt 原guard代次目录 --readonly-audit 实际R3.json
```

输出 schema `h3_service_exit_image_disposition/v35`，绑定本轮 PLAN/原授权/projection、精确原 job/ID、六份原记录、CONTEXT_SPEC、工作单、原 PROCESS/EXIT/CLAIM/stderr 与只读审计。Root 记录自己的精确处置和证据，将 `approved_for_successor` 设为 true；不是再次向用户伪造数字授权。最多一个新图片后继，旧 claim 仍占原八图范围的一次。

保存为 `segments/S01/ROOT_SERVICE_EXIT_DISPOSITION.json` 后，独立写：

```json
{
  "schema": "h3_service_exit_image_recovery_opt_in/v35",
  "minute_plan": {"path": "实际本轮PLAN", "sha256": "实际SHA"},
  "dispositions": {"S01": {"path": "实际root处置", "sha256": "实际SHA"}}
}
```

文件为本轮根的 `SERVICE_EXIT_RECOVERY.json`。只允许一个精确图片记录；不同 ID、不同工作单、不同 source/tail、不同 projection 或 video 路径不能套用。

## 新任务与真实首图准入

`prepare` 在本轮 `stills/<本轮名>_S01_service_exit_v35` 准备新的图片 job。规范化原图/新图的 LoadImage scope 和 SaveImage 前缀后，要求图签名相等：同四张输入像素、prompt、seed、模型与参数，只有新 namespace/native ID 不同。

```text
python scripts/run_h3_service_exit_image_successor_v35.py prepare --shot S01
python scripts/run_h3_service_exit_image_successor_v35.py approval-request --shot S01
```

逐图审批保存为 `ROOT_SERVICE_EXIT_IMAGE_APPROVAL.json`。只有 root 唯一运行的 v34 dispatcher 会在全局新代码审批、精确原 ID 的 fresh GET 以及预算检查齐全后调用已有 stills 提交。原图片不会再调用 `jobs.poll` 写状态；只查 GET/文件，保持原 STATE 字节。

新图片真实原 ID 保存后，审核文件为 `SERVICE_EXIT_ANCHOR_REVIEW.json`，仍执行 v33 同源身份、房间、拓扑、当前状态、实际输入像素和 native receipt 全核。通过后单独冻结 `SERVICE_EXIT_SELECTED_ANCHOR.json`，正常交 I2V；原图片没有 RESULT 不再被假扮成 saved。后继本身变 unknown 时停止，不能借原 sidecar 再创建第三条任务。

## 显式 v34 桥接与审批版本

没有 opt-in 时，原行为和普通 unknown 保护不变。opt-in 只处理绑定的那条原 image：

- 原 raw unknown 继续显示和计图；预算另外列 `image_unknown_claims_raw` 与已明确处置的条数，不改原生状态。
- 新 successor ID 优先按冻结任务收存，即使当前审核或 source 已失效。
- 原 ID 的当前 output/history/queue 在每次新 POST 前重新核对；其他 unknown 和所有 unknown video 不豁免。
- Root 新建 `ROOT_LAUNCH_APPROVAL_REVISION_V35.json`，保留旧 LAUNCH。其 `execution_sources` 为 v34 `_sources()` 加 `service_exit_image_recovery`、`service_exit_image_recovery_cli` 两个实际源码绑定，另绑 `service_exit_recovery_opt_in` 与新 CPU 验收。

## 第二次独审后的收存边界

旧 210 项 CPU 验收仍保留为历史候选。独审发现目录读取错误可能被 `Path.rglob` 隐藏，以及当前 opt-in 深核可能挡住已知视频收存；修正后的源码和唯一回归另存 `data/qa/h3_service_exit_image_v35_20261109/final_release_r2`。

产物检查改为显式 `os.scandir`：逐层读取冻结 namespace 的父目录、namespace 内所有项，以及原 job 的本地 artifacts。读取/属性错误都阻断，链接和 Windows reparse point 不跟随；只在父目录确实读成功且没有该名字时才认定 namespace 不存在。不能把无权限当作零产物。

显式 CPU `prepare` 另冻结 `segments/S01/SERVICE_EXIT_ORIGINAL_PROTECTION.json`，绑定原六文件、原 ID 和分钟 PLAN。此文件仅表示收存阶段保护原记录，`dispatch_authorization=false`，不授予任何新派发资格。既有已准备后继可重复运行 CPU prepare 补该文件，不改原 `SERVICE_EXIT_SUCCESSOR_PREPARED.json`。

收存不读取当前 opt-in 或处置审批：已知后继图片和已知视频按其原 ID 收存；原图片通过独立本地保护文件跳过 `jobs.poll`。保护文件缺失、读失败或不匹配时仍保守跳过原图片，记录 `COLLECTION_INPUT_INVALID.json` 并阻止新派发。当前 opt-in/处置变更或删除只在新派发阶段报 `INPUT_INVALID.json`，不能阻断已知视频保存。实际后继选择和每次新派发仍严格验证最新处置、原产物目录、当前 history/queue、同源审核和预算。

## 冷进程轮换候选

此 sidecar 不启动、停止、kill 或配置服务，也不改 dynamic flags。保留动态 H3 性能并在模型 family 边界用冷进程，能避免本次 warm H3 卸载路径，是待生产验证的候选。

轮换必须由 root 单独管理：当前拟停代次没有在途或未收存输出、队列空、实际 listener PID/create_time/guard attempt/argv 已核定。成功任务原件先保存；此前退出的原代另有精确处置，不能冒称它成功。保留现有一小时三次 guard 上限，不清 attempts/EXHAUSTED/PAUSE，也不旁启同端口。轮换前后的 operator 身份观察与 provider 的原生回执分开记录。
