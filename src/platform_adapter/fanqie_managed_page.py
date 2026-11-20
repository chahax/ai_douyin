"""Small bridge from our tab-fenced Page RPC to the batch adapter's Page API.

Uses the installed Playwright selector builder so accessible-name matching has
the same semantics as native get_by_role. No browser creation or ownership here.
"""
from playwright._impl._locator import get_by_role_selector


class FanqieManagedPage:
    def __init__(self, page):
        self.page = page

    @property
    def url(self):
        # Read the worker, not Page.url's cached fallback after an RPC failure.
        return self.page._cmd("current_url")["url"]

    def reload(self, *, wait_until="domcontentloaded"):
        self.page.goto(self.url, wait_until=wait_until)

    def evaluate(self, js):
        return self.page.evaluate(js)

    def wait_for_timeout(self, ms):
        return self.page.wait_for_timeout(ms)

    def get_by_role(self, role, *, name, exact=False):
        return ManagedLocator(self.page, get_by_role_selector(role, name=name, exact=exact))


class ManagedLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def _locator(self):
        return self.page.locator(self.selector)

    def count(self):
        return self._locator().count()

    def is_visible(self):
        return self._locator().evaluate("e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'")

    def is_enabled(self):
        return self._locator().evaluate("e => !e.matches(':disabled') && !e.closest('[aria-disabled=true]')")

    def click(self):
        return self._locator().click()

    def set_input_files(self, path):
        return self._locator().set_input_files(path)

    def locator(self, selector):
        return ManagedLocator(self.page, self.selector + " >> " + selector)

    def get_by_role(self, role, *, name, exact=False):
        return self.locator(get_by_role_selector(role, name=name, exact=exact))
