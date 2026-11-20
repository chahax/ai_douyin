# 视频失败恢复建议器

`video_recovery/v1` 将机器门禁、人工验收或旧版 Claude Code QA 报告统一转换成一个下一步动作。

它解决的问题不是“再写一版更长提示词”，而是：

- 每轮只允许修改一个工具、资产或参数。
- 手和手机漂移时自动退出普通 I2V。
- 背景漂移时优先回贴静态背景，不重新生成主体。
- 光色漂移时优先执行参考外观锁定。
- 精准口型失败时检查 Sonic 是否真正 `ready`，缺模型则停止。
- 同一问题连续出现三次时停止原工具重试。

## 清单

```json
{
  "template": "video_recovery/v1",
  "id": "anti_fraud_l01_recovery",
  "review_report": "D:\\IT\\AI_vido\\ComfyUI\\output\\qa\\shot_review.json",
  "inventory_report": "D:\\IT\\ai_douyin\\data\\qa\\video_tool_inventory.json",
  "current_tool": "ltx_i2v",
  "intent": {
    "motion": "micro",
    "framing": "medium",
    "camera": "locked",
    "background": "static",
    "contains_hands": true,
    "contains_phone": true
  }
}
```

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_recovery.py `
  docs\examples\video_recovery_ltx_phone.example.json `
  --output data\qa\video_recovery_ltx_phone.report.json
```

输出中的 `route.single_change` 是下一轮唯一允许变化的内容。`locked_fields` 中的 seed、提示词、采样器、分辨率和时长必须保持不变。

当 `status=blocked` 时，Claude Code 必须停止 ComfyUI 队列；当 `status=actionable` 时，Hermes 只准备 `required_assets`，Claude Code 只执行 `single_change`。
