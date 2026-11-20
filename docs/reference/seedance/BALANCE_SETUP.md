# 火山引擎账户余额查询配置

SDK 已在本项目虚拟环境安装。另一个环境可运行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-volcengine.txt
```

需要用户提供的只有以下两类配置：

1. **Access Key ID 与 Secret Access Key**：在火山引擎控制台的 API 访问密钥管理中获取，写入项目根目录 `.env` 预留字段。不要用方舟推理 `ARK_API_KEY`，不要将密钥发到聊天或提交到 Git。[官方访问密钥说明](https://www.volcengine.com/docs/6291/65568?lang=zh)
2. **该身份的余额查询权限**：IAM 身份可使用 `BillingCenterReadOnlyAccess`（费用中心全部只读），或按组织要求使用更窄的余额查询策略。旧的 `BillingReadOnlyAccess` 只覆盖账单，不应当作资金余额权限。[官方费用中心权限说明](https://www.volcengine.com/docs/6269/1186807?lang=zh)

```dotenv
VOLCENGINE_ACCESS_KEY=填写AccessKeyID
VOLCENGINE_SECRET_KEY=填写SecretAccessKey
```

本项目 `.env` 已预留空字段。程序每次查询重新读取配置，不需要重新复制推理密钥或重启网页。

在网页「视频模型用量 → 火山方舟 API」点击 **查询方舟账户余额**，或运行：

```powershell
# 本地检查 SDK 与两项管理凭证是否存在，不联网、不显示密钥
.venv\Scripts\python.exe scripts/query_volcengine_balance.py --check

# 发出一个只读余额查询，不创建视频任务
.venv\Scripts\python.exe scripts/query_volcengine_balance.py
```

返回账户可用余额、现金余额、欠费、冻结金额等；缺失字段保留为空，零余额保留为零。查询时间使用真实接口完成时间，网页显示北京时间。

接口为 [QueryBalanceAcct](https://www.volcengine.com/docs/6269/1223898?lang=zh)，只查询账户资金；不返回 Seedance 免费资源包剩余秒数或安心体验的剩余 tokens。本地视频任务的 `usage` 也不等于余额。未配置 AK/SK 时，项目不会发出无效查询或推算余额。
