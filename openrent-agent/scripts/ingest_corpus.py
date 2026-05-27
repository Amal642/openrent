"""Post-closure L2-retest probe: ingest real OpenRent conversation corpus
into memory-kit-mcp, run one consolidate pass, report schemas-per-1000.

Precommit:
  hippocampus-1:docs/OPENRENT-POSTCLOSURE-CORPUS-PROBE-PRECOMMIT.md
  (commit 584fd07 on docs/project-guide)

Verdict bands (precommitted, NOT negotiable post-result):
  L2-CONFIRMED  schemas/1000 cells <= 27  -> arc-closure stands
  L2-AMBIGUOUS  28-99                     -> RCA-style synthesis
  L2-FLIP       >= 100                    -> draft new arc precommit

Q1-Q4 locked to defaults:
  Q1 = single global token '[PHONE_REDACTED]'
  Q2 = per-turn cells (1611 total)
  Q3 = pooled source-id ('corpus-all') -- F4 partitioning disabled
  Q4 = $0.25 cap via --max-clusters 250

Self-contained: only stdlib + subprocess to node memory-kit-mcp server.
No OpenRent app/ai/memory module needed (this script bypasses
hippo-memory-integration's HippoOutreachClient wrapper).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Iterable, Mapping


def _load_dotenv(repo_root: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines only, no quoting.
    The consolidator's summarizer needs OPENAI_API_KEY in the MCP
    child's env; without this, the parent shell would have to export
    it manually. Idempotent (won't overwrite already-set vars)."""

    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------- redaction


# UK mobile patterns + raw 10-11 digit runs cover the 152 literal phones
# observed in full-conversations.md. Underscores ([PHONE_REDACTED] etc.)
# inside the redaction token never trigger \d.
_PHONE_PATTERNS = (
    re.compile(r"\+?44\s?7\d{3}\s?\d{3,4}\s?\d{3,4}"),
    re.compile(r"\b07\d{3,4}\s?\d{3,4}\s?\d{3,4}\b"),
    re.compile(r"\b\d{10,11}\b"),
)
_REDACTED_MARKER = re.compile(r"\(\s*(?:Number|Phone)\s+Removed\s*\)", re.I)
_REDACT_TOKEN = "[PHONE_REDACTED]"


def redact_phones(text: str) -> str:
    """Replace every literal phone-shaped string and every legacy
    redaction marker with a single stable token. Idempotent."""

    text = _REDACTED_MARKER.sub(_REDACT_TOKEN, text)
    for pat in _PHONE_PATTERNS:
        text = pat.sub(_REDACT_TOKEN, text)
    return text


def contains_phone_literal(text: str) -> bool:
    """Apparatus precondition (P1.1 predicate 2): zero literal phones
    must survive in the redacted corpus."""

    return any(pat.search(text) for pat in _PHONE_PATTERNS)


# ---------------------------------------------------------------------- parse


_CONV_SPLIT = re.compile(r"^## Conversation \d+", flags=re.M)
_TURN_RX = re.compile(r"^(Landlord|Tenant):\s*\"(.*?)\"\s*$", flags=re.M | re.S)
_SOURCE_RX = re.compile(r"^Source:\s*(\S+)\s*$", flags=re.M)


def parse_corpus(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    chunks = _CONV_SPLIT.split(text)[1:]
    convs: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        source_match = _SOURCE_RX.search(chunk)
        turns = [
            {"speaker": sp, "text": msg.strip()}
            for sp, msg in _TURN_RX.findall(chunk)
        ]
        convs.append(
            {
                "id": idx,
                "source": source_match.group(1) if source_match else "",
                "turns": turns,
            }
        )
    return convs


# ---------------------------------------------------------------------- MCP client (vendored, stdlib-only)


class MemoryKitMcpError(RuntimeError):
    pass


class MemoryKitMcpClient:
    def __init__(
        self,
        *,
        server_js: str,
        node: str = "node",
        storage: str = ":memory:",
        project_id: str | None = None,
        redact_contacts: bool = False,
    ) -> None:
        env = dict(os.environ)
        env["HIPPO_MEMORY_STORAGE"] = storage
        if project_id is not None:
            env["HIPPO_MEMORY_PROJECT_ID"] = project_id
        env["HIPPO_MEMORY_REDACT_CONTACTS"] = (
            "true" if redact_contacts else "false"
        )
        self._proc = subprocess.Popen(
            [node, server_js],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        self._next_id = 1
        self._lock = threading.Lock()
        self._stderr_q: Queue[str] = Queue()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr_loop, daemon=True
        )
        self._stderr_thread.start()

    def __enter__(self) -> "MemoryKitMcpClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self) -> dict[str, Any]:
        return self._request("initialize", {})

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        content = result.get("content") or []
        if not content:
            raise MemoryKitMcpError(f"tool {name!r} returned empty content")
        text = content[0].get("text", "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MemoryKitMcpError(
                f"tool {name!r} returned non-JSON: {text!r}"
            ) from exc
        if result.get("isError"):
            raise MemoryKitMcpError(f"tool {name!r} error: {payload}")
        return payload

    def close(self, timeout: float = 5.0) -> None:
        if self._proc.poll() is not None:
            return
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=timeout)

    def drain_stderr(self) -> list[str]:
        out: list[str] = []
        while True:
            try:
                out.append(self._stderr_q.get_nowait())
            except Empty:
                break
        return out

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": dict(params)}
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            tail = "\n".join(self.drain_stderr()[-20:])
            raise MemoryKitMcpError(
                f"MCP server closed stdout on id={req_id}; stderr:\n{tail}"
            )
        resp = json.loads(line)
        if resp.get("id") != req_id:
            raise MemoryKitMcpError(
                f"id mismatch: expected {req_id}, got {resp.get('id')}"
            )
        if "error" in resp:
            raise MemoryKitMcpError(f"JSON-RPC error for {method}: {resp['error']}")
        return resp.get("result", {})

    def _drain_stderr_loop(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr_q.put(line.rstrip("\n"))


# ---------------------------------------------------------------------- ingest


def ingest_turn(
    client: MemoryKitMcpClient,
    *,
    conv_id: int,
    seq: int,
    speaker: str,
    text: str,
    source_url: str,
    source_id: str,
) -> int:
    """Ingest one cell. Returns the count of cellIds the server reported
    minted (normally 1 because singleCell=True)."""

    payload = {
        "kind": "interaction",
        "sourceId": source_id,
        "entityIds": [source_id, f"corpus-conv-{conv_id:03d}"],
        "tags": [
            "corpus",
            "post-closure-probe",
            f"conv:{conv_id}",
            f"speaker:{speaker.lower()}",
            f"seq:{seq}",
        ],
        "text": (
            f"Conversation: corpus-conv-{conv_id:03d}\n"
            f"Source: {source_url}\n"
            f"Speaker: {speaker}\n"
            f"Seq: {seq}\n"
            f"Message:\n{text}"
        ),
        "structured": {
            "atom": "message",
            "speaker": speaker.lower(),
            "seq": seq,
            "convId": conv_id,
            "sourceUrl": source_url,
        },
        "singleCell": True,
    }
    result = client.call_tool("hippo_memory_remember_event", payload)
    return len(result.get("cellIds", []))


# ---------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--hippo-server-js", required=True, type=Path)
    ap.add_argument("--hippo-snap", required=True, type=Path)
    ap.add_argument(
        "--source-id",
        default="corpus-all",
        help="Single pooled sourceId for all cells (Q3 default = corpus-all).",
    )
    ap.add_argument(
        "--max-clusters",
        type=int,
        default=250,
        help="Cost cap surrogate (Q4); ~$0.001 summarizer call per cluster.",
    )
    ap.add_argument(
        "--consolidator-min-salience", type=float, default=1.05,
        help="Q4-amended from a2 lock-in.",
    )
    ap.add_argument(
        "--consolidator-overlap-threshold", type=int, default=25,
        help="Q4-amended from a2 lock-in.",
    )
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument(
        "--no-summarizer",
        action="store_true",
        help="Disable LLM summarizer for $0 dry-run (still counts schemas).",
    )
    args = ap.parse_args(argv)

    # Load .env so the consolidator's summarizer sees OPENAI_API_KEY.
    _load_dotenv(Path(__file__).resolve().parent.parent)

    if not args.corpus.is_file():
        print(f"ERROR: corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    if not args.hippo_server_js.is_file():
        print(f"ERROR: server-js not found: {args.hippo_server_js}", file=sys.stderr)
        return 2

    # --- Redact at the file-text level FIRST, then parse.
    # Some phones in the corpus are split across consecutive turns
    # (e.g. "07419" \n "833395") and per-turn redaction misses the
    # cross-turn bridge. Redacting upstream catches those.
    raw_text = args.corpus.read_text(encoding="utf-8")
    redacted_text = redact_phones(raw_text)

    # Write redacted corpus to disk so the run is reproducible from a
    # known-clean source (apparatus A2 + P1.1 predicate 2).
    redacted_corpus_path = args.output_dir / "corpus_redacted.md"
    redacted_corpus_path.parent.mkdir(parents=True, exist_ok=True)
    redacted_corpus_path.write_text(redacted_text, encoding="utf-8")

    # P1.1 predicate 2: post-redaction sweep must find zero literal phones
    if contains_phone_literal(redacted_text):
        print("APPARATUS-RED: literal phone survived redaction", file=sys.stderr)
        return 3

    convs = parse_corpus(redacted_corpus_path)
    assert len(convs) == 288, f"expected 288 conversations, got {len(convs)}"
    redacted_convs = convs

    n_turns = sum(len(c["turns"]) for c in redacted_convs)
    print(f"parsed: {len(redacted_convs)} convs, {n_turns} turns")
    print(f"redaction: GREEN (zero literal phones post-redaction)")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.hippo_snap.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    cells_ingested = 0

    with MemoryKitMcpClient(
        server_js=str(args.hippo_server_js),
        storage=str(args.hippo_snap),
        project_id="openrent-postclosure-corpus",
        redact_contacts=False,  # we did our own redaction above
    ) as client:
        client.initialize()
        ingest_started = time.time()
        for c in redacted_convs:
            for seq, turn in enumerate(c["turns"], start=1):
                cells_ingested += ingest_turn(
                    client,
                    conv_id=c["id"],
                    seq=seq,
                    speaker=turn["speaker"],
                    text=turn["text"],
                    source_url=c["source"],
                    source_id=args.source_id,
                )
            if c["id"] % 50 == 0:
                elapsed = time.time() - ingest_started
                rate = cells_ingested / max(elapsed, 0.001)
                print(
                    f"  ingested conv {c['id']}/288  cells={cells_ingested}  "
                    f"rate={rate:.1f}/s  elapsed={elapsed:.0f}s",
                    flush=True,
                )
        ingest_ms = int((time.time() - ingest_started) * 1000)
        print(f"ingest complete: {cells_ingested} cells in {ingest_ms} ms")

        consolidate_payload: dict[str, Any] = {
            "partitionBy": "sourceId",
            "minSalience": args.consolidator_min_salience,
            "overlapThreshold": args.consolidator_overlap_threshold,
            "maxClusters": args.max_clusters,
        }
        if args.no_summarizer:
            consolidate_payload["useSummarizer"] = False
        cons_started = time.time()
        report = client.call_tool("hippo_memory_consolidate", consolidate_payload)
        consolidate_ms = int((time.time() - cons_started) * 1000)
        print(f"consolidate complete in {consolidate_ms} ms")
        print(f"report: {json.dumps(report, indent=2)}")

    schemas_minted = int(report.get("schemasNewlyMinted", 0))
    cells_clustered = int(report.get("cellsClustered", 0))
    clusters_total = int(report.get("clustersTotal", 0))
    schemas_abstained = int(report.get("schemasAbstained", 0))

    rate_per_1000 = (schemas_minted / cells_ingested) * 1000 if cells_ingested else 0.0
    if rate_per_1000 >= 100:
        verdict = "L2-FLIP"
    elif rate_per_1000 > 27:
        verdict = "L2-AMBIGUOUS"
    else:
        verdict = "L2-CONFIRMED"

    manifest = {
        "fixture": "full-conversations.md",
        "convs_parsed": len(redacted_convs),
        "cells_ingested": cells_ingested,
        "source_id_scheme": "pooled (Q3)",
        "source_id": args.source_id,
        "redaction": {
            "strategy": "single-global (Q1)",
            "token": _REDACT_TOKEN,
            "p1_predicate_2": "GREEN (zero literal phones post-redaction)",
        },
        "consolidator": {
            "partitionBy": "sourceId",
            "minSalience": args.consolidator_min_salience,
            "overlapThreshold": args.consolidator_overlap_threshold,
            "maxClusters": args.max_clusters,
            "useSummarizer": not args.no_summarizer,
        },
        "report": report,
        "computed": {
            "schemas_minted": schemas_minted,
            "cells_ingested": cells_ingested,
            "schemas_per_1000_cells": round(rate_per_1000, 2),
            "baseline_a5_a6_per_1000": 26.67,
            "verdict": verdict,
            "verdict_bands": {
                "L2-CONFIRMED": "<= 27",
                "L2-AMBIGUOUS": "28-99",
                "L2-FLIP": ">= 100",
            },
        },
        "timing": {
            "ingest_ms": ingest_ms,
            "consolidate_ms": consolidate_ms,
            "wall_clock_s": int(time.time() - started),
        },
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print()
    print("=" * 60)
    print(f"VERDICT: {verdict}")
    print(f"  schemas_minted = {schemas_minted}")
    print(f"  cells_ingested = {cells_ingested}")
    print(f"  schemas_per_1000_cells = {rate_per_1000:.2f}")
    print(f"  baseline (a5+a6) = 26.67")
    print(f"  clusters_total = {clusters_total}  cells_clustered = {cells_clustered}  abstained = {schemas_abstained}")
    print(f"  artifacts in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
