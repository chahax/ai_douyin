"""Read a single exact book card and its promotion form without submitting it."""
import json
import re
import time


class BookInspectionStopped(ValueError):
    pass


def inspect_book(page, title, guard, checkpoint, *, chapters=1):
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise BookInspectionStopped('invalid_book_title')
    title = title.strip()
    if type(chapters) is not int or not 1 <= chapters <= 3:
        raise BookInspectionStopped('chapter_limit_invalid')
    result = {'book_name': title, 'observed_at': time.time(),
              'promotion_submitted': False, 'promotion_task_active': False}
    deadline = time.monotonic() + 50

    def evaluate(js):
        if time.monotonic() >= deadline:
            raise BookInspectionStopped('inspection_deadline')
        guard()
        return page.evaluate(js)

    def save(stage, value):
        result[stage] = value
        checkpoint(result)
        return value

    def card_js(action):
        return '''() => {
          const wanted = %s;
          const cards = Array.from(document.querySelectorAll('.book-hQ7GYr'))
            .filter(c => (c.querySelector('.book-title-txt-_CIhYa')?.innerText || '').trim() === wanted);
          if (cards.length !== 1) return {ok:false,reason:'exact_card_not_unique',count:cards.length};
          const card = cards[0];
          const text = card.innerText;
          %s
        }''' % (json.dumps(title, ensure_ascii=False), action)

    # Login identity can arrive before the asynchronously rendered book cards.
    # Wait only for rendering; never repeat a click or silently pick another book.
    rendered = None
    for _ in range(20):
        rendered = evaluate('''() => ({titles:Array.from(document.querySelectorAll('.book-hQ7GYr'))
          .map(c=>(c.querySelector('.book-title-txt-_CIhYa')?.innerText || '').trim()),
          text:document.body.innerText.slice(0,20000)})''')
        if rendered['titles']:
            break
        page.wait_for_timeout(500)
    save('catalogue_snapshot', rendered)
    opened = save('promotion_card', evaluate(card_js('''
          const button = Array.from(card.querySelectorAll('.c-promotions button,button'))
            .find(b => b.innerText.trim() === '别名推广' && !b.disabled);
          if (!button) return {ok:false,reason:'promotion_button_unavailable',text};
          button.click(); return {ok:true,text};''')))
    if not opened.get('ok'):
        raise BookInspectionStopped(opened.get('reason', 'card_unavailable'))
    page.wait_for_timeout(1200)
    form = save('promotion_form', evaluate('''() => {
      const visible = e => !!(e.getBoundingClientRect().width && e.getBoundingClientRect().height);
      const dialogs = Array.from(document.querySelectorAll('.arco-modal-content')).filter(visible);
      if (dialogs.length !== 1) return {ok:false,reason:'promotion_form_not_unique'};
      const modal=dialogs[0];
      const selects=Array.from(modal.querySelectorAll('.arco-select')).filter(visible);
      if (selects.length !== 1) return {ok:false,reason:'publish_type_not_unique',text:modal.innerText};
      const text=modal.innerText;
      selects[0].click(); return {ok:true,text};
    }'''))
    if not form.get('ok'):
        raise BookInspectionStopped(form.get('reason', 'form_unavailable'))
    book_ids = re.findall(re.escape(title) + r'（([0-9]{10,24})）', form['text'])
    if len(book_ids) != 1:
        raise BookInspectionStopped('promotion_book_id_missing')
    result['book_id'] = book_ids[0]
    page.wait_for_timeout(500)
    options = save('publish_types', evaluate('''() => Array.from(document.querySelectorAll('.arco-select-option,[role="option"]'))
      .filter(e => e.getBoundingClientRect().width && e.getBoundingClientRect().height)
      .map(e => ({text:e.innerText.trim(),disabled:e.getAttribute('aria-disabled')==='true' || /disabled/.test(e.className)}))'''))
    result['aigc_available'] = any(o['text'] == 'AIGC' and not o['disabled'] for o in options)
    checkpoint(result)
    # Dismiss the form, never fill an alias, accept terms, or press submit.
    closed = evaluate('''() => {
      const close=Array.from(document.querySelectorAll('.arco-modal-close-icon'))
        .filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().height);
      if(close.length!==1) return false;
      close[0].click();return true;
    }''')
    if not closed:
        raise BookInspectionStopped('form_close_unavailable')
    page.wait_for_timeout(300)
    guard()
    # Existing platform route, with the ID actually rendered in this exact form.
    page.goto('https://kol.fanqieopen.com/page/content/book-detail?tab_type=2&top_tab_genre=-1&book_id=' + result['book_id'] + '&genre=0', wait_until='domcontentloaded')
    for _ in range(20):
        if evaluate('''() => !!document.querySelector('.book-name-WEvqxi,[class*="book-name"]:not([class*="copy"])')'''):
            break
        page.wait_for_timeout(500)
    snapshot = save('detail', evaluate('''() => {
      const u=new URL(location.href);
      const text=e=>e ? e.innerText.trim() : '';
      return {url:u.href,book_id:u.searchParams.get('book_id') || '',
        title:text(document.querySelector('.book-name-WEvqxi,[class*="book-name"]:not([class*="copy"])')),
        author:text(document.querySelector('.book-author-Ygu_Z1,[class*="book-author"]')),
        text:document.body.innerText.slice(0,80000),
        chapter_text:text(document.querySelector('#content,[class*="chapter-content"]')),
        item_id:u.searchParams.get('item_id') || ''};
    }'''))
    if not re.fullmatch(r'[0-9]{10,24}', snapshot.get('book_id','')):
        raise BookInspectionStopped('detail_book_id_missing')
    if snapshot.get('title') != title:
        raise BookInspectionStopped('detail_title_mismatch')
    if snapshot['book_id'] != result['book_id']:
        raise BookInspectionStopped('detail_id_mismatch')
    chapter = save('chapter_selection', evaluate('''() => {
      const items=Array.from(document.querySelectorAll('.catalogue__item-ImEeJx,[class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])'));
      const item=items.find(e=>e.querySelector('.catalogue__item-text-Dcm6hj,[class*="catalogue__item-text"]'));
      if(!item) return {ok:false,reason:'catalogue_missing'};
      const title=item.querySelector('.catalogue__item-text-Dcm6hj,[class*="catalogue__item-text"]').innerText.trim();
      if(item.querySelector('svg.catalogue__item-icon-VgbkwJ,[class*="lock"]')) return {ok:false,reason:'chapter_locked',title};
      item.click();return {ok:true,title};
    }'''))
    if chapter.get('ok'):
        for _ in range(16):
            page.wait_for_timeout(500)
            reader = evaluate('''() => {
              const u=new URL(location.href),el=document.querySelector('#content,[class*="chapter-content"]');
              return {url:u.href,book_id:u.searchParams.get('book_id') || '', item_id:u.searchParams.get('item_id') || '',
                text:el ? el.innerText.trim() : ''};
            }''')
            if reader.get('item_id') and len(reader.get('text','')) >= 100:
                break
        save('chapter', reader)
        if reader['book_id'] != result['book_id'] or not re.fullmatch(r'[0-9]{10,24}',reader['item_id']):
            raise BookInspectionStopped('chapter_source_unconfirmed')
        if len(reader['text']) < 100 or any(x in reader['text'] for x in ('试读结束','付费章节','请先登录','开通会员')):
            raise BookInspectionStopped('chapter_unavailable')
        result['chapters'] = [{**reader, 'title':chapter['title']}]
        checkpoint(result)
        for index in range(1, chapters):
            selection = evaluate('''() => {
              const items=Array.from(document.querySelectorAll('.catalogue__item-ImEeJx,[class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])'))
                .filter(e=>e.querySelector('.catalogue__item-text-Dcm6hj,[class*="catalogue__item-text"]'));
              const item=items[%d];
              if(!item) return {ok:false,reason:'chapter_missing'};
              const title=item.querySelector('.catalogue__item-text-Dcm6hj,[class*="catalogue__item-text"]').innerText.trim();
              if(item.querySelector('svg.catalogue__item-icon-VgbkwJ,[class*="lock"]')) return {ok:false,reason:'chapter_locked',title};
              item.click();return {ok:true,title};
            }''' % index)
            if not selection.get('ok'):
                save('chapter_stop',selection)
                break
            previous=result['chapters'][-1]
            for _ in range(16):
                page.wait_for_timeout(500)
                next_reader=evaluate('''() => {
                  const u=new URL(location.href),el=document.querySelector('#content,[class*="chapter-content"]');
                  return {url:u.href,book_id:u.searchParams.get('book_id') || '',item_id:u.searchParams.get('item_id') || '',text:el ? el.innerText.trim() : ''};
                }''')
                if next_reader['item_id'] != previous['item_id'] and next_reader['text'] != previous['text'] and len(next_reader['text'])>=100:
                    break
            if (next_reader['book_id'] != result['book_id'] or not re.fullmatch(r'[0-9]{10,24}',next_reader['item_id'])
                    or next_reader['item_id'] in {c['item_id'] for c in result['chapters']} or next_reader['text']==previous['text']):
                raise BookInspectionStopped('next_chapter_source_unconfirmed')
            if len(next_reader['text'])<100 or any(x in next_reader['text'] for x in ('试读结束','付费章节','请先登录','开通会员')):
                raise BookInspectionStopped('next_chapter_unavailable')
            result['chapters'].append({**next_reader,'title':selection['title']})
            checkpoint(result)
    result['status'] = 'inspected'
    checkpoint(result)
    return result
