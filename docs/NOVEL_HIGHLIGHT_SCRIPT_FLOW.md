# 小说高光推广剧本流程

## 目标

小说推广不再默认只取开头章节，也不再固定为 15 秒。流程先扫描授权小说文本中的高光，再选择一个具备前因、冲突升级、转折、情绪峰值和峰值余波的完整区间。视频时长由这段剧情的跨度和情绪台阶决定，默认范围为 45—180 秒。

## 两类素材的职责

- 小说原文是剧情事实来源。人物、关系、对白、事件顺序和悬念都必须回指原文。
- 已分析的热门视频只提供表达统计，例如钩子位置、情绪峰值位置、镜头节奏和冲突呈现方式。视频中的人物、对白和剧情不能进入小说剧本。

高光报告记录小说全文哈希、原文起止引文和绝对字符位置。拆镜前会重新核对这三项，任何一项不一致都会停止，防止报告错绑到另一个版本的小说。

## 两套可切换驱动

- `novel_highlight`：小说高光驱动。小说候选的冲突强度、情绪台阶和原文跨度决定选段与时长；采用小说编辑节奏分配。参考视频不决定剧情结构。
- `reference_video`：参考视频结构驱动。带时间证据的视频分析决定目标时长、钩子位置和峰值位置，再把这套结构映射到小说原文高光；人物、对白和事件仍只能来自小说。缺少有效峰值时间证据时直接停止。

账号配置通过 `domain_config.script_driver` 选择默认驱动；单次运行可以用 `--driver` 覆盖。

## 执行顺序

1. 将完整授权文本按约 6000 字分段扫描，相邻分段保留重叠区，避免高光刚好被切断。
2. 每段最多提出三个候选，并按冲突强度、情绪强度、反转、可视化和情节完整度评分。
3. 合并重叠候选后选出最高分区间，推荐 45、60、90、120、150 或 180 秒的成片长度。
4. 用选中区间拆镜。峰值必须包含至少三个相邻镜头：刺激或关键对白之前、发生当下、发生后的双方反应。
5. 检查总时长是否接近高光报告目标；偏差超过 12% 或 5 秒时重试拆镜。
6. 在剧情与对白锁定后读取小说元数据和简介标签，先判定题材，再建立美术圣经。题材判断必须保存平台分类与简介标签证据，不能把所有小说统一套用 `dream_shaper_xl`。
7. 为每镜补齐景别、焦段、机位、前中后景、焦点、世界光源、微表演、首末状态和切镜理由；人物轴线、发型、服装、道具及光源坐标跨镜锁定。
8. 视觉导演层不得改写原文对白或剧情动作。正文事实和为了保持画面一致而作的发色、服装色、左右手等制作选择必须分别记录。

## 生成高光报告与分镜脚本

```powershell
.\.venv\Scripts\python.exe scripts\analyze_novel_highlights.py `
  data\novels\book.txt `
  --title "小说名" `
  --driver novel_highlight `
  --reference-analysis data\video_analysis\sample.json `
  --output-dir data\novel_highlights\book
```

输出：

- `novel_highlight_analysis.json`：供脚本与拆镜流程读取的结构化报告。
- `novel_highlight_analysis.md`：供人工检查高光、情绪峰值和节奏分配。
- `novel_highlight_storyboard.json`：已记录驱动模式，并绑定选中原文区间、动态时长和峰值放大约束的分镜脚本。
- `novel_highlight_storyboard_directed.json`：题材、画风、美术圣经、空间设计与逐镜摄影表。只有视觉方向审计通过后才可进入画面生成。

## 原文事实闸门

绑定高光后，分镜生成必须同时通过以下检查：

1. 所有角色对白都能在选中原文区间逐字定位；找不到即拒绝并重写。
2. 用独立的低温审计逐镜核对人物、物件、地点、服饰、颜色、关系、动作与结果；泛称不得擅自具体化。
3. 景别、运镜、光线、构图和剪辑属于摄影设计，不作为新增剧情事实；它们不能借机引入新的地点、人物或动作。
4. 短原文受信息容量上限约束。400 字以内高光最高推荐 45 秒，避免为了填时长编写情节。
5. 自动稿在重试上限内不能同时通过结构和事实审计时，记录失败并停止自动放行；人工校正版仍需重新通过对白定位和逐镜事实审计。

命令默认会完成“扫描全文 → 选择高光 → 拆镜”。只检查高光而暂不拆镜时，加 `--analysis-only`；需要覆盖推荐时长时，加 `--target-seconds 90`。

切换为参考视频结构驱动：

```powershell
.\.venv\Scripts\python.exe scripts\analyze_novel_highlights.py `
  data\novels\book.txt `
  --title "小说名" `
  --driver reference_video `
  --reference-analysis data\video_analysis\sample.json `
  --output-dir data\novel_highlights\book_reference_driven
```

## 接入拆镜

```python
import json
from pathlib import Path

from src.content_factory.novel_splitter import split_novel

novel_text = Path("data/novels/book.txt").read_text(encoding="utf-8").strip()
report = json.loads(
    Path("data/novel_highlights/book/novel_highlight_analysis.json")
    .read_text(encoding="utf-8")
)
storyboard = split_novel(
    novel_text,
    novel_title="小说名",
    highlight_report=report,
)
```

需要加长或缩短时可以传 `target_duration_seconds`，但仍需处于 30—300 秒且分镜容量足够。正式小说推广配置默认限制为 45—180 秒。
