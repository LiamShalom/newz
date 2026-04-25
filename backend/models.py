from pydantic import BaseModel


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
