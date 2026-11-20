"""Passive, minimal identity observation from the platform's own UI requests.

The endpoint and data.uid are evidenced in the saved official frontend bundle.
No credential extraction, request replay, or nickname-to-identity inference.
"""
import re
import time
from urllib.parse import urlsplit

HOME = "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
ENDPOINT = re.compile(r"^/api/platform/user/info/v(?:\d+|:version|%3[Aa]version)$")


def identity_from_response(url, status, body, observed_at):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "kol.fanqieopen.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not ENDPOINT.fullmatch(parsed.path)):
        return None
    result = {"verified": False, "observed_at": observed_at, "endpoint": parsed.path,
              "identity_source": "platform_account_id", "platform": "fanqie"}
    if status != 200 or not isinstance(body, dict) or type(body.get("code")) is not int or body["code"] != 0:
        return result
    data = body.get("data")
    uid = data.get("uid") if isinstance(data, dict) else None
    if type(uid) not in (str, int) or not re.fullmatch(r"[1-9]\d{2,29}", str(uid)):
        return result
    return {**result, "verified": True, "platform_identity_key": "uid:" + str(uid)}


class FanqieIdentityObserver:
    def __init__(self, page, clock=time.time):
        self.page, self.clock = page, clock
        self.latest = None
        page.on("response", self.on_response)
        page.on("framenavigated", self.on_navigation)

    def on_navigation(self, frame):
        if frame == self.page.main_frame:
            self.reset()

    def reset(self):
        self.latest = None

    def on_response(self, response):
        try:
            parsed = urlsplit(response.url)
            if parsed.hostname != "kol.fanqieopen.com" or not ENDPOINT.fullmatch(parsed.path):
                return
            if response.request.frame != self.page.main_frame:
                return
            # Only the small whitelisted identity subset survives this callback.
            self.latest = identity_from_response(response.url, response.status, response.json(), self.clock())
        except Exception:
            self.latest = {"verified": False, "observed_at": self.clock(), "reason": "identity_response_unreadable"}

    def observe(self):
        parsed = urlsplit(self.page.url)
        visible = self.page.evaluate("""() => {
          const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
          return Array.from(document.querySelectorAll('iframe[src*="captcha"],iframe[src*="verify"],[id*="captcha"],[class*="captcha-slider"],[class*="verify-bar"]')).some(visible);
        }""")
        value = dict(self.latest or {"verified": False, "reason": "identity_not_observed"})
        fresh = type(value.get("observed_at")) in (int, float) and 0 <= self.clock() - value["observed_at"] <= 300
        value.update(challenge=bool(visible), verified=bool(value.get("verified") and fresh and not visible
                     and parsed.scheme == "https" and parsed.hostname == "kol.fanqieopen.com"))
        value['page_location'] = {'origin': parsed.scheme + '://' + (parsed.hostname or ''), 'path': parsed.path}
        return value
