import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from meshcorp.db import init_db
    from meshcorp.templates import load_templates
    await init_db()
    load_templates()
    yield


app = FastAPI(title="MeshCorp HQ", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include API routes
from meshcorp.routes import router
app.include_router(router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "meshcorp-hq",
        "uptime": round(time.time() - start_time),
    }


# Serve single-file frontend (replaces broken Svelte app)
_index_html = os.path.join(os.path.dirname(__file__), "index.html")


@app.get("/{path:path}")
async def serve_frontend(path: str):
    return FileResponse(_index_html, media_type="text/html")
