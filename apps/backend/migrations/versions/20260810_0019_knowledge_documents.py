"""Replace KnowledgeBase text revisions with ordered document snapshots.

Revision ID: 20260810_0019
Revises: 20260810_0018
"""

from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260810_0019"
down_revision = "20260810_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_knowledge_bases_tenant_id_id", "knowledge_bases", ["tenant_id", "id"]
    )
    op.create_unique_constraint(
        "uq_knowledge_base_revisions_tenant_base_id",
        "knowledge_base_revisions",
        ["tenant_id", "knowledge_base_id", "id"],
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("knowledge_base_id", "key"),
        sa.UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_documents_tenant_base_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "knowledge_document_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("knowledge_document_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("knowledge_document_id", "revision_number"),
        sa.UniqueConstraint(
            "tenant_id",
            "knowledge_base_id",
            "knowledge_document_id",
            "id",
            name="uq_knowledge_document_revisions_owner_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id", "knowledge_document_id"],
            [
                "knowledge_documents.tenant_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "media_type = 'text/markdown'",
            name="ck_knowledge_document_revisions_markdown",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_knowledge_document_revisions_revision_number_positive",
        ),
    )
    op.create_table(
        "knowledge_base_revision_documents",
        sa.Column("knowledge_base_revision_id", sa.Uuid(), primary_key=True),
        sa.Column("knowledge_document_revision_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("knowledge_base_revision_id", "position"),
        sa.UniqueConstraint("knowledge_base_revision_id", "knowledge_document_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id", "knowledge_base_revision_id"],
            [
                "knowledge_base_revisions.tenant_id",
                "knowledge_base_revisions.knowledge_base_id",
                "knowledge_base_revisions.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "knowledge_base_id",
                "knowledge_document_id",
                "knowledge_document_revision_id",
            ],
            [
                "knowledge_document_revisions.tenant_id",
                "knowledge_document_revisions.knowledge_base_id",
                "knowledge_document_revisions.knowledge_document_id",
                "knowledge_document_revisions.id",
            ],
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_knowledge_base_revision_documents_position_nonnegative",
        ),
    )

    bind = op.get_bind()
    bases = list(
        bind.execute(
            sa.text(
                "SELECT kb.id, kb.tenant_id, COALESCE(MIN(kbr.created_at), now()) "
                "AS created_at FROM knowledge_bases kb "
                "LEFT JOIN knowledge_base_revisions kbr "
                "ON kbr.knowledge_base_id = kb.id "
                "GROUP BY kb.id, kb.tenant_id ORDER BY kb.id"
            )
        ).mappings()
    )
    documents: dict[object, object] = {}
    for base in bases:
        document_id = uuid4()
        documents[base["id"]] = document_id
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_documents "
                "(id, knowledge_base_id, tenant_id, key, created_at) "
                "VALUES (:id, :base, :tenant, 'knowledge', :created)"
            ),
            {
                "id": document_id,
                "base": base["id"],
                "tenant": base["tenant_id"],
                "created": base["created_at"],
            },
        )

    revisions = list(
        bind.execute(
            sa.text(
                "SELECT id, knowledge_base_id, tenant_id, revision_number, text, "
                "created_at FROM knowledge_base_revisions "
                "ORDER BY knowledge_base_id, revision_number"
            )
        ).mappings()
    )
    for item in revisions:
        document_revision_id = uuid4()
        content = item["text"]
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_document_revisions "
                "(id, knowledge_document_id, knowledge_base_id, tenant_id, "
                "revision_number, media_type, content, content_hash, created_at) "
                "VALUES (:id, :document, :base, :tenant, :number, "
                "'text/markdown', :content, :hash, :created)"
            ),
            {
                "id": document_revision_id,
                "document": documents[item["knowledge_base_id"]],
                "base": item["knowledge_base_id"],
                "tenant": item["tenant_id"],
                "number": item["revision_number"],
                "content": content,
                "hash": sha256(content.encode("utf-8")).hexdigest(),
                "created": item["created_at"],
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_base_revision_documents "
                "(knowledge_base_revision_id, knowledge_document_revision_id, "
                "tenant_id, knowledge_base_id, knowledge_document_id, position) "
                "VALUES (:revision, :document_revision, :tenant, :base, "
                ":document, 0)"
            ),
            {
                "revision": item["id"],
                "document_revision": document_revision_id,
                "tenant": item["tenant_id"],
                "base": item["knowledge_base_id"],
                "document": documents[item["knowledge_base_id"]],
            },
        )

    migrated = bind.execute(
        sa.text("SELECT count(*) FROM knowledge_base_revision_documents")
    ).scalar_one()
    if migrated != len(revisions):
        raise RuntimeError("KnowledgeBase document backfill is incomplete")
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM knowledge_base_revisions kbr "
            "JOIN knowledge_base_revision_documents link "
            "ON link.knowledge_base_revision_id = kbr.id "
            "JOIN knowledge_documents document "
            "ON document.id = link.knowledge_document_id "
            "JOIN knowledge_document_revisions revision "
            "ON revision.id = link.knowledge_document_revision_id "
            "WHERE link.position <> 0 OR document.key <> 'knowledge' "
            "OR revision.content IS DISTINCT FROM kbr.text)"
        )
    ).scalar_one():
        raise RuntimeError("KnowledgeBase document backfill changed legacy content")
    op.drop_column("knowledge_base_revisions", "text")


def downgrade() -> None:
    bind = op.get_bind()
    incompatible = bind.execute(
        sa.text(
            "SELECT kbr.id FROM knowledge_base_revisions kbr "
            "LEFT JOIN knowledge_base_revision_documents link "
            "ON link.knowledge_base_revision_id = kbr.id "
            "LEFT JOIN knowledge_documents document "
            "ON document.id = link.knowledge_document_id "
            "LEFT JOIN knowledge_document_revisions revision "
            "ON revision.id = link.knowledge_document_revision_id "
            "GROUP BY kbr.id "
            "HAVING count(link.knowledge_document_revision_id) <> 1 "
            "OR min(link.position) <> 0 "
            "OR min(document.key) <> 'knowledge' "
            "OR min(revision.media_type) <> 'text/markdown'"
        )
    ).first()
    if incompatible is not None:
        raise RuntimeError(
            "KnowledgeBase downgrade refused: snapshots are not legacy-compatible "
            "single knowledge.md documents"
        )

    op.add_column(
        "knowledge_base_revisions", sa.Column("text", sa.Text(), nullable=True)
    )
    bind.execute(
        sa.text(
            "UPDATE knowledge_base_revisions kbr SET text = revision.content "
            "FROM knowledge_base_revision_documents link "
            "JOIN knowledge_document_revisions revision "
            "ON revision.id = link.knowledge_document_revision_id "
            "WHERE link.knowledge_base_revision_id = kbr.id"
        )
    )
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM knowledge_base_revisions WHERE text IS NULL)"
        )
    ).scalar_one():
        raise RuntimeError("KnowledgeBase downgrade could not restore legacy text")
    op.alter_column("knowledge_base_revisions", "text", nullable=False)
    op.drop_table("knowledge_base_revision_documents")
    op.drop_table("knowledge_document_revisions")
    op.drop_table("knowledge_documents")
    op.drop_constraint(
        "uq_knowledge_base_revisions_tenant_base_id",
        "knowledge_base_revisions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_knowledge_bases_tenant_id_id", "knowledge_bases", type_="unique"
    )
