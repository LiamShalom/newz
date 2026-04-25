import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Plan 02 will call db.init() here.
    # Plan 02 will mount StaticFiles to serve clip files here.
    yield


app = FastAPI(title="Newz API", lifespan=lifespan)

# CORS allowlist per STACK.md §"CORS" + PATTERNS.md S6.
# FRONTEND_URL is the Vercel deploy origin in prod (Plan 05); localhost:5173 is dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True}
