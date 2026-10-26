"""Monitoring engine and alert manager (COMP-04/COMP-08; WF-02, WF-03; FR-MON-04/05, FR-ALR-02..08).

Every ``ALERT_EVAL_INTERVAL_SECONDS`` the engine:

1. updates every target's ``last_seen_at``/``status`` from one batched Prometheus query;
2. evaluates each enabled rule with an allowlisted query and updates its durable
   ``alert_rule_state`` (consecutive breach/clear counters survive restarts);
3. fires an alert after N = ceil(duration / Δ_eval) consecutive breaches, dedupes repeated
   breaches into the open alert, and auto-resolves after ``resolve_after`` clear evaluations.

If Prometheus cannot be queried nothing changes state; the error is recorded (NFR-REL-05).
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from toolkit.alerting.notify import enqueue_notifications
from toolkit.core.config import get_settings
from toolkit.core.metrics import ALERT_EVALUATIONS
from toolkit.db.models import Alert, AlertRule, AlertRuleState, MonitoringTarget, Project
from toolkit.monitoring import queries as Q
from toolkit.monitoring.prometheus import PrometheusClient, PrometheusUnavailable
from toolkit.monitoring.sli import required_consecutive, zscore

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="rule-eval")

ABSENCE_GUIDANCE = "The service stopped sending metrics. Check that it is running and can reach the collector."


@dataclass
class Outcome:
    violated: bool | None  # None = query error / not evaluable (state unchanged)
    value: float | None
    query_name: str
    query: str
    note: str | None = None
    z_score: float | None = None


def _selector(target: MonitoringTarget) -> Q.Selector:
    return Q.Selector(target.service_name, target.environment)


def evaluate_rule(
    prom: PrometheusClient, rule: AlertRule, target: MonitoringTarget, now: datetime, eval_interval: int
) -> Outcome:
    sel = _selector(target)
    try:
        if rule.type == "absence":
            query = Q.data_absent(sel, Q.seconds_to_promql(rule.duration_seconds))
            if target.last_seen_at is None:
                return Outcome(False, None, "data_absent", query, "target has never reported; absence not evaluated")
            value = prom.query_scalar(query, now)
            violated = value is not None and value >= 1
            return Outcome(violated, float(rule.duration_seconds) if violated else 0.0, "data_absent", query)
        if rule.type == "anomaly":
            params = rule.params or {}
            baseline = int(params.get("baseline_points", 60))
            k = float(params.get("z_threshold", 3))
            query = Q.metric_query(rule.metric, sel, rule.window or "5m")
            start = now - timedelta(seconds=eval_interval * (baseline + 1))
            series = prom.query_range(query, start, now, eval_interval)
            points = [v for _t, v in series[0].points] if series else []
            if len(points) < max(10, baseline // 2) + 1:
                return Outcome(False, None, rule.metric, query, "not enough baseline samples")
            current, history = points[-1], points[-(baseline + 1) : -1]
            z = zscore(history, current)
            if z is None:
                return Outcome(False, None if math.isnan(current) else current, rule.metric, query, "no traffic")
            return Outcome(abs(z.z) > k, current, rule.metric, query, z_score=round(z.z, 3))
        query = Q.metric_query(rule.metric, sel, rule.window or "5m")
        value = prom.query_scalar(query, now)
        if value is None or math.isnan(value):
            if rule.metric == "request_rate":
                value = 0.0
            else:
                return Outcome(False, None, rule.metric, query, "no traffic")
        if math.isinf(value):
            return Outcome(False, None, rule.metric, query, "undefined value")
        threshold = rule.threshold if rule.threshold is not None else 0.0
        violated = value > threshold if rule.comparator == "gt" else value < threshold
        return Outcome(violated, value, rule.metric, query)
    except PrometheusUnavailable as exc:
        return Outcome(None, None, rule.metric, "", f"query_error: {exc}")


def update_target_statuses(db: Session, prom: PrometheusClient, now: datetime) -> int:
    """Batch status derivation for all push targets (FR-PRJ-04). Raises PrometheusUnavailable."""
    s = get_settings()
    targets = list(
        db.scalars(
            select(MonitoringTarget)
            .join(Project, Project.id == MonitoringTarget.project_id)
            .where(Project.archived_at.is_(None))
        )
    )
    if not targets:
        return 0
    samples = prom.query(Q.last_sample_batch([t.service_name for t in targets]), now)
    latest: dict[tuple[str, str], float] = {}
    for smp in samples:
        key = (smp.labels.get(Q.SERVICE_LABEL, ""), smp.labels.get(Q.ENV_LABEL, ""))
        if not math.isnan(smp.v):
            latest[key] = max(latest.get(key, 0.0), smp.v)
    for t in targets:
        ts = max(
            [v for (svc, env), v in latest.items() if svc == t.service_name and env in ("", t.environment)],
            default=None,
        )
        if ts is not None:
            seen = datetime.fromtimestamp(ts, now.tzinfo)
            if t.last_seen_at is None or seen > t.last_seen_at:
                t.last_seen_at = seen
        if t.last_seen_at is None:
            status = "waiting"
        elif (now - t.last_seen_at).total_seconds() <= s.target_stale_after_seconds:
            status = "receiving"
        else:
            status = "stale"
        t.status = status
    return len(targets)


def _evidence(rule: AlertRule, out: Outcome, now: datetime, n: int) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "query": f"{out.query_name}: {out.query}",
        "query_name": out.query_name,
        "observed_value": out.value,
        "threshold": rule.threshold
        if rule.type == "threshold"
        else (rule.params.get("z_threshold") if rule.type == "anomaly" else float(rule.duration_seconds)),
        "comparator": rule.comparator or ("abs_z_gt" if rule.type == "anomaly" else "no_samples_for_seconds"),
        "window": rule.window or Q.seconds_to_promql(rule.duration_seconds),
        "guidance": rule.guidance
        or (ABSENCE_GUIDANCE if rule.type == "absence" else "Investigate recent changes affecting this service."),
        "evaluated_at": now.isoformat(),
        "consecutive_evaluations": n,
        "duration_seconds": rule.duration_seconds,
    }
    if out.z_score is not None:
        ev["z_score"] = out.z_score
    return ev


def apply_outcome(
    db: Session, rule: AlertRule, target: MonitoringTarget, out: Outcome, now: datetime, eval_interval: int
) -> str:
    """Update durable counters and alert lifecycle for one evaluation. Returns a short outcome."""
    db.execute(
        insert(AlertRuleState)
        .values(rule_id=rule.id, target_id=target.id, consecutive_breaches=0, consecutive_clears=0)
        .on_conflict_do_nothing()
    )
    state = db.get(AlertRuleState, rule.id, with_for_update=True)
    assert state is not None
    state.last_evaluated_at = now
    if out.violated is None:
        state.last_outcome = "query_error"
        ALERT_EVALUATIONS.labels("query_error").inc()
        return "query_error"
    ALERT_EVALUATIONS.labels("ok").inc()
    state.last_value = out.value
    open_alert = db.scalar(
        select(Alert)
        .where(Alert.rule_id == rule.id, Alert.target_id == target.id, Alert.status != "resolved")
        .with_for_update()
    )
    if rule.type == "absence":
        needed = 1  # the absent_over_time window already spans duration_seconds
    elif rule.type == "anomaly":
        needed = int((rule.params or {}).get("consecutive", 3))
    else:
        needed = required_consecutive(rule.duration_seconds, eval_interval)

    if out.violated:
        state.consecutive_breaches += 1
        state.consecutive_clears = 0
        state.breach_since = state.breach_since or now
        state.last_outcome = "breach"
        if open_alert is not None:
            open_alert.last_seen_at = now
            open_alert.occurrence_count += 1
            open_alert.evidence = {
                **open_alert.evidence,
                "last_observed_value": out.value,
                "last_evaluated_at": now.isoformat(),
            }
            return "updated"
        if state.consecutive_breaches >= needed:
            alert = Alert(
                rule_id=rule.id,
                target_id=target.id,
                project_id=rule.project_id,
                rule_name=rule.name,
                status="firing",
                severity=rule.severity,
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=1,
                evidence=_evidence(rule, out, now, state.consecutive_breaches),
            )
            try:
                with db.begin_nested():
                    db.add(alert)
                    db.flush()
            except IntegrityError:
                return "duplicate"  # another evaluator won the race (partial unique index)
            enqueue_notifications(db, alert, "firing", now)
            log.info("alert fired", extra={"alert_id": str(alert.id), "rule": rule.name})
            return "fired"
        return "pending"

    state.consecutive_clears += 1
    state.consecutive_breaches = 0
    state.breach_since = None
    state.last_outcome = "clear" if out.note is None else out.note[:30]
    if open_alert is not None and state.consecutive_clears >= rule.resolve_after:
        open_alert.status = "resolved"
        open_alert.resolved_at = now
        open_alert.resolved_by = None
        enqueue_notifications(db, open_alert, "resolved", now)
        log.info("alert auto-resolved", extra={"alert_id": str(open_alert.id), "rule": rule.name})
        return "resolved"
    return "clear"


def evaluate_once(db: Session, prom: PrometheusClient, now: datetime) -> dict[str, int]:
    """One evaluation tick. Caller owns the transaction."""
    s = get_settings()
    counts: dict[str, int] = {}
    try:
        update_target_statuses(db, prom, now)
    except PrometheusUnavailable as exc:
        ALERT_EVALUATIONS.labels("query_error").inc()
        log.warning("evaluation_error: Prometheus unavailable; alert state unchanged", extra={"error": str(exc)})
        return {"evaluation_error": 1}
    pairs = db.execute(
        select(AlertRule, MonitoringTarget)
        .join(MonitoringTarget, MonitoringTarget.id == AlertRule.target_id)
        .join(Project, Project.id == AlertRule.project_id)
        .where(AlertRule.enabled.is_(True), Project.archived_at.is_(None))
    ).all()
    futures = [(_pool.submit(evaluate_rule, prom, r, t, now, s.alert_eval_interval_seconds), r, t) for r, t in pairs]
    for fut, rule, target in futures:
        result = apply_outcome(db, rule, target, fut.result(), now, s.alert_eval_interval_seconds)
        counts[result] = counts.get(result, 0) + 1
    db.flush()
    return counts
