import re

from src.content_factory.presenter.models import PresenterSegment


SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?", re.MULTILINE)
STOPWORDS = {
    "一个", "一种", "这个", "那个", "我们", "你会", "就是", "其实", "如果", "因为",
    "所以", "但是", "然后", "可以", "不要", "时候", "自己", "什么",
}


class ScriptSegmenter:
    def __init__(self, max_chars: int = 42, max_segments: int = 8):
        self.max_chars = max_chars
        self.max_segments = max_segments

    def split(self, text: str, title: str = "") -> list[PresenterSegment]:
        sentences = self._sentences(text)
        chunks = self._pack_sentences(sentences)
        if self.max_segments > 0:
            chunks = chunks[: self.max_segments]

        segments = []
        for index, chunk in enumerate(chunks):
            style = self._style_for(index, chunk)
            keywords = self._extract_keywords(chunk, title=title)
            segments.append(
                PresenterSegment(
                    index=index,
                    text=chunk,
                    style=style,
                    keywords=keywords,
                )
            )
        return segments

    def _sentences(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", "\n", (text or "").strip())
        if not cleaned:
            return []
        sentences = [m.group(0).strip() for m in SENTENCE_RE.finditer(cleaned)]
        return [s for s in sentences if s]

    def _pack_sentences(self, sentences: list[str]) -> list[str]:
        chunks = []
        buffer = ""

        for sentence in sentences:
            if len(sentence) > self.max_chars * 1.5:
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.extend(self._split_long_sentence(sentence))
                continue

            candidate = f"{buffer}{sentence}" if buffer else sentence
            if len(candidate) <= self.max_chars or not buffer:
                buffer = candidate
            else:
                chunks.append(buffer)
                buffer = sentence

        if buffer:
            chunks.append(buffer)
        return chunks

    def _split_long_sentence(self, sentence: str) -> list[str]:
        parts = re.split(r"(?<=[，,、])", sentence)
        chunks = []
        buffer = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            candidate = f"{buffer}{part}" if buffer else part
            if len(candidate) <= self.max_chars or not buffer:
                buffer = candidate
            else:
                chunks.append(buffer)
                buffer = part
        if buffer:
            chunks.append(buffer)
        return chunks

    def _style_for(self, index: int, text: str) -> str:
        if index == 0:
            return "title"
        if any(mark in text for mark in ("！", "!", "？", "?")) or len(text) <= 18:
            return "highlight"
        return "caption"

    def _extract_keywords(self, text: str, title: str = "") -> list[str]:
        source = text
        tokens = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_-]{2,}", source)
        seen = set()
        keywords = []
        for token in tokens:
            if token in STOPWORDS or token in seen:
                continue
            seen.add(token)
            keywords.append(token)
            if len(keywords) >= 3:
                break
        return keywords
