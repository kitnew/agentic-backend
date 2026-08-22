from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class PlatformRuntimeDraft(Base):
    __tablename__ = "platform_runtime_component_drafts"
    __table_args__ = (CheckConstraint("id = 1", name="ck_platform_runtime_draft_one"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlatformRuntimeComponentRevision(Base):
    __tablename__ = "platform_runtime_component_revisions"
    __table_args__ = (
        UniqueConstraint("revision_number", name="uq_platform_runtime_revision_number"),
        CheckConstraint("revision_number > 0", name="ck_platform_runtime_revision_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    revision_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformSystemPromptDraft(Base):
    __tablename__ = "platform_system_prompt_drafts"
    __table_args__ = (CheckConstraint("id = 1", name="ck_platform_system_prompt_draft_one"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlatformSystemPromptComponentRevision(Base):
    __tablename__ = "platform_system_prompt_component_revisions"
    __table_args__ = (
        UniqueConstraint("revision_number", name="uq_platform_system_prompt_revision_number"),
        CheckConstraint(
            "revision_number > 0", name="ck_platform_system_prompt_revision_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    revision_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformProfilePromptDraft(Base):
    __tablename__ = "platform_profile_prompt_drafts"
    __table_args__ = (UniqueConstraint("profile", name="uq_platform_profile_prompt_draft"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlatformProfilePromptComponentRevision(Base):
    __tablename__ = "platform_profile_prompt_component_revisions"
    __table_args__ = (
        UniqueConstraint(
            "profile", "revision_number", name="uq_platform_profile_prompt_revision"
        ),
        CheckConstraint(
            "revision_number > 0", name="ck_platform_profile_prompt_revision_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile: Mapped[str] = mapped_column(String(100))
    revision_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformRelease(Base):
    __tablename__ = "platform_releases"
    __table_args__ = (
        UniqueConstraint("release_number", name="uq_platform_release_number"),
        ForeignKeyConstraint(
            ("runtime_revision_id",),
            ("platform_runtime_component_revisions.id",),
        ),
        ForeignKeyConstraint(
            ("system_prompt_revision_id",),
            ("platform_system_prompt_component_revisions.id",),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    release_number: Mapped[int] = mapped_column(Integer)
    runtime_revision_id: Mapped[UUID] = mapped_column(Uuid)
    system_prompt_revision_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformReleaseProfilePrompt(Base):
    __tablename__ = "platform_release_profile_prompts"
    __table_args__ = (
        ForeignKeyConstraint(("release_id",), ("platform_releases.id",), ondelete="CASCADE"),
        ForeignKeyConstraint(
            ("profile_prompt_revision_id",),
            ("platform_profile_prompt_component_revisions.id",),
        ),
        UniqueConstraint("release_id", "profile", name="uq_platform_release_profile"),
    )

    release_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    profile: Mapped[str] = mapped_column(String(100), primary_key=True)
    profile_prompt_revision_id: Mapped[UUID] = mapped_column(Uuid)


class PlatformControl(Base):
    __tablename__ = "platform_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_platform_control_one"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_release_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("platform_releases.id"), nullable=True
    )
