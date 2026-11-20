# 空间短片 v24 独立 CPU 检查

本工具只读取新空间试验已保存的原生结果，不提交媒体、不访问 Comfy 服务或队列、不改原始 STATE / RESULT，也不解除旧 H3 暂停。CPU 检查结果不是人物身份识别、空间语义审核或生产批准。

## 调用

在项目根使用现有虚拟环境：

```powershell
.venv/Scripts/python.exe -X utf8 -B scripts/qa_spatial_movie_v24.py segment --run data/video_generation/spatial_minute_experiments_20261107_v1/variants/canary_A --segment S01 --asr
.venv/Scripts/python.exe -X utf8 -B scripts/qa_spatial_movie_v24.py final --run data/video_generation/spatial_minute_experiments_20261107_v1/variants/A
```

仅在实际对应版本明确指定空间设计时，另外传 `--spatial-handoff <HANDOFF.json>`。不自动寻找最近的空间文件，不给没有使用该设计的 A 版附上 B 版设计。空间图始终标记 PLANNED；它不证明模型遵从设计，不由人物名称或参考裁剪推断实际人物。

## 原始结果绑定

独立读取并检查 PLAN、物理 SPEC、管理员审核、授权、原始提示词、保护的旧 PAUSE、基础工作流、STATE、CLAIM、REQUEST、RESPONSE、GRAPH_BINDING、RESULT 和成功 HISTORY。原始 prompt_id、JSON 摘要、物理文件 SHA 必须一致。

重新构造纯 JSON 图核对真实 `MiniMaxH3ReferenceToVideo`、五张具名参考、`MiniMaxH3AddGuide` 的 frame_idx=0、可选末帧引导和四个独立保存节点；核对实际 input 目录的参考及引导图片字节，以及 HISTORY 四保存输出与原生 output / artifacts 副本。仅允许 HISTORY 中 BasicScheduler.denoise 的 1→1.0 和 CreateVideo.fps 的 24→24.0 两处原生 FLOAT 规范化；布尔值、其他数字变化均拒绝。

第一段引导必须绑定已审核的原生端点或生产回执。后段必须使用本次上一段实际原生尾帧，保留其 native_id 和 RESULT SHA；不伪造后段尾帧的人审回执。原 Seedance 对白按本段完整保留；小样只允许第一句。工具不导入或调用 v20 的严格片段验证器。

## 片段产物

每个原生 ID 独立保存在 `variants/<版>/qc/Sxx/<prompt_id>/`：

- `BINDING.json`：冻结所有原始依据；同 ID 不接受输入被替换。
- `OBJECTIVE_QA.json`：尺寸、实际解码帧数、24fps、音轨元数据、音量、静音事件及对白识别对照。
- `CONTACT.jpg`：六个实际 MP4 帧与原生最后一帧。
- `GUIDE_VS_ACTUAL.jpg`：输入引导、实际原生首帧、实际 MP4 frame 0。
- `ANCHORBOARD.jpg`：引导、三张声明身份的参考、实际首尾帧；显式传入时附标为 PLANNED 的设计起止图。
- `ASR.json` / 日志：可选现有离线 CPU ASR；关闭 CUDA 可见性，启用离线环境，不触发模型下载。

小样核对 124 帧、288×512 或 384×672；正式每段核对 362 帧、736×1312。RGB MAE / RMSE 仅是注明缩放方式的像素差异，不设“语义通过”阈值。ASR 未检出可能是识别遗漏，尤其 S03 儿童心声，不能冒称实际听审。

CLI 成功 stdout 为 JSON，包含 `status=cpu_qa_complete`、`segment`、`prompt_id`、`video_sha256` 和 `manifest` / `contact` / `guide_vs_actual` / `anchorboard` 的 `{path,sha256}`。`production_approved` 恒为 false。失败返回退出码 2 和 `no_media_retry=true`；仅修复、重跑 CPU 检查，绝不重派媒体。

## 一分钟合片

只接受当前四个不同原生 ID / 视频摘要及其 FINAL_RESULT 绑定。独立 ffprobe 实际核对 1448 帧、736×1312、24fps、60.333333 秒、音视频起点 0、48kHz 双声道、2,896,000 个有效音频样本。输出 `qc/final/FINAL_OBJECTIVE_QA.json` 和 `JOINS_CONTACT.jpg`，并提取 361/362、723/724、1085/1086 三处前后实际帧、计算像素差。像素差不能替代跨镜语义连续性审核。

重复 CPU 检查保留原始文件、冻结输入绑定，复用原 ID。已经登记的派生文件被改动也会拒绝静默接受。历史 CPU ASR 失败日志由现有 helper 归档；重试不访问媒体服务。

## 测试范围

`tests/test_spatial_movie_qa_v24.py` 使用明确标为合成协议夹具的 CPU 色板视频、静音轨和 JSON 回执，实际执行 ffmpeg/ffprobe、独立 CLI、重复运行与最终帧/样本时钟检查。原生未知、ID / 图 / source / 引导 / staged 图 / HISTORY / 旧 PAUSE 篡改在任何 CPU ASR 前阻断。测试不声称产生真实 H3 图像、ASR 模型语义或生产人审通过。

证据：`data/qa/spatial_movie_cpu_v24_20261107.xml`。临时目录指定在项目 D 盘，不使用受限的 C 盘 pytest 目录。真实 canary 的结果另保存在对应原生 ID 的 qc 目录，与合成测试分离。

## 本轮实际 canary_A 结果

合并回归 41 项通过：本工具 23 项，复用的旧纯 CPU helper 18 项，非多次运行累加。首次默认 pytest 临时目录在 C 盘被拒绝，之后显式使用 D 盘独立 QA 临时目录完成回归；没有放宽系统权限。

有限文件监测已等到原生 `9a9025fe-1664-4e31-9356-3df73bf9bccd` technical_saved，随后只执行本工具和离线 CPU ASR，原监测进程正常退出。实际 288×512 / 124 帧 / 24fps，即 5.166667 秒。ASR 原文为“二 哥 今 天 没 偷 到 钱 怎 么 办 呀”，归一后与第一句一致；mean -15.7dB、max -0.7dB。引导缩放后对原生首帧 MAE=0.020454、RMSE=0.031269，仅供数值比较。没有空间 HANDOFF 参数，不冒称 A 使用后续空间设计。

实际文件根：`data/video_generation/spatial_minute_experiments_20261107_v1/variants/canary_A/qc/S01/9a9025fe-1664-4e31-9356-3df73bf9bccd/`。`OBJECTIVE_QA.json` 物理 SHA256 为 `cf7c161d0d8a6d30c7eb2bf6e1f24f5242ca3c7a076c4841041fa3c0ef793191`。同目录 CONTACT、GUIDE_VS_ACTUAL 和 ANCHORBOARD 提交主代理实际查看。本工具不代替其视觉、听觉审核，不自动放行后续生成。

## 2026-11-08 B 原生六段式提示词兼容

新增 `prompt_format=official_ref2va_v29` 的独立纯 CPU 契约：实际 REQUEST 的文本必须是冻结源文本原样直交，保留六个英文 section、五个 Picture 与四个 Subject 标识，中文只在完整的 `<d>[Mandarin Chinese] “原台词”</d>` 内。按四段核对 `B_NATIVE_COMPILED_PREFLIGHT.json` 的 UTF8 SHA、对白数量、末帧引导标志及所绑定的实际 SPEC；禁止重新追加旧中文参考说明。旧 A 的图契约保留原行为，旧报告不改写。

显式传入的 `--spatial-handoff` 现在必须与冻结 SPEC 的 `spatial_handoff` 物理绑定完全一致；设计图仍只标 PLANNED。B 本轮有限文件监测把实际原生 ID、REQUEST / 图摘要与 preflight 的对照保存在 `variants/B/qc/NATIVE_REQUEST_AUDIT.json`，输入摘要另冻存在 `NATIVE_REQUEST_AUDIT_INPUTS.json`。该汇总只读业务原件，仅写 CPU 检查证据，不查询媒体服务或派发任务。

当本段实际 SPEC 声明末帧引导时，另输出 `END_GUIDE_VS_ACTUAL.jpg`：输入 end-guide、原生 last、实际 MP4 最后一帧三列。`OBJECTIVE_QA.end_guide_vs_actual` 记录完整输入来源、原生结果绑定、实际末帧索引及 MAE / RMSE。B/S03 是本轮唯一声明的末帧引导，实际索引为 361。引导图是已绑定的输入目标，不能冒称生成结果或语义审核通过。其他段不会借用别的 PNG 充当末帧引导。

本轮独立测试证据：`data/qa/spatial_movie_cpu_v24_B_native_20261108.xml`（46 项），随后新增末帧对照专项的 `data/qa/spatial_movie_cpu_v24_B_native_end_20261108.xml`。不覆盖此前 XML 或实际 A 的原报告。

B/S01 首次已成功原生保存，但旧 CPU 验证器把 `reference_id` 当成固定 `kind:entity:view`，拒绝了实际版本化的 `room_front_spatial_v26` / `room_side_spatial_v26` 资产键；这是 CPU 字段建模错误，不是媒体失败。修正为核对五个明确的 `(kind,entity_id,view)` 槽位、非空唯一资产 ID，以及原有图像 / 人审 / provenance / staged SHA 全部绑定，不从 ID 文字推断机位。原 exit2 证据保存在 B 的 `qc/CPU_QA_ATTEMPTS/S01_v47_reference_key_failure.json`；只对原生 ID 做 CPU 重跑。新增版本化及不含实体前缀 ID、错误视角回归后，`data/qa/spatial_movie_cpu_v24_B_native_refs_20261108.xml` 为 50 项通过；此前 XML 保留。
