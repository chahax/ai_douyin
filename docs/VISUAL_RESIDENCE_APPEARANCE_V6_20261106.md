# 共享住所外观参考 v6（2026-11-06）

旧 material 路线两次真实审核均未通过，原始结果保留到界。其问题是让灰色平涂墙、棕色饰面小图必须证明材质身份和纹理，超出了共享住房风格的需要。v6 是独立的 appearance 审核范围，不将旧结果改成通过。

## 显式启用与原图复用

只有新 run 配置以下两项才进入新合同：

```python
style_reference_contract = "appearance/v1"
style_reference_parent_manifest = "<已冻结 v2 材质 bundle 的 MANIFEST.json 绝对路径>"
```

默认仍走旧 material 行为。组定义、style_version、房间 design_version、几何和视觉 profile 不因新合同变化，因而可复用已经正式通过布局审核的 master。

新合同从明确指定的父 manifest 验证当前 master 身份、版本、原图 SHA、组摘要和实际裁剪重算结果。复制原来三张裁剪的相同 PNG 字节，不再选 ROI、提亮或重生成。新 manifest 指纹包含合同及父 manifest 路径/SHA；新 schema 为 `residence_appearance_reference/v6`，与旧 material 文件夹、失败结果和 READY 完全分开。

## 新审核范围

`review_residence_appearance` 返回 `residence_appearance_visual_review/v6`，`approval_scope="appearance/v1"`。

完整 master 只作为 VLM 上下文，用于整体色调、可见做工档次、磨损和写实感。每张裁剪独立检查 `usable_color`、`visible_finish`、`layout_free`：均匀灰色涂层或棕色饰面可以提供可用外观，无须出现木纹，也不证明隐藏基材。实际全暗、遮挡、颜色不可读或包含完整布局的图仍不能通过。

所有必需项必须严格为 true；null、字符串、错位 slot、错误源 SHA 或未知结果均不得建立 READY。回执固定 `material_identity_approved=false`、`layout_approved=false`、`novel_fidelity_approved=false`。独立的房间布局审核继续执行。

Klein 生成方式不变：本房 guide＋与本房材质兼容的真实裁剪，需要时另加本房自己的 canonical front。完整 master 不进入其它房生成。新 source appearance 核验上限一次；回执已保存后只读取，不重新派发。只有 source READY 后才生成最多两张 sibling front；本轮 `max_repair_rounds=1` 使目标失败时停止，不自动再画。

## 绑定和验证

`reference_contract` 进入新 manifest、READY、request.binding、派生资产 provenance 和后续审核绑定。父文件变化、master 更新、裁剪变化或新旧结果 schema 混用都会被拒绝。group/design_version 不改变，但新参考合同仍通过依赖和首图/H3 回执校验阻止旧证明误用。

v6 存储及接线 **10 项通过**，33.62 秒，证据 `data/qa/residence_appearance_storage_v6.xml`。包含禁止 ROI 重选、三图 SHA 保持、旧失败不升级、master 不重生、source 失败只调用一次、真实临时 HTTP 只生成两个 sibling front，以及错误 scope/材质身份声明/null 检查拒绝。

旧 material 兼容 **24 项通过**，54.49 秒，`data/qa/residence_material_compat_v6.xml`。最终统一发布回归由主代理另行冻结统计，不累加阶段测试次数。上述协议夹具不是语义验收；唯一真实 source appearance 核验和后续图片由主代理运行，环境开发代理没有发起 GPU 或模型请求。
