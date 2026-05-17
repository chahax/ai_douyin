"""
auth.py — 登录认证与角色验证组件
"""

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


def login_user(username: str, password: str) -> tuple[bool, str]:
    """
    验证用户名和密码，登录成功返回 (True, role)。
    失败返回 (False, error_msg)。
    """
    from src.services.user_profile_service import verify_password, get_user_config, set_user_password
    config = get_user_config(username)
    # 无用户记录，先创建（首次登录设密码）
    if config.get("created_at") is None or config.get("created_at") == "":
        set_user_password(username, password)
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


def render_login_page() -> bool:
    if st.session_state.get("user"):
        return True
    st.set_page_config(page_title="AI Douyin 管理后台", page_icon="🚀", layout="wide")
    st.title("🚀 AI Douyin 管理后台")
    with st.form("login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录", use_container_width=True)
        if submitted and username and password:
            ok, result = login_user(username.strip(), password)
            if ok:
                st.rerun()
            else:
                st.error(result)
        elif submitted:
            st.warning("请输入用户名和密码")
    return False


def is_logged_in() -> bool:
    return st.session_state.get("user") is not None


def get_current_user() -> str:
    return st.session_state.get("user", "")


def get_current_role() -> str:
    return st.session_state.get("user_role", "viewer")
