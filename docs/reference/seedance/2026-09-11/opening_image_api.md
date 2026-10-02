# 原生开场图用于首镜

核查日期：2026-09-11（北京时间）。这是一份接口参数摘要，不是生成结果审核。

- 当前账号真实 `GET /api/v3/models` 目录返回 `doubao-seedream-5-0-pro-260628`。目录可见不等于账号已经开通，不自动开启服务。
- 本项目单张开场图使用 `POST /images/generations`，请求仅带 `model`、`prompt`、`size=1440x2560`、`response_format=url`、`watermark=false`，不带参考图或音轨。
- [官方图像生成教程](https://docs.byteplus.com/api/docs/ModelArk/1824121)列出同版 Seedream 5.0 Pro 支持自定义宽高，总像素范围 921,600–4,624,220，比例范围 1/16–16；1440×2560 在范围内。该教程的国际站模型前缀不同，实际请求使用国内服务目录返回的精确模型 ID。
- 上述教程说明输出图片 URL 保存24小时。此下载地址寿命与原生媒体的30天可信来源窗口分别检查，不能混为一谈。
- [国内方舟肖像参考说明](https://ark.volcengine.com/region:cn-beijing/docs/82379/2608626?lang=zh#trust-model-output)及本地保存的 [原文](../2026-09-08/portrait_reference_official.md)说明：Seedream 5.0 lite/pro 纯文生图的含人脸原图，可以在同账号规定窗口内用于 Seedance。保留原平台URL及下载原始字节，不裁剪、重编码或改造失败尾帧冒充原图。
- 当前环境已安装的官方 `volcenginesdkarkruntime/resources/images/images.py` 提供 `images.generate`。无需为了这个接口重新安装 SDK。

开场图只从已审 S01 的初态、人物外观、场景、机位和光线取值。图生成后仍须实际检查座位、身份、手、纸和唯一一支笔；文本校验、API成功或原图来源合规都不代表画面通过。S02以后仍只继承上一段审核通过的原始尾帧。
