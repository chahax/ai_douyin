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
from datetime import datetime, timedelta
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

_SECRET_FILE = Path(__file__).resolve().parents[3] / "data" / ".session_secret"
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
# CookieManager（每次 Streamlit 脚本执行时初始化一次）
# ──────────────────────────────────────────────────────────────

_LOGOUT_PENDING_KEY = "_auth_logout_pending"
_COOKIE_WRITE_PENDING_KEY = "_auth_cookie_write_pending"


def _browser_cookie(cookies):
    """Read browser echo only: CookieManager.get() also includes unsaved writes."""
    from src.shared.config import settings
    snapshot = getattr(cookies, "_cookies", None)
    return snapshot.get(settings.SESSION_COOKIE_NAME) if snapshot is not None else None


def _get_cookie_manager():
    """创建当前浏览器会话的 CookieManager。

    CookieManager 本身会在 ``st.session_state`` 中维护待写队列，不能用
    ``st.cache_resource`` 做全局缓存，否则其他浏览器会话不会渲染负责同步
    Cookie 的前端组件。
    """
    from streamlit_cookies_manager.cookie_manager import CookieManager
    from src.shared.config import settings

    class AcknowledgedCookieManager(CookieManager):
        def save(self):
            if self._queue:
                # The library's saveOnly=True never returns an acknowledgement.
                # Keep a readback component alive until the browser echoes the write.
                self._run_component(save_only=False, key="CookieManager.sync_cookies.save")

    cookies = AcknowledgedCookieManager(path="/")
    cookies._default_expiry = datetime.now() + timedelta(days=settings.SESSION_COOKIE_DAYS)
    return cookies


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
        count_users_with_password,
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
    """清除内存登录态，并安排在下一次重绘时删除持久 Cookie。"""
    st.session_state.pop("user", None)
    st.session_state.pop("user_role", None)
    st.session_state.pop(_COOKIE_WRITE_PENDING_KEY, None)
    st.session_state[_LOGOUT_PENDING_KEY] = True


def _delete_session_cookie(cookies) -> None:
    """删除浏览器中的持久登录 Cookie。"""
    from src.shared.config import settings

    queue = getattr(cookies, "_queue", None)
    if queue is not None:
        # Cancel an in-flight login write too, even if no cookie was echoed yet.
        queue[settings.SESSION_COOKIE_NAME] = dict(value=None, path="/")
        cookies.save()
    elif settings.SESSION_COOKIE_NAME in cookies:
        del cookies[settings.SESSION_COOKIE_NAME]
        cookies.save()


def _persist_session_cookie(cookies, username: str, role: str) -> None:
    """保存签名登录令牌；Cookie 中不包含密码。"""
    from src.shared.config import settings

    token = st.session_state.get(_COOKIE_WRITE_PENDING_KEY)
    if not token:
        token = _sign_token(username, role)
        st.session_state[_COOKIE_WRITE_PENDING_KEY] = token
    cookies[settings.SESSION_COOKIE_NAME] = token
    cookies.save()


def _confirm_cookie_write(cookies) -> bool:
    token = st.session_state.get(_COOKIE_WRITE_PENDING_KEY)
    if token and _browser_cookie(cookies) == token and _verify_token(token):
        st.session_state.pop(_COOKIE_WRITE_PENDING_KEY, None)
        return True
    return False


def _wait_for_cookie(message: str) -> None:
    st.info(message)
    st.caption("请稍候，正在等待浏览器确认。若一直未完成，请检查此站点是否允许 Cookie。")
    st.button("重新检查登录状态", key="auth_cookie_retry")
    st.stop()


def _try_restore_session_from_cookie(cookies) -> bool:
    """
    若 cookie 里存在有效 token，则回填 session_state 并返回 True。
    调用方负责确保 CookieManager 已经 ready。
    """
    from src.shared.config import settings

    token = _browser_cookie(cookies)
    if not token:
        return False
    data = _verify_token(token)
    if not data:
        # cookie 损坏或过期 → 清掉，避免一直挡着登录页
        try:
            _delete_session_cookie(cookies)
        except Exception:
            pass
        return False

    st.session_state["user"] = data["u"]
    st.session_state["user_role"] = data["r"]
    return True


def render_login_page() -> bool:
    st.set_page_config(page_title="Douyin Studio · 内容创作与运营", page_icon="✦", layout="wide")
    from src.web.components.ui import inject_app_theme

    inject_app_theme()

    # Cookie 组件必须在每次脚本执行时渲染一次。首次加载时等待组件把浏览器
    # Cookie 同步给 Python，避免先错误地显示登录页或漏写登录令牌。
    cookies = None
    cookie_error = None
    try:
        cookies = _get_cookie_manager()
    except Exception as exc:
        cookie_error = exc

    if cookies is not None and not cookies.ready():
        st.caption("正在恢复登录状态…")
        st.stop()

    # 退出按钮在上一轮设置此标记；本轮 CookieManager 已就绪，可以可靠删除。
    logged_out = bool(st.session_state.get(_LOGOUT_PENDING_KEY, False))
    if logged_out and cookies is not None:
        if _browser_cookie(cookies) is not None:
            _delete_session_cookie(cookies)
            _wait_for_cookie("已退出当前会话，正在确认浏览器登录凭证已删除…")
        # The readback is absent. Clear any queued write left from the old session.
        queue = getattr(cookies, "_queue", {})
        from src.shared.config import settings
        queue.pop(settings.SESSION_COOKIE_NAME, None)
        st.session_state.pop(_LOGOUT_PENDING_KEY, None)

    # Always mount cookie sync, including authenticated reruns. Do not treat the
    # pending write queue as proof that the browser persisted the credential.
    if st.session_state.get("user") and not logged_out:
        if cookies is None:
            st.warning("当前仅保持临时登录：Cookie组件不可用，刷新后可能需要重新登录。")
            return True
        if st.session_state.get(_COOKIE_WRITE_PENDING_KEY):
            if not _confirm_cookie_write(cookies):
                cookies.save()
                _wait_for_cookie("登录已验证，正在确认免登录凭证已保存…")
        else:
            saved = _verify_token(_browser_cookie(cookies) or "")
            if not saved or saved.get("u") != st.session_state["user"]:
                _persist_session_cookie(cookies, st.session_state["user"], st.session_state["user_role"])
                _wait_for_cookie("正在保存本次登录，确认完成后进入后台…")
        return True

    # 尝试从 cookie 恢复（刷新后免登录）
    if not logged_out and cookies is not None and _try_restore_session_from_cookie(cookies):
        return True

    # Two-column introduction and focused login surface; authentication is unchanged.
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown('''<div class="studio-brand"><span class="studio-brand-mark">✦</span>
<div>Douyin Studio<small>内容创作与运营</small></div></div>
<div class="studio-login-hero"><div class="studio-eyebrow">YOUR NEXT STORY STARTS HERE</div>
<h1>好内容，<br>从一个<em>好想法</em>开始。</h1>
<p>发现值得讲述的选题，打磨每一个镜头。<br>在同一个工作空间，连接灵感、作品与观众。</p>
<div class="studio-login-steps"><span>01 发现选题</span><span>02 打磨作品</span><span>03 持续运营</span></div></div>''', unsafe_allow_html=True)
    with right, st.container(key="login_panel"):
        st.markdown("## 欢迎回到工作台")
        st.caption("登录，继续你的内容创作。")
        if cookie_error is not None:
            st.warning("登录状态暂时无法保存；本次仍可登录。请检查 Cookie 组件依赖。")
        with st.form("login_form"):
            username = st.text_input("用户名", placeholder="输入你的用户名")
            password = st.text_input("密码", type="password", placeholder="输入密码")
            submitted = st.form_submit_button("进入工作台 →", type="primary", width="stretch")
        from src.services.user_profile_service import count_ip_accounts, MAX_ACCOUNTS_PER_IP
        ip = get_client_ip()
        remaining = MAX_ACCOUNTS_PER_IP - count_ip_accounts(ip)
        if remaining > 0:
            st.caption(f"新用户名将自动注册 · 当前网络还可注册 {remaining} 个账号")
        else:
            st.caption("使用已有账号登录；如需新账号，请联系管理员。")
    # Cookie readback must live OUTSIDE the form: forms batch component changes
    # until submission, which would prevent the automatic acknowledgement rerun.
    if submitted and username and password:
        ok, role = login_user(username.strip(), password)
        if ok:
            if cookies is not None:
                try:
                    _persist_session_cookie(cookies, username.strip(), role)
                except Exception:
                    st.warning("登录成功，但保存登录状态失败。请重新检查；未确认前不要刷新页面。")
                # Keep both components mounted; their readback triggers the rerun.
                st.info("登录已验证，正在保存免登录凭证；浏览器确认后自动进入后台。")
                st.button("重新检查登录状态", key="auth_cookie_retry")
                return False
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
