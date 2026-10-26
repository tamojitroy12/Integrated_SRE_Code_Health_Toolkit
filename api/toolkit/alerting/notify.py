"""Notification channels and delivery (FR-ALR-05, FR-ALR-06, NFR-SEC-09).

Deliveries are written as ``pending`` rows in the same transaction that changes the alert
(an outbox), then sent by the worker's delivery loop. This keeps alert evaluation fast and
makes delivery retry-safe across restarts and multiple workers.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.core.crypto import Sealed, get_keyring
from toolkit.core.metrics import NOTIFICATIONS
from toolkit.core.netguard import UnsafeUrlError, validate_outbound_url
from toolkit.db.models import Alert, MonitoringTarget, NotificationChannel, NotificationDelivery, Project

log = logging.getLogger(__name__)
WEBHOOK_TIMEOUT = 5.0


def seal_config(channel_id: uuid.UUID, config: dict[str, Any]) -> Sealed:
    return get_keyring().encrypt(json.dumps(config), aad=f"channel:{channel_id}")


def open_config(channel: NotificationChannel) -> dict[str, Any]:
    raw = get_keyring().decrypt(
        Sealed(channel.config_ciphertext, channel.nonce, channel.key_id), aad=f"channel:{channel.id}"
    )
    data: dict[str, Any] = json.loads(raw)
    return data


@dataclass(frozen=True)
class SendResult:
    status: str  # delivered | failed
    http_status: int | None
    error: str | None
    latency_ms: int


def send_webhook(url: str, payload: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    """POST JSON to a webhook. Errors are stored as class names / status codes only."""
    started = time.monotonic()
    try:
        # Re-validated at send time so DNS changes after creation are caught (TH-10).
        validate_outbound_url(url, allow_private=get_settings().allow_private_webhooks)
    except UnsafeUrlError:
        return SendResult("failed", None, "UnsafeUrlError", 0)
    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT, follow_redirects=False, transport=transport) as client:
            resp = client.post(url, json=payload, headers={"User-Agent": "sre-code-health-toolkit/1.0"})
    except httpx.HTTPError as exc:
        return SendResult("failed", None, type(exc).__name__, int((time.monotonic() - started) * 1000))
    latency = int((time.monotonic() - started) * 1000)
    if 200 <= resp.status_code < 300:
        return SendResult("delivered", resp.status_code, None, latency)
    return SendResult("failed", resp.status_code, f"HTTP {resp.status_code}", latency)


def build_payload(db: Session, alert: Alert, event: str, now: datetime) -> dict[str, Any]:
    project = db.get(Project, alert.project_id)
    target = db.get(MonitoringTarget, alert.target_id) if alert.target_id else None
    base = get_settings().public_base_url.rstrip("/")
    ev = alert.evidence
    text = (
        f"[{event.upper()}] {alert.rule_name} ({alert.severity}) on "
        f"{target.service_name if target else 'deleted target'}: observed {ev.get('observed_value')} "
        f"vs threshold {ev.get('threshold')} over {ev.get('window')}"
    )
    return {
        "event": event,
        "text": text,
        "alert_id": str(alert.id),
        "project": {"id": str(alert.project_id), "name": project.name if project else None},
        "rule": {"id": str(alert.rule_id) if alert.rule_id else None, "name": alert.rule_name},
        "target": {"service_name": target.service_name, "environment": target.environment} if target else None,
        "severity": alert.severity,
        "status": alert.status,
        "first_seen_at": alert.first_seen_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "evidence": ev,
        "url": f"{base}/projects/{alert.project_id}/alerts/{alert.id}",
        "sent_at": now.isoformat(),
    }


def enqueue_notifications(db: Session, alert: Alert, event: str, now: datetime) -> int:
    """Create one delivery row per enabled channel, applying the cooldown (FR-ALR-06)."""
    s = get_settings()
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.enabled.is_(True))).all()
    if not channels:
        return 0
    payload = build_payload(db, alert, event, now)
    cooldown_since = now - timedelta(seconds=s.notification_cooldown_seconds)
    created = 0
    for ch in channels:
        recent = None
        if s.notification_cooldown_seconds > 0 and alert.rule_id is not None:
            recent = db.scalar(
                select(NotificationDelivery.id)
                .where(
                    NotificationDelivery.channel_id == ch.id,
                    NotificationDelivery.rule_id == alert.rule_id,
                    NotificationDelivery.event == event,
                    NotificationDelivery.status.in_(["delivered", "pending"]),
                    NotificationDelivery.created_at >= cooldown_since,
                )
                .limit(1)
            )
        status = "suppressed" if recent else "pending"
        db.add(
            NotificationDelivery(
                alert_id=alert.id,
                rule_id=alert.rule_id,
                channel_id=ch.id,
                event=event,
                status=status,
                payload=payload,
                attempts=0,
                next_attempt_at=None if recent else now,
                attempted_at=now if recent else None,
                error="cooldown" if recent else None,
                created_at=now,
            )
        )
        if recent:
            NOTIFICATIONS.labels("suppressed").inc()
        created += 1
    return created


def deliver_pending(db: Session, now: datetime, batch: int = 20, transport: httpx.BaseTransport | None = None) -> int:
    """Send due pending deliveries. Safe with several workers (SKIP LOCKED)."""
    s = get_settings()
    rows = db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now)
        .order_by(NotificationDelivery.next_attempt_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for d in rows:
        channel = db.get(NotificationChannel, d.channel_id)
        d.attempts += 1
        d.attempted_at = now
        if channel is None or not channel.enabled:
            d.status, d.error = "failed", "ChannelDisabled"
            continue
        try:
            url = str(open_config(channel)["url"])
        except Exception:
            d.status, d.error = "failed", "ConfigUnreadable"
            continue
        result = send_webhook(url, d.payload, transport=transport)
        d.http_status, d.error, d.latency_ms = result.http_status, result.error, result.latency_ms
        if result.status == "delivered":
            d.status = "delivered"
        elif d.attempts >= s.notification_max_attempts:
            d.status = "failed"
        else:
            d.next_attempt_at = now + timedelta(seconds=10 * (3 ** (d.attempts - 1)))
        NOTIFICATIONS.labels(d.status).inc()
    return len(rows)
