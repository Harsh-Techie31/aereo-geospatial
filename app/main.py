from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import files
from app.db import Base, engine
from app.errors import GeoFileError


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a KML or zipped Shapefile and get per-feature area / length measurements.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router)


@app.exception_handler(GeoFileError)
async def geo_file_error_handler(_: Request, exc: GeoFileError):
    body = {"detail": str(exc)}
    if hasattr(exc, "file_id"):
        body.update(id=exc.file_id, status="FAILED")
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
