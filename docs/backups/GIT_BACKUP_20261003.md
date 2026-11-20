# 2026-10-03 创作流程版本备份

用户要求继续目标前先上传 Git 保存副本。备份已保存到 `codex/backup-ai-creative-20261003`，提交 `97a0c3a6ce37ac63b3741a508a4d538e8db65d5e`。远端为 GitHub 登录用户 chahax 自己拥有且具 ADMIN 权限的原配置仓库 chahax/ai_douyin（PUBLIC）。只读身份核对后完成推送，远端提交一致。

3392 个文件包含当前源码、脚本、测试、配置、文档、治理包、冻结文本试跑及本轮验收报告；如实记录当前 258 项既有删除。原 HEAD 2baa701 作为父提交保留。原工作分支 codex/content-opportunity-framework、工作树及原暂存区未切换或清空。

未纳入密钥、登录状态、会话密钥、运行数据库、模型权重、媒体、重复测试缓存与临时工作目录；这些仍在本地。不是全部本地运行数据的灾备副本。精确文件范围和原始 SHA256 见 [清单](git_backup_20261003_manifest.json)，远端核对见 [回执](git_backup_20261003_receipt.json)。

已从 Git 对象回读清单中的全部 3391 个原文件，原始 SHA256 均一致；清单本身是额外第 3392 个文件。见 [对象验证](git_backup_20261003_verification.json)。为了保留冻结材料原字节，恢复时必须禁用行尾自动转换，例如在新目录中 `git -c core.autocrlf=false clone --branch codex/backup-ai-creative-20261003 git@github.com:chahax/ai_douyin.git`，之后 `git config core.autocrlf false`，按清单验 SHA256。不要直接覆盖当前工作区或据备份复领预算。

此版本尚无已采用的完整剧本、整片导演计划、逐镜物理表演与制作交接。离线验证和历史回执保持各自状态，备份不构成创作质量通过。
