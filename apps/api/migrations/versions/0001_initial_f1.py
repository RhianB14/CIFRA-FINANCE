from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

user_id = postgresql.UUID(as_uuid=True)
timestamp_tz = sa.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", user_id, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("totp_secret_encrypted", sa.String(length=512), nullable=True),
        sa.Column("totp_pending_secret_encrypted", sa.String(length=512), nullable=True),
        sa.Column("totp_last_step", sa.Integer(), nullable=True),
        sa.Column("totp_confirmed_at", timestamp_tz, nullable=True),
        sa.Column("locale", sa.CHAR(length=5), nullable=False, server_default=sa.text("'pt-BR'")),
        sa.Column("created_at", timestamp_tz, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", timestamp_tz, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_normalized")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", user_id, nullable=False),
        sa.Column("user_id", user_id, nullable=False),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", user_id, nullable=False),
        sa.Column("device_label", sa.String(length=255), nullable=True),
        sa.Column("issued_at", timestamp_tz, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", timestamp_tz, nullable=False),
        sa.Column("revoked_at", timestamp_tz, nullable=True),
        sa.Column("replaced_by", user_id, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("jti_hash", name=op.f("uq_refresh_tokens_jti_hash")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_refresh_tokens"),
        ),
    )
    op.create_table(
        "backup_codes",
        sa.Column("id", user_id, nullable=False),
        sa.Column("user_id", user_id, nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", timestamp_tz, nullable=True),
        sa.Column("created_at", timestamp_tz, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_backup_codes_code_hash")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_backup_codes_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", user_id, nullable=False),
        sa.Column("user_id", user_id, nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_ip", sa.String(length=64), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", user_id, nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", timestamp_tz, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_user_id_users"),
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("backup_codes")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
