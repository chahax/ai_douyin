# video_recipe/v1 视频配方

`video_recipe/v1` 用一份 JSON 固定以下内容：

- 镜头意图
- 已生成视频、参考图和人物蒙版
- 是否启用参考外观锁定
- 动作保留强度
- 输出分辨率与帧率
- 静态区、动态区和手持物验收阈值

执行器会自动完成：

```text
读取意图并选择控制模式
→ 校验输入素材
→ reference_appearance_lock
→ FFmpeg 插帧与缩放
→ 生成 video_control/v1 清单
→ 自动质量门禁
→ 输出 accepted / rejected 报告
```

## 命令

仅检查配方，不生成：

```powershell
.\.venv\Scripts\python.exe scripts\video_recipe.py `
  docs\examples\video_recipe_subject_lock.example.json `
  --dry-run
```

正式执行：

```powershell
.\.venv\Scripts\python.exe scripts\video_recipe.py `
  docs\examples\video_recipe_subject_lock.example.json `
  --report data\qa\video_recipe_example\run.report.json
```

进程退出码：

- `0`：生成成功且门禁通过
- `2`：生成成功但门禁拒绝
- 其他：清单、素材、FFmpeg 或运行错误

## Hermes 职责

Hermes 只负责准备素材和配方，不负责自行宣布视频通过：

1. 生成或选择故事板、驱动视频和蒙版。
2. 填写 `video_recipe/v1`。
3. 使用 `rect_normalized` 声明背景、人物、手机和手部区域。
4. 不修改门禁报告。
5. 把配方路径交给 Claude Code。

建议提示词：

```text
请为镜头生成一份 video_recipe/v1 JSON。
只填写可验证事实，不自行标记通过。
固定镜头、静态背景、单人物、可见手机。
输入必须包含 generated_video、reference_image、subject_mask。
appearance_lock.enabled=true，motion_gain=0.55。
输出 704x1248、30fps。
使用 rect_normalized 声明两个静态背景区、人物动态区和 phone_hand 动态区。
保存后只返回 JSON 路径和素材路径。
```

## Claude Code 职责

Claude Code 只执行清单和读取机器报告：

1. 先运行 `--dry-run`。
2. 检查推荐工具、输入路径、输出尺寸和区域。
3. 正式运行配方。
4. 只在 `status=accepted` 且 `gate.passed=true` 时进入配音或合成。
5. 被拒绝时保留报告，只调整一个参数后重跑。

建议提示词：

```text
执行指定 video_recipe/v1。
先 --dry-run，不要改输入素材。
干跑无错误后正式执行，并保存 recipe report。
只有 status=accepted 且 gate.passed=true 才能继续。
若失败，停止后续生产，列出 issue code；下一轮只允许修改一个参数。
不要修改 D:\IT\ai_douyin 之外的调度代码。
ComfyUI 模型和原始输出位于 D:\IT\AI_vido\ComfyUI，请勿混淆两个项目目录。
```

## 区域写法

推荐使用 0–1 的归一化坐标：

```json
{
  "phone_hand": {
    "rect_normalized": [0.253, 0.475, 0.372, 0.258],
    "motion": "dynamic",
    "max_frame_distance": 5.0,
    "max_anchor_distance": 10.0,
    "max_active_pixel_ratio": 0.15
  }
}
```

执行器会按照最终输出尺寸转换为像素坐标，分辨率变化时无需重新计算。

## 已验证样例

- 配方：`docs\examples\video_recipe_subject_lock.example.json`
- 输出：`data\qa\video_recipe_example\final.mp4`
- 结果：`accepted`
- 分辨率：704×1248
- 帧率：30 fps
- 背景活动比例：0.0
- 人物活动比例：0.0165
- 手机手部活动比例：0.0898
