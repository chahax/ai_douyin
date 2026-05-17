---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# RAG 知识库数据安全方案

> 更新时间：2026-04-28

---

## 1. 当前安全现状

### 1.1 存储架构

```
data/chroma_db/
├── chroma.sqlite3          # Chroma 元数据 + 向量（SQLite 明文）
└── a905e1c2-.../          # HNSW 持久化向量索引
    ├── data_level0.bin    # 向量数据（二进制明文）
    └── length.bin
```

**数据库内容（明文可见）：**
- `embedding_metadata` 表：存储 `chroma:document` 原始文本、`source_book` 来源书籍名
- `collections` 表：collection 名称（`langchain`）
- 向量数据：768 维 float 数组

### 1.2 风险矩阵

| 威胁场景 | 风险等级 | 说明 |
|---------|---------|------|
| 电脑被他人访问 | 🔴 高 | 直接读取 SQLite 文件，所有知识内容明文可见 |
| 硬盘/电脑丢失 | 🔴 高 | 无加密保护，数据完全裸露 |
| Chroma 服务被未授权访问 | 🔴 高 | 无认证机制（当前仅本地进程调用，但若暴露服务端口） |
| 备份文件泄露 | 🔴 高 | 备份=完整知识库复制，无任何保护 |
| 传输链路窃听 | 🟡 中 | 多机环境访问时无 TLS |
| 内部人员滥用 | 🟡 中 | 无细粒度权限控制 |

---

## 2. 防御方案

### 2.1 方案 A：文件系统级加密（推荐，最简）

**原理**：利用 Windows BitLocker 对存放数据的磁盘/文件夹加密。

**优点**：零代码改动，数据在磁盘层加密
**缺点**：需要 OS 支持（Windows Pro/Enterprise 有 BitLocker）

```bash
# 启用 BitLocker（PowerShell 管理员）
# 对数据盘符加密
manage-bde -on D: -RecoveryPassword

# 或对单个文件夹用 EFS（NTFS 加密）
cipher /e:"D:\IT\ai_douyin\data"
```

**验证**：
```bash
# 加密后，非法用户无法读取数据库文件
# 即使拆下硬盘也无解
```

---

### 2.2 方案 B：加密整个 SQLite 数据库（中等成本）

**原理**：用 `sqlcipher` 替代标准 SQLite，所有数据库操作在加密层进行。

```bash
# 安装 sqlcipher
pip install sqlcipher

# Chroma 支持通过 connection_string 指定加密密钥
CHROMA_DB_CONNECTION_STRING="postgresql+psycopg2://user:pass@host:5432/chroma?sslmode=prefer"
# 注：Chroma 原生 SQLite 不支持 sqlcipher，
#     如需加密需迁移到 PostgreSQL + pgcrypto
```

**评估**：需要迁移数据，改动较大。

---

### 2.3 方案 C：文档内容加密后导入（应用层）

**原理**：在导入知识库前对敏感内容加密，检索时解密。

```python
# 示例：导入前加密
from cryptography.fernet import Fernet

key = os.environ.get("RAG_ENCRYPTION_KEY")
fernet = Fernet(key)

# 加密原文后存入向量数据库
encrypted_doc = fernet.encrypt(doc.encode())
# 检索时解密
decrypted = fernet.decrypt(encrypted_doc)
```

**问题**：加密后向量语义会变化，影响检索质量（不推荐用于 RAG 场景）

---

### 2.4 方案 D：限制 Chroma 为本地服务（网络隔离）

**原理**：Chroma 仅暴露给本地进程，不开启网络服务端口。

```python
# wisdom_retriever.py 当前已是本地持久化（无网络暴露）
# 确认未使用 Chroma Server 模式
```

**评估**：这是当前默认状态，风险主要在文件层面。

---

### 2.5 方案 E：数据分类 + 敏感数据脱敏

**原理**：导入前对敏感字段（人名、联系方式、具体数字等）做脱敏处理。

```python
import re

def redact_sensitive(text: str) -> str:
    # 手机号
    text = re.sub(r'1[3-9]\d{9}', '[手机号]', text)
    # 身份证
    text = re.sub(r'\d{17}[\dXx]', '[身份证]', text)
    # 具体人名（可配置名单）
    for name in SENSITIVE_NAMES:
        text = text.replace(name, '[人名]')
    return text
```

---

## 3. 推荐路线

### 短期（立即可做）

1. **文件级加密**：启用 Windows BitLocker（零成本，10 分钟配置）
2. **备份安全**：备份文件不要放在网盘/共享目录
3. **访问控制**：确保电脑有登录密码/PIN，防止陌生人直接接触系统

### 中期（1-2 周）

1. **审计日志**：记录谁在什么时间检索了哪些知识（`wisdom_retriever.py` 加日志）
2. **敏感数据脱敏**：在 `rag_engine/text_loader.py` 导入链路加脱敏处理
3. **定期清理**：删除不再需要的导入文档，减少暴露面

### 长期（如需多用户共享）

1. **迁移到带认证的后端**：PostgreSQL + Chroma + 认证中间件
2. **密钥管理**：引入 `python-keyring` 或 `.env` 管理加密密钥（不提交到 Git）
3. **TLS 传输**：若跨机器访问，给 Chroma Server 配置自签名证书

---

## 4. 快速检查清单

```bash
# ✅ 已做
[ ] .env 文件在 .gitignore 中（密钥不提交）
[ ] storage_state.json 不在 Git（登录态文件）
[ ] 数据库文件不在公共目录

# ⚠️ 需确认
[ ] Chroma 持久化目录 `./data/chroma_db/` 是否在备份白名单中（备份需加密）
[ ] 导入的知识库内容是否包含个人隐私/商业秘密

# ❌ 未做（高优先级）
[ ] 磁盘未加密 → 启用 BitLocker
[ ] 无审计日志 → 增加检索日志
[ ] 备份文件未加密 → 确保备份在加密盘
```

---

## 5. 代码层面可落地的改进

### 5.1 增加检索审计日志

```python
# wisdom_retriever.py
def search_wisdom(self, query: str, top_k: int = 3) -> list:
    logger.info(f"[RAG审计] 用户查询: '{query}', top_k={top_k}")
    results = self.db.similarity_search(query, k=top_k)
    for r in results:
        logger.info(f"[RAG审计] 命中来源: {r.metadata.get('source_book')}")
    return results
```

### 5.2 导入时脱敏（示例）

```python
# rag_engine/text_loader.py — 导入链路加脱敏
def redact_before_import(text: str) -> str:
    import re
    patterns = [
        (r'1[3-9]\d{9}', '[手机号]'),
        (r'\d{17}[\dXx]', '[身份证]'),
    ]
    for pat, repl in patterns:
        text = re.sub(pat, repl, text)
    return text
```

### 5.3 Chroma 数据不与备份混放

```ini
# .gitignore 补充
data/chroma_db/
data/browser/
data/videos/
```

---

## 6. 总结

| 维度 | 当前状态 | 目标 |
|------|---------|------|
| 存储加密 | ❌ 明文 SQLite | ✅ BitLocker |
| 访问认证 | ❌ 无 | ⚠️ 网络隔离 |
| 传输加密 | ⚠️ 本地进程 | ✅ TLS（跨机时）|
| 审计日志 | ❌ 无 | ✅ 检索日志 |
| 备份安全 | ❌ 未加密 | ✅ 加密盘备份 |
| 敏感脱敏 | ❌ 无 | ✅ 导入时处理 |

**最推荐的短期方案**：启用 Windows BitLocker + 检索审计日志，零代码改动，成本最低。
