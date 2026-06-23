"""관리자 로그인 이벤트와 공개 API 키 테이블 추가.

Revision ID: 20260623_0010
Revises: 20260621_0009
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0010"
down_revision = "20260621_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("attempted_username", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("client_ip", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("next_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_events_created_at",
        "login_events",
        ["created_at", "id"],
    )
    op.create_index("ix_login_events_outcome", "login_events", ["outcome"])

    op.create_table(
        "public_api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_hint", sa.String(length=12), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_public_api_keys_key_hash"),
    )
    op.create_index(
        "ix_public_api_keys_state_created",
        "public_api_keys",
        ["state", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_public_api_keys_state_created", table_name="public_api_keys")
    op.drop_table("public_api_keys")
    op.drop_index("ix_login_events_outcome", table_name="login_events")
    op.drop_index("ix_login_events_created_at", table_name="login_events")
    op.drop_table("login_events")
