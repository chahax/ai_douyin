"""Inspect only the three submitted workspaces, and collect rendered media."""
import json
import re
import argparse
import hashlib
import urllib.request
from urllib.parse import urlsplit

import jimeng_web_automation as web
from jimeng_continuity_test import RUN


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    session = web.connect(web.DEFAULT_CDP_URL)
    try:
        for shot in ['S01', 'S02', 'S03']:
            receipt = RUN / (shot + '.json')
            record = json.loads(receipt.read_text(encoding='utf-8'))
            pages = [p for c in session.browser.contexts for p in c.pages]
            page = next((p for p in pages if p.url == record['url']), None)
            if page is None:
                page = session.browser.contexts[0].new_page()
                page.goto(record['url'], wait_until='domcontentloaded')
            page.bring_to_front()
            page.get_by_text('详细信息', exact=True).first.wait_for(state='attached', timeout=20000)
            page.wait_for_timeout(2000)
            body = web.body_excerpt(page)
            media = page.locator('video').evaluate_all('els => els.map(e => ({src:e.currentSrc || e.src, poster:e.poster, duration: Number.isFinite(e.duration)?e.duration:null}))')
            progress = re.findall(r'\d+%造梦中|生成失败|排队中|生成中\.\.\.', body)
            record['latest_progress'] = progress
            record['rendered_media'] = media
            record['status'] = 'generating' if progress else 'inspect_result'
            outputs = [m for m in media if urlsplit(m['src']).netloc.endswith('.vlabvod.com') and m['duration'] and m['duration'] >= 4]
            if outputs and not progress and '再次生成' in body:
                record['status'] = 'completed_on_web'
                if args.download:
                    destination = RUN / (shot + '.mp4')
                    if not destination.exists():
                        request = urllib.request.Request(outputs[0]['src'], headers={'Referer': page.url})
                        with urllib.request.urlopen(request, timeout=60) as response:
                            payload = response.read()
                        if len(payload) < 10000 or b'ftyp' not in payload[:32]:
                            raise RuntimeError('Response is not an expected MP4')
                        destination.write_bytes(payload)
                    record['local_video'] = str(destination)
                    record['video_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
                    record['status'] = 'downloaded'
            receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(dict(shot=shot, status=record['status'], progress=progress, video_count=len(media), media_hosts=[urlsplit(m['src']).netloc for m in media], local_video=record.get('local_video')),ensure_ascii=False), flush=True)
            page.screenshot(path=str(RUN / (shot + '_latest.png')))
    finally:
        session.close()


if __name__ == '__main__':
    main()
