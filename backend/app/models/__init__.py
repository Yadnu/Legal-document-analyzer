# Import all models here so that:
# 1. Alembic can discover them via SQLModel.metadata
# 2. Any module that does `from app import models` gets the full set
from app.models.audit_event import AuditEvent
from app.models.chunk import Chunk
from app.models.clause_comment import ClauseComment
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message, MessageRole
from app.models.obligation import Obligation
from app.models.organization import Organization
from app.models.summary import DocumentSummaryCard
from app.models.user import User

__all__ = [
    "AuditEvent",
    "Chunk",
    "ClauseComment",
    "Conversation",
    "Document",
    "DocumentStatus",
    "DocumentSummaryCard",
    "Message",
    "MessageRole",
    "Obligation",
    "Organization",
    "User",
]
