from pydantic import BaseModel, Field


class Clip(BaseModel):
    id: str
    url: str
    lat: float
    lng: float
    ts: float
    created_at: float


class IngestResponse(BaseModel):
    clip_id: str
    status: str


class CommentCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)
