"""Publication copy shared by the Fanqie workspace preview and publisher."""
from src.platform_adapter.publish_verification import declared_description


def novel_publication_copy(hook, book_name, alias):
    if not all(isinstance(value, str) and value.strip() for value in (hook, book_name, alias)):
        raise ValueError('生成小说推广文案需要剧情引子、书名和推广词')
    body = hook.strip() + '\n本视频含小说推广，推广者可能获益。画面与声音由 AI 生成。'
    return {
        'description': declared_description(body, fictional_story=True),
        'comment': f'想看后续，打开番茄小说搜「{alias.strip()}」。原著是《{book_name.strip()}》📖',
    }
