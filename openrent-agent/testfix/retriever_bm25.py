"""
testfix.retriever_bm25
----------------------
BM25 retrieval over all top-level functions in app/.

Index: function name + body text (tokenized).
Query: test source + error message + test name + pytest E-lines.

Query construction rules:
  INCLUDE : test name, test source, error message, assertion E-lines (actual/expected values)
  EXCLUDE : function A source, call-graph helper names, seed metadata, target function name

Returns top-K ranked functions with rank, BM25 score, file path, and source.
The entry-point function (function A) is filtered out of results so candidates
are all helpers, not the function the prompt already shows.
"""

import ast
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── tokenizer ──────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset([
    "def", "return", "if", "else", "elif", "for", "in", "not", "and", "or",
    "is", "none", "true", "false", "import", "from", "as", "class", "self",
    "with", "try", "except", "raise", "pass", "break", "continue", "lambda",
    "yield", "assert", "while", "str", "int", "list", "dict", "set", "tuple",
    "len", "any", "all", "print", "range", "re", "lower", "upper", "strip",
    "get", "append", "join", "split", "type", "bool", "float", "where",
    "test", "tests",
])


def _tokenize(text: str) -> list[str]:
    """
    Split Python source / test text into BM25 tokens.
    - Splits on non-alphanumeric characters (keeps _ for snake_case splitting)
    - Splits snake_case on underscores
    - Splits camelCase on case transitions
    - Lowercases, drops stopwords, drops tokens shorter than 2 chars
    """
    chunks = re.split(r"[^a-zA-Z0-9_]", text)
    tokens: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        for part in chunk.split("_"):
            if not part:
                continue
            # camelCase → ["camel", "Case"]
            sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).split()
            tokens.extend(s.lower() for s in sub)
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


# ── BM25 index ─────────────────────────────────────────────────────────────────

class BM25Index:
    """
    BM25Okapi over a corpus of Python functions.
    Parameters: k1=1.5, b=0.75 (standard).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict] = []
        self._df: Counter = Counter()
        self._avgdl: float = 1.0
        self._built = False

    def add(self, function_name: str, file_path: str, source: str) -> None:
        assert not self._built
        doc_text = f"{function_name} {source}"
        tokens = _tokenize(doc_text)
        self._docs.append({
            "function_name": function_name,
            "file_path": file_path,
            "source": source,
            "tokens": tokens,
            "_tf": Counter(tokens),
            "_len": len(tokens),
        })

    def build(self) -> None:
        self._built = True
        n = len(self._docs)
        if not n:
            return
        self._avgdl = sum(d["_len"] for d in self._docs) / n
        for d in self._docs:
            for t in set(d["tokens"]):
                self._df[t] += 1

    @property
    def size(self) -> int:
        return len(self._docs)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        n = len(self._docs)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        exclude_function: str | None = None,
    ) -> list[dict]:
        """
        Return top_k results by BM25 score.
        exclude_function: skip the entry-point function (already shown to model separately).
        Each result: {rank, score, function_name, file_path, source}.
        """
        if not self._built or not self._docs:
            return []
        q_tokens = _tokenize(query_text)
        if not q_tokens:
            return []

        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            if exclude_function and doc["function_name"] == exclude_function:
                continue
            score = 0.0
            dl = doc["_len"]
            tf_map = doc["_tf"]
            for t in set(q_tokens):
                tf = tf_map.get(t, 0)
                if tf == 0:
                    continue
                idf = self._idf(t)
                num = tf * (self.k1 + 1)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * num / denom
            scored.append((score, idx))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (score, idx) in enumerate(scored[:top_k], 1):
            d = self._docs[idx]
            results.append({
                "rank": rank,
                "score": round(score, 4),
                "function_name": d["function_name"],
                "file_path": d["file_path"],
                "source": d["source"],
            })
        return results


# ── corpus builder ─────────────────────────────────────────────────────────────

def build_corpus(app_root: Path | None = None) -> BM25Index:
    """Index all top-level functions in app/. Returns a built BM25Index."""
    if app_root is None:
        app_root = ROOT / "app"

    index = BM25Index()
    for py_file in sorted(app_root.rglob("*.py")):
        try:
            src = py_file.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        lines = src.splitlines(keepends=True)
        rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_src = "".join(lines[node.lineno - 1 : node.end_lineno])
                index.add(node.name, rel, func_src)

    index.build()
    return index


# ── query builder ──────────────────────────────────────────────────────────────

def build_query(
    test_source: str,
    error_message: str,
    test_name: str,
    pytest_output: str = "",
) -> str:
    """
    Build a BM25 query from test-side signals only.

    INCLUDES : test name, test source, error message, assertion E-lines
               (actual/expected values like "assert VIEWING_DISCUSSION == VIEWING_BOOKED")
    EXCLUDES : function A source, helper names from call graph, seed/mutation metadata
    """
    # Extract up to 5 E-lines (actual/expected values, assertion expressions)
    e_lines: list[str] = []
    for line in (pytest_output or "").splitlines():
        s = line.strip()
        if s.startswith("E ") and len(s) > 2:
            e_lines.append(s[2:].strip())
        if len(e_lines) >= 5:
            break

    parts = [test_name, test_source, error_message] + e_lines
    return " ".join(p for p in parts if p)
