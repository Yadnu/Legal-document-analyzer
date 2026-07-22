import uuid
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlmodel import Field

from app.models.base import TenantModel


class Chunk(TenantModel, table=True):
    """
    A clause-level chunk extracted from a Document.

    Structural metadata (section_number, heading, page, cross_refs) is preserved
    during parsing so that citations point to the exact clause in the source.

    Embedding rules (enforced by the RAG pipeline):
    - embedding_model and embedding_model_version must be recorded with every chunk.
    - The exact same model+version must be used for query embeddings at retrieval time.
    - Never mix models across chunks or queries within a tenant.

    search_vector (tsvector) powers the sparse BM25-style retrieval path.
    The embedding column (vector) powers the dense retrieval path.
    """

    __tablename__ = "chunks"

    document_id: uuid.UUID = Field(nullable=False, index=True, foreign_key="documents.id")
    # Structural metadata preserved from the source document
    section_number: Optional[str] = Field(default=None)
    heading: Optional[str] = Field(default=None)
    page: Optional[int] = Field(default=None)
    # JSON array of section references found in this chunk, e.g. ["Section 2.1", "Exhibit B"]
    cross_refs: Optional[str] = Field(default=None, sa_column=Column(Text))
    content: str = Field(sa_column=Column(Text, nullable=False))
    # Token count for context-window budgeting at generation time
    token_count: Optional[int] = Field(default=None)
    # Embedding provenance — must never be mixed across chunks or queries
    embedding_model: str = Field(nullable=False)
    embedding_model_version: str = Field(nullable=False)
    # Dense retrieval vector (dimension set to 1024 for voyage-law-2 / Bedrock Titan)
    embedding: Optional[list[float]] = Field(
        default=None,
        sa_column=Column(Vector(1024)),
    )
    # Sparse retrieval — populated by a Postgres trigger or the worker after insert
    search_vector: Optional[str] = Field(
        default=None,
        sa_column=Column(TSVECTOR),
    )

    __table_args__ = (
        # HNSW index for approximate nearest-neighbour dense retrieval.
        # Created here so Alembic detects it; tenant_id filter applied in queries.
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN index for fast tsvector full-text search
        Index(
            "ix_chunks_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
    )
