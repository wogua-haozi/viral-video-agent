"""Add vNext-C candidate confirmation snapshots and decisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260725_0004"
down_revision = "20260723_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("analysis_jobs", "status", existing_type=sa.String(length=20), type_=sa.String(length=40), existing_nullable=False)
    op.create_table(
        "collection_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source_execution_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("workflow_version", sa.String(length=20), nullable=False),
        sa.Column("topic_spec", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("tool_results", sa.JSON(), nullable=False),
        sa.Column("search_queries_used", sa.JSON(), nullable=False),
        sa.Column("collection_usage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "source_execution_version", name="uq_collection_snapshot_job_execution"),
    )
    op.create_index("ix_collection_snapshots_job_execution", "collection_snapshots", ["job_id", "source_execution_version"])
    op.create_table(
        "candidate_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("source_execution_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("topic_summary", sa.JSON(), nullable=False),
        sa.Column("max_candidates", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_snapshot_id"], ["collection_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_snapshot_id", name="uq_candidate_snapshot_collection"),
        sa.UniqueConstraint("job_id", "source_execution_version", name="uq_candidate_snapshot_job_execution"),
    )
    op.create_index("ix_candidate_snapshots_job_execution", "candidate_snapshots", ["job_id", "source_execution_version"])
    op.create_table(
        "candidate_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_account_id", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("matched_video_count", sa.Integer(), nullable=False),
        sa.Column("sample_titles", sa.JSON(), nullable=False),
        sa.Column("evidence_links", sa.JSON(), nullable=False),
        sa.Column("why_surfaced", sa.JSON(), nullable=False),
        sa.Column("identity_confidence", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["candidate_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "candidate_id", name="uq_candidate_account_snapshot_candidate"),
        sa.UniqueConstraint("snapshot_id", "platform", "platform_account_id", name="uq_candidate_account_snapshot_identity"),
    )
    op.create_index("ix_candidate_accounts_snapshot_order", "candidate_accounts", ["snapshot_id", "sort_order"])
    op.create_table(
        "candidate_decision_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["candidate_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_candidate_decision_batches_request_id"),
        sa.UniqueConstraint("snapshot_id", name="uq_candidate_decision_batches_snapshot_id"),
    )
    op.create_index("ix_candidate_decision_batches_job_id", "candidate_decision_batches", ["job_id"])
    op.create_table(
        "candidate_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_account_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["candidate_decision_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_account_id"], ["candidate_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "candidate_account_id", name="uq_candidate_decision_batch_candidate"),
    )
    op.create_table(
        "candidate_synthesis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("decision_batch_id", sa.Uuid(), nullable=False),
        sa.Column("execution_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_batch_id"], ["candidate_decision_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "execution_version", name="uq_candidate_synthesis_run_job_execution"),
    )
    op.create_index("ix_candidate_synthesis_runs_job_execution", "candidate_synthesis_runs", ["job_id", "execution_version"])


def downgrade() -> None:
    op.drop_index("ix_candidate_synthesis_runs_job_execution", table_name="candidate_synthesis_runs")
    op.drop_table("candidate_synthesis_runs")
    op.drop_table("candidate_decisions")
    op.drop_index("ix_candidate_decision_batches_job_id", table_name="candidate_decision_batches")
    op.drop_table("candidate_decision_batches")
    op.drop_index("ix_candidate_accounts_snapshot_order", table_name="candidate_accounts")
    op.drop_table("candidate_accounts")
    op.drop_index("ix_candidate_snapshots_job_execution", table_name="candidate_snapshots")
    op.drop_table("candidate_snapshots")
    op.drop_index("ix_collection_snapshots_job_execution", table_name="collection_snapshots")
    op.drop_table("collection_snapshots")
    op.alter_column("analysis_jobs", "status", existing_type=sa.String(length=40), type_=sa.String(length=20), existing_nullable=False)
