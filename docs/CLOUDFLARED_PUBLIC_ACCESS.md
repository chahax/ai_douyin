---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-14
model_usage: cloudflared 公网访问使用说明。用于把本机 Streamlit 管理后台临时暴露给公网用户访问。
---

> 文档状态：当前主线文档。用于临时公网访问管理后台。

# Cloudflared 公网访问

更新时间：2026-05-14

## 当前用途

管理后台默认只监听本机：

```text
http://127.0.0.1:8501
```

如果需要给公网用户临时访问，可以用本机已安装的 `cloudflared` 创建 Cloudflare Quick Tunnel，将公网链接转发到本机 `8501`。

当前已验证本机存在：

```text
C:\Program Files (x86)\cloudflared\cloudflared.exe
```

## 启动本地后台

先确认 Streamlit 后台已启动：

```powershell
C:\Python314\python.exe D:\IT\ai_douyin\scripts\run_streamlit_web.py
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health
```

返回 `200` 表示本地后台可用。

## 临时公网隧道

前台运行，方便直接看到公网 URL：

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8501 --no-autoupdate
```

日志里会出现类似：

```text
Your quick Tunnel has been created! Visit it at:
https://xxxx.trycloudflare.com
```

这个 `trycloudflare.com` 地址就是公网访问地址。

## 后台运行

建议把日志写入项目目录：

```powershell
$logDir = "D:\IT\ai_douyin\data\logs"
$out = "$logDir\cloudflared_tunnel.log"
$err = "$logDir\cloudflared_tunnel.err.log"

Start-Process `
  -FilePath "C:\Program Files (x86)\cloudflared\cloudflared.exe" `
  -ArgumentList @("tunnel", "--url", "http://127.0.0.1:8501", "--no-autoupdate") `
  -WorkingDirectory "D:\IT\ai_douyin" `
  -WindowStyle Hidden `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err
```

查看当前公网 URL：

```powershell
Select-String -Path D:\IT\ai_douyin\data\logs\cloudflared_tunnel.err.log -Pattern "https://.*trycloudflare.com"
```

查看进程：

```powershell
Get-Process cloudflared
```

停止隧道：

```powershell
Get-Process cloudflared | Stop-Process
```

## 当前临时地址

本次启动生成的临时地址：

```text
https://thomson-interface-trails-letting.trycloudflare.com
```

注意：Quick Tunnel 地址不是固定域名。cloudflared 进程停止或重启后，通常会生成新的公网地址，请以日志中的最新地址为准。

## 安全注意

- 该地址会把管理后台暴露到公网，请不要公开发到不可信渠道。
- 公网访问前必须确认管理后台账号登录、角色权限、用户用量限制已经启用。
- 抖音登录窗口、发布调试模式、SMTP 配置等涉及敏感能力，不建议给低权限用户开放。
- 临时 Quick Tunnel 没有稳定性保证。长期使用建议配置 Cloudflare 账号下的 named tunnel 和固定域名。
