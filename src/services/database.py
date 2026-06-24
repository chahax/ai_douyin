"""
database.py — SQLite 数据库连接与建表

数据库文件：data/douyin.db
独立 Base 和模型，不复用已有的 wisdom_ai.db
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# 数据库文件路径
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "douyin.db"

# 建表 SQL（从 DATA_PERSISTENCE_SPEC.md）
CREATE_TABLES_SQL = """
-- 视频主表
CREATE TABLE IF NOT EXISTS videos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
    local_id       TEXT,                       -- 本地唯一标识（publish 时生成 UUID）
    video_id       TEXT,                       -- 抖音视频 ID（sync 后补上）
    title          TEXT,                       -- 视频标题（sync 匹配 key）
    description    TEXT,                       -- 视频描述
    status         TEXT DEFAULT 'pending_review',  -- pending_review / published / failed
    publish_time   TEXT,                       -- 发布时间字符串
    cover_url      TEXT,                       -- 封面URL
    stats_views    INTEGER DEFAULT 0,          -- 播放量
    stats_likes    INTEGER DEFAULT 0,          -- 点赞数
    stats_comments INTEGER DEFAULT 0,          -- 评论数
    last_synced_at TEXT,                       -- 最后同步时间
    created_at     TEXT,                       -- 首次入库时间
    rag_context    TEXT                        -- 视频生成时 RAG 检索的知识片段（用于回复增强）
);

-- 评论表
CREATE TABLE IF NOT EXISTS comments (
    comment_id     TEXT PRIMARY KEY,           -- 抖音评论ID
    video_id       TEXT,                       -- 关联 videos.video_id
    user_nickname  TEXT,                       -- 评论用户昵称
    user_avatar    TEXT,                       -- 评论用户头像URL
    content        TEXT,                       -- 评论内容
    like_count     INTEGER DEFAULT 0,          -- 点赞数
    is_top         INTEGER DEFAULT 0,          -- 是否置顶 0/1
    reply_count    INTEGER DEFAULT 0,          -- 子回复数
    created_at     TEXT,                       -- 评论时间
    is_replied     INTEGER DEFAULT 0,          -- 是否已回复 0/1
    replied_at     TEXT,                       -- 回复时间
    reply_content  TEXT,                       -- 回复内容
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

-- 同步历史
CREATE TABLE IF NOT EXISTS sync_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type     TEXT,                        -- videos / comments / stats
    total_count   INTEGER DEFAULT 0,           -- 本次处理总数
    new_count     INTEGER DEFAULT 0,           -- 本次新增数
    started_at    TEXT,                        -- 开始时间
    finished_at   TEXT,                        -- 结束时间
    status        TEXT                         -- success / failed / partial
);

-- 自动回复规则
CREATE TABLE IF NOT EXISTS auto_reply_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword        TEXT,                       -- 触发关键词
    reply_template TEXT,                       -- 回复模板
    match_type     TEXT DEFAULT 'contains',  -- exact / contains / regex
    reply_type     TEXT DEFAULT 'fixed',      -- fixed / llm / default
    llm_model      TEXT,                      -- LLM 模型名称
    enabled        INTEGER DEFAULT 1,          -- 是否启用 0/1
    created_at     TEXT
);

-- 用户回复配置
CREATE TABLE IF NOT EXISTS user_reply_configs (
    user_nickname  TEXT PRIMARY KEY,          -- 抖音昵称
    role           TEXT DEFAULT 'viewer',    -- 角色: viewer/editor/admin/superadmin
    daily_limit     INTEGER DEFAULT 5,         -- 每日回复上限
    total_limit    INTEGER DEFAULT 50,        -- 累计回复上限
    daily_count     INTEGER DEFAULT 0,         -- 今日已回复数
    total_count     INTEGER DEFAULT 0,        -- 累计已回复数
    last_reply_date TEXT,                     -- 上次重置日期（YYYY-MM-DD）
    is_whitelist   INTEGER DEFAULT 0,         -- 白名单 0/1
    password_hash   TEXT,                      -- 管理后台登录密码哈希
    registered_ip  TEXT,                      -- 注册时的 IP 地址
    created_at     TEXT,
    updated_at     TEXT
);

-- 回复历史
CREATE TABLE IF NOT EXISTS reply_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_nickname  TEXT,                      -- 用户昵称
    video_id       TEXT,                       -- 视频ID
    comment_id     TEXT,                       -- 被回复的评论ID
    reply_content  TEXT,                       -- 回复内容
    auto_generated INTEGER DEFAULT 1,          -- 1=自动，0=手动
    model_used     TEXT,                      -- 使用的模型
    created_at     TEXT
);

-- 回复上下文（每组对话保留最近N条）
CREATE TABLE IF NOT EXISTS reply_context (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_nickname  TEXT,                      -- 用户昵称
    video_id       TEXT,                       -- 视频ID
    role           TEXT,                       -- user / assistant
    content        TEXT,                       -- 评论或回复内容
    created_at     TEXT
);

-- 违禁词表
CREATE TABLE IF NOT EXISTS blocked_words (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    word            TEXT UNIQUE,               -- 违禁词
    created_at     TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_comments_video_id   ON comments(video_id);
CREATE INDEX IF NOT EXISTS idx_comments_is_replied ON comments(is_replied);
CREATE INDEX IF NOT EXISTS idx_videos_status       ON videos(status);
CREATE INDEX IF NOT EXISTS idx_reply_history_user   ON reply_history(user_nickname);
CREATE INDEX IF NOT EXISTS idx_reply_context_user_video ON reply_context(user_nickname, video_id);
CREATE INDEX IF NOT EXISTS idx_sync_history_type   ON sync_history(sync_type);
"""


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（自动建表）"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """确保表已创建（仅在表不存在时创建），并执行必要的 schema 迁移"""
    cursor = conn.cursor()
    cursor.executescript(CREATE_TABLES_SQL)

    # 迁移：从旧 schema（video_id PK）升级到新 schema（id autoincrement + local_id）
    _migrate_videos_table(cursor)
    # 迁移 auto_reply_rules 表
    _migrate_auto_reply_rules(cursor)
    # 迁移 user_reply_configs 表：添加后台登录相关列
    _migrate_user_configs(cursor)
    # 迁移 videos 表：添加 rag_context 列
    _migrate_videos_rag_context(cursor)
    # 初始化违禁词
    _init_blocked_words(cursor)
    conn.commit()


def _migrate_videos_table(cursor: sqlite3.Cursor) -> None:
    """迁移 videos 表：添加 id 和 local_id 列（如不存在），处理旧数据"""
    cursor.execute("PRAGMA table_info(videos)")
    columns = {row[1] for row in cursor.fetchall()}

    if "local_id" not in columns:
        # 旧表没有 local_id，添加列
        cursor.execute("ALTER TABLE videos ADD COLUMN local_id TEXT")

    if "id" not in columns:
        # 旧表没有自增 id 列（PK 原为 video_id），需要重建表
        # SQLite 不支持 DROP COLUMN，需要创建新表再迁移数据
        cursor.execute("ALTER TABLE videos RENAME TO videos_old")
        cursor.execute("""
            CREATE TABLE videos (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                local_id       TEXT,
                video_id       TEXT,
                title          TEXT,
                description    TEXT,
                status         TEXT DEFAULT 'pending_review',
                publish_time   TEXT,
                cover_url      TEXT,
                stats_views    INTEGER DEFAULT 0,
                stats_likes    INTEGER DEFAULT 0,
                stats_comments INTEGER DEFAULT 0,
                last_synced_at TEXT,
                created_at     TEXT
            )
        """)
        # 迁移旧数据（video_id -> video_id, title -> title）
        cursor.execute("""
            INSERT INTO videos (video_id, title, description, status, publish_time,
                cover_url, stats_views, stats_likes, stats_comments, last_synced_at, created_at)
            SELECT video_id, title, description,
                COALESCE(status, 'published'), publish_time,
                cover_url, stats_views, stats_likes, stats_comments, last_synced_at, created_at
            FROM videos_old
        """)
        cursor.execute("DROP TABLE videos_old")

    # 为已有记录补充 local_id（如需）
    cursor.execute("SELECT video_id FROM videos WHERE local_id IS NULL OR local_id = ''")
    for row in cursor.fetchall():
        video_id = row["video_id"]
        if video_id:
            cursor.execute(
                "UPDATE videos SET local_id = ? WHERE video_id = ?",
                (video_id[:8], video_id),
            )

    # 确保新索引存在
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_local_id ON videos(local_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_title ON videos(title)")


def _migrate_videos_rag_context(cursor: sqlite3.Cursor) -> None:
    """迁移 videos 表：添加 rag_context 列（如不存在）"""
    cursor.execute("PRAGMA table_info(videos)")
    columns = {row[1] for row in cursor.fetchall()}
    if "rag_context" not in columns:
        cursor.execute("ALTER TABLE videos ADD COLUMN rag_context TEXT")


def _migrate_auto_reply_rules(cursor: sqlite3.Cursor) -> None:
    """迁移 auto_reply_rules 表：添加新列（如不存在）"""
    cursor.execute("PRAGMA table_info(auto_reply_rules)")
    columns = {row[1] for row in cursor.fetchall()}

    if "match_type" not in columns:
        cursor.execute("ALTER TABLE auto_reply_rules ADD COLUMN match_type TEXT DEFAULT 'contains'")
    if "reply_type" not in columns:
        cursor.execute("ALTER TABLE auto_reply_rules ADD COLUMN reply_type TEXT DEFAULT 'fixed'")
    if "llm_model" not in columns:
        cursor.execute("ALTER TABLE auto_reply_rules ADD COLUMN llm_model TEXT")


def _migrate_user_configs(cursor: sqlite3.Cursor) -> None:
    """迁移 user_reply_configs 表：添加后台登录相关列（如不存在）"""
    cursor.execute("PRAGMA table_info(user_reply_configs)")
    columns = {row[1] for row in cursor.fetchall()}
    if "role" not in columns:
        cursor.execute("ALTER TABLE user_reply_configs ADD COLUMN role TEXT DEFAULT 'viewer'")
    if "password_hash" not in columns:
        cursor.execute("ALTER TABLE user_reply_configs ADD COLUMN password_hash TEXT")
    if "registered_ip" not in columns:
        cursor.execute("ALTER TABLE user_reply_configs ADD COLUMN registered_ip TEXT")


def _init_blocked_words(cursor: sqlite3.Cursor) -> None:
    """初始化违禁词（如为空则插入预置词）"""
    cursor.execute("SELECT COUNT(*) FROM blocked_words")
    if cursor.fetchone()[0] > 0:
        return  # 已有数据，跳过

    now = datetime.now().isoformat()
    preset_words = [
        "微信", "加我", "私信", "看主页", "QQ",
        "联系我", "购买", "链接", "网址",
    ]
    for word in preset_words:
        cursor.execute(
            "INSERT OR IGNORE INTO blocked_words (word, created_at) VALUES (?, ?)",
            (word, now),
        )


@contextmanager
def get_db():
    """上下文管理器，用法：with get_db() as conn: ... """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> None:
    """手动初始化数据库（创建所有表）"""
    conn = get_connection()
    conn.close()
    print(f"数据库已初始化: {DB_PATH}")


if __name__ == "__main__":
    init_database()
