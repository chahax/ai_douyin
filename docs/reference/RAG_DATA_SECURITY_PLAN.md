---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# RAG 知识库数据安全修改方案（可执行版）

> 更新时间：2026-04-28
> 状态：待实施

---

## 1. 现状与风险

### 1.1 当前存储

```
data/chroma_db/
├── chroma.sqlite3              # 明文 SQLite（文本+向量+元数据）
└── a905e1c2-.../              # HNSW 向量索引（二进制）
    ├── data_level0.bin
    └── length.bin
```

### 1.2 真实风险

| 风险 | 等级 | 说明 |
|------|------|------|
| **Git 已跟踪** | 🔴 紧急 | `data/chroma_db/` 已被 Git 跟踪（`git status` 显示 M），提交代码即附带知识库 |
| **磁盘文件明文** | 🔴 高 | 任何人打开 `chroma.sqlite3` 可直接读所有文本内容 |
| **无访问审计** | 🔴 高 | 谁查了什么知识完全无记录 |
| **备份明文** | 🔴 高 | 备份文件=完整知识库复制 |
| **导入无脱敏** | 🟡 中 | 含手机号/身份证的文档直接入库 |

---

## 2. 三阶段方案

### Phase 0：立即处理 Git 风险（今天）

> 这是唯一不需要代码改动、直接影响安全的步骤。

**Step 0.1**：把已跟踪的文件从 Git 索引移除（保留本地文件）

```bash
# 从 Git 索引移除，但保留本地文件（--cached）
git rm --cached -r data/chroma_db/
git rm --cached -r data/browser/

# 确认状态：data/chroma_db 变为 untracked
git status data/chroma_db/
```

**Step 0.2**：更新 `.gitignore`

```gitignore
# RAG 知识库（明文，不可提交）
data/chroma_db/

# 浏览器会话状态（含登录凭证，不可提交）
data/browser/

# 审计日志（可能含敏感查询内容）
data/logs/
```

**Step 0.3**：提交此改动

```bash
git add .gitignore
git commit -m "chore: stop tracking chroma_db and browser data"
```

**验证**：

```bash
# 确认 data/chroma_db 不在暂存区
git status --short data/chroma_db/
# 期望：?? data/chroma_db/（untracked，不是 tracked）

# 确认本地文件完好
ls data/chroma_db/
```

⚠️ **注意**：如果之前有人 clone 了此仓库，`git rm --cached` 后需要 `git pull` 才会删除本地方已跟踪的文件记录。但本地实际文件不受影响（`--cached` 只移除索引）。

---

### Phase 1：磁盘加密 + NTFS 访问控制

**目标**：防止已解锁机器上其他用户/进程直接读取文件。

#### Step 1.1：BitLocker（防硬盘离线泄露）

```powershell
# 检查状态（管理员 PowerShell）
Get-BitLockerVolume -MountPoint "D:"

# 如果 Protection=Off，启用
manage-bde -on D: -RecoveryPassword
# 将恢复密钥保存到 Microsoft 账户（不要存本地）
```

**作用**：防止硬盘被拔到另一台机器读取。设备丢失/被盗时数据不可读。

#### Step 1.2：NTFS 访问控制（防同机未授权访问）

BitLocker 解锁后，同机器其他 Windows 账户仍可通过 NTFS 权限访问文件。用 `icacls` 限制仅当前用户可读写：

```powershell
# 查看当前权限
icacls "D:\IT\ai_douyin\data\chroma_db"

# 移除其他用户的读取权限（保留 SYSTEM/Administrators）
icacls "D:\IT\ai_douyin\data\chroma_db" /inheritance:r
icacls "D:\IT\ai_douyin\data\chroma_db" /grant:r "%USERNAME%:(OI)(CI)RX"
icacls "D:\IT\ai_douyin\data\chroma_db" /grant:r "SYSTEM:(OI)(CI)F"
icacls "D:\IT\ai_douyin\data\chroma_db" /grant:r "Administrators:(OI)(CI)F"
```

**验证**（用同机器另一个用户测试）：
```cmd
# 以另一个 Windows 用户身份运行
icacls "D:\IT\ai_douyin\data\chroma_db"
# 期望：Access Denied
```

⚠️ **注意**：当前用户需要是 Administrators 或有 SeSecurityPrivilege 才能修改某些权限。

#### Step 1.3：备份文件隔离

如果定期备份 `data/chroma_db/`，确保备份文件也落在加密盘或加密压缩包里：

```powershell
# 示例：备份到加密盘
Copy-Item -Path "D:\IT\ai_douyin\data\chroma_db" `
           -Destination "E:\backups\chroma_db_$(Get-Date -Format 'yyyyMMdd')" `
           -Recurse
# E: 必须是 BitLocker 加密盘
```

---

### Phase 2：审计日志 + 导入脱敏

#### Step 2.1：检索审计日志

**关键**：查询内容本身可能含敏感信息（用户输入的问题可能暴露关注点），不能直接落盘。提供三种模式：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `sanitized`（默认） | 替换手机号/身份证等后记录 | 一般记录需求 |
| `truncated` | 只记录前20字符 + SHA256 哈希 | 需精确匹配但不想明文 |
| `none` | 不记录查询内容，只记 hit_count | 最高隐私要求 |

```python
# wisdom_retriever.py 修改

import hashlib
import logging
import logging.handlers
import os
import re
from datetime import datetime
from typing import Literal

# 脱敏正则
_SANITIZE_PATTERNS = [
    (re.compile(r'1[3-9]\d{9}'), '[手机号]'),
    (re.compile(r'\d{17}[\dXx]'), '[身份证]'),
]

def _sanitize(text: str) -> str:
    for pat, repl in _SANITIZE_PATTERNS:
        text = pat.sub(repl, text)
    return text

# 审计日志配置
_audit_log_path = "./data/logs/rag_audit.log"
os.makedirs(os.path.dirname(_audit_log_path), exist_ok=True)

_audit_logger = logging.getLogger("rag_audit")
_audit_logger.setLevel(logging.INFO)
_handler = logging.handlers.TimedRotatingFileHandler(
    _audit_log_path, when="midnight", backupCount=30
)
_audit_logger.addHandler(_handler)

# 审计模式配置（可通过环境变量或配置改）
AUDIT_MODE = os.environ.get("RAG_AUDIT_MODE", "sanitized")

def search_wisdom(self, query: str, top_k: int = 3) -> list:
    start = datetime.now()
    results = self.db.similarity_search(query, k=top_k)
    elapsed_ms = (datetime.now() - start).total_seconds() * 1000

    if AUDIT_MODE == "sanitized":
        query_record = _sanitize(query)
    elif AUDIT_MODE == "truncated":
        query_record = query[:20] + "|" + hashlib.sha256(query.encode()).hexdigest()[:16]
    else:
        query_record = ""

    self._audit(
        query=query_record,
        hit_count=len(results),
        elapsed_ms=round(elapsed_ms, 1),
        top_k=top_k,
    )
    return results

def _audit(self, **kwargs):
    self._audit_logger.info(
        f"{datetime.now().isoformat()} | "
        + " | ".join(f"{k}={v}" for k, v in kwargs.items())
    )
```

**日志格式**：

```text
2026-04-28T12:00:00.000000 | query=人生迷茫如何找到方向 | hit_count=3 | elapsed_ms=45.2 | top_k=3
```

**导入链路也加审计**（`knowledge_importer.py` 末尾）：

```python
# knowledge_importer.py — import_books() 末尾
if total_docs:
    _audit_logger.info(
        f"{datetime.now().isoformat()} | action=import | "
        f"file_count={len(files)} | chunks={len(total_docs)}"
    )
```

#### Step 2.2：导入脱敏

**插入点**：`knowledge_importer.py` 的 `_load_book_as_documents()` 返回前，或 `split_documents()` 后、`add_documents()` 前。

推荐在 `split_documents()` 之后、`add_documents()` 之前（这样 chunk 粒度也受保护）：

```python
# knowledge_importer.py 第 144-146 行
for chunk in chunks:
    chunk.metadata["source_book"] = file
    chunk.page_content = _sanitize(chunk.page_content)  # 新增：脱敏
```

```python
# 文件顶部或同文件末尾添加
_SANITIZE_PATTERNS = [
    (re.compile(r'1[3-9]\d{9}'), '[手机号]'),
    (re.compile(r'\d{17}[\dXx]'), '[身份证]'),
]

def _sanitize_text(text: str) -> str:
    for pat, repl in _SANITIZE_PATTERNS:
        text = pat.sub(repl, text)
    return text
```

#### Step 2.3：已有数据脱敏迁移（可选执行）

**判断是否需要**：检查已有导入文档是否含手机号/身份证：

```bash
cd d:/IT/ai_douyin && python -c "
import sqlite3, re
conn = sqlite3.connect('data/chroma_db/chroma.sqlite3')
cur = conn.cursor()
cur.execute('PRAGMA table_info(embedding_metadata)')
cols = [c[1] for c in cur.fetchall()]
if 'string_value' in cols:
    cur.execute('SELECT string_value FROM embedding_metadata WHERE key=\"chroma:document\" LIMIT 100')
    phone_pat = re.compile(r'1[3-9]\d{9}')
    id_pat = re.compile(r'\d{17}[\dXx]')
    phones, ids = set(), set()
    for (val,) in cur.fetchall():
        for m in phone_pat.findall(val or ''):
            phones.add(m)
        for m in id_pat.findall(val or ''):
            ids.add(m)
    print(f'发现手机号: {len(phones)} 个')
    print(f'发现身份证: {len(ids)} 个')
    if phones or ids:
        print('需要迁移执行脱敏')
    else:
        print('无需迁移，已有数据不含敏感信息')
conn.close()
"
```

**迁移步骤**（仅在上述检查发现敏感信息时执行）：

```bash
# 1. 备份
xcopy /E /I /H "D:\IT\ai_douyin\data\chroma_db" "D:\IT\ai_douyin\data\chroma_db.backup.$(date /T)"
```

```python
# 2. 清库重建（迁移脚本）
# migrate_rag_sanitize.py
import os, re, sqlite3
from datetime import datetime

_SANITIZE_PATTERNS = [
    (re.compile(r'1[3-9]\d{9}'), '[手机号]'),
    (re.compile(r'\d{17}[\dXx]'), '[身份证]'),
]

def sanitize(text):
    for pat, repl in _SANITIZE_PATTERNS:
        text = pat.sub(repl, text)
    return text

# 直接修改 SQLite（不重建索引）
conn = sqlite3.connect('data/chroma_db/chroma.sqlite3')
cur = conn.cursor()
cur.execute('SELECT id, string_value FROM embedding_metadata WHERE key="chroma:document"')
updated = 0
for row_id, val in cur.fetchall():
    if val:
        sanitized = sanitize(val)
        if sanitized != val:
            cur.execute('UPDATE embedding_metadata SET string_value=? WHERE id=?', (sanitized, row_id))
            updated += 1
conn.commit()
conn.close()
print(f"脱敏完成，更新 {updated} 条记录")
```

---

## 3. 架构图（修正后）

```
┌─────────────────────────────────────────────────────────┐
│  Phase 0: Git 隔离                                        │
│  .gitignore + git rm --cached                           │
│  确保 chroma_db 不随代码仓库泄露                          │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 1: 磁盘访问控制                                    │
│  BitLocker（防离线磁盘读取）                               │
│  + NTFS ACL（同机其他用户隔离）                            │
│  确保文件级访问受 OS 层保护                                │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Phase 2: 应用层                                         │
│  L2 检索审计（脱敏/截断/不记录查询原文）                   │
│  L3 导入脱敏（在 add_documents 前执行）                    │
│  新写入文档自动保护                                        │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 实施检查清单

```markdown
## Phase 0（立即执行）
- [ ] `git rm --cached -r data/chroma_db/`
- [ ] `git rm --cached -r data/browser/`
- [ ] .gitignore 添加 data/chroma_db/、data/browser/、data/logs/
- [ ] git commit
- [ ] `git status data/chroma_db/` 确认为 untracked

## Phase 1
- [ ] BitLocker 状态为 "Encryption in Progress" 或 "Encryption On"
- [ ] `icacls` 验证仅当前用户+SYSTEM+Administrators 可访问
- [ ] 备份脚本验证备份落在加密盘

## Phase 2
- [ ] wisdom_retriever.py 审计日志代码已更新
- [ ] AUDIT_MODE 环境变量可切换模式（默认 sanitized）
- [ ] knowledge_importer.py 导入链路已加 _sanitize_text
- [ ] data/logs/ 目录已创建且在 .gitignore 中
- [ ] 日志轮转（30天）已配置
- [ ] 已有数据敏感信息检查脚本执行完毕
- [ ] 如需迁移，脱敏迁移脚本已执行完毕

## 交付
- [ ] V1: `git status data/chroma_db/` 显示 untracked
- [ ] V2: 检索后 `data/logs/rag_audit.log` 有记录，query 为脱敏后文本
- [ ] V3: 导入含手机号文档后，Chroma 查询到 `[手机号]`
```

---

## 5. 各层验证方法（修正）

| 验证目标 | 正确方法 |
|---------|---------|
| Git 隔离 | `git status data/chroma_db/` 显示 `??`（untracked） |
| BitLocker 防离线 | 拔硬盘到另一台电脑，无法挂载读取 |
| NTFS 同机隔离 | `icacls` 确认其他用户无读取权限 |
| 审计日志 query | `cat data/logs/rag_audit.log` 确认不含明文手机号/身份证 |
| 导入脱敏 | 直接 `sqlite3 data/chroma_db/chroma.sqlite3` 查 embedding_metadata.string_value，已为 `[手机号]` |

---

## 6. 成本评估

| 阶段 | 实际命令/代码 | 预计耗时 |
|------|--------------|---------|
| Phase 0 | `git rm --cached` + 修改 .gitignore + commit | 15 分钟 |
| Phase 1 | BitLocker 检查 + `icacls` 配置 | 30 分钟 |
| Phase 2 | 修改 2 个 Python 文件 + 测试 + 可选迁移脚本 | 2-3 小时 |

---

## 7. 不在此方案范围

- Chroma SQLite 本身加密（需迁移 PostgreSQL，改动过大，且当前 Chroma 不支持）
- 网络传输 TLS（当前无多机访问场景）
- 向量数据加密（会破坏相似度搜索）
- Chroma 服务认证（当前是嵌入式，无独立服务端口）
