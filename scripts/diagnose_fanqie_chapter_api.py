"""Probe the authenticated Fanqie chapter endpoints without printing credentials.

This is a recovery diagnostic for a book that was fetched previously but whose
saved material directory was removed.  It reports response status and JSON
shape only; chapter text is not printed.
"""

from __future__ import annotations

import json

from src.platform_adapter.fanqie_promotion import FanqiePromotionService


BOOK_ID = "7656344274241326104"
ITEM_ID = "7656344295510655512"


def main() -> None:
    service = FanqiePromotionService()
    session = service._open_browser_cache_session(headless=True)
    try:
        page = session.open_page(
            "https://kol.fanqieopen.com/page/content/book-detail"
            f"?tab_type=2&top_tab_genre=-1&book_id={BOOK_ID}&genre=0"
        )
        page.wait_for_timeout(5000)
        result = page.evaluate(
            """
            async () => {
              const probes = [
                ['book', `/api/platform/content/book/list/by_conf/v1?book_id=${%s}&content_tab=2&genre=0`],
                ['list_v1', `/api/platform/content/chapter/list/v1?book_id=${%s}&page_index=0&page_size=500&content_tab=2`],
                ['list_literal', `/api/platform/content/chapter/list/v:version?book_id=${%s}&page_index=0&page_size=500&content_tab=2`],
                ['detail_v1', `/api/platform/content/chapter/detail/v1?book_id=${%s}&item_id=${%s}&content_tab=2`],
                ['detail_literal', `/api/platform/content/chapter/detail/v:version?book_id=${%s}&item_id=${%s}&content_tab=2`],
              ];
              const out = [];
              for (const [name, url] of probes) {
                try {
                  const response = await fetch(url, {credentials: 'include'});
                  const text = await response.text();
                  let parsed = null;
                  try { parsed = JSON.parse(text); } catch (_) {}
                  const data = parsed && typeof parsed === 'object' ? parsed.data : null;
                  out.push({
                    name,
                    status: response.status,
                    ok: response.ok,
                    length: text.length,
                    top_keys: parsed && typeof parsed === 'object' ? Object.keys(parsed) : [],
                    code: parsed && (parsed.code ?? parsed.status_code ?? parsed.err_no),
                    message: parsed && (parsed.message ?? parsed.msg ?? parsed.status_msg),
                    data_keys: data && typeof data === 'object' ? Object.keys(data) : [],
                    data_array_length: Array.isArray(data) ? data.length : null,
                  });
                } catch (error) {
                  out.push({name, fetch_error: String(error)});
                }
              }
              const resources = performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(url => url.includes('/api/platform/content/') && url.includes(%s));
              for (const [index, url] of resources.entries()) {
                try {
                  const response = await fetch(url, {credentials: 'include'});
                  const text = await response.text();
                  let parsed = null;
                  try { parsed = JSON.parse(text); } catch (_) {}
                  const data = parsed && typeof parsed === 'object' ? parsed.data : null;
                  out.push({
                    name: `observed_${index}`,
                    endpoint: new URL(url).pathname,
                    status: response.status,
                    ok: response.ok,
                    length: text.length,
                    top_keys: parsed && typeof parsed === 'object' ? Object.keys(parsed) : [],
                    code: parsed && (parsed.code ?? parsed.status_code ?? parsed.err_no),
                    message: parsed && (parsed.message ?? parsed.msg ?? parsed.status_msg),
                    data_keys: data && typeof data === 'object' ? Object.keys(data) : [],
                    data_array_length: Array.isArray(data) ? data.length : null,
                  });
                } catch (error) {
                  out.push({name: `observed_${index}`, fetch_error: String(error)});
                }
              }
              return out;
            }
            """
            % (
                json.dumps(BOOK_ID),
                json.dumps(BOOK_ID),
                json.dumps(BOOK_ID),
                json.dumps(BOOK_ID),
                json.dumps(ITEM_ID),
                json.dumps(BOOK_ID),
                json.dumps(ITEM_ID),
                json.dumps(BOOK_ID),
            )
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        session.stop()


if __name__ == "__main__":
    main()
