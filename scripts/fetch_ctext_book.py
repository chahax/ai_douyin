"""
从 ctext.org 抓取中文古籍并导入 RAG 知识库

用法：
    python scripts/fetch_ctext_book.py 论语
    python scripts/fetch_ctext_book.py 孟子
    python scripts/fetch_ctext_book.py 道德经

依赖：
    pip install beautifulsoup4 requests
"""

import re
import sys
import time
import argparse
from pathlib import Path
from typing import Optional, List
from urllib.parse import quote

import logging
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fetch_ctext")


CTEXT_BASE = "https://ctext.org"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 复用 session，自动重试
_session = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


# ctext.org 书籍名 → URL 路径映射
BOOK_NAME_MAP = {
    "论语": "analects",
    "孟子": "mencius",
    "道德经": "taoteching",
    "庄子": "zhuangzi",
    "中庸": "doctrine-of-mean",
    "大学": "great-learning",
    "易经": "iching",
    "尚书": "shujing",
    "诗经": "shijing",
    "礼记": "liji",
    "春秋": "chunqiu",
    "左传": "zuozhuan",
    "史记": "shiji",
    "资治通鉴": "tzuchi",
    "孝经": "xiaojing",
    "黄帝内经": "huangdi-neijing",
    "孙子兵法": "art-of-war",
    "墨子": "mozí",
    "荀子": "xunzi",
    "韩非子": "hanfeizi",
    "鬼谷子": "guiguzi",
    "管子": "guanzi",
    "吕氏春秋": "lvshi",
    "淮南子": "huainanzi",
    "盐铁论": "yantielun",
}


def _get(url: str, timeout: int = 30) -> Optional[requests.Response]:
    """带重试的 GET 请求"""
    try:
        resp = get_session().get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.warning(f"请求失败 {url}: {e}")
        return None


def search_book(query: str) -> Optional[str]:
    """搜索书籍，返回 ctext.org 的 URL 路径，无匹配返回 None"""
    key = query.strip()
    if key in BOOK_NAME_MAP:
        return BOOK_NAME_MAP[key]

    # 模糊匹配
    for cn_name, path in BOOK_NAME_MAP.items():
        if key in cn_name or cn_name in key:
            return path

    return None


def fetch_chapters(book_path: str) -> List[dict]:
    """获取书籍所有章节链接"""
    url = f"{CTEXT_BASE}/{book_path}/zh"
    chapters = []

    resp = _get(url, timeout=30)
    if not resp:
        return chapters

    soup = BeautifulSoup(resp.text, "html.parser")

    for a in soup.select("a"):
        href = a.get("href", "")
        if (book_path + "/") in href and href.endswith("/zh"):
            title = a.get_text(strip=True)
            full_url = CTEXT_BASE + "/" + href if not href.startswith("/") else CTEXT_BASE + href
            chapters.append({"title": title, "url": full_url})

    return chapters


def fetch_chapter_content(url: str) -> List[str]:
    """获取单个章节的所有段落文本"""
    paragraphs = []

    resp = _get(url, timeout=30)
    if not resp:
        return paragraphs

    soup = BeautifulSoup(resp.text, "html.parser")

    # ctext.org 正文在 div#content 下的 p 标签中
    content_div = soup.select_one("div#content")
    if not content_div:
        return paragraphs

    for p in content_div.find_all("p"):
        text = p.get_text(strip=True)
        # 过滤：过短、仅含翻译标签、仅含参考来源
        if len(text) < 10:
            continue
        skip_keywords = ["翻译显示", "英文翻", "底本：", "理雅各", "ctp:", "不顯示", "英文翻譯"]
        if any(kw in text for kw in skip_keywords):
            continue
        paragraphs.append(text)

    return paragraphs


def fetch_book(book_name: str) -> tuple[str, List[str]]:
    """抓取整本书的内容，返回 (书名, [段落列表])"""
    logger.info(f"正在搜索书籍: {book_name}")

    book_path = search_book(book_name)
    if not book_path:
        raise ValueError(f"未找到书籍，请检查书名是否正确。当前支持：{', '.join(BOOK_NAME_MAP.keys())}")

    logger.info(f"找到书籍路径: {book_path}，正在获取章节列表...")

    chapters = fetch_chapters(book_path)
    # 过滤掉书名本身（第一个通常是书名页，不是章节）
    chapters = [ch for ch in chapters if ch["title"] != book_name]

    if not chapters:
        raise ValueError(f"无法获取章节列表: {book_name}")

    logger.info(f"共找到 {len(chapters)} 个章节，开始抓取内容（每个请求最多30秒）...")

    all_paragraphs = []
    for i, ch in enumerate(chapters):
        paras = fetch_chapter_content(ch["url"])
        all_paragraphs.extend(paras)
        status = "OK" if paras else "EMPTY"
        logger.info(f"  [{i+1}/{len(chapters)}] {ch['title']} - {len(paras)}段 {status}")
        time.sleep(0.5)  # 礼貌爬取

    return book_name, all_paragraphs


def save_as_txt(book_name: str, paragraphs: List[str], output_dir: Path) -> Path:
    """将段落保存为 txt 文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{book_name}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"{book_name}\n")
        f.write("=" * 40 + "\n\n")
        for para in paragraphs:
            f.write(para + "\n\n")

    return filepath


def import_to_rag(txt_path: Path) -> int:
    """调用 KnowledgeImporter 导入 RAG"""
    from src.rag_engine.knowledge_importer import KnowledgeImporter
    importer = KnowledgeImporter()
    return importer.import_books(str(txt_path.parent))


def main():
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(description="从 ctext.org 抓取中文古籍并导入 RAG")
    parser.add_argument("book_name", help="书名，支持：论语、孟子、道德经、庄子、大学、中庸、易经、诗经、史记等")
    parser.add_argument("--source-dir", default=None, help="保存 txt 的目录，默认使用 config.BOOKS_DIR")
    parser.add_argument("--no-import", action="store_true", help="仅下载，不导入 RAG")
    args = parser.parse_args()

    book_name = args.book_name.strip()
    from src.shared.config import settings
    output_dir = Path(args.source_dir) if args.source_dir else Path(settings.BOOKS_DIR)

    logger.info("=" * 50)
    logger.info(f"开始抓取: {book_name}")

    try:
        name, paragraphs = fetch_book(book_name)
        logger.info(f"抓取完成，共 {len(paragraphs)} 个段落")
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    if not paragraphs:
        logger.error("未抓取到任何正文内容，可能是网络超时或网站结构变化")
        sys.exit(1)

    txt_path = save_as_txt(name, paragraphs, output_dir)
    logger.info(f"已保存到: {txt_path}")

    if not args.no_import:
        logger.info("正在导入 RAG 知识库...")
        chunk_count = import_to_rag(txt_path)
        logger.info(f"导入完成，新增 {chunk_count} 个 chunk")


if __name__ == "__main__":
    main()
