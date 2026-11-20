# ComfyUI 升级与主审交接（2026-10-15）

用户要求升级最新版 ComfyUI，并沿用此前“下载不放 C 盘”的要求。本轮已把 `D:\IT\AI_vido\ComfyUI` 从 0.28.0 快进更新至官方最新稳定版 v0.40.0，提交 `3541246a9c997f4b8c32f9f88f3c985d02021c79`。目标来自官方 releases/latest 的实际跳转，并非 master 的开发版。

## 实际变更与保留

- 14 个官方 requirements 需要的包更新/新增，实际安装报告与事先 dry-run 完全一致；前端 1.55.17、模板 0.11.82、文档 0.5.14、comfy-kitchen 0.2.37、comfy-aimdo 0.5.6。
- 原 CUDA 13 PyTorch 组合保持：torch 2.11.0+cu130 / torchvision 0.26.0+cu130 / torchaudio 2.11.0+cu130。未修改系统驱动、VC 运行库或分页文件。
- Git 原有四个空占位文件删除和全部未跟踪用户文件逐项保留。未更新或停用自定义插件，没有修改项目默认服务、工作流、媒体、账本或冻结记录。
- 新下载、缓存、临时文件均指定在 D 盘。既有 C 盘 Python 解释器和旧模型搜索路径保留；保留搜索路径不代表新下载到 C 盘。
- 配置/工作流备份 38 项，待覆盖原包备份 9033 项，均通过 CRC 与 SHA 校验；升级前源码归档单独保留。

## 主审验收结果

证据根：`D:\IT\ai_douyin\data\environment_maintenance\comfyui_upgrade_20261015`。

- `PRIMARY_REVIEW_CHECKS.json`：实际 tag/commit、requirements 原文、14 包计划/安装一致性、Git 改动保留和 pip check 前后结果均复核。
- `core_HTTP_ACCEPTANCE.json`：禁自定义插件、离线、隔离用户目录，网页 HTTP 200、673 节点，H3 图生视频与参考视频原生节点注册成功。
- `normal_HTTP_ACCEPTANCE.json`：带现有自定义插件、离线、隔离用户目录，网页 HTTP 200、1058 节点，同样验证 H3 原生节点。两次都识别 RTX 5070 Ti / 16GB 显存与 CUDA 后端。
- 两个验收服务均已停止，没有留下占用 8188/8189 的测试服务。验收没有提交生成工作流，也没有加载 H3 权重做推理；不能把本结果写成 H3 推理成功或内容通过。

第一次短时验收在 Windows DLL 冷加载阶段超时，失败证据保存在 `attempts/core_initial`；后续定位过程保存在 `attempts/core_trace_stopped`。逐 DLL 日志证明加载持续前进，延长一次等待后核心启动成功：约 405 秒，随后热启动带插件约 21 秒。没有用重装 torch、关闭证书验证或更换 DLL 掩盖问题。曾将现有 H3 文件合并进程暂停 60 秒排查 I/O，随后按原 PID 恢复；相关回执保存，未终止或重新派发下载。

## 已知限制

旧 `ComfyUI-LTXVideo` 插件新增导入不兼容：它引用新版核心已移除的 `interleaved_freqs_cis`。其源文件保持原状，没有盲目更新整组自定义插件。该插件对应的 LTX 模型已按用户此前要求移除，H3 原生节点不依赖它。

原有 `_liveportrait_install` 残留目录缺 `__init__.py`、KJNodes 可选 PatchTritonVAE 缺 triton，以及六项旧 pip 依赖告警仍存在；六项 pip check 与升级前逐行一致。原内置 `nodes_glsl` 缺 comfy-angle 的问题已被新版官方依赖补齐。

## H3 下载任务衔接

此前已授权的 H3 下载在本轮后台完成：7/7 文件、64956607775 字节（约 60.50 GiB），SHA256 与官方 Hugging Face/ModelScope 的同文件一致，safetensors 头与偏移完整。三个下载/校验任务均正常退出，未派发媒体生成。

权重目录：`D:\IT\AI_vido\ComfyUI\models`。

下载凭据：`D:\IT\ai_douyin\data\model_maintenance\minimax_h3_20261015\DOWNLOAD_VERIFIED_COMPLETE.json`。此下载时点回执保留其原运行环境快照；当前升级状态以同目录 `RUNTIME_COMPATIBILITY_CHECK.json` 与可变的 `STATUS.json` 为准。最终状态明确保留 `inference_tested: false`。

## 备份位置

`D:\IT\ai_douyin\data\environment_maintenance\comfyui_upgrade_20261015\backup`

可从该目录恢复升级前核心与被替换依赖；恢复须在停止 ComfyUI 后单独进行，并保留当前状态，不能覆盖模型、媒体、用户工作流或项目账本。本轮没有执行恢复。

后续用户已另行授权并完成本地 H3 低分辨率5秒、15秒联合音视频生成与保存验证，见 [本地短片测试记录](MINIMAX_H3_LOCAL_SMOKE_PLAN_20261015.md)。此为升级验收之后的新执行证据，上文“未做推理”保留其升级验收时点含义；当前运行范围以该测试原回执与 SUMMARY.json 为准，视频内容仍待用户人工审核。
