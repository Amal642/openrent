"""
testfix.retriever_embedding
---------------------------
Embedding-based retrieval for ARM_B3 and ARM_B5.

Embeds all top-level functions in app/ at startup using OpenAI text-embedding-3-small.
Query = test source + test name + error message + pytest E-lines (NO function A source).
Returns top-K by cosine similarity, excluding the entry-point function.

Two retrieval modes:
  query()              — search across all 266 corpus functions
  query_from_subset()  — re-rank a named subset (used by ARM_B5 hybrid)

Cache: embeddings computed once at build() time in batches of 100.
       Each query() call costs 1 embed API call.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── cosine similarity ──────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── embedding index ────────────────────────────────────────────────────────────

class EmbeddingIndex:
    """
    OpenAI embedding index over a corpus of Python functions.
    Model: text-embedding-3-small (1536-dim).
    """

    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self._docs: list[dict] = []
        self._built = False
        self._client = None

    def _get_client(self):
        if self._client is None:
            sys.path.insert(0, str(ROOT))
            from openai import OpenAI
            from app.config import settings
            self._client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
        return self._client

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        response = client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    def add(self, function_name: str, file_path: str, source: str) -> None:
        assert not self._built
        self._docs.append({
            "function_name": function_name,
            "file_path": file_path,
            "source": source,
            "embedding": None,
        })

    def build(self, batch_size: int = 100) -> None:
        """Embed all documents in batches. One API round-trip per batch."""
        self._built = True
        if not self._docs:
            return
        texts = [f"{d['function_name']}\n{d['source']}" for d in self._docs]
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            all_embeddings.extend(self._embed_batch(batch))
        for doc, emb in zip(self._docs, all_embeddings):
            doc["embedding"] = emb

    @property
    def size(self) -> int:
        return len(self._docs)

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        exclude_function: str | None = None,
    ) -> list[dict]:
        """
        Return top_k results by cosine similarity.
        exclude_function: skip the entry-point (already shown to model separately).
        Each result: {rank, score, function_name, file_path, source}.
        """
        if not self._built or not self._docs:
            return []
        [q_emb] = self._embed_batch([query_text])
        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            if exclude_function and doc["function_name"] == exclude_function:
                continue
            if doc["embedding"] is None:
                continue
            sim = _cosine(q_emb, doc["embedding"])
            scored.append((sim, idx))
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

    def query_from_subset(
        self,
        query_text: str,
        top_k: int = 5,
        exclude_function: str | None = None,
        include_only: set[str] | None = None,
    ) -> list[dict]:
        """
        Re-rank a named subset of the corpus by embedding similarity.
        Used by ARM_B5: structural filter (import graph) -> semantic re-rank.
        include_only: set of function_name strings to consider; None = all.
        """
        if not self._built or not self._docs:
            return []
        [q_emb] = self._embed_batch([query_text])
        scored: list[tuple[float, int]] = []
        for idx, doc in enumerate(self._docs):
            if exclude_function and doc["function_name"] == exclude_function:
                continue
            if include_only is not None and doc["function_name"] not in include_only:
                continue
            if doc["embedding"] is None:
                continue
            sim = _cosine(q_emb, doc["embedding"])
            scored.append((sim, idx))
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

import ast as _ast


def build_corpus(app_root: Path | None = None) -> EmbeddingIndex:
    """
    Index all top-level functions in app/. Returns a built EmbeddingIndex.
    Makes batched embedding API calls — expect ~3-5s for 266 functions.
    """
    if app_root is None:
        app_root = ROOT / "app"

    index = EmbeddingIndex()
    for py_file in sorted(app_root.rglob("*.py")):
        try:
            src = py_file.read_text(encoding="utf-8")
            tree = _ast.parse(src)
        except (OSError, SyntaxError):
            continue
        lines = src.splitlines(keepends=True)
        rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                func_src = "".join(lines[node.lineno - 1: node.end_lineno])
                index.add(node.name, rel, func_src)

    index.build()
    return index


# ── query builder ─────────────────────────────────────────────────────────────
# Shared with retriever_bm25 — same rules apply:
#   INCLUDE: test name, test source, error message, assertion E-lines
#   EXCLUDE: function A source, call-graph helper names, mutation metadata

def build_query(
    test_source: str,
    error_message: str,
    test_name: str,
    pytest_output: str = "",
) -> str:
    e_lines: list[str] = []
    for line in (pytest_output or "").splitlines():
        s = line.strip()
        if s.startswith("E ") and len(s) > 2:
            e_lines.append(s[2:].strip())
        if len(e_lines) >= 5:
            break
    parts = [test_name, test_source, error_message] + e_lines
    return " ".join(p for p in parts if p)
