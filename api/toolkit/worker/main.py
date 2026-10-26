"""Worker process (COMP-03).

Runs, in one process:
* ``WORKER_CONCURRENCY`` job slots claiming from the PostgreSQL queue;
* the lease reaper (crash recovery, NFR-REL-01);
* the monitoring/alert loop — leader-elected with a PostgreSQL advisory lock so several
  worker replicas can run without double-evaluating rules;
* the notification delivery loop (outbox, SKIP LOCKED — safe on every replica);
* the scheduler (scheduled rescans, daily retention), also leader-elected.

Any number of worker replicas can be started for more job throughput.
"""

from __future__ import annotations

import functools
import hmac
import logging
import signal
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from toolkit import __version__
from toolkit.core.clock import Clock, system_clock
from toolkit.core.config import get_settings
from toolkit.core.logging import configure_logging
from toolkit.core.metrics import BUILD_INFO, QUEUE_DEPTH, REGISTRY
from toolkit.db.session import get_engine, session_scope
from toolkit.jobs import queue
from toolkit.jobs.runner import execute

log = logging.getLogger("toolkit.worker")

MONITOR_LOCK = 0x5EC0_0001
SCHEDULER_LOCK = 0x5EC0_0002


def _import_handlers() -> None:
    import toolkit.ai.service
    import toolkit.remediation.pipeline
    import toolkit.remediation.pr
    import toolkit.scanning.orchestrator  # noqa: F401


@contextmanager
def advisory_lock(lock_id: int) -> Iterator[bool]:
    """Session-level advisory lock held on a dedicated connection while the block runs."""
    conn = get_engine().connect()
    try:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id}).scalar())
        conn.commit()
        try:
            yield got
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id})
                conn.commit()
    finally:
        conn.close()


class Worker:
    def __init__(self, clock: Clock = system_clock) -> None:
        self.settings = get_settings()
        self.clock = clock
        self.worker_id = f"{socket.gethostname()}:{id(self) & 0xFFFF:04x}"
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.active_jobs = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loops
    def _job_slot(self, slot: int) -> None:
        s = self.settings
        while not self.stop.is_set():
            try:
                with session_scope() as db:
                    job = queue.claim(db, f"{self.worker_id}/{slot}", self.clock.now(), s.job_lease_seconds)
                    if job is not None:
                        db.expunge(job)
            except Exception:
                log.exception("claim failed")
                job = None
            if job is None:
                self.stop.wait(s.job_poll_interval_seconds)
                continue
            with self._lock:
                self.active_jobs += 1
            try:
                status = execute(job, f"{self.worker_id}/{slot}", clock=self.clock)
                log.info("job finished", extra={"job_id": str(job.id), "job_type": job.type, "status": status})
            finally:
                with self._lock:
                    self.active_jobs -= 1

    def _every(self, name: str, interval: Callable[[], float], fn: Callable[[], None]) -> None:
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                fn()
            except Exception:
                log.exception("loop iteration failed", extra={"loop": name})
            self.stop.wait(max(0.5, interval() - (time.monotonic() - started)))

    def reap(self) -> None:
        with session_scope() as db:
            n = queue.reap_expired(db, self.clock.now())
            for job_type, depth in queue.queue_depth(db).items():
                QUEUE_DEPTH.labels(job_type).set(depth)
        if n:
            log.warning("requeued expired jobs", extra={"count": n})

    def monitor_loop(self) -> None:
        """Leader election: the worker holding the advisory lock evaluates every Δ_eval.

        The lock is held on a dedicated connection for as long as this worker is leader, so the
        evaluation cadence stays exactly Δ_eval no matter how many workers run. If the leader dies
        its connection closes, the lock is released and another worker takes over.
        """
        from toolkit.alerting.engine import evaluate_once
        from toolkit.monitoring.prometheus import PrometheusClient

        interval = self.settings.alert_eval_interval_seconds
        while not self.stop.is_set():
            try:
                conn = get_engine().connect()
            except Exception:
                log.exception("monitor: cannot connect to the database")
                self.stop.wait(interval)
                continue
            try:
                leader = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": MONITOR_LOCK}).scalar())
                conn.commit()
                if not leader:
                    self.stop.wait(interval)
                    continue
                log.info("monitor: acquired leadership")
                prom = PrometheusClient()
                try:
                    while not self.stop.is_set():
                        started = time.monotonic()
                        conn.execute(text("SELECT 1"))  # fail fast if the lock connection died
                        conn.commit()
                        try:
                            with session_scope() as db:
                                counts = evaluate_once(db, prom, self.clock.now())
                            if counts.get("fired") or counts.get("resolved") or counts.get("evaluation_error"):
                                log.info("evaluation tick", extra={"counts": counts})
                        except Exception:
                            log.exception("evaluation tick failed")
                        self.stop.wait(max(0.5, interval - (time.monotonic() - started)))
                finally:
                    prom.close()
            except Exception:
                log.exception("monitor: lost leadership connection")
                self.stop.wait(1)
            finally:
                conn.close()

    def deliver(self) -> None:
        from toolkit.alerting.notify import deliver_pending

        with session_scope() as db:
            deliver_pending(db, self.clock.now())

    def scheduler_tick(self) -> None:
        with advisory_lock(SCHEDULER_LOCK) as leader:
            if not leader:
                return
            from toolkit.retention import run_retention_if_due
            from toolkit.scheduler import enqueue_scheduled_scans

            with session_scope() as db:
                enqueue_scheduled_scans(db, self.clock.now())
            with session_scope() as db:
                run_retention_if_due(db, self.clock.now())

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        s = self.settings
        from toolkit.scanning.clone import cleanup_orphans

        removed = cleanup_orphans(s.work_dir, prefix=f"scan-{socket.gethostname()[:30]}-")
        if removed:
            log.info("removed orphan workspaces", extra={"count": removed})
        if s.remediation_enabled:
            self._reap_sandbox()
        spawn = self._spawn
        for slot in range(s.worker_concurrency):
            spawn(f"job-{slot}", functools.partial(self._job_slot, slot))
        spawn("reaper", lambda: self._every("reaper", lambda: 15, self.reap))
        spawn("delivery", lambda: self._every("delivery", lambda: 2, self.deliver))
        spawn("scheduler", lambda: self._every("scheduler", lambda: 300, self.scheduler_tick))
        if s.enable_monitoring_loop:
            spawn("monitor", self.monitor_loop)
        log.info(
            "worker started",
            extra={
                "worker_id": self.worker_id,
                "concurrency": s.worker_concurrency,
                "monitoring": s.enable_monitoring_loop,
            },
        )

    def _reap_sandbox(self) -> None:
        try:
            from toolkit.remediation.sandbox import DockerSandbox

            DockerSandbox().reap_orphans()
        except Exception as exc:
            log.warning("sandbox reaper skipped", extra={"error": type(exc).__name__})

    def _spawn(self, name: str, target: Callable[[], None]) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def shutdown(self, grace_seconds: float = 30.0) -> None:
        log.info("worker stopping; waiting for running jobs", extra={"active": self.active_jobs})
        self.stop.set()
        deadline = time.monotonic() + grace_seconds
        for t in self.threads:
            t.join(timeout=max(0.1, deadline - time.monotonic()))
        # Jobs still running keep their lease; the reaper on another worker requeues them.


def _metrics_server(port: int) -> ThreadingHTTPServer:
    token = get_settings().metrics_scrape_token.get_secret_value()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/metrics", "/health"):
                self.send_response(404)
                self.end_headers()
                return
            if self.path == "/health":
                body, ctype = b'{"status":"ok"}', "application/json"
            else:
                if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                    self.send_response(403)
                    self.end_headers()
                    return
                body, ctype = generate_latest(REGISTRY), CONTENT_TYPE_LATEST
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - internal network only
    threading.Thread(target=server.serve_forever, name="metrics", daemon=True).start()
    return server


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    BUILD_INFO.info({"version": __version__, "component": "worker"})
    _import_handlers()
    server = _metrics_server(s.worker_metrics_port)
    worker = Worker()
    worker.start()
    stopped = threading.Event()

    def _signal(signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGINT, _signal)
    while not stopped.wait(1.0):
        pass
    worker.shutdown()
    server.shutdown()


if __name__ == "__main__":
    main()
