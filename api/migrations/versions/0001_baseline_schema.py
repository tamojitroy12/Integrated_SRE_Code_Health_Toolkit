"""Baseline schema for every entity in DATA_MODEL §2.

Revision ID: 0001
Revises: 
Create Date: 2026-10-26 01:16:01.099830
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram index support for the findings explorer free-text search (trusted extension).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('login_attempt',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempt'))
    )
    op.create_index('ix_login_attempt_email_ip', 'login_attempt', ['email', 'ip', 'created_at'], unique=False)
    op.create_index('ix_login_attempt_ip', 'login_attempt', ['ip', 'created_at'], unique=False)
    op.create_table('user',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"role" IN (\'viewer\', \'maintainer\', \'admin\')', name=op.f('ck_user_role_enum')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user'))
    )
    op.create_index('uq_user_email_lower', 'user', [sa.literal_column('lower(email)')], unique=True)
    op.create_table('audit_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('resource_type', sa.String(length=50), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['user.id'], name=op.f('fk_audit_log_actor_id_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_action', 'audit_log', ['action', 'created_at'], unique=False)
    op.create_index('ix_audit_log_actor', 'audit_log', ['actor_id', 'created_at'], unique=False)
    op.create_index('ix_audit_log_created', 'audit_log', ['created_at'], unique=False)
    op.create_table('credential',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('nonce', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=40), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"kind" IN (\'github_pat\')', name=op.f('ck_credential_kind_enum')),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_credential_created_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credential'))
    )
    op.create_table('job',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=60), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_by', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('resource_type', sa.String(length=30), nullable=True),
    sa.Column('resource_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"status" IN (\'queued\', \'running\', \'succeeded\', \'partial\', \'failed\', \'cancelled\')', name=op.f('ck_job_status_enum')),
    sa.CheckConstraint('"type" IN (\'scan\', \'recommendation\', \'fix_proposal\', \'pr_creation\', \'pr_cleanup\')', name=op.f('ck_job_type_enum')),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_job_created_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job'))
    )
    op.create_index('ix_job_claim', 'job', ['status', 'created_at'], unique=False)
    op.create_index('ix_job_lease', 'job', ['lease_expires_at'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index('ix_job_resource', 'job', ['resource_type', 'resource_id'], unique=False)
    op.create_table('notification_channel',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('config_ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('nonce', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=40), nullable=False),
    sa.Column('config_public', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_test_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"type" IN (\'webhook\', \'email\')', name=op.f('ck_notification_channel_type_enum')),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_notification_channel_created_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_channel'))
    )
    op.create_table('project',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_project_created_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project'))
    )
    op.create_index('uq_project_name_active', 'project', [sa.literal_column('lower(name)')], unique=True, postgresql_where=sa.text('archived_at IS NULL'))
    op.create_table('refresh_session',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rotated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_refresh_session_user_id_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_session')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_session_token_hash'))
    )
    op.create_index('ix_refresh_session_user', 'refresh_session', ['user_id', 'revoked_at'], unique=False)
    op.create_table('fix_proposal',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('base_commit_sha', sa.String(length=40), nullable=True),
    sa.Column('base_ref', sa.String(length=200), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('has_major_bump', sa.Boolean(), nullable=False),
    sa.Column('diff', sa.Text(), nullable=True),
    sa.Column('changed_files', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('validation_result', sa.String(length=20), nullable=False),
    sa.Column('delta_scan', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('risk_notes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approval_ack', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rejected_by', sa.Uuid(), nullable=True),
    sa.Column('rejection_reason', sa.String(length=1000), nullable=True),
    sa.Column('pr_number', sa.Integer(), nullable=True),
    sa.Column('pr_url', sa.String(length=500), nullable=True),
    sa.Column('pr_branch', sa.String(length=100), nullable=True),
    sa.Column('pr_error', sa.String(length=500), nullable=True),
    sa.Column('pr_closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("pr_branch IS NULL OR pr_branch ~ '^toolkit/fix/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name=op.f('ck_fix_proposal_pr_branch_pattern')),
    sa.CheckConstraint("status NOT IN ('approved', 'pr_opened') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name=op.f('ck_fix_proposal_approval_recorded')),
    sa.CheckConstraint('"status" IN (\'pending\', \'validating\', \'ready\', \'approved\', \'pr_opened\', \'rejected\', \'failed\', \'superseded\')', name=op.f('ck_fix_proposal_status_enum')),
    sa.CheckConstraint('"validation_result" IN (\'passed\', \'failed\', \'unverified\', \'not_run\')', name=op.f('ck_fix_proposal_validation_result_enum')),
    sa.ForeignKeyConstraint(['approved_by'], ['user.id'], name=op.f('fk_fix_proposal_approved_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_fix_proposal_job_id_job'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_fix_proposal_project_id_project'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rejected_by'], ['user.id'], name=op.f('fk_fix_proposal_rejected_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['user.id'], name=op.f('fk_fix_proposal_requested_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fix_proposal'))
    )
    op.create_index('ix_fix_proposal_project', 'fix_proposal', ['project_id', 'created_at'], unique=False)
    op.create_table('monitoring_target',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('service_name', sa.String(length=100), nullable=False),
    sa.Column('environment', sa.String(length=50), nullable=False),
    sa.Column('ingestion_mode', sa.String(length=30), nullable=False),
    sa.Column('scrape_url', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"ingestion_mode" IN (\'otlp_push\', \'prometheus_scrape\')', name=op.f('ck_monitoring_target_ingestion_mode_enum')),
    sa.CheckConstraint('"status" IN (\'waiting\', \'receiving\', \'stale\')', name=op.f('ck_monitoring_target_status_enum')),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_monitoring_target_project_id_project'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_monitoring_target')),
    sa.UniqueConstraint('project_id', 'service_name', 'environment', name='uq_target_identity')
    )
    op.create_table('repository',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('owner', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('url', sa.String(length=300), nullable=False),
    sa.Column('default_branch', sa.String(length=200), nullable=False),
    sa.Column('ecosystems', postgresql.ARRAY(sa.String(length=10)), nullable=False),
    sa.Column('manifests', postgresql.ARRAY(sa.String(length=300)), nullable=False),
    sa.Column('test_command', sa.String(length=50), nullable=True),
    sa.Column('credential_id', sa.Uuid(), nullable=True),
    sa.Column('can_open_prs', sa.Boolean(), nullable=False),
    sa.Column('is_private', sa.Boolean(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"provider" IN (\'github\')', name=op.f('ck_repository_provider_enum')),
    sa.ForeignKeyConstraint(['credential_id'], ['credential.id'], name=op.f('fk_repository_credential_id_credential'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_repository_project_id_project'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_repository')),
    sa.UniqueConstraint('project_id', name=op.f('uq_repository_project_id'))
    )
    op.create_table('alert_rule',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('metric', sa.String(length=30), nullable=False),
    sa.Column('comparator', sa.String(length=5), nullable=True),
    sa.Column('threshold', sa.Float(), nullable=True),
    sa.Column('window', sa.String(length=5), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=False),
    sa.Column('resolve_after', sa.Integer(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('guidance', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"comparator" IS NULL OR "comparator" IN (\'gt\', \'lt\')', name=op.f('ck_alert_rule_comparator_enum')),
    sa.CheckConstraint('"metric" IN (\'error_ratio\', \'latency_p95\', \'request_rate\', \'data_absent\')', name=op.f('ck_alert_rule_metric_enum')),
    sa.CheckConstraint('"severity" IN (\'critical\', \'high\', \'medium\', \'low\', \'info\')', name=op.f('ck_alert_rule_severity_enum')),
    sa.CheckConstraint('"type" IN (\'threshold\', \'anomaly\', \'absence\')', name=op.f('ck_alert_rule_type_enum')),
    sa.CheckConstraint('"window" IS NULL OR "window" IN (\'1m\', \'5m\', \'15m\')', name=op.f('ck_alert_rule_window_enum')),
    sa.CheckConstraint('duration_seconds > 0', name=op.f('ck_alert_rule_duration_positive')),
    sa.CheckConstraint('resolve_after >= 1', name=op.f('ck_alert_rule_resolve_after_positive')),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_alert_rule_created_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_alert_rule_project_id_project'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['monitoring_target.id'], name=op.f('fk_alert_rule_target_id_monitoring_target'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_rule'))
    )
    op.create_index('ix_alert_rule_enabled', 'alert_rule', ['enabled'], unique=False)
    op.create_index('ix_alert_rule_project', 'alert_rule', ['project_id'], unique=False)
    op.create_table('scan',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=True),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('ref', sa.String(length=200), nullable=False),
    sa.Column('commit_sha', sa.String(length=40), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('providers', postgresql.ARRAY(sa.String(length=20)), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"status" IN (\'queued\', \'running\', \'succeeded\', \'partial\', \'failed\', \'cancelled\')', name=op.f('ck_scan_status_enum')),
    sa.CheckConstraint('"trigger" IN (\'manual\', \'scheduled\')', name=op.f('ck_scan_trigger_enum')),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name=op.f('fk_scan_created_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_scan_job_id_job'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_scan_project_id_project'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['repository_id'], ['repository.id'], name=op.f('fk_scan_repository_id_repository'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scan'))
    )
    op.create_index('ix_scan_project_created', 'scan', ['project_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('uq_scan_active_per_project', 'scan', ['project_id'], unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_table('validation_run',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('fix_proposal_id', sa.Uuid(), nullable=False),
    sa.Column('stage', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('exit_code', sa.Integer(), nullable=True),
    sa.Column('duration_s', sa.Float(), nullable=False),
    sa.Column('output_tail', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"stage" IN (\'baseline\', \'apply\', \'post_change\', \'rescan\')', name=op.f('ck_validation_run_stage_enum')),
    sa.CheckConstraint('"status" IN (\'passed\', \'failed\', \'skipped\', \'error\')', name=op.f('ck_validation_run_status_enum')),
    sa.ForeignKeyConstraint(['fix_proposal_id'], ['fix_proposal.id'], name=op.f('fk_validation_run_fix_proposal_id_fix_proposal'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_validation_run'))
    )
    op.create_index('ix_validation_run_proposal', 'validation_run', ['fix_proposal_id'], unique=False)
    op.create_table('alert',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('rule_id', sa.Uuid(), nullable=True),
    sa.Column('target_id', sa.Uuid(), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('rule_name', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('occurrence_count', sa.Integer(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('acknowledged_by', sa.Uuid(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"severity" IN (\'critical\', \'high\', \'medium\', \'low\', \'info\')', name=op.f('ck_alert_severity_enum')),
    sa.CheckConstraint('"status" IN (\'firing\', \'acknowledged\', \'resolved\')', name=op.f('ck_alert_status_enum')),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['user.id'], name=op.f('fk_alert_acknowledged_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_alert_project_id_project'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolved_by'], ['user.id'], name=op.f('fk_alert_resolved_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rule.id'], name=op.f('fk_alert_rule_id_alert_rule'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['target_id'], ['monitoring_target.id'], name=op.f('fk_alert_target_id_monitoring_target'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert'))
    )
    op.create_index('ix_alert_last_seen', 'alert', ['last_seen_at', 'id'], unique=False)
    op.create_index('ix_alert_project_status', 'alert', ['project_id', 'status'], unique=False)
    op.create_index('uq_alert_open_per_rule_target', 'alert', ['rule_id', 'target_id'], unique=True, postgresql_where=sa.text("status <> 'resolved'"))
    op.create_table('alert_rule_state',
    sa.Column('rule_id', sa.Uuid(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('breach_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consecutive_breaches', sa.Integer(), nullable=False),
    sa.Column('consecutive_clears', sa.Integer(), nullable=False),
    sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_value', sa.Float(), nullable=True),
    sa.Column('last_outcome', sa.String(length=30), nullable=True),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rule.id'], name=op.f('fk_alert_rule_state_rule_id_alert_rule'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['monitoring_target.id'], name=op.f('fk_alert_rule_state_target_id_monitoring_target'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('rule_id', name=op.f('pk_alert_rule_state'))
    )
    op.create_table('dependency',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=False),
    sa.Column('ecosystem', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=214), nullable=False),
    sa.Column('version', sa.String(length=100), nullable=False),
    sa.Column('scope', sa.String(length=12), nullable=False),
    sa.Column('manifest_path', sa.String(length=300), nullable=False),
    sa.Column('purl', sa.String(length=400), nullable=True),
    sa.CheckConstraint('"ecosystem" IN (\'npm\', \'pypi\')', name=op.f('ck_dependency_ecosystem_enum')),
    sa.CheckConstraint('"scope" IN (\'direct\', \'transitive\')', name=op.f('ck_dependency_scope_enum')),
    sa.ForeignKeyConstraint(['scan_id'], ['scan.id'], name=op.f('fk_dependency_scan_id_scan'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dependency')),
    sa.UniqueConstraint('scan_id', 'ecosystem', 'name', 'version', 'manifest_path', name='uq_dependency')
    )
    op.create_table('finding',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=True),
    sa.Column('severity_rank', sa.SmallInteger(), nullable=False),
    sa.Column('severity_source', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_change', sa.String(length=20), nullable=False),
    sa.Column('ecosystem', sa.String(length=10), nullable=True),
    sa.Column('package_name', sa.String(length=214), nullable=True),
    sa.Column('package_version', sa.String(length=100), nullable=True),
    sa.Column('scope', sa.String(length=12), nullable=True),
    sa.Column('manifest_path', sa.String(length=300), nullable=True),
    sa.Column('file_path', sa.String(length=500), nullable=True),
    sa.Column('line_start', sa.Integer(), nullable=True),
    sa.Column('line_end', sa.Integer(), nullable=True),
    sa.Column('rule_id', sa.String(length=300), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('advisory', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sources', postgresql.ARRAY(sa.String(length=20)), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('dismissal_reason', sa.String(length=20), nullable=True),
    sa.Column('dismissal_note', sa.String(length=1000), nullable=True),
    sa.Column('dismissed_by', sa.Uuid(), nullable=True),
    sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('first_seen_scan_id', sa.Uuid(), nullable=True),
    sa.Column('last_seen_scan_id', sa.Uuid(), nullable=True),
    sa.Column('resolved_scan_id', sa.Uuid(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"dismissal_reason" IS NULL OR "dismissal_reason" IN (\'false_positive\', \'accepted_risk\', \'wont_fix\')', name=op.f('ck_finding_dismissal_reason_enum')),
    sa.CheckConstraint('"last_change" IN (\'new\', \'unchanged\', \'resolved\')', name=op.f('ck_finding_last_change_enum')),
    sa.CheckConstraint('"severity" IS NULL OR "severity" IN (\'critical\', \'high\', \'medium\', \'low\', \'info\')', name=op.f('ck_finding_severity_enum')),
    sa.CheckConstraint('"status" IN (\'open\', \'dismissed\', \'resolved\')', name=op.f('ck_finding_status_enum')),
    sa.CheckConstraint('"type" IN (\'dependency_vulnerability\', \'dependency_outdated\', \'dependency_incompatibility\', \'code_issue\')', name=op.f('ck_finding_type_enum')),
    sa.ForeignKeyConstraint(['dismissed_by'], ['user.id'], name=op.f('fk_finding_dismissed_by_user'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['first_seen_scan_id'], ['scan.id'], name=op.f('fk_finding_first_seen_scan_id_scan'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['last_seen_scan_id'], ['scan.id'], name=op.f('fk_finding_last_seen_scan_id_scan'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], name=op.f('fk_finding_project_id_project'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolved_scan_id'], ['scan.id'], name=op.f('fk_finding_resolved_scan_id_scan'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_finding')),
    sa.UniqueConstraint('project_id', 'fingerprint', name='uq_finding_fingerprint')
    )
    op.create_index('ix_finding_advisory', 'finding', ['advisory'], unique=False, postgresql_using='gin')
    op.create_index('ix_finding_explorer', 'finding', ['project_id', 'status', 'severity_rank'], unique=False)
    op.create_index('ix_finding_last_seen', 'finding', ['project_id', 'last_seen_at', 'id'], unique=False)
    op.create_index('ix_finding_search', 'finding', ['search_text'], unique=False, postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.create_index('ix_finding_type', 'finding', ['project_id', 'type'], unique=False)
    op.create_table('scan_provider_run',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('tool_version', sa.String(length=100), nullable=True),
    sa.Column('db_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint('"provider" IN (\'trivy\', \'osv\', \'registry\', \'semgrep\')', name=op.f('ck_scan_provider_run_provider_enum')),
    sa.CheckConstraint('"status" IN (\'ok\', \'failed\', \'skipped\')', name=op.f('ck_scan_provider_run_status_enum')),
    sa.ForeignKeyConstraint(['scan_id'], ['scan.id'], name=op.f('fk_scan_provider_run_scan_id_scan'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scan_provider_run')),
    sa.UniqueConstraint('scan_id', 'provider', name='uq_provider_run')
    )
    op.create_table('evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('finding_id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=True),
    sa.Column('evidence_key', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=True),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('"kind" IN (\'advisory_record\', \'registry_metadata\', \'code_snippet\', \'scanner_output\')', name=op.f('ck_evidence_kind_enum')),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.id'], name=op.f('fk_evidence_finding_id_finding'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['scan_id'], ['scan.id'], name=op.f('fk_evidence_scan_id_scan'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence')),
    sa.UniqueConstraint('finding_id', 'content_sha256', name='uq_evidence_content'),
    sa.UniqueConstraint('finding_id', 'evidence_key', name='uq_evidence_key')
    )
    op.create_table('finding_occurrence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=False),
    sa.Column('finding_id', sa.Uuid(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('change', sa.String(length=20), nullable=False),
    sa.CheckConstraint('"change" IN (\'new\', \'unchanged\')', name=op.f('ck_finding_occurrence_change_enum')),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.id'], name=op.f('fk_finding_occurrence_finding_id_finding'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['scan_id'], ['scan.id'], name=op.f('fk_finding_occurrence_scan_id_scan'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_finding_occurrence')),
    sa.UniqueConstraint('scan_id', 'fingerprint', name='uq_occurrence_scan_fingerprint')
    )
    op.create_index('ix_occurrence_finding', 'finding_occurrence', ['finding_id'], unique=False)
    op.create_table('fix_proposal_finding',
    sa.Column('fix_proposal_id', sa.Uuid(), nullable=False),
    sa.Column('finding_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.id'], name=op.f('fk_fix_proposal_finding_finding_id_finding'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['fix_proposal_id'], ['fix_proposal.id'], name=op.f('fk_fix_proposal_finding_fix_proposal_id_fix_proposal'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('fix_proposal_id', 'finding_id', name=op.f('pk_fix_proposal_finding'))
    )
    op.create_table('notification_delivery',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('alert_id', sa.Uuid(), nullable=True),
    sa.Column('rule_id', sa.Uuid(), nullable=True),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('event', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('"event" IN (\'firing\', \'resolved\', \'test\')', name=op.f('ck_notification_delivery_event_enum')),
    sa.CheckConstraint('"status" IN (\'pending\', \'delivered\', \'failed\', \'suppressed\')', name=op.f('ck_notification_delivery_status_enum')),
    sa.ForeignKeyConstraint(['alert_id'], ['alert.id'], name=op.f('fk_notification_delivery_alert_id_alert'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['channel_id'], ['notification_channel.id'], name=op.f('fk_notification_delivery_channel_id_notification_channel'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rule.id'], name=op.f('fk_notification_delivery_rule_id_alert_rule'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_delivery'))
    )
    op.create_index('ix_delivery_alert', 'notification_delivery', ['alert_id'], unique=False)
    op.create_index('ix_delivery_cooldown', 'notification_delivery', ['channel_id', 'rule_id', 'event', 'attempted_at'], unique=False)
    op.create_index('ix_delivery_pending', 'notification_delivery', ['next_attempt_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_table('recommendation',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('finding_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('validation_status', sa.String(length=30), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('prompt_version', sa.String(length=20), nullable=False),
    sa.Column('evidence_pack_sha256', sa.String(length=64), nullable=True),
    sa.Column('evidence_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('raw_output', sa.Text(), nullable=True),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('feedback_rating', sa.String(length=20), nullable=True),
    sa.Column('feedback_comment', sa.String(length=1000), nullable=True),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('"kind" IN (\'library_alternative\', \'upgrade_guidance\', \'code_improvement\')', name=op.f('ck_recommendation_kind_enum')),
    sa.CheckConstraint('"status" IN (\'pending\', \'completed\', \'failed\')', name=op.f('ck_recommendation_status_enum')),
    sa.CheckConstraint('"validation_status" IS NULL OR "validation_status" IN (\'validated\', \'partially_validated\', \'rejected\')', name=op.f('ck_recommendation_validation_status_enum')),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.id'], name=op.f('fk_recommendation_finding_id_finding'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['job.id'], name=op.f('fk_recommendation_job_id_job'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['user.id'], name=op.f('fk_recommendation_requested_by_user'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recommendation'))
    )
    op.create_index('ix_recommendation_created', 'recommendation', ['created_at'], unique=False)
    op.create_index('ix_recommendation_finding', 'recommendation', ['finding_id', 'created_at'], unique=False)

    # TH-23: the audit log is append-only. Rows may be deleted by the retention job, never edited.
    op.execute(
        """
        CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (DATA_MODEL §10).")
