"""감사 로그 멱등 키·상태 전용 컬럼과 고유 인덱스(T-183).

`payload_json` 전체 검색에 의존하던 MCP 멱등 조회를 제거한다. 기존 payload가 유효한
JSON object이고 key/state 계약을 만족하는 행만 backfill한다. 같은
`(actor_type, action, idempotency_key)`가 여러 건이면 최신 ID 행의 state까지 유효한
경우에만 그 한 건을 승격한다. 최신 행의 state가 잘못됐으면 오래된 유효 행도 stale
결과로 승격하지 않는다. 손상 JSON·비-object·잘못된 key/state는 감사 원문을 보존하되
전용 컬럼은 NULL로 둔다. state가 없는 legacy 행은 완료 응답이므로 `final`로 해석한다.

T-170의 provider별 지오코딩 캐시(`20260713_0024`)가 먼저 main에 병합됐으므로
동시 head를 만들지 않도록 그 revision 뒤에 직렬로 연결한다.

Revision ID: 20260713_0023
Revises: 20260713_0024
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_0023"
down_revision = "20260713_0024"
branch_labels = None
depends_on = None

_UNIQUE_INDEX = "uq_audit_logs_actor_action_idempotency_key"
_PAIR_CHECK = "ck_audit_logs_idempotency_pair"


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("idempotency_state", sa.String(length=16), nullable=True),
    )

    # Text 전체를 jsonb로 한 번에 cast하면 손상된 legacy 한 행이 migration 전체를
    # 중단한다. 행별 예외를 NULL로 바꾸는 transaction-local helper로 안전하게 거른다.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION pg_temp.ktc_safe_jsonb(input_text text)
        RETURNS jsonb
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN input_text::jsonb;
        EXCEPTION WHEN others THEN
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        WITH parsed AS MATERIALIZED (
            SELECT
                id,
                actor_type,
                action,
                pg_temp.ktc_safe_jsonb(payload_json) AS payload
            FROM audit_logs
            WHERE payload_json IS NOT NULL
        ),
        extracted AS MATERIALIZED (
            SELECT
                id,
                actor_type,
                action,
                payload ->> 'idempotency_key' AS idempotency_key,
                CASE
                    WHEN NOT (payload ? 'idempotency_state') THEN 'final'
                    WHEN jsonb_typeof(payload -> 'idempotency_state') = 'string'
                         AND payload ->> 'idempotency_state' IN ('pending', 'final')
                    THEN payload ->> 'idempotency_state'
                    ELSE NULL
                END AS idempotency_state
            FROM parsed
            WHERE jsonb_typeof(payload) = 'object'
              AND jsonb_typeof(payload -> 'idempotency_key') = 'string'
        ),
        ranked AS (
            SELECT
                id,
                idempotency_key,
                idempotency_state,
                row_number() OVER (
                    PARTITION BY actor_type, action, idempotency_key
                    ORDER BY id DESC
                ) AS duplicate_rank
            FROM extracted
            WHERE char_length(idempotency_key) BETWEEN 1 AND 255
        )
        UPDATE audit_logs AS audit
        SET
            idempotency_key = ranked.idempotency_key,
            idempotency_state = ranked.idempotency_state
        FROM ranked
        WHERE audit.id = ranked.id
          AND ranked.duplicate_rank = 1
          AND ranked.idempotency_state IN ('pending', 'final')
        """
    )
    op.execute("DROP FUNCTION pg_temp.ktc_safe_jsonb(text)")

    op.create_check_constraint(
        _PAIR_CHECK,
        "audit_logs",
        "(idempotency_key IS NULL AND idempotency_state IS NULL) OR "
        "(idempotency_key IS NOT NULL AND idempotency_key <> '' AND "
        "idempotency_state IS NOT NULL AND "
        "idempotency_state IN ('pending', 'final'))",
    )
    op.create_index(
        _UNIQUE_INDEX,
        "audit_logs",
        ["actor_type", "action", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    # 조회와 column drop 사이에 새 pending이 생기는 TOCTOU를 막는다. 기존 writer가
    # 끝날 때까지 기다린 뒤 이 migration transaction 동안 새 insert/update를 차단한다.
    op.execute("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE")
    pending_exists = op.get_bind().execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM audit_logs
                WHERE idempotency_state = 'pending'
            )
            """
        )
    ).scalar_one()
    if pending_exists:
        raise RuntimeError(
            "audit_logs에 pending 멱등 작업이 있어 0023 downgrade를 중단한다"
        )

    op.drop_index(_UNIQUE_INDEX, table_name="audit_logs")
    op.drop_constraint(_PAIR_CHECK, "audit_logs", type_="check")
    op.drop_column("audit_logs", "idempotency_state")
    op.drop_column("audit_logs", "idempotency_key")
