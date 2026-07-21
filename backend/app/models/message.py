import uuid
from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TenantModel


class MessageRole:
    USER = "user"
    ASSISTANT = "assistant"


class Message(TenantModel, table=True):
    """
    A single turn in a Conversation.

    citations stores a JSON array of structured citation objects:
    [{"document_id": "...", "chunk_id": "...", "section": "Section 3.2", "quote": "..."}]

    This structure lets the viewer highlight the exact source passage when the
    user clicks a citation in the chat UI.
    """

    __tablename__ = "messages"

    conversation_id: uuid.UUID = Field(
        nullable=False,
        index=True,
        foreign_key="conversations.id",
    )
    role: str = Field(nullable=False, description="'user' or 'assistant'")
    content: str = Field(sa_column=Column(Text, nullable=False))
    # JSON array of citation objects; null for user messages
    citations: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Token count of this message for quota tracking
    token_count: Optional[int] = Field(default=None)
    # Latency in ms for assistant messages (for RAG eval)
    latency_ms: Optional[int] = Field(default=None)
