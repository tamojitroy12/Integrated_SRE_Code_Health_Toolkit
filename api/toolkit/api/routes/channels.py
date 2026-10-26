"""Notification channels (API_SPEC §5.4a). Webhook URLs are write-only secrets."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import Field
from sqlalchemy import select

from toolkit import audit
from toolkit.alerting.notify import seal_config, send_webhook
from toolkit.api.deps import DB, Admin, ClockDep, Maintainer, client_ip
from toolkit.api.schemas.common import Out, StrictModel, UtcDatetime
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.core.netguard import UnsafeUrlError, mask_url_host, validate_outbound_url
from toolkit.db.models import NotificationChannel, NotificationDelivery

router = APIRouter(prefix="/notification-channels", tags=["notification-channels"])
TEST_COOLDOWN_SECONDS = 5


class WebhookConfig(StrictModel):
    url: str = Field(min_length=8, max_length=2048)


class ChannelCreate(StrictModel):
    type: Literal["webhook", "email"]
    name: str = Field(min_length=1, max_length=100)
    config: WebhookConfig


class ChannelPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    config: WebhookConfig | None = None


class ChannelOut(Out):
    id: uuid.UUID
    type: str
    name: str
    enabled: bool
    config: dict[str, Any]
    created_at: UtcDatetime
    updated_at: UtcDatetime


def _out(ch: NotificationChannel) -> ChannelOut:
    return ChannelOut(
        id=ch.id,
        type=ch.type,
        name=ch.name,
        enabled=ch.enabled,
        config=ch.config_public,
        created_at=ch.created_at,
        updated_at=ch.updated_at,
    )


def _validated_url(url: str) -> str:
    try:
        return validate_outbound_url(url.strip(), allow_private=get_settings().allow_private_webhooks)
    except UnsafeUrlError as exc:
        raise ApiError(ErrorCode.VALIDATION_ERROR, details=[{"field": "config.url", "issue": str(exc)}]) from exc


def _apply_config(ch: NotificationChannel, url: str) -> None:
    sealed = seal_config(ch.id, {"url": url})
    ch.config_ciphertext, ch.nonce, ch.key_id = sealed.ciphertext, sealed.nonce, sealed.key_id
    ch.config_public = mask_url_host(url)


@router.get("", response_model=list[ChannelOut])
def list_channels(principal: Maintainer, db: DB) -> list[ChannelOut]:
    return [_out(c) for c in db.scalars(select(NotificationChannel).order_by(NotificationChannel.name))]


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelCreate, principal: Admin, db: DB, request: Request) -> ChannelOut:
    if body.type == "email":
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "email channel is not enabled in this release",
            details=[{"field": "type", "issue": "email channel is not enabled in this release"}],
        )
    url = _validated_url(body.config.url)
    ch = NotificationChannel(id=uuid.uuid4(), type=body.type, name=body.name, enabled=True, created_by=principal.id)
    _apply_config(ch, url)
    db.add(ch)
    db.flush()
    audit.record(
        db,
        "channel.created",
        actor_id=principal.id,
        resource_type="notification_channel",
        resource_id=ch.id,
        ip=client_ip(request),
    )
    db.refresh(ch)
    return _out(ch)


def _get(db: DB, channel_id: uuid.UUID) -> NotificationChannel:
    ch = db.get(NotificationChannel, channel_id, with_for_update=True)
    if ch is None:
        raise not_found("Notification channel")
    return ch


@router.patch("/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: uuid.UUID, body: ChannelPatch, principal: Admin, db: DB, request: Request) -> ChannelOut:
    ch = _get(db, channel_id)
    if body.name is not None:
        ch.name = body.name
    if body.enabled is not None:
        ch.enabled = body.enabled
    if body.config is not None:
        _apply_config(ch, _validated_url(body.config.url))
    audit.record(
        db,
        "channel.updated",
        actor_id=principal.id,
        resource_type="notification_channel",
        resource_id=ch.id,
        metadata={"fields": sorted(body.model_fields_set)},
        ip=client_ip(request),
    )
    db.flush()
    db.refresh(ch)
    return _out(ch)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: uuid.UUID, principal: Admin, db: DB, request: Request) -> Response:
    ch = _get(db, channel_id)
    db.delete(ch)
    audit.record(
        db,
        "channel.deleted",
        actor_id=principal.id,
        resource_type="notification_channel",
        resource_id=channel_id,
        ip=client_ip(request),
    )
    return Response(status_code=204)


@router.post("/{channel_id}/test")
def test_channel(channel_id: uuid.UUID, principal: Admin, db: DB, clock: ClockDep) -> dict[str, Any]:
    from toolkit.alerting.notify import open_config

    ch = _get(db, channel_id)
    now = clock.now()
    if ch.last_test_at and now - ch.last_test_at < timedelta(seconds=TEST_COOLDOWN_SECONDS):
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "Wait a few seconds before testing this channel again.",
            headers={"Retry-After": str(TEST_COOLDOWN_SECONDS)},
        )
    ch.last_test_at = now
    payload = {
        "event": "test",
        "alert_id": None,
        "text": f"Test notification from SRE + Code Health ({ch.name})",
        "channel": {"id": str(ch.id), "name": ch.name},
        "sent_at": now.isoformat(),
    }
    result = send_webhook(str(open_config(ch)["url"]), payload)
    delivery = NotificationDelivery(
        alert_id=None,
        channel_id=ch.id,
        event="test",
        status=result.status,
        payload=payload,
        attempts=1,
        http_status=result.http_status,
        error=result.error,
        latency_ms=result.latency_ms,
        attempted_at=now,
        created_at=now,
    )
    db.add(delivery)
    db.flush()
    return {
        "channel_id": str(ch.id),
        "delivery_id": str(delivery.id),
        "status": result.status,
        "http_status": result.http_status,
        "error": result.error,
        "latency_ms": result.latency_ms,
        "attempted_at": now,
    }
