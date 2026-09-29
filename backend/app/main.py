import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.api import images, listings, scrape
from app.db import init_db

log = logging.getLogger(__name__)
FRONTEND_DIST = config.ROOT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Morganti Cerca Case", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error(_req: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "data": None, "error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_req: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    return JSONResponse(
        status_code=422,
        content={"success": False, "data": None, "error": f"Parametro non valido: {field} ({first.get('msg')})"},
    )


@app.exception_handler(Exception)
async def unexpected_error(_req: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"success": False, "data": None, "error": "Errore interno"})


app.include_router(listings.router)
app.include_router(images.router)
app.include_router(scrape.router)

config.ensure_dirs()
app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

# In "production" mode the built React app is served by the same process.
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Endpoint inesistente")
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
