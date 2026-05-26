"""Vendored thin Python client for the @hippocampus/memory-kit-mcp stdio server.

This file is a verbatim copy of
`packages/memory-kit-mcp/examples/python/memory_kit_client.py` from
the hippocampus monorepo (commit b48bb44 on
`feat/outreach-hippo-productization-prodV1`). It is vendored here so
OpenRent has no runtime filesystem dependency on the hippocampus
worktree. Bump this file by re-copying when the upstream client
changes; do not edit it in-place to add OpenRent-specific behaviour
(that goes in `hippo_client.py` instead).

Protocol contract (matches packages/memory-kit-mcp/src/stdio.ts):

- Each request is one JSON object terminated by '\\n'.
- Each response is one JSON object terminated by '\\n'.
- Requests with no `id` are notifications and get no response.
- Methods: initialize, tools/list, tools/call, shutdown.
- Server config from env: HIPPO_MEMORY_STORAGE,
  HIPPO_MEMORY_PROJECT_ID, HIPPO_MEMORY_REDACT_CONTACTS.

Dependency-free (stdlib only).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from queue import Empty, Queue
from typing import Any, Mapping


class MemoryKitMcpError(RuntimeError):
    """Raised when the MCP server returns a JSON-RPC error or an isError tool result."""


class MemoryKitMcpClient:
    """Subprocess client for the memory-kit MCP stdio server.

    Use as a context manager, or call close() explicitly.
    """

    def __init__(
        self,
        *,
        server_js: str,
        node: str = "node",
        storage: str = ":memory:",
        project_id: str | None = None,
        redact_contacts: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> None:
        child_env = dict(env if env is not None else os.environ)
        child_env["HIPPO_MEMORY_STORAGE"] = storage
        if project_id is not None:
            child_env["HIPPO_MEMORY_PROJECT_ID"] = project_id
        child_env["HIPPO_MEMORY_REDACT_CONTACTS"] = (
            "true" if redact_contacts else "false"
        )

        self._proc = subprocess.Popen(
            [node, server_js],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
            text=True,
            bufsize=1,
        )
        self._next_id = 1
        self._lock = threading.Lock()
        self._stderr_queue: Queue[str] = Queue()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_thread.start()

    def __enter__(self) -> "MemoryKitMcpClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def initialize(self) -> dict[str, Any]:
        return self._request("initialize", {})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return list(result.get("tools", []))

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call a tool and return the parsed JSON payload (text of content[0]).

        Raises MemoryKitMcpError on JSON-RPC error or tool isError result.
        """
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
                f"tool {name!r} returned non-JSON text: {text!r}"
            ) from exc
        if result.get("isError"):
            raise MemoryKitMcpError(
                f"tool {name!r} reported error: {payload}"
            )
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
        """Return any stderr lines collected so far (for debugging)."""
        lines: list[str] = []
        while True:
            try:
                lines.append(self._stderr_queue.get_nowait())
            except Empty:
                break
        return lines

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            stderr_tail = "\n".join(self.drain_stderr()[-20:])
            raise MemoryKitMcpError(
                f"MCP server closed stdout before responding to id={request_id}; "
                f"recent stderr:\n{stderr_tail}"
            )
        message = json.loads(line)
        if message.get("id") != request_id:
            raise MemoryKitMcpError(
                f"id mismatch: expected {request_id}, got {message.get('id')}"
            )
        if "error" in message:
            raise MemoryKitMcpError(
                f"JSON-RPC error for {method}: {message['error']}"
            )
        return message.get("result", {})

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr_queue.put(line.rstrip("\n"))
