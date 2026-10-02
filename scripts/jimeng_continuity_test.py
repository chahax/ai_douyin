"""Three-shot web-only continuity test; preserve native generated audio."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import jimeng_web_automation as web

RUN = web.PROJECT_ROOT / 'data/video_generation/jimeng_continuity_20260906'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('shot', choices=['S01', 'S02', 'S03'])
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    receipt = RUN / (args.shot + '.json')
    if receipt.exists():
        raise RuntimeError('Existing receipt; inspect before retry to avoid duplicate spending: ' + str(receipt))
    session = web.connect(web.DEFAULT_CDP_URL)
    try:
        page = session.page
        page.goto('https://jimeng.jianying.com/ai-tool/home?type=video', wait_until='domcontentloaded')
        page.get_by_role('textbox').first.wait_for(timeout=15000)
        page.locator('[role=combobox]').filter(has_text='Seedance').first.wait_for(timeout=20000)
        web.set_video_defaults(page)
        prompt = web.extract_shot(web.DEFAULT_SCRIPT, args.shot)
        web.fill_prompt(page, prompt)
        page.keyboard.press('Escape')
        button, cost = web.submit_button_and_cost(page)
        if cost > 60:
            raise RuntimeError('Unexpected price above established 60 credits: ' + str(cost))
        record = dict(shot=args.shot, prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                      cost_credits=cost, model='Seedance 2.5', resolution='480P', aspect='9:16',
                      duration=5, count=1, references=[], status='submit_outcome_unknown',
                      created_at=datetime.now(timezone.utc).isoformat())
        receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        button.click(timeout=8000)
        page.wait_for_timeout(4000)
        record.update(url=page.url, page_after=web.body_excerpt(page))
        # A click alone does not prove the server accepted the generation.
        record['status'] = 'awaiting_ui_verification'
        receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        page.screenshot(path=str(RUN / (args.shot + '_submitted.png')))
        print(json.dumps(record, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == '__main__':
    main()
