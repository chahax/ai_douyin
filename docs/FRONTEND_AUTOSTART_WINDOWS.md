# Windows 前端开机自启

## 前端入口

项目使用现有 Streamlit 管理后台：

```text
http://127.0.0.1:8501
```

视频生产线重置后，“Seedance 用量”已从当前侧边栏移除；历史页面代码保留，打开管理页不会调用付费视频接口。

管理后台登录成功后会在当前浏览器保存签名登录令牌，默认 30 天内刷新、关闭标签页或重启浏览器无需再次输入密码。令牌不保存明文密码；点击“退出登录”会同时删除该浏览器的登录令牌。

## 后台启动器

`scripts/run_streamlit_web.py` 使用项目环境启动 `src/web/app.py`，并提供：

- 仅监听本机 `127.0.0.1:8501`。
- 使用 `pythonw.exe` 时不显示命令行窗口。
- 8501端口已运行时跳过重复启动。
- PID写入 `data/logs/streamlit_web.pid`。
- 标准输出和错误写入 `data/logs/streamlit_combined.log`。
- 进程正常退出时清理PID文件。

## 安装当前用户登录自启

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_frontend_autostart.ps1 -StartNow
```

计划任务名称：

```text
AI_Douyin_Streamlit
```

任务以当前Windows用户的有限权限运行，仅在该用户登录后启动；不会申请管理员权限，也不会向公网开放端口。

## 查看状态

```powershell
powershell -ExecutionPolicy Bypass -File scripts\frontend_status.ps1
```

正常状态应包括：

```text
TaskInstalled : True
TaskState     : Running 或 Ready
Health        : ok
```

## 取消自启

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_frontend_autostart.ps1
```

取消计划任务不会删除项目、配置、日志或生成视频。
