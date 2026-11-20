# 自有资产库追加导入合同

新增图片以每批独立JSON放在`data/visual_asset_library/personal_catalog_v1/imports/*.json`。工具读取该目录并追加到原32图；旧图、原兼容库及原文件不搬动。首度成功入库后，清单文件自身和来源证据均列入SHA256基线；修改或删除旧清单/证据会拒绝重建，不重新接受新字节。新增版本写新清单，不能编辑旧清单。

顶层为`schema: personal_local_asset_import/v1`和非空`assets`数组。每项字段：

| 字段 | 要求 |
|---|---|
| `asset_id` | 非空稳定ASCII ID，仅字母、数字、点、下划线、短横线；全库不得重复 |
| `name` | 非空展示名称；同名可保存独立ID/版本，不覆盖 |
| `kind` | `character`、`scene`、`composition`、`prop`或`costume` |
| `style` | `photoreal`或`3d_soft_doll` |
| `series_id`, `version` | 非空；新增清单间同一series/version组合不得重复，构图首尾图分别使用独立series或version |
| `image` | `{path, sha256}`，指向已保存的PNG/JPEG/WebP；核文件头、扩展MIME、完整SHA256 |
| `source` | `{receipt: {path, sha256}}`或`{evidence: [{path, sha256}, ...]}`，可同时提供；至少一份真实本地来源文件。可附`service`标识 |
| `selection` | `{status, scope, project_id?}`；status仅`assistant_selected`或`unselected`；scope非空，说明本片局部用途/委托范围 |
| `user_media_approval` | 必须显式为`null` |
| `human_identity_approval` | 可省略，提供时只能为`null` |
| `details` | 可选描述对象；不作为批准或原生服务资格 |

所有文件路径可用项目根相对路径或项目内绝对路径；拒绝外部URL、UNC/网络路径、`..`越出项目及解析后越界的链接。来源证据与图片均要求存在且符合清单哈希。不能将视频作为图片导入，不做视频解析或内容检查。

以下仅为结构占位说明，不是可导入资产，不保存为imports清单；必须用真实输出位置与完整哈希替换占位符：

```json
{
  "schema": "personal_local_asset_import/v1",
  "assets": [{
    "asset_id": "<稳定ID>",
    "name": "<展示名>",
    "kind": "scene",
    "style": "photoreal",
    "series_id": "<场景系列>",
    "version": "v1",
    "image": {"path": "<项目内原图路径>", "sha256": "<真实64位SHA256>"},
    "source": {
      "service": "comfyui_h3",
      "receipt": {"path": "<项目内原生服务回执路径>", "sha256": "<真实64位SHA256>"},
      "evidence": [{"path": "<生成及图片选择记录路径>", "sha256": "<真实64位SHA256>"}]
    },
    "selection": {"status": "assistant_selected", "scope": "<本次图片委托与场景固定范围>", "project_id": "<当前片项目标识>"},
    "user_media_approval": null,
    "human_identity_approval": null,
    "details": {"purpose": "<场景/首构图/尾构图等>"}
  }]
}
```

从项目根运行：

```powershell
python scripts/manage_personal_assets_v1.py build
python scripts/manage_personal_assets_v1.py verify
python scripts/manage_personal_assets_v1.py list --query h3
```

`build`遇到新清单错误会写`VERIFY_LATEST.json`与事件，返回非零，并保留旧`CATALOG.json`原字节。已入库来源变化同样拒绝，不改期望哈希。成功追加保留旧catalog快照。索引中的`current_casting`仍为unbound、`current_media_approval`和`api_native_eligibility`仍为null；图片委托选择单独存于`details.selection`，不提升为人物身份批准或视频批准。主agent仍须记录实际参考输入序号和本片角色绑定。

本次实现仅扩展本地导入器；未创建实际H3素材清单、未调用模型/媒体、未改旧生产兼容库。新增6项导入完整性测试连同原8项共14项通过。
