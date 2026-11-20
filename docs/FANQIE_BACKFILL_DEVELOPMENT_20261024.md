# 番茄发文回填开发与观察

本轮用户授权打开网页、检查前后端地址并先开发流程；未授权申请新推广词、真实发布或真实回填。使用已有内置浏览器番茄会话观察，不复制登录凭据，不占用抖音专属环境。

## 2026-10-24 真实页面

- 申词记录： https://kol.fanqieopen.com/page/promotion-list?tab_type=2&top_tab_genre=-1
- 批量记录： https://kol.fanqieopen.com/page/batch-history
- 当前页面显示5条旧推广记录，4条强制失效、1条审核不通过，没有可回填的生效任务。不创建新词来伪造验收条件。
- “批量回填发文”打开“批量上传发文-番茄小说”弹窗；支持一个xlsx文件，最多2万行，未上传时提交按钮禁用。
- 实际模板：https://lf3-reading.fqnovelstatic.com/obj/novel-static/34feab9a366dc5cba9aec875f96b54f7.xlsx
- 模板列为：别名、发文日期（YYYY/MM/DD）、发文链接、抖音号（个人主页对外展示的抖音号）；第5列是说明。模板要求保留首行、删除示例，每个链接一行。账号UUID/open_id/sec_uid不能替代展示抖音号。

## 前端代码可见的内部接口

公开main脚本及其引用的async-main已下载用于静态分析，无Cookie或token。证据目录 data/fanqie_backfill_development/20261024，observed_endpoint_contracts.json保存路径模板、方法和字段名。未重放请求、未取得认证头或执行写接口；v:version的实际替换及响应契约尚未实测，不猜版本或枚举。

- GET /api/platform/promotion/plan/list/v:version：推广任务列表。
- GET /api/platform/promotion/post/list/v:version：原别名的发文列表。
- GET /api/platform/promotion/post/link/parse_new/v1：链接解析，字段post_link、alias_id、post_date、post_platform_type、promotion_type、aweme_uuid。
- POST /api/platform/promotion/post/create/v:version：单任务发文回填，字段alias_id、post_records、alias_name、alias_type、promotion_type、materials、alias_post_type等。
- POST /api/platform/promotion/batch_task/create/v:version：批量任务创建，字段excel_uri、job_type、alias_type、excel_version等。
- GET /api/platform/promotion/batch_task/list/v:version：批量任务结果。

这些来自网站前端，不是公开开放API。当前不实现猜测私有参数/复制签名的直接HTTP提交，先使用页面已观察的批量入口。

## 开发范围

1. 从原账号browser_control发布成功回执读取作品ID/链接；任务ID、账号、binding_version必须一致，未知/未验证回执拒绝。
2. 冻结书籍ID、推广别名、发文类型AIGC、番茄账号标识、展示抖音号、原发布日期；不推测日期或展示账号。
3. 根据官方模板生成一行回填文件及SHA清单；这不等于向平台提交。
4. 执行器接收受管控的现有页面与身份/租约检查器；再次读取当前列表，要求别名唯一、书籍匹配、生效且可用、类型一致。默认dry-run，真实提交还需明确授权。
5. 上传前持久占位。超时/退出保留原job与未知结果，不自动重传。成功必须重读原别名的明确作品链接，通用“提交成功”不能当回填完成。
6. 不接入无人值守生产调度，直到番茄身份绑定及真实生效推广任务完成验收；不改法律号/小说号暂停及旧任务。

## 官方接口检索

抖音有官方申请及授权体系，video.create需要权限及用户授权，公开配额文档说明部分接口每日免费配额。不能将旧文档示例当当前账号必获权限/额度。当前能力目录以移动/网站投稿、投稿任务等为主，资格和scope须看实际控制台。

- https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/create/create-video/
- https://open.douyin.com/platform/resource/docs/common-question/free-quota-common-question
- https://partner.open-douyin.com/docs/resource/zh-CN/dop/ability/common-solution
- https://partner.open-douyin.com/docs/resource/zh-CN/dop/operation-standard/platform-capabilities/useclue

本轮未找到番茄别名回填公开API申请文档或免费承诺，不能把搜索结果中的第三方“番茄API”当官方接口。

## 实现和测试结果

- src/services/fanqie_backfill_workflow.py：原成功发布回执只读适配、绑定检查、官方模板导出、持久原子占位及一次回填状态机。
- src/platform_adapter/fanqie_backfill.py：实际观察到的批量弹窗页面适配器，注入已有受管控page和独立身份探测器；不自动新建浏览器。不采信昵称作为稳定账号身份。
- scripts/prepare_fanqie_backfill.py：离线准备入口，--binding绑定JSON、--template官方模板、--output新目录；读取原browser_control成功发布记录，不上传不提交。日期及展示抖音号必须明确提供；不以当前日期或内部账号ID替代。
- execute默认dry_run=True。显式提交须绑定job_id、manifest_sha256及授权reference，guard负责原账号/绑定/暂停/租约检查；当前没有生产guard或番茄身份绑定适配接线，不能接后台自动派发。只支持原publish成功命令；经独立reconciliation确认的历史unknown暂不支持，不读取其成功标记来绕过原门。
- 48项联合回归通过：包含隔离Chrome真实DOM/上传控件测试、失效/歧义/账号不符/重复执行/超时/文件变化/中途状态变化等；报告data/qa/fanqie_backfill_release_20261024.xml。初次43通过/1失败为测试HTML没有UTF-8声明导致中文表头误码，已修测试fixture并保留失败回执。
- 官方下载模板另做本地导出验证：保留原首行5列及所有非sheet XML条目，删除示例、仅填入一行文本，无公式执行。OFFICIAL_TEMPLATE_TEST.json记录结果。QA_ONLY_template_export.xlsx仅合成测试数据，禁止上传或作为生产推广任务。
- 当前状态：开发版本通过离线测试，真实表单已观察，但未完成真实上传/回填验收、未接入生产定时调度、未重启服务；原账号暂停/任务/登录环境不变。当前页面5条旧词无一生效，真实验收需对应成片的新有效AIGC推广任务和已验证原发布回执。
