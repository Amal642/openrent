"""
Parses troubleshooting_guide.md at startup and provides keyword-based section lookup.
No LLM calls needed for troubleshooting — matched content is returned directly.
"""

import re
from pathlib import Path

_GUIDE_PATH = Path(__file__).parent.parent.parent / "troubleshooting_guide.md"

_STOPWORDS = {
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for", "of", "and", "or", "but",
    "not", "with", "this", "that", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can",
    "i", "my", "your", "their", "our", "its", "we", "they", "he", "she", "you", "me",
    "what", "when", "where", "which", "who", "how", "why", "just", "also", "then", "than",
    "if", "from", "by", "as", "up", "so", "no", "yes", "all",
}


def _tokenize(text: str) -> set:
    words = re.findall(r"\b[a-z0-9]+\b", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


class _Section:
    def __init__(self, title: str, content: str):
        self.title = title
        self.content = content
        self._title_tokens = _tokenize(title)
        # Use first 600 chars of content for scoring (enough for What This Means + causes)
        self._content_tokens = _tokenize(content[:600])

    def score(self, query_tokens: set) -> float:
        title_overlap = len(query_tokens & self._title_tokens)
        content_overlap = len(query_tokens & self._content_tokens)
        return title_overlap * 3.0 + content_overlap * 1.0

    def formatted(self) -> str:
        return f"**{self.title}**\n\n{self.content}"


def _parse_guide() -> list:
    if not _GUIDE_PATH.exists():
        return []

    text = _GUIDE_PATH.read_text(encoding="utf-8")
    sections = []

    # Split on ## headings (individual issue articles)
    parts = re.split(r"^## ", text, flags=re.MULTILINE)

    skip_titles = {
        "How to Use This Guide",
        "Quick Reference — Most Common Issues",
        "Glossary",
    }

    for part in parts[1:]:
        lines = part.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()

        if title in skip_titles:
            continue
        # Skip section category markers
        if re.match(r"^Section\s+\d+", title):
            continue

        content = "\n".join(lines[1:]).strip()
        # Collapse triple+ newlines
        content = re.sub(r"\n{3,}", "\n\n", content)

        sections.append(_Section(title, content))

    return sections


_SECTIONS: list = _parse_guide()


def search_guide(query: str) -> str | None:
    """Return the best-matching troubleshooting article, or None if nothing matches well."""
    if not _SECTIONS:
        return None

    query_tokens = _tokenize(query)
    if not query_tokens:
        return None

    scored = sorted(
        ((s.score(query_tokens), s) for s in _SECTIONS),
        key=lambda x: x[0],
        reverse=True,
    )

    # Minimum score of 2 required (at least some meaningful overlap)
    top = [(sc, s) for sc, s in scored if sc >= 2.0]
    if not top:
        return None

    # Return up to 2 most relevant sections
    results = top[:2]

    if len(results) == 1:
        return results[0][1].formatted()

    return "\n\n---\n\n".join(s.formatted() for _, s in results)


def guide_loaded() -> bool:
    return len(_SECTIONS) > 0
