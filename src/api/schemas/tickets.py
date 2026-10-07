"""
Request bodies of the ticket and chat endpoints.

Input limits (Fase 11.6): every field below ends up in an LLM prompt, a DB
row and possibly a GitHub issue — unbounded input is unbounded cost and a
way to push the system prompt out of the context window. Images: inline
data URIs of a real png/jpeg/webp only (src/security/image_input.py).
"""
from pydantic import BaseModel, Field, field_validator

from src.core.config import get_settings
from src.security.image_input import MAX_IMAGE_DATA_URI_CHARS, validate_image_data_uri


class TicketPayload(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    summary: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., max_length=10_000)
    user_email: str = Field(..., max_length=150)
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_DATA_URI_CHARS)

    @field_validator("image_base64")
    @classmethod
    def _real_inline_image(cls, v):
        return validate_image_data_uri(v)


class ApprovalPayload(BaseModel):
    approved: bool
    approver_id: str


class ChatPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=get_settings().chat_message_max_chars)
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_DATA_URI_CHARS)

    @field_validator("image_base64")
    @classmethod
    def _real_inline_image(cls, v):
        return validate_image_data_uri(v)
