"""
auth.py — 登录认证与角色验证组件

登录态通过两个层次维护：
  1. st.session_state  —— 内存级，单次脚本运行内有效（widget 交互 / rerun）
  2. HTTP Cookie        —— 浏览器级，跨页面刷新仍保留
                          用 HMAC-SHA256 签名防篡改，30 天 TTL

刷新页面时由 CookieManager 读 cookie → 验签 → 回填 session_state。
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Optional

import streamlit as st

ROLE_LEVELS = {
    "superadmin": 1,
    "admin": 2,
    "editor": 3,
    "viewer": 4,
}

ROLE_NAMES = {
    "superadmin": "超级管理员",
    "admin": "运营管理员",
    "editor": "运营编辑",
    "viewer": "查看者",
}


def get_role_level(role: str) -> int:
    return ROLE_LEVELS.get(role, 4)


def has_permission(user_role: str, required_role: str) -> bool:
    return get_role_level(user_role) <= get_role_level(required_role)


def get_client_ip() -> str:
    """从请求头获取客户端 IP"""
    headers = st.context.headers if hasattr(st, "context") else {}
    for header in ["X-Forwarded-For", "X-Real-IP", "X-Client-IP", "X-Originating-IP"]:
        ip = headers.get(header, "")
        if ip:
            return ip.split(",")[0].strip()
    return "127.0.0.1"


# ──────────────────────────────────────────────────────────────
# Cookie 签名密钥管理
# ──────────────────────────────────────────────────────────────

_SECRET_FILE = Path("data/.session_secret")
_session_secret_cache: Optional[str] = None


def _get_session_secret() -> str:
    """
    HMAC 签名密钥解析顺序：
      1. env / .env 里的 SESSION_SECRET
      2. data/.session_secret 文件
      3. 生成新的 secrets.token_urlsafe(48) 并落盘

    文件方式保证：
      - 数据库重建后旧 cookie 仍然有效
      - 攻击者拿到 cookie 也无法在没有密钥文件的情况下伪造新 cookie
    """
    global _session_secret_cache
    if _session_secret_cache:
        return _session_secret_cache

    from src.shared.config import settings
    if settings.SESSION_SECRET:
        _session_secret_cache = settings.SESSION_SECRET
        return _session_secret_cache

    if _SECRET_FILE.exists():
        cached = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if cached:
            _session_secret_cache = cached
            return _session_secret_cache

    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_secret = secrets.token_urlsafe(48)
    _SECRET_FILE.write_text(new_secret, encoding="utf-8")
    _session_secret_cache = new_secret
    return _session_secret_cache


def _sign_token(username: str, role: str) -> str:
    """生成签名 token：base64(payload).hex_sig"""
    payload = json.dumps(
        {"u": username, "r": role, "t": int(time.time())},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    sig = hmac.new(
        _get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8")).rstrip(b"=").decode("ascii")
        + "."
        + sig
    )


def _verify_token(token: str) -> Optional[dict]:
    """验签 + 检查 TTL，返回 {u, r, t} 或 None"""
    from src.shared.config import settings
    try:
        payload_b64, sig = token.split(".", 1)
        padding = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        expected_sig = hmac.new(
            _get_session_secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(expected_sig, sig):
            return None
        data = json.loads(payload)
        age_days = (time.time() - data.get("t", 0)) / 86400
        if age_days > settings.SESSION_COOKIE_DAYS:
            return None
        return data
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# CookieManager 单例（必须在脚本顶层实例化）
# ──────────────────────────────────────────────────────────────

_COOKIE_KEY = "auth_cookies_singleton"


@st.cache_resource
def _get_cookie_manager():
    """懒初始化 CookieManager；首次渲染时 ready() 为 False，需要 st.stop 等待。"""
    # streamlit_cookies_manager 0.2.0 的加密变体（EncryptedCookieManager）
    # 内部用了 Streamlit 已废弃的 @st.cache。一旦被 import 就会刷一屏警告。
    # 我们只用普通 CookieManager，加密版完全不需要加载。
    # 解法：在子模块真正加载前，往 sys.modules 注入桩，让 Python 不去读
    # encrypted_cookie_manager.py。这是从 import 层面切断废弃 API 的最小手术。
    import sys
    import types as _types
    _stub_key = "streamlit_cookies_manager.encrypted_cookie_manager"
    if _stub_key not in sys.modules:
        _stub = _types.ModuleType(_stub_key)
        _stub.EncryptedCookieManager = None  # type: ignore[attr-defined]
        sys.modules[_stub_key] = _stub
    from streamlit_cookies_manager.cookie_manager import CookieManager
    return CookieManager(key=_COOKIE_KEY)


# ──────────────────────────────────────────────────────────────
# 登录主流程
# ──────────────────────────────────────────────────────────────

def login_user(username: str, password: str) -> tuple[bool, str]:
    """
    验证用户名和密码，登录成功返回 (True, role)。
    失败返回 (False, error_msg)。
    """
    from src.services.user_profile_service import (
        verify_password,
        get_user_config,
        set_user_password,
        set_user_role,
        set_whitelist,
        count_ip_accounts,
        count_users_with_password,
        MAX_ACCOUNTS_PER_IP,
    )

    ip = get_client_ip()
    config = get_user_config(username)

    # 无用户记录，先创建（首次登录设密码 + 记录 IP）
    if config.get("created_at") in (None, ""):
        try:
            set_user_password(username, password, registered_ip=ip)
        except PermissionError as exc:
            return False, str(exc)
        # 首位注册者自动成为 superadmin + 白名单，
        # 避免数据库重建后无人能进用户管理页面改角色。
        # 此时刚刚插入的那条记录是表中唯一带密码的用户。
        if count_users_with_password() == 1:
            set_user_role(username, "superadmin")
            set_whitelist(username, True)
            role = "superadmin"
        else:
            role = "viewer"
        st.session_state["user"] = username
        st.session_state["user_role"] = role
        return True, role

    # 验证密码
    if verify_password(username, password):
        role = config.get("role", "viewer")
        st.session_state["user"] = username
        st.session_state["user_role"] = role
        return True, role

    return False, "用户名或密码错误"


def logout_user() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("user_role", None)
    # 同时清掉 cookie
    try:
        from src.shared.config import settings
        cookies = _get_cookie_manager()
        if cookies.ready():
            cookies.delete(settings.SESSION_COOKIE_NAME)
            cookies.save()
    except Exception:
        pass


def _try_restore_session_from_cookie() -> bool:
    """
    若 cookie 里存在有效 token，则回填 session_state 并返回 True。
    CookieManager 首次渲染未就绪时跳过（依赖下一次 render 重试）。
    """
    try:
        from src.shared.config import settings
        cookies = _get_cookie_manager()
    except Exception:
        return False
    if not cookies.ready():
        return False

    token = cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return False
    data = _verify_token(token)
    if not data:
        # cookie 损坏或过期 → 清掉，避免一直挡着登录页
        try:
            cookies.delete(settings.SESSION_COOKIE_NAME)
            cookies.save()
        except Exception:
            pass
        return False

    st.session_state["user"] = data["u"]
    st.session_state["user_role"] = data["r"]
    return True


def render_login_page() -> bool:
    # 0. session_state 已有用户 → 直接放行
    if st.session_state.get("user"):
        return True

    # 1. 尝试从 cookie 恢复（刷新后免登录）
    if _try_restore_session_from_cookie():
        st.rerun()
        return True

    # 2. 渲染登录页
    st.set_page_config(page_title="AI Douyin 管理后台", page_icon="🚀", layout="wide")
    st.title("🚀 AI Douyin 管理后台")

    # 展示当前 IP 和剩余注册名额
    from src.services.user_profile_service import count_ip_accounts, MAX_ACCOUNTS_PER_IP
    ip = get_client_ip()
    current_count = count_ip_accounts(ip)
    remaining = MAX_ACCOUNTS_PER_IP - current_count
    if remaining > 0:
        st.caption(f"📍 当前 IP {ip} 剩余注册名额：{remaining}/{MAX_ACCOUNTS_PER_IP}")
    else:
        st.caption("⚠️ 当前 IP 已达到账号上限，如需新账号请联系管理员")

    with st.form("login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录 / 注册", use_container_width=True)
        if submitted and username and password:
            ok, role = login_user(username.strip(), password)
            if ok:
                # 写 cookie（30 天有效）
                try:
                    from src.shared.config import settings
                    cookies = _get_cookie_manager()
                    if cookies.ready():
                        cookies[settings.SESSION_COOKIE_NAME] = _sign_token(username.strip(), role)
                        cookies.save()
                except Exception:
                    pass  # cookie 写失败不影响本次登录
                st.rerun()
            else:
                st.error(role)
        elif submitted:
            st.warning("请输入用户名和密码")
    return False


def is_logged_in() -> bool:
    return st.session_state.get("user") is not None


def get_current_user() -> str:
    return st.session_state.get("user", "")


def get_current_role() -> str:
    return st.session_state.get("user_role", "viewer")
