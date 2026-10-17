"""Reserve submission quota and fence interrupted workers.

Revision ID: 20261017_0005
Revises: 20260725_0004

Stop workers while upgrading; old workers do not understand execution leases.
"""

import uuid

from alembic import op
import sqlalchemy as sa


revision = "20261017_0005"
down_revision = "20260725_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("worker_token", sa.String(36), nullable=True))
    op.add_column("analysis_jobs", sa.Column("worker_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_analysis_jobs_worker_lease", "analysis_jobs", ["status", "worker_lease_expires_at"])

    bind = op.get_bind()
    job_fk = next(item for item in sa.inspect(bind).get_foreign_keys("usage_records") if item["constrained_columns"] == ["job_id"])
    with op.batch_alter_table("usage_records", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s"}) as batch:
        batch.add_column(sa.Column("accounted_attempts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.alter_column("job_id", existing_type=sa.Uuid(), nullable=True)
        batch.drop_constraint(job_fk["name"] or "fk_usage_records_job_id", type_="foreignkey")
        batch.create_foreign_key("fk_usage_records_job_id", "analysis_jobs", ["job_id"], ["id"], ondelete="SET NULL")

    jobs = sa.table(
        "analysis_jobs",
        sa.column("id", sa.Uuid()), sa.column("user_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("interaction_usage", sa.JSON()),
    )
    usage = sa.table(
        "usage_records",
        sa.column("id", sa.Uuid()), sa.column("job_id", sa.Uuid()), sa.column("user_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("input_tokens", sa.Integer()), sa.column("output_tokens", sa.Integer()),
        sa.column("estimated_cost", sa.Float()), sa.column("asr_seconds", sa.Float()),
        sa.column("accounted_attempts", sa.JSON()),
    )
    # Keep historical measured totals. The interaction checkpoint prevents old
    # clarification costs being added again when an existing job is retried.
    rows = bind.execute(sa.select(
        usage.c.id, usage.c.input_tokens, usage.c.output_tokens, usage.c.estimated_cost,
        jobs.c.created_at, jobs.c.interaction_usage,
    ).join(jobs, jobs.c.id == usage.c.job_id)).mappings().all()
    for row in rows:
        interaction = row["interaction_usage"] or {}
        checkpoint = {
            "input_tokens": min(row["input_tokens"], max(0, int(interaction.get("input_tokens", 0) or 0))),
            "output_tokens": min(row["output_tokens"], max(0, int(interaction.get("output_tokens", 0) or 0))),
            "estimated_cost": min(row["estimated_cost"], max(0.0, float(interaction.get("estimated_cost", 0) or 0))),
            "asr_seconds": 0.0,
        }
        bind.execute(usage.update().where(usage.c.id == row["id"]).values(
            created_at=row["created_at"], accounted_attempts={"interaction": checkpoint},
        ))

    # Pre-existing pending/failed jobs also consume their original submission
    # month's slot; a migration must not let them bypass the admission limit.
    missing = bind.execute(sa.select(jobs).where(
        ~sa.exists(sa.select(usage.c.id).where(usage.c.job_id == jobs.c.id))
    )).mappings().all()
    for job in missing:
        interaction = job["interaction_usage"] or {}
        checkpoint = {
            "input_tokens": max(0, int(interaction.get("input_tokens", 0) or 0)),
            "output_tokens": max(0, int(interaction.get("output_tokens", 0) or 0)),
            "estimated_cost": max(0.0, float(interaction.get("estimated_cost", 0) or 0)),
            "asr_seconds": 0.0,
        }
        bind.execute(usage.insert().values(
            id=uuid.uuid4(), job_id=job["id"], user_id=job["user_id"],
            created_at=job["created_at"], **checkpoint,
            accounted_attempts={"interaction": checkpoint},
        ))


def downgrade() -> None:
    # Deleted jobs' ledger entries cannot fit the old NOT NULL/CASCADE schema.
    # Refuse rather than silently discard their consumption history.
    bind = op.get_bind()
    deleted_job_usage = bind.scalar(sa.text("SELECT count(*) FROM usage_records WHERE job_id IS NULL"))
    if deleted_job_usage:
        raise RuntimeError("Cannot downgrade while retained usage for deleted jobs exists; restore from a pre-upgrade backup instead.")
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_constraint("fk_usage_records_job_id", type_="foreignkey")
        batch.create_foreign_key("fk_usage_records_job_id", "analysis_jobs", ["job_id"], ["id"], ondelete="CASCADE")
        batch.alter_column("job_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("accounted_attempts")
    op.drop_index("ix_analysis_jobs_worker_lease", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "worker_lease_expires_at")
    op.drop_column("analysis_jobs", "worker_token")
