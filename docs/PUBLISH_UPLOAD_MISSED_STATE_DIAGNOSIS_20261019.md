# 本次追加发布的上传识别诊断与修复计划

本次用户“追加”对应唯一9681ccee331040df9c4d946e9593ae16，16:46:53明确upload_failed，未进入标题、标签、声明、提交或评论，无作品ID。原生journal及上传timeout UI表明同页“作品未见异常”和“重新上传”均存在；完整journal证明16:44:55已存bytes/cancel传输证据，UI03/04分别出现检测中5%/9%；仅checking节点绑定未成功，reupload候选1但usable=false。先前初步摘要“漏传输状态”已由完整证据纠正。截图有“视频预览功能”新手提示；不能仅据截图确认遮挡/视口是唯一原因，不能把已在编辑页写成正式上传通过。

先保存终态和完整原生证据；子agent只读分析此次与此前成功上传的采样、初始化与可用性差异，提出最小可复用修复。主agent审查方案后才修改。当前优先方向：唯一原重新上传候选在读回资格前有界native滚动进入视口，仍保留原命中/可用性/身份/导航门；补充可用性拒绝原因。无需选择前观察大改。v6凭短暂上传成功标志提前返回，不能证明重上传可用性门曾实平台通过。不得仅以静态clean、预览、发布按钮或没有进度条放行；不得放松未知/失败/导航或输入身份门，不读媒体、接口、凭据或内部状态。

原v7一次已用，日31→32，旧冻结/失败/上限保持。无再次上传、自动重试、部署重启或增加预算。本轮先完成可审查诊断及有必要的离线修复验证。

## 已核实的最小实施边界

原upload_check_proof RPC能调用真正Playwright ElementHandle原生scroll_into_view_if_needed，无需增加worker启动串或公开RPC。只有原proof有效、已知editor、唯一exact重新上传且有限诊断明确offscreen时，每selection最多一次原生滚动；不点击重新上传或关闭提示。滚动前后原document/URL/generation/文本叶/交互control必须保持，重查唯一候选及原disabled/inert/pointer/viewport/hit-test。onscreen遮挡仍拒绝。滚动导致导航、候选替换或未知必须终止本次检测，旧bytes分支不得绕过。原checking→clean和bytes/cancel→两次clean继续要求真实状态证据；静态clean本身不能通过。

子agent限定helper及必要workflow未知拒绝接线、小量真实DOM/worker离线案，主agent审查实际接线和关键失败用例。AI/tag/单次提交逻辑与旧授权/账本不变。修复不部署、不上传。
