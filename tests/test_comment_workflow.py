from src.platform_adapter.browser_session import Page
from src.platform_adapter.comment_workflow import CommentWorkflow


class _Session:
    def __init__(self):
        self.calls = []

    def cmd(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == "evaluate":
            return {"value": [{
                "comment_id": "123",
                "author_name": "用户甲",
                "content": "先把合同依据问清楚",
                "created_at": "1小时前",
            }]}
        return {}


def test_page_load_state_accepts_playwright_timeout_and_global_evaluate():
    session = _Session()
    page = Page(session)

    page.wait_for_load_state("domcontentloaded", timeout=30000)
    assert page.evaluate("() => 1") == [{
        "comment_id": "123",
        "author_name": "用户甲",
        "content": "先把合同依据问清楚",
        "created_at": "1小时前",
    }]
    assert session.calls[-1][0] == "evaluate"
    assert session.calls[-1][1]["index"] == -1


def test_comment_parse_uses_one_browser_side_extraction():
    session = _Session()
    page = Page(session)
    workflow = CommentWorkflow(session)

    rows = workflow._parse_comments(page, "https://www.douyin.com/video/1")

    assert len(rows) == 1
    assert rows[0].comment_id == "123"
    assert rows[0].author_name == "用户甲"
    assert rows[0].content == "先把合同依据问清楚"
