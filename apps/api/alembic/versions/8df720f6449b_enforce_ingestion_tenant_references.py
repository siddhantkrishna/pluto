"""Enforce tenant ownership on ingestion references."""

from alembic import op

revision = "8df720f6449b"
down_revision = "26f63f67a5df"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_dataset_tenant_id", "datasets", ["institution_id", "id"])
    op.create_unique_constraint("uq_file_tenant_id", "ingest_files", ["institution_id", "id"])
    for table, column, target in [
        ("ingest_files", "dataset_id", "datasets"),
        ("ingest_jobs", "file_id", "ingest_files"),
        ("content_chunks", "file_id", "ingest_files"),
    ]:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_tenant",
            table,
            target,
            ["institution_id", column],
            ["institution_id", "id"],
            ondelete="CASCADE" if column == "file_id" else None,
        )


def downgrade():
    for table, column, target in [
        ("content_chunks", "file_id", "ingest_files"),
        ("ingest_jobs", "file_id", "ingest_files"),
        ("ingest_files", "dataset_id", "datasets"),
    ]:
        op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
        op.create_foreign_key(f"{table}_{column}_fkey", table, target, [column], ["id"])
    op.drop_constraint("uq_file_tenant_id", "ingest_files", type_="unique")
    op.drop_constraint("uq_dataset_tenant_id", "datasets", type_="unique")
