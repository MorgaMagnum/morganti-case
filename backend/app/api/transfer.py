"""CSV export/import of all listings, and what this copy of the app can do."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlmodel import Session

from app import config
from app.api import scrape
from app.db import engine, get_session
from app.schemas import AppInfo, Envelope, ImportSummary
from pipeline.transfer import ImportFileError, ImportResult, export_csv, import_csv

router = APIRouter(prefix="/api", tags=["transfer"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/info", response_model=Envelope[AppInfo])
def info():
    return Envelope(data=AppInfo(mode=config.APP_MODE, can_scrape=config.CAN_SCRAPE))


@router.get("/export.csv")
def export(session: SessionDep):
    body = export_csv(session).encode("utf-8-sig")  # BOM: Excel then reads the accents correctly
    filename = f"cerca-case-{date.today().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=Envelope[ImportSummary])
async def import_file(request: Request):
    """The CSV is the raw request body (no multipart form needed)."""
    if int(request.headers.get("content-length") or 0) > config.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Il file è troppo grande.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > config.MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="Il file è troppo grande.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(status_code=400, detail="Il file è vuoto.")
    try:
        text = b"".join(chunks).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Il file non è in formato UTF-8: usa il file esportato così com'è, senza aprirlo e salvarlo con Excel.",
        ) from None
    result = await run_in_threadpool(_import, text)
    return Envelope(data=ImportSummary(**result.__dict__))


def _import(text: str) -> ImportResult:
    with Session(engine) as session:
        if config.CAN_SCRAPE and (scrape._process_running() or scrape._db_running(session)):
            raise HTTPException(status_code=409, detail="Aspetta la fine dell'aggiornamento, poi importa il file.")
        try:
            return import_csv(session, text)
        except ImportFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
