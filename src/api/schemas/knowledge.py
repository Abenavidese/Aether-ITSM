"""Request bodies of the knowledge-base endpoints."""
from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    feedback_text: str = Field(..., min_length=1, max_length=2000)


class ReviewRequest(BaseModel):
    approve: bool


class ReindexRequest(BaseModel):
    force: bool = False
