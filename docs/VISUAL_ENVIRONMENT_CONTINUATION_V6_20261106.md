# 已审核背景的显式机位续跑（2026-11-06）

独立 `visual_environment_continuation_v6` API 为同一本书、同份固定稿、同一住所风格的已审核 front 增加 reverse/side。默认 pipeline.prepare 仍把参考根绑定到自身 run；只有包含完整有效 continuation 证明的新 sibling run 才能只读复用原参考根。

## 使用方式

```python
from src.content_factory import visual_environment_continuation_v6 as continuation

origin = "D:/IT/ai_douyin/data/visual_asset_pipeline/runs/novel_residence_appearance_20261106_v6"
new_run = "D:/IT/ai_douyin/data/visual_asset_pipeline/runs/novel_residence_multiview_20261106_v7"

# 只读：不建 run、不创建作业、不调用模型。
derived = continuation.derive(origin, new_run, allowed_prefix="residence_multiview_v7")

# 只登记新 run；之后仍由既有 CLI 执行。
prepared = continuation.prepare(origin, new_run, allowed_prefix="residence_multiview_v7")
```

`views` 默认 `("reverse", "side")`，可显式只选其中一个。拒绝其它视图、重复视图、原 run 自身、嵌套目标以及不安全输出 prefix。原图必须是 background-only front 来源，不把 continuation 链继续泛化为任意任务来源。

派生 packet 保留 book/source、原组、布局、相机、设计版本、材质和审核语义，只增加所选 `required_views`；移除无关人物 `import_manifest`，保持 characters/shots 为空。新配置仅允许显式新输出 prefix，图像服务、视觉模型和其它源配置固定；强制每个新视图最多一图、两次已知审核、零 source-reference 审核，无首图、视频或发布。

## 精确源证明

证明绑定原 PLAN 与 packet SHA、固定稿实际 SHA、每个 front 当前资产 ID/版本/图像 SHA/审核 SHA/来源摘要、guide 图像与 manifest SHA、组定义、已审 master、原完整参考 MANIFEST/READY/审核/父 manifest 和 crop 的实际 SHA。

不绑定整个 library INDEX 的总 SHA：新 reverse/side 的合法登记不会使下一步失效。也不冻结 mutable STATE 的内容或状态标签；资格以当前已审核 front 与真实引用核验为准。读取失败不会当作正常。

新 run 的 prepare/status 都重新只读核对来源。源 front 更新或被撤销、固定稿/guide/原参考/parent/crop 变化、预算或模型配置被改动都会拒绝继续。该 API 不替换过期源，不自动重派未知原生请求。

## 引用复用与审核

continuation 的参考准备阶段只读加载原 READY 和完整审核回执，仅更新新 run 的继承状态。不会调用参考的 prepare、accept 或 source 模型审核，不创建新参考目录、不复制改写原 bundle、不洗换来源 SHA。

实际新视图仍以本房对应机位 guide、本房已审核 front 和兼容的实际材质裁剪作为条件。它们独立接受布局、方向、同房身份及 appearance 审核；测试通过不代表六张新图语义通过。

## 验证边界

针对性 **17 项通过，0 失败/跳过**，278.91 秒，`data/qa/environment_continuation_v6.xml`。包括真实临时 HTTP 六次新图请求、零 source 审核、禁止 reference prepare/accept、原 run 树 SHA 不变、新 library 行不影响续跑、原状态标签可变、来源和引用篡改拒绝，以及预算和设计变更拒绝。关键联集由主代理另行冻结统计，不累加旧整套次数。

实际 origin 的原三 front 资格由主代理独立核对，可复用版本为苏墨房间 v2、孩子房 v2、厨房 v3。开发代理只实现并测试续跑，没有对真实服务发起 GPU/模型请求，没有改旧 PLAN/STATE/bundle、原 H3 暂停、服务或账号。
