# 图像生成与视觉审核资源交接（2026-11-06）

新管线配置 `release_comfy_before_review: true` 才启用，缺省 false；旧冻结 run 不增加资源探测或卸载操作。开关必须是布尔值。

图像 worker 与外部视觉 worker 是不同进程。ComfyUI 的 `--cache-none` 清理节点缓存，并不保证所有模型权重离开显存。本机代码的正常任务末尾仅在关闭 smart memory 时主动卸载，因而不能把队列空当作显存充足。

`visual_asset_pipeline_v3.gpu_access` 在 `GPU.lock` 和 `VISUAL_GPU.lock` 两把锁同时持有期间执行资源交接。严格校验原生 running/pending 队列的字段和每行结构，只有队列完全空闲才继续。实测可用内存至少 6 GiB、显存至少 5 GiB 时直接进入审核；不足时先核对同一 Comfy 服务的 input/output 目录，再仅向该服务发送 `/free` 的 `unload_models=true, free_memory=true`。

Comfy 的 HTTP 200 只表示已接受异步 flag。调用后持续检查队列及实际 RAM/VRAM，达到门槛后才进入视觉 worker；保持两把锁直至 worker 返回。不会重启服务、改启动参数或打断在途任务。内存探测不创建 CUDA 上下文。

每次需要卸载时，在原 `gpu_lock_root/GPU_HANDOFF/<服务绑定>/attempts/<独立ID>` 保留 REQUEST、CLAIM、RESPONSE 和状态。已确认接收但资源未达标时保留 PENDING，下次只续查，不重复发 `/free`。连接中断、非确定响应或 CLAIM 无回执保留 UNKNOWN，禁止自动重发，也禁止后续图像或视觉派发；不删除未知标记来冒充恢复。明确 400/404/422 作为已知拒绝保存。

本地临时 HTTP 服务的资源模块 **22 项通过**，13.41 秒，证据 `data/qa/visual_gpu_handoff_v4_final.xml`。覆盖双锁、运行中和排队中不卸载、无效队列、充分资源跳过、异步确认、资源超时续查、响应未知不重发、不接续模型、服务目录不符和只读测量失败。此前新 20 项与原管线 65 项同跑的 85 项记录在 `data/qa/visual_gpu_handoff_v4.xml`；最终统一发布回归单独统计。

开发代理只对真实 8190 做只读采样，未实际发送 `/free` 或模型请求。当前主代理的真实 Klein 完成后资源充分，因此新开关在该现场会跳过卸载；不能把临时 HTTP 测试当作真实卸载验收。
