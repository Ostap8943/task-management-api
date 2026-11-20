from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .domain import Priority, Status


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
        Index("ix_tasks_deadline_status", "deadline", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[Status] = mapped_column(
        Enum(
            Status, name="task_status", native_enum=False, create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        default=Status.BACKLOG,
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(
            Priority, name="task_priority", native_enum=False, create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        default=Priority.MEDIUM,
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deadline: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_task_created", "task_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
