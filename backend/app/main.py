from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import files, pads, ws
from app.api.ws import server as crdt_server
from app.core.config import get_settings
from app.services import storage

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.ensure_bucket()
    async with crdt_server:
        yield


app = FastAPI(title="SpacePad", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pads.router)
app.include_router(ws.router)
app.include_router(files.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
