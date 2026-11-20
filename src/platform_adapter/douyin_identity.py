"""Douyin identity verification through official OAuth or a visible account page."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.platform_adapter.browser_session import BrowserSession, BrowserNavigationTimeout
from src.platform_adapter.douyin_challenge import confirmed_douyin_challenge, DouyinVerificationSurfaceError
from src.shared.config import settings


DOUYIN_SELF_URL = "https://www.douyin.com/user/self?from_tab_name=main"
_DOUYIN_CHALLENGE_SELECTOR = (
    'iframe[src*="/verifycenter/"], '
    'iframe[src*="/captcha/"], iframe[src*="captcha"]'
)


class DouyinIdentityVerificationError(RuntimeError):
    def __init__(self, code: str, message: str, *, navigation_evidence=None):
        super().__init__(message)
        self.code = code
        self.navigation_evidence = navigation_evidence


class DouyinPageIdentityVerifier:
    """Read only the public identity shown by the authenticated Douyin page."""

    def probe(self, session: BrowserSession) -> DouyinIdentity:
        navigation = None
        try:
            page = session.open_page(DOUYIN_SELF_URL)
        except BrowserNavigationTimeout as exc:
            navigation = exc.navigation_evidence
            # Inspect only this navigation's committed target. Never accept
            # identity left on the old page or reload a failed request.
            if (exc.page is None or not navigation['navigation_committed']
                    or not navigation['target_matched']
                    or navigation['ready_state'] not in {'interactive', 'complete'}):
                raise DouyinIdentityVerificationError(
                    exc.code, str(exc), navigation_evidence=navigation) from exc
            page = exc.page
        profile_navigation_attempted = False
        login_required = False
        for _ in range(16):
            page.wait_for_timeout(500)
            try:
                captcha_ready = self._has_captcha(page)
            except DouyinVerificationSurfaceError as exc:
                raise DouyinIdentityVerificationError(exc.code, str(exc)) from exc
            if captcha_ready:
                raise DouyinIdentityVerificationError(
                    "human_required", "抖音要求人工完成安全验证。"
                )
            body_text = self._body_text(page)
            login_required = self._requires_login(body_text)
            identity = self._extract(page)
            if identity.nickname and identity.platform_identity_key:
                identity.validate()
                return identity
            if not profile_navigation_attempted and navigation is None:
                profile_navigation_attempted = True
                try:
                    profile_links = page.locator('a[href*="/user/self"]')
                    if profile_links.count() > 0:
                        profile_links.first().click()
                        page.wait_for_timeout(1000)
                        continue
                except Exception:
                    pass
        if login_required:
            raise DouyinIdentityVerificationError(
                "login_expired", "抖音页面要求登录，当前会话无法读取绑定身份，请重新登录后验证。"
            )
        if navigation is not None:
            raise DouyinIdentityVerificationError(
                "browser_navigation_timeout",
                "原身份页跳转超时，当前页面仍未读到可核验身份；未重新加载或恢复任务。",
                navigation_evidence=navigation,
            )
        raise DouyinIdentityVerificationError(
            "identity_unavailable",
            "已打开抖音页面，但没有读取到可确认的昵称和公开 UID。",
        )

    @staticmethod
    def _extract(page) -> DouyinIdentity:
        from src.operations_accounts.models import DouyinIdentity

        script = r"""
        (() => {
          const text = String(document.body?.innerText || '');
          const publicMatch = text.match(
            /(?:抖音号|抖音\s*ID)\s*[:：]\s*([0-9A-Za-z_.-]{2,80})/i
          );
          const currentHref = String(location.href || '');
          const secMatch = currentHref.match(/\/user\/(?!self(?:[/?#]|$))([^/?#]+)/);
          const nicknameNode = [
            document.querySelector('[data-e2e="user-title"]'),
            document.querySelector('[data-e2e="user-name"]'),
            document.querySelector('[class*="user-info"] h1'),
            document.querySelector('h1'),
          ].find(node => node && String(node.innerText || '').trim());
          const title = String(
            document.querySelector('meta[property="og:title"]')?.content
            || document.title || ''
          ).replace(/\s*[-_|].*抖音.*$/i, '').replace(/的主页.*$/, '').trim();
          const avatarNode = [
            document.querySelector('[data-e2e="user-avatar"] img'),
            document.querySelector('[class*="avatar"] img'),
            document.querySelector('meta[property="og:image"]'),
          ].find(Boolean);
          return {
            nickname: String(nicknameNode?.innerText || title || '').trim().slice(0, 120),
            avatar_url: String(avatarNode?.src || avatarNode?.content || '').trim().slice(0, 1000),
            public_uid: String(publicMatch?.[1] || '').trim(),
            sec_uid: String(secMatch?.[1] || '').trim(),
          };
        })()
        """
        value = page.locator("").evaluate(script) or {}
        return DouyinIdentity(
            nickname=str(value.get("nickname") or "").strip(),
            avatar_url=str(value.get("avatar_url") or "").strip(),
            public_uid=str(value.get("public_uid") or "").strip(),
            sec_uid=str(value.get("sec_uid") or "").strip(),
            verification_source="page_verified",
            verified_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _body_text(page) -> str:
        try:
            return page.locator("body").inner_text() or ""
        except Exception:
            return ""

    @staticmethod
    def _has_captcha(page) -> bool:
        return has_visible_douyin_challenge(page)

    @staticmethod
    def _requires_login(body_text: str) -> bool:
        normalized = re.sub(r"\s+", "", body_text or "")
        return any(
            marker in normalized
            for marker in (
                "扫码登录",
                "验证码登录",
                "密码登录",
                "登录/注册",
                "创作者登录",
            )
        )


def has_visible_douyin_challenge(page) -> bool:
    """Only ready verification content is human_required; unknown remains blocked."""
    evidence = confirmed_douyin_challenge(page)
    if evidence['blocking'] and evidence['surface_state'] != 'challenge_ready':
        raise DouyinVerificationSurfaceError(evidence)
    return evidence['blocking']


class DouyinOAuthClient:
    """Minimal server-side OAuth exchange used only when app credentials exist."""

    authorize_endpoint = "https://open.douyin.com/platform/oauth/connect/"
    token_endpoint = "https://open.douyin.com/oauth/access_token/"
    userinfo_endpoint = "https://open.douyin.com/oauth/userinfo/"

    @property
    def configured(self) -> bool:
        return bool(
            settings.DOUYIN_CLIENT_KEY
            and settings.DOUYIN_CLIENT_SECRET
            and settings.DOUYIN_OAUTH_REDIRECT_URI
        )

    def new_state(self) -> str:
        return secrets.token_urlsafe(24)

    def authorization_url(self, state: str) -> str:
        if not self.configured:
            raise DouyinIdentityVerificationError(
                "oauth_not_configured",
                "尚未配置抖音开放平台 ClientKey、ClientSecret 和回调地址。",
            )
        query = urlencode(
            {
                "client_key": settings.DOUYIN_CLIENT_KEY,
                "response_type": "code",
                "scope": "user_info",
                "redirect_uri": settings.DOUYIN_OAUTH_REDIRECT_URI,
                "state": state,
            }
        )
        return f"{self.authorize_endpoint}?{query}"

    def exchange_identity(self, code: str) -> DouyinIdentity:
        from src.operations_accounts.models import DouyinIdentity

        if not self.configured:
            raise DouyinIdentityVerificationError(
                "oauth_not_configured", "抖音开放平台 OAuth 尚未配置。"
            )
        token_payload = self._post_form(
            self.token_endpoint,
            {
                "client_key": settings.DOUYIN_CLIENT_KEY,
                "client_secret": settings.DOUYIN_CLIENT_SECRET,
                "code": code.strip(),
                "grant_type": "authorization_code",
            },
        )
        token_data = token_payload.get("data") or {}
        self._raise_api_error(token_data, "换取 access_token 失败")
        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise DouyinIdentityVerificationError(
                "oauth_token_missing", "开放平台未返回 access_token。"
            )
        user_payload = self._post_json(
            self.userinfo_endpoint,
            {},
            headers={"access-token": access_token},
        )
        user_data = user_payload.get("data") or {}
        self._raise_api_error(user_data, "读取抖音公开身份失败")
        expires_in = int(token_data.get("expires_in") or 0)
        identity = DouyinIdentity(
            nickname=str(user_data.get("nickname") or "").strip(),
            avatar_url=str(user_data.get("avatar") or "").strip(),
            open_id=str(user_data.get("open_id") or token_data.get("open_id") or "").strip(),
            union_id=str(user_data.get("union_id") or "").strip(),
            verification_source="official_oauth",
            verified_at=datetime.now(timezone.utc).isoformat(),
            auth_expires_at=(
                (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
                if expires_in > 0
                else ""
            ),
        )
        identity.validate()
        return identity

    @staticmethod
    def _post_form(url: str, data: dict[str, str]) -> dict:
        request = Request(
            url,
            data=urlencode(data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return DouyinOAuthClient._read_json(request)

    @staticmethod
    def _post_json(
        url: str, data: dict, *, headers: dict[str, str] | None = None
    ) -> dict:
        request = Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        return DouyinOAuthClient._read_json(request)

    @staticmethod
    def _read_json(request: Request) -> dict:
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise DouyinIdentityVerificationError(
                "oauth_request_failed", f"抖音开放平台请求失败：{exc}"
            ) from exc

    @staticmethod
    def _raise_api_error(data: dict, prefix: str) -> None:
        code = str(data.get("error_code") or "0")
        if code not in {"", "0"}:
            description = str(data.get("description") or code)
            raise DouyinIdentityVerificationError(
                "oauth_api_error", f"{prefix}：{description}"
            )
