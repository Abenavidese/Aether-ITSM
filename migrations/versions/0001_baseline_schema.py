"""baseline schema

The schema exactly as the app built it before Alembic (create_all() plus the
ALTER TABLEs of the old _ensure_schema_migrations in src/main.py), including
four Company columns nothing used — 0002 drops them. A database created by
that older app is adopted with `alembic stamp 0001` (python -m src.db.migrate
does it automatically) instead of re-running this.

Revision ID: 0001
Revises:
Create Date: 2026-09-26 17:19:48.664267

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('payload', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_by', sa.String(), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(), nullable=True),
    sa.Column('dedupe_key', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_run_after'), ['run_after'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_status'), ['status'], unique=False)

    op.create_table('subscription_plans',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('price_usd', sa.Float(), nullable=True),
    sa.Column('max_users', sa.Integer(), nullable=True),
    sa.Column('max_tickets_per_month', sa.Integer(), nullable=True),
    sa.Column('max_ai_resolutions_per_month', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('companies',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('company_size', sa.String(), nullable=True),
    sa.Column('industry', sa.String(), nullable=True),
    sa.Column('current_tool', sa.String(), nullable=True),
    sa.Column('onboarding_completed', sa.String(), nullable=True),
    sa.Column('api_key', sa.String(), nullable=True),
    sa.Column('api_key_hash', sa.String(), nullable=True),
    sa.Column('webhook_url', sa.String(), nullable=True),
    sa.Column('github_token', sa.String(), nullable=True),
    sa.Column('github_repo', sa.String(), nullable=True),
    sa.Column('mcp_server_url', sa.String(), nullable=True),
    sa.Column('mcp_auth_token', sa.String(), nullable=True),
    sa.Column('llm_engine', sa.String(), nullable=True),
    sa.Column('monitored_services', sa.String(), nullable=True),
    sa.Column('render_api_key', sa.String(), nullable=True),
    sa.Column('vercel_drain_secret', sa.String(), nullable=True),
    sa.Column('plan_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('api_key')
    )
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_companies_api_key_hash'), ['api_key_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_companies_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_companies_name'), ['name'], unique=False)

    op.create_table('agent_spans',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=True),
    sa.Column('trace_id', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_spans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_spans_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_spans_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_spans_trace_id'), ['trace_id'], unique=False)

    op.create_table('platform_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('service_id', sa.String(), nullable=False),
    sa.Column('level', sa.String(), nullable=True),
    sa.Column('message', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('request_path', sa.String(), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('platform_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_platform_logs_service_id'), ['service_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_platform_logs_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_platform_logs_timestamp'), ['timestamp'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('full_name', sa.String(), nullable=False),
    sa.Column('job_title', sa.String(), nullable=True),
    sa.Column('primary_goal', sa.String(), nullable=True),
    sa.Column('password_hash', sa.String(), nullable=True),
    sa.Column('role', sa.String(), nullable=True),
    sa.Column('company_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_id'), ['id'], unique=False)

    op.create_table('knowledge_audit',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('source_type', sa.String(), nullable=True),
    sa.Column('sha256', sa.String(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('chunks', sa.Integer(), nullable=True),
    sa.Column('injection_flags', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('knowledge_audit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_audit_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_audit_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('log_access_audit',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=True),
    sa.Column('service_name', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('service_id', sa.String(), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lines_returned', sa.Integer(), nullable=True),
    sa.Column('verdict', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('log_access_audit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_log_access_audit_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_log_access_audit_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('tickets',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('tenant_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('external_id', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('urgency', sa.String(), nullable=True),
    sa.Column('category', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('resolution_path', sa.String(), nullable=True),
    sa.Column('estimated_time_saved_minutes', sa.Integer(), nullable=True),
    sa.Column('cost_saved_usd', sa.Float(), nullable=True),
    sa.Column('ai_confidence_score', sa.Float(), nullable=True),
    sa.Column('github_issue_url', sa.String(), nullable=True),
    sa.Column('proposed_plan', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'external_id', name='uq_ticket_tenant_external')
    )
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tickets_external_id'), ['external_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tickets_id'), ['id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tickets_id'))
        batch_op.drop_index(batch_op.f('ix_tickets_external_id'))

    op.drop_table('tickets')
    with op.batch_alter_table('log_access_audit', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_log_access_audit_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_log_access_audit_created_at'))

    op.drop_table('log_access_audit')
    with op.batch_alter_table('knowledge_audit', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_audit_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_knowledge_audit_created_at'))

    op.drop_table('knowledge_audit')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_id'))
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('platform_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_platform_logs_timestamp'))
        batch_op.drop_index(batch_op.f('ix_platform_logs_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_platform_logs_service_id'))

    op.drop_table('platform_logs')
    with op.batch_alter_table('agent_spans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_spans_trace_id'))
        batch_op.drop_index(batch_op.f('ix_agent_spans_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_agent_spans_started_at'))

    op.drop_table('agent_spans')
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_companies_name'))
        batch_op.drop_index(batch_op.f('ix_companies_id'))
        batch_op.drop_index(batch_op.f('ix_companies_api_key_hash'))

    op.drop_table('companies')
    op.drop_table('subscription_plans')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_jobs_run_after'))
        batch_op.drop_index(batch_op.f('ix_jobs_kind'))

    op.drop_table('jobs')
