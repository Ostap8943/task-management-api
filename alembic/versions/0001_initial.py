"""Create users, tasks and comments."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "backlog", "in_progress", "review", "done", "cancelled",
                name="task_status", native_enum=False, create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("high", "medium", "low", name="task_priority", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tasks_author_id", "tasks", ["author_id"])
    op.create_index("ix_tasks_assignee_status", "tasks", ["assignee_id", "status"])
    op.create_index("ix_tasks_deadline_status", "tasks", ["deadline", "status"])
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_comments_task_created", "comments", ["task_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("tasks")
    op.drop_table("users")
