"""Hermetic fakes and local mock servers (TEST_STRATEGY §2.1 item 5)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx


class FakePrometheus:
    """httpx transport answering /api/v1/query and /query_range from rules."""

    def __init__(self) -> None:
        self.down = False
        self.rules: list[tuple[Callable[[str], bool], Any]] = []
        self.calls: list[str] = []

    def on(self, predicate: Callable[[str], bool] | str, result: Any) -> None:
        pred = (lambda q, s=predicate: s in q) if isinstance(predicate, str) else predicate
        self.rules.insert(0, (pred, result))

    def _match(self, q: str) -> Any:
        for pred, result in self.rules:
            if pred(q):
                return result(q) if callable(result) else result
        return []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("prometheus down")
        if request.url.path == "/-/ready":
            return httpx.Response(200, text="ready")
        params = dict(request.url.params)
        q = params.get("query", "")
        self.calls.append(q)
        result = self._match(q)
        if request.url.path.endswith("query_range"):
            if isinstance(result, list) and result and isinstance(result[0], (int, float)):
                start, step = float(params["start"]), float(params["step"])
                values = [[start + i * step, str(v)] for i, v in enumerate(result)]
                data = [{"metric": {}, "values": values}]
            else:
                data = result if isinstance(result, list) else []
            return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": data}})
        ts = float(params.get("time", datetime.now(UTC).timestamp()))
        if isinstance(result, (int, float)):
            data = [{"metric": {}, "value": [ts, str(result)]}]
        else:
            data = result
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": data}})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def json_transport(routes: dict[tuple[str, str], Any], calls: list[httpx.Request] | None = None) -> httpx.MockTransport:
    """Route (METHOD, path) → (status, body) or callable(request) → httpx.Response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        key = (request.method, request.url.path)
        spec = routes.get(key)
        if spec is None:
            for (m, p), s in routes.items():
                if m == request.method and p.endswith("*") and request.url.path.startswith(p[:-1]):
                    spec = s
                    break
        if spec is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if callable(spec):
            return spec(request)  # type: ignore[no-any-return]
        status, body = spec
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


class WebhookReceiver:
    """Local HTTP server recording JSON payloads (bound to 127.0.0.1:0)."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.received: list[dict[str, Any]] = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                receiver.received.append({"headers": dict(self.headers), "json": json.loads(body or b"{}")})
                self.send_response(receiver.status)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/hook"

    def __enter__(self) -> WebhookReceiver:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
