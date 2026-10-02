# 分析驱动的视频生成流程

`analysis_to_video/v1` 把账号绑定、热门内容研究、机会筛选、15 秒脚本、分镜、
本地预览和质量检查串成一条可审计链路。它不会自动发布视频。

## 流程

1. 通过 `AccountRuntimeContext` 读取运营账号、浏览器环境和已绑定抖音身份。
2. 优先使用本次成功分析；本次采集受登录或安全验证阻断时，只允许回退到时效内、
   含真实视频 ID 的最近有效快照，并在清单中记录 `valid_snapshot_fallback` 和原因。
3. 机会必须与当前快照有视频交集，并通过有效期、不同视频样本量、账号相关度和
   内容置信度检查。
4. 法律账号还必须命中账号配置的业务范围。比如只做婚姻、劳动、合同、债务和
   交通事故时，刑事热点即使分数最高也不能自动进入制作。
5. 生成 A/B 版本的三段脚本，时间线固定为 0—5、5—10、10—15 秒。
6. 法律内容必须附至少一个 `npc.gov.cn`、`court.gov.cn` 或 `gov.cn` 权威来源，
   热门视频只能作为用户兴趣证据，不能作为法律依据。
7. 可选择只生成清单、生成配音与背景资产，或生成本地 MP4。视频模式会检查实际
   时长、画幅、帧率、编码、音视频流、像素格式与抽样帧。
8. 无论预览是否通过，发布闸门都保持关闭，直到管理员审核脚本和成片。

## 命令

只生成分析、选题、脚本和分镜：

```powershell
.\.venv\Scripts\python.exe main.py analysis-video `
  --account-id account01 `
  --render-mode plan `
  --authority-source "https://www.court.gov.cn/zixun/xiangqing/212721.html"
```

生成不发布的本地测试视频：

```powershell
.\.venv\Scripts\python.exe main.py analysis-video `
  --account-id account01 `
  --render-mode video `
  --quality-profile preview `
  --authority-source "https://www.court.gov.cn/zixun/xiangqing/212721.html" `
  --authority-source "https://www.npc.gov.cn/npc/c2/c30834/202401/P020240108541839745616.pdf"
```

管理页“热门选题 → 选题卡 → 新视频生成流程（不发布）”提供相同入口。

## 产物

每次运行写入独立目录：

```text
data/video_preproduction/analysis-video_<id>/
├── manifest.json
├── video_quality_report.json       # 视频模式
└── video/
    └── presenter_<timestamp>.mp4   # 视频模式
```

`manifest.json` 保存账号身份、分析快照、降级原因、候选淘汰统计、选中机会、
脚本与分镜、权威来源、全部闸门结果、实际成片时长和媒体质量报告路径。

## 2026-09-04 account01 测试

- 本次实时抖音搜索出现可见的“点击两个形状相同的物体”验证，未自动处理。
- 流程回退到 24.7 小时内最近有效快照：206 条观察、133 个不同视频、78 个内容分析。
- 未选择分数最高但超出服务范围的“刑事律师”，选择由 10 条视频支持、命中
  “婚姻家事”的“法律咨询”机会。
- 账号相关度 64.7，内容置信度 41.85。
- 生成三段共 60 字脚本；本地测试片实际 13.575 秒。
- 测试片为 H.264/AAC、540×960、约 24 fps，结构与时长检查通过；未发布。

