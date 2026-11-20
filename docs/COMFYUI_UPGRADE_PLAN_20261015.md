# ComfyUI 本地升级计划（2026-10-15）

用户要求升级最新 ComfyUI，既有“下载不得放 C 盘”继续适用。目标安装为 `D:/IT/AI_vido/ComfyUI`；2026-10-15 实际读取官方 `releases/latest` 指向正式版 `v0.40.0`，来源和精确 requirements 已保存到 `data/environment_maintenance/comfyui_upgrade_20261015`。GitHub API 的一次公开查询明确 403 限流，改读官方网页重定向，不推断 API 查询成功。

原核心版本 0.28.0，HEAD `83082a51c420a364b15ea5f40d61da74e35b2da5`，Python 3.14.3，torch 2.11.0+cu130。前端、模板和文档包还落后于原核心要求。当前本地改动含四个跟踪占位文件的删除及用户自有未跟踪脚本/目录，升级必须保留。官方远程为 `https://github.com/comfy-org/ComfyUI.git`。

子agent负责备份、Git更新及依赖安装，主agent复核真实接线、启动与节点注册。升级前保存源码归档、原HEAD/状态/差异、pip完整清单、工作流和用户配置；依赖采用pip dry-run报告，只更新正式版要求的包。torch/torchvision/torchaudio优先保留当前CUDA13组合；如新依赖确需改变，先记录具体冲突再处理。对实际待覆盖的包保存可恢复文件或原版本包。不要覆盖用户未跟踪文件，不运行 reset --hard/clean，不改旧项目冻结或调用账本。

模型、输入输出、现有custom_nodes和用户工作流保留。H3的两路下载及校验进程继续，不搬动正在下载的文件。所有升级缓存、wheel、临时文件、日志和检查点均在D盘，本轮不生成图片/视频/音频，不调用付费模型。

验收为：核心达到最新正式版、依赖符合该版requirements、torch CUDA可用、ComfyUI本地HTTP服务可启动、H3文生/图生及参考节点实际出现在object_info。先隔离自定义节点检查核心，再识别实际自定义节点导入情况；不因服务启动就宣称H3实际推理或视频质量通过。正常服务仅绑定127.0.0.1，不外网暴露。升级前没有真实ComfyUI服务需停止；进程核验须匹配Python程序和独立的main.py参数，不把包含检查脚本文字的PowerShell误识别为服务。

已读取目标安装的AGENTS.md。只升级官方代码和依赖，不自行给核心新增联网、遥测或上传代码。故障保留原日志并在必要时恢复备份；恢复不能回滚模型/媒体账本或重新派发旧任务。
