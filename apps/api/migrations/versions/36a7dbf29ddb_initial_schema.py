"""initial schema

The §5 data model. Alembic is the only place schema changes happen (§11):
the API owns migrations, the worker never runs them.

Revision ID: 36a7dbf29ddb
Revises: 
Create Date: 2026-09-20 06:42:55.303008
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '36a7dbf29ddb'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('idempotency_records',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=64), nullable=False),
    sa.Column('user_key', sa.String(length=64), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('response_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope', 'user_key', 'key', name='uq_idempotency')
    )
    op.create_table('job_events',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_events_job_id'), 'job_events', ['job_id'], unique=False)
    op.create_index(op.f('ix_job_events_type'), 'job_events', ['type'], unique=False)
    op.create_index(op.f('ix_job_events_user_id'), 'job_events', ['user_id'], unique=False)
    op.create_table('stripe_events',
    sa.Column('id', sa.String(length=128), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('uploads',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('key', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('declared_bytes', sa.BigInteger(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uploads_user_id'), 'uploads', ['user_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=64), nullable=True),
    sa.Column('credits_cached', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('stripe_customer_id')
    )
    op.create_table('webhook_deliveries',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('target_url', sa.Text(), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('api_keys',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)
    op.create_table('batches',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('completed', sa.Integer(), nullable=False),
    sa.Column('failed', sa.Integer(), nullable=False),
    sa.Column('zip_key', sa.String(length=512), nullable=True),
    sa.Column('webhook_url', sa.Text(), nullable=True),
    sa.Column('options', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_batches_user_id'), 'batches', ['user_id'], unique=False)
    op.create_table('credit_grants',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('remaining', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stripe_event_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_event_id')
    )
    op.create_index(op.f('ix_credit_grants_user_id'), 'credit_grants', ['user_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('stripe_subscription_id', sa.String(length=64), nullable=False),
    sa.Column('plan', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_subscription_id')
    )
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_table('usage_daily',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('jobs', sa.Integer(), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('bytes_in', sa.BigInteger(), nullable=False),
    sa.Column('bytes_out', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'date', name='uq_usage_user_date')
    )
    op.create_index(op.f('ix_usage_daily_user_id'), 'usage_daily', ['user_id'], unique=False)
    op.create_table('credit_ledger',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('grant_id', sa.String(length=64), nullable=True),
    sa.Column('delta', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=48), nullable=False),
    sa.Column('stripe_event_id', sa.String(length=128), nullable=True),
    sa.Column('root_job_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['grant_id'], ['credit_grants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('root_job_id', 'reason', name='uq_ledger_root_job_reason'),
    sa.UniqueConstraint('stripe_event_id', 'reason', name='uq_ledger_stripe_event_reason')
    )
    op.create_index(op.f('ix_credit_ledger_user_id'), 'credit_ledger', ['user_id'], unique=False)
    op.create_index('ix_ledger_user_created', 'credit_ledger', ['user_id', 'created_at'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('batch_id', sa.String(length=64), nullable=True),
    sa.Column('root_job_id', sa.String(length=64), nullable=False),
    sa.Column('parent_job_id', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('options', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=True),
    sa.Column('source_key', sa.String(length=512), nullable=True),
    sa.Column('source_bytes', sa.BigInteger(), nullable=True),
    sa.Column('source_w', sa.Integer(), nullable=True),
    sa.Column('source_h', sa.Integer(), nullable=True),
    sa.Column('profile', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('classification', sa.String(length=32), nullable=True),
    sa.Column('classification_confidence', sa.Float(), nullable=True),
    sa.Column('engine_version', sa.String(length=64), nullable=True),
    sa.Column('score_version', sa.String(length=16), nullable=True),
    sa.Column('chosen_params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('score', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('warnings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('physical_w_mm', sa.Float(), nullable=True),
    sa.Column('physical_size_source', sa.String(length=16), nullable=True),
    sa.Column('output_keys', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('credits_charged', sa.Integer(), nullable=False),
    sa.Column('unlocked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_jobs_user_idempotency')
    )
    op.create_index('ix_jobs_expires_at', 'jobs', ['expires_at'], unique=False)
    op.create_index('ix_jobs_root', 'jobs', ['root_job_id'], unique=False)
    op.create_index(op.f('ix_jobs_root_job_id'), 'jobs', ['root_job_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index('ix_jobs_user_created', 'jobs', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_jobs_user_id'), 'jobs', ['user_id'], unique=False)
    op.create_table('job_candidates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('score', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('fidelity', sa.Float(), nullable=True),
    sa.Column('total', sa.Float(), nullable=True),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('node_count', sa.Integer(), nullable=True),
    sa.Column('path_count', sa.Integer(), nullable=True),
    sa.Column('exit_status', sa.Integer(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_candidates_job_id'), 'job_candidates', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_candidates_job_id'), table_name='job_candidates')
    op.drop_table('job_candidates')
    op.drop_index(op.f('ix_jobs_user_id'), table_name='jobs')
    op.drop_index('ix_jobs_user_created', table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_root_job_id'), table_name='jobs')
    op.drop_index('ix_jobs_root', table_name='jobs')
    op.drop_index('ix_jobs_expires_at', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_ledger_user_created', table_name='credit_ledger')
    op.drop_index(op.f('ix_credit_ledger_user_id'), table_name='credit_ledger')
    op.drop_table('credit_ledger')
    op.drop_index(op.f('ix_usage_daily_user_id'), table_name='usage_daily')
    op.drop_table('usage_daily')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_credit_grants_user_id'), table_name='credit_grants')
    op.drop_table('credit_grants')
    op.drop_index(op.f('ix_batches_user_id'), table_name='batches')
    op.drop_table('batches')
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_table('webhook_deliveries')
    op.drop_table('users')
    op.drop_index(op.f('ix_uploads_user_id'), table_name='uploads')
    op.drop_table('uploads')
    op.drop_table('stripe_events')
    op.drop_index(op.f('ix_job_events_user_id'), table_name='job_events')
    op.drop_index(op.f('ix_job_events_type'), table_name='job_events')
    op.drop_index(op.f('ix_job_events_job_id'), table_name='job_events')
    op.drop_table('job_events')
    op.drop_table('idempotency_records')
