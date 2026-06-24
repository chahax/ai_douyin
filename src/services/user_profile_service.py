"""
user_profile_service.py — 用户回复配置服务

管理每个用户的回复次数上限和计数
"""

from datetime import datetime, date
from typing import Optional

from src.services.database import get_db


DEFAULT_DAILY_LIMIT = 5
DEFAULT_TOTAL_LIMIT = 50
MAX_ACCOUNTS_PER_IP = 3  # 同 IP 最多注册账号数


def get_client_ip() -> str:
    """获取客户端 IP，优先从 Streamlit 请求头读取"""
    try:
        import streamlit as st
        # Streamlit 部署时通过 X-Forwarded-For 等头获取真实 IP
        for header in ["X-Forwarded-For", "X-Real-IP", "X-Client-IP"]:
            ip = st.context.headers.get(header, "")
            if ip:
                # X-Forwarded-For 可能为 "ip1, ip2"，取第一个
                return ip.split(",")[0].strip()
    except Exception:
        pass
    return "127.0.0.1"


def count_ip_accounts(ip: str) -> int:
    """查询指定 IP 已注册的账号数量"""
    if not ip:
        return 0
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_reply_configs WHERE registered_ip = ? AND password_hash IS NOT NULL AND password_hash != ''",
            (ip,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0


def count_users_with_password() -> int:
    """查询已设置密码的用户总数（任何 IP）。用于判断是否是首位注册者。"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_reply_configs WHERE password_hash IS NOT NULL AND password_hash != ''"
        )
        row = cursor.fetchone()
        return row[0] if row else 0

# ─── 密码管理 ────────────────────────────────────────────

def hash_password(password: str) -> str:
    """SHA256 哈希密码"""
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(user_nickname: str, password: str) -> bool:
    """验证用户名和密码，返回 True/False"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT password_hash FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        stored_hash = row[0] or ""
        return stored_hash == hash_password(password)


def set_user_password(user_nickname: str, password: str, registered_ip: str = "") -> bool:
    """设置用户密码，同时记录注册 IP"""
    pw_hash = hash_password(password)
    now = _now()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        if cursor.fetchone():
            # 已存在用户，只更新密码
            if registered_ip:
                cursor.execute(
                    "UPDATE user_reply_configs SET password_hash = ?, updated_at = ?, registered_ip = COALESCE(NULLIF(registered_ip, ''), ?) WHERE user_nickname = ?",
                    (pw_hash, now, registered_ip, user_nickname)
                )
            else:
                cursor.execute(
                    "UPDATE user_reply_configs SET password_hash = ?, updated_at = ? WHERE user_nickname = ?",
                    (pw_hash, now, user_nickname)
                )
        else:
            # 新用户，检查 IP 限制
            if registered_ip and count_ip_accounts(registered_ip) >= MAX_ACCOUNTS_PER_IP:
                raise PermissionError(
                    f"该 IP ({registered_ip}) 已达到账号上限（{MAX_ACCOUNTS_PER_IP}个），请联系管理员"
                )
            cursor.execute("""
                INSERT INTO user_reply_configs
                    (user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                     last_reply_date, is_whitelist, password_hash, registered_ip, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_nickname, "viewer", DEFAULT_DAILY_LIMIT, DEFAULT_TOTAL_LIMIT,
                  0, 0, "", 0, pw_hash, registered_ip, now, now))
        conn.commit()
        return True


def create_user(user_nickname: str, password: str, role: str = "viewer", registered_ip: str = "") -> bool:
    """创建新用户（含密码），检查 IP 限制"""
    valid_roles = ("viewer", "editor", "admin", "superadmin")
    if role not in valid_roles:
        return False
    pw_hash = hash_password(password)
    now = _now()
    # 检查 IP 上限
    if registered_ip and count_ip_accounts(registered_ip) >= MAX_ACCOUNTS_PER_IP:
        raise PermissionError(
            f"该 IP ({registered_ip}) 已达到账号上限（{MAX_ACCOUNTS_PER_IP}个），请联系管理员"
        )
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        if cursor.fetchone():
            return False  # 用户已存在
        cursor.execute("""
            INSERT INTO user_reply_configs
                (user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                 last_reply_date, is_whitelist, password_hash, registered_ip, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_nickname, role, DEFAULT_DAILY_LIMIT, DEFAULT_TOTAL_LIMIT,
              0, 0, "", 0, pw_hash, registered_ip, now, now))
        conn.commit()
        return True


def _now() -> str:
    return datetime.now().isoformat()


def _today() -> str:
    return date.today().isoformat()


# ─── 用户配置 ────────────────────────────────────────────

def get_user_config(user_nickname: str) -> dict:
    """
    获取用户配置，不存在则返回默认配置。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                   last_reply_date, is_whitelist, created_at, updated_at
            FROM user_reply_configs WHERE user_nickname = ?
        """, (user_nickname,))
        row = cursor.fetchone()
        if row:
            return dict(row)

    # 返回默认配置
    return {
        "user_nickname": user_nickname,
        "role": "viewer",
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "total_limit": DEFAULT_TOTAL_LIMIT,
        "daily_count": 0,
        "total_count": 0,
        "last_reply_date": "",
        "is_whitelist": False,
        "created_at": "",
        "updated_at": "",
    }


def can_reply(user_nickname: str) -> bool:
    """
    检查用户是否可以继续回复。
    白名单用户永远可以。
    自动重置每日计数器（新的一天）。
    """
    config = get_user_config(user_nickname)

    # 白名单用户
    if config.get("is_whitelist"):
        return True

    # 检查今日是否需要重置
    today = _today()
    last_date = config.get("last_reply_date") or ""
    if last_date != today:
        # 新的一天，重置每日计数
        _reset_daily(user_nickname, today)
        return True

    daily_limit = config.get("daily_limit", DEFAULT_DAILY_LIMIT)
    total_limit = config.get("total_limit", DEFAULT_TOTAL_LIMIT)
    daily_count = config.get("daily_count", 0)
    total_count = config.get("total_count", 0)

    if daily_count >= daily_limit:
        return False
    if total_count >= total_limit:
        return False

    return True


def _reset_daily(user_nickname: str, today: str) -> None:
    """重置用户每日计数"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_reply_configs
            SET daily_count = 0, last_reply_date = ?
            WHERE user_nickname = ?
        """, (today, user_nickname))
        conn.commit()


def record_reply(user_nickname: str) -> None:
    """
    记录用户发出了一条回复，累加计数。
    如果用户配置不存在，先创建。
    """
    today = _today()

    with get_db() as conn:
        cursor = conn.cursor()

        # 检查记录是否存在
        cursor.execute(
            "SELECT daily_count, total_count, last_reply_date FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        row = cursor.fetchone()

        if row:
            daily_count = row[0]
            total_count = row[1]
            last_date = row[2]

            # 如果跨天了，重置每日计数
            if last_date != today:
                daily_count = 0

            cursor.execute("""
                UPDATE user_reply_configs
                SET daily_count = ?, total_count = ?, last_reply_date = ?, updated_at = ?
                WHERE user_nickname = ?
            """, (daily_count + 1, total_count + 1, today, _now(), user_nickname))
        else:
            # 新用户，首次记录
            cursor.execute("""
                INSERT INTO user_reply_configs
                    (user_nickname, daily_limit, total_limit, daily_count, total_count,
                     last_reply_date, is_whitelist, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_nickname, DEFAULT_DAILY_LIMIT, DEFAULT_TOTAL_LIMIT,
                  1, 1, today, 0, _now(), _now()))
        conn.commit()


def set_user_limits(user_nickname: str, daily_limit: Optional[int] = None,
                    total_limit: Optional[int] = None) -> bool:
    """设置用户回复上限"""
    updates = []
    values = []
    if daily_limit is not None:
        updates.append("daily_limit = ?")
        values.append(daily_limit)
    if total_limit is not None:
        updates.append("total_limit = ?")
        values.append(total_limit)

    if not updates:
        return False

    with get_db() as conn:
        cursor = conn.cursor()
        # 如果用户不存在，先插入
        cursor.execute(
            "SELECT 1 FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO user_reply_configs
                    (user_nickname, daily_limit, total_limit, daily_count, total_count,
                     last_reply_date, is_whitelist, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_nickname,
                  daily_limit if daily_limit else DEFAULT_DAILY_LIMIT,
                  total_limit if total_limit else DEFAULT_TOTAL_LIMIT,
                  0, 0, "", 0, _now(), _now()))
        else:
            values.append(_now())
            values.append(user_nickname)
            cursor.execute(
                f"UPDATE user_reply_configs SET {', '.join(updates)}, updated_at = ? WHERE user_nickname = ?",
                values
            )
        conn.commit()
        return True


def set_user_role(user_nickname: str, role: str) -> bool:
    """设置用户角色"""
    valid_roles = ("viewer", "editor", "admin", "superadmin")
    if role not in valid_roles:
        return False
    now = _now()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,)
        )
        if cursor.fetchone():
            cursor.execute("""
                UPDATE user_reply_configs SET role = ?, updated_at = ?
                WHERE user_nickname = ?
            """, (role, now, user_nickname))
        else:
            cursor.execute("""
                INSERT INTO user_reply_configs
                    (user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                     last_reply_date, is_whitelist, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_nickname, role, DEFAULT_DAILY_LIMIT, DEFAULT_TOTAL_LIMIT,
                  0, 0, "", 0, now, now))
        conn.commit()
        return True


def set_whitelist(user_nickname: str, is_whitelist: bool) -> bool:
    """设置用户白名单状态"""
    now = _now()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_reply_configs WHERE user_nickname = ?",
            (user_nickname,),
        )
        if cursor.fetchone():
            cursor.execute("""
                UPDATE user_reply_configs
                SET is_whitelist = ?, updated_at = ?
                WHERE user_nickname = ?
            """, (int(is_whitelist), now, user_nickname))
        else:
            cursor.execute("""
                INSERT INTO user_reply_configs
                    (user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                     last_reply_date, is_whitelist, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_nickname, "viewer", DEFAULT_DAILY_LIMIT, DEFAULT_TOTAL_LIMIT,
                  0, 0, "", int(is_whitelist), now, now))
        conn.commit()
        return True


def list_users() -> list[dict]:
    """列出所有有配置的用户"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_nickname, role, daily_limit, total_limit, daily_count, total_count,
                   last_reply_date, is_whitelist
            FROM user_reply_configs ORDER BY total_count DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
