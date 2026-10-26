"""Instrumented demo service with injectable faults (T-03.01, SM-03, SM-04).

Emits the OpenTelemetry HTTP semantic-convention histogram ``http.server.request.duration``
(seconds) with ``http.request.method``, ``http.route`` and ``http.response.status_code``,
exported over OTLP/HTTP using the standard ``OTEL_*`` environment variables.

Fault injection (bearer ``DEMO_ADMIN_TOKEN``):
  POST /admin/fault  {"error_rate": 0.6, "latency_seconds": 0.5, "ttl_seconds": 600}
  POST /admin/clear
  GET  /admin/status
``/admin/*`` and ``/health`` are never affected by faults.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import random
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("demo-app")

BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10]
PORT = int(os.environ.get("PORT", "8080"))
ADMIN_TOKEN = os.environ.get("DEMO_ADMIN_TOKEN", "")
SELF_TRAFFIC_RPS = float(os.environ.get("DEMO_SELF_TRAFFIC_RPS", "5"))


class Faults:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.error_rate = 0.0
        self.latency = 0.0
        self.expires = 0.0

    def set(self, error_rate: float, latency: float, ttl: float) -> None:
        with self.lock:
            self.error_rate, self.latency, self.expires = error_rate, latency, time.time() + ttl

    def clear(self) -> None:
        with self.lock:
            self.error_rate, self.latency, self.expires = 0.0, 0.0, 0.0

    def current(self) -> dict[str, float]:
        with self.lock:
            if self.expires and time.time() > self.expires:
                self.error_rate, self.latency, self.expires = 0.0, 0.0, 0.0
            return {"error_rate": self.error_rate, "latency_seconds": self.latency,
                    "expires_in_seconds": max(0.0, self.expires - time.time()) if self.expires else 0.0}


FAULTS = Faults()


def setup_metrics() -> metrics.Histogram:
    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "demo-app"),
        "deployment.environment.name": os.environ.get("DEMO_ENVIRONMENT", "dev"),
    })
    interval = int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "5000"))
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=interval)
    view = View(instrument_name="http.server.request.duration",
                aggregation=ExplicitBucketHistogramAggregation(boundaries=BUCKETS))
    provider = MeterProvider(resource=resource, metric_readers=[reader], views=[view])
    metrics.set_meter_provider(provider)
    meter = metrics.get_meter("demo-app", "1.0.0")
    return meter.create_histogram("http.server.request.duration", unit="s",
                                  description="Duration of HTTP server requests.")


DURATION = setup_metrics()


class Handler(BaseHTTPRequestHandler):
    server_version = "demo-app"

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return bool(ADMIN_TOKEN) and hmac.compare_digest(header, f"Bearer {ADMIN_TOKEN}")

    def _admin(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path == "/admin/status" and self.command == "GET":
            self._json(200, FAULTS.current())
        elif self.path == "/admin/clear" and self.command == "POST":
            FAULTS.clear()
            log.info("faults cleared")
            self._json(200, FAULTS.current())
        elif self.path == "/admin/fault" and self.command == "POST":
            length = min(int(self.headers.get("Content-Length", "0")), 10_000)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                error_rate = float(body.get("error_rate", 0))
                latency = float(body.get("latency_seconds", 0))
                ttl = float(body.get("ttl_seconds", 600))
            except (ValueError, TypeError):
                self._json(400, {"error": "invalid body"})
                return
            if not (0 <= error_rate <= 1 and 0 <= latency <= 30 and 0 < ttl <= 3600):
                self._json(400, {"error": "error_rate in [0,1], latency_seconds <= 30, ttl_seconds <= 3600"})
                return
            FAULTS.set(error_rate, latency, ttl)
            log.info("fault injected at %.3f: %s", time.time(), FAULTS.current())
            self._json(200, {**FAULTS.current(), "injected_at": time.time()})
        else:
            self._json(404, {"error": "not found"})

    def _serve(self) -> None:
        if self.path.startswith("/admin/"):
            self._admin()
            return
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        started = time.perf_counter()
        route = self.path.split("?")[0] if self.path.split("?")[0] in ("/", "/api/items", "/api/checkout") else "/other"
        fault = FAULTS.current()
        if fault["latency_seconds"]:
            time.sleep(fault["latency_seconds"])
        time.sleep(random.uniform(0.005, 0.04))  # noqa: S311 - simulated work
        status = 500 if random.random() < fault["error_rate"] else (404 if route == "/other" else 200)  # noqa: S311
        self._json(status, {"route": route, "status": status})
        DURATION.record(time.perf_counter() - started, {
            "http.request.method": self.command, "http.route": route, "http.response.status_code": status})

    def do_GET(self) -> None:  # noqa: N802
        self._serve()

    def do_POST(self) -> None:  # noqa: N802
        self._serve()

    def log_message(self, *args: Any) -> None:
        return


def self_traffic() -> None:
    """Steady background load so charts have data without an external load generator."""
    if SELF_TRAFFIC_RPS <= 0:
        return
    paths = ["/", "/api/items", "/api/items", "/api/checkout"]
    while True:
        start = time.time()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}{random.choice(paths)}", timeout=10).read()  # noqa: S310,S311
        except Exception:  # noqa: BLE001 - 5xx responses raise HTTPError; that is expected
            pass
        time.sleep(max(0.0, 1.0 / SELF_TRAFFIC_RPS - (time.time() - start)))


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104
    threading.Thread(target=self_traffic, daemon=True).start()
    log.info("demo-app listening on :%d (self traffic %.1f rps)", PORT, SELF_TRAFFIC_RPS)
    server.serve_forever()


if __name__ == "__main__":
    main()
