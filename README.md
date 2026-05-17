# AI Douyin

AI Douyin 是一个本地运行的短视频内容生成与抖音运营自动化项目。

它的目标是把内容运营里重复的步骤串起来：关键词生成脚本、TTS 配音、视频合成、上传发布、同步数据、抓取评论和自动回复。

## 当前能做什么

- 关键词或直接文本生成口播脚本和音频。
- 生成单人口播模板视频，并可自动上传到抖音。
- 手动发布已有 mp4。
- 同步抖音视频、抓取评论、自动回复评论。
- 运行 Streamlit 管理后台。
- 半自动生成动漫数字人主讲视频：Edge-TTS + Sonic 角色视频层 + ComfyUI 分段背景 + FFmpeg 合成。

更完整的能力边界见 [docs/CURRENT_CAPABILITIES.md](docs/CURRENT_CAPABILITIES.md)。

## 快速开始

```powershell
pip install -r requirements.txt
copy .env.example .env
python main.py quick --keywords "人生哲学导向"
python main.py presenter --keywords "人生哲学导向" --tts-provider edge --max-segments 16
streamlit run src/web/app.py
```

管理后台默认访问：

```text
http://localhost:8501
```

首次发布到抖音前，需要先登录：

```powershell
python main.py douyin-login
```

## 推荐阅读

1. [docs/PROJECT_INTRO.md](docs/PROJECT_INTRO.md)：项目是什么，解决什么问题。
2. [docs/USER_GUIDE.md](docs/USER_GUIDE.md)：怎么运行常用命令。
3. [docs/CURRENT_CAPABILITIES.md](docs/CURRENT_CAPABILITIES.md)：当前哪些能力可用，哪些仍是半自动。
4. [docs/DEVELOPMENT_PROGRESS.md](docs/DEVELOPMENT_PROGRESS.md)：当前阶段和下一步。
5. [docs/ANIME_DIGITAL_HUMAN_PLAN.md](docs/ANIME_DIGITAL_HUMAN_PLAN.md)：动漫数字人主讲视频路线。

## 当前边界

- `auto-publish` 仍以单人口播模板视频为稳定主线。
- 动漫数字人主讲视频已能半自动生成，但 ComfyUI 分段背景还未正式 provider 化。
- GPT-SoVITS 当前作为可选路线；本机快速测试默认使用 Edge-TTS。
- 抖音发布依赖浏览器自动化，平台页面变化可能影响稳定性。

本项目仅供技术研究与个人使用，请遵守平台服务协议和相关法律法规。
